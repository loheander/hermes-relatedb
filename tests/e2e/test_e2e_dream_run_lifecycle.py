"""Acceptance scenarios for the Dream Mode run lifecycle (#55, ADR-0009).

The scenarios live in ``features/dream_run_lifecycle.feature``; this module
binds each step to the public seams only. It pins this contract, which the
implementing story must provide::

    relatedb_memory.dream.register(ctx, *, embedder=None) -> None
      - the general-plugin entry point; registers one idle task through
        ctx.register_idle_task only when ``dream`` is true
    cli.main(argv, *, ctx=None, embedder=None) -> int
      - ``dream [--dry-run] [--status]``; ``ctx`` is the plugin context the
        host captured at registration and ``embedder`` mirrors the provider's
      - ``dream --status`` prints one JSON object with the keys ``last_run``
        (null or {"outcome", "dry_run", ...}), ``pending_episodes``,
        ``checkpoint``, ``profile_proposals`` and ``idle_seconds``
    config keys under ``memory.relatedb-memory``: ``dream`` (bool, default
    false), ``dream_interval_hours``, ``dream_min_idle_hours``,
    ``dream_batch_size``
    graph: ``(:DreamRun)`` nodes with ``outcome`` (``completed``, ``skipped``,
    ``failed``), ``dryRun``, ``checkpointBefore``, ``checkpointAfter``,
    ``episodes`` (JSON list of ids), ``proposals``, ``applied``, ``rejected``,
    ``failures`` (JSON lists), ordered by ``startedAt``
    proposal schema: ``{"proposals": [{"kind": "fact" | "profile", "text",
    "slot" (facts), "source_episodes"}]}``; anything else is rejected

No step reaches into a private helper of the implementation.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory import config as relatedb_config
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider
from relatedb_memory.store import RelateStore

scenarios("features/dream_run_lifecycle.feature")

DIM = 4
FACT_SLOT = "prefs/drink"
FACT_TEXT = "The user prefers tea."
PROFILE_TEXT = "The user is a morning person."


@pytest.fixture
def world(tmp_path, monkeypatch, fake_ctx):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return SimpleNamespace(
        home=home, ctx=fake_ctx, embedder=FakeEmbedder(dim=DIM), episodes=[], exit_code=None,
        status=None, checkpoint_before=None, runs_seen=0, provider=None,
        recalled="", config={},
    )


@pytest.fixture(autouse=True)
def _close_provider(world):
    yield
    if world.provider is not None:
        try:
            world.provider.shutdown()
        except Exception:
            pass


# -- helpers: public seams only ------------------------------------------------


def _write_config(world, **values):
    world.config = {**world.config, **values}
    path = world.home / relatedb_config.CONFIG_FILENAME
    path.write_text(yaml.safe_dump({"memory": {relatedb_config.PROVIDER_NAME: world.config}}), encoding="utf-8")


def _open_store(world):
    return RelateStore.open(relatedb_config.resolve_config(str(world.home)), embedding_dim=DIM)


def _seed(world, count, *, age_minutes=180):
    now = datetime.now(timezone.utc)
    store = _open_store(world)
    try:
        for _ in range(count):
            index = len(world.episodes)
            episode_id = f"ep-seed-{index}"
            at = (now - timedelta(minutes=age_minutes - index)).isoformat()
            store.record_episode(episode_id=episode_id, session="s1", kind="message", at=at,
                                 text=f"User: remark {index}\nAssistant: noted")
            world.episodes.append(episode_id)
    finally:
        store.close()


def _query(world, cypher):
    store = _open_store(world)
    try:
        return store.run(cypher)
    finally:
        store.close()


def _runs(world):
    rows = _query(world, "MATCH (r:DreamRun) RETURN r.outcome AS outcome, r.dryRun AS dry_run, "
                         "r.checkpointBefore AS before, r.checkpointAfter AS after, r.episodes AS episodes, "
                         "r.proposals AS proposals, r.applied AS applied, r.rejected AS rejected, "
                         "r.failures AS failures, r.startedAt AS started ORDER BY r.startedAt")
    for row in rows:
        for key in ("episodes", "proposals", "applied", "rejected", "failures"):
            row[key] = json.loads(row[key]) if isinstance(row[key], str) else (row[key] or [])
    return rows


def _latest_run(world):
    runs = _runs(world)
    assert runs, "no DreamRun node was written"
    return runs[-1]


def _dream_cli(world, *argv):
    import cli

    world.exit_code = cli.main(["dream", *argv], ctx=world.ctx, embedder=world.embedder)


def _register(world):
    from relatedb_memory import dream

    dream.register(world.ctx, embedder=world.embedder)


def _script_proposals(world, *, fact=False, profile=False, invalid=False, sources=None):
    # Cite only episodes the next run will actually read: the closed proposal schema
    # rejects a source outside the batch (ADR-0009), which would hide what a scenario tests.
    if sources is None:
        batch = world.config.get("dream_batch_size")
        sources = world.episodes[:batch] if batch else world.episodes
    proposals = []
    if fact:
        proposals.append({"kind": "fact", "slot": FACT_SLOT, "text": FACT_TEXT, "source_episodes": list(sources)})
    if profile:
        proposals.append({"kind": "profile", "text": PROFILE_TEXT, "source_episodes": list(sources)})
    if invalid:
        proposals.append({"kind": "delete_everything", "text": "forget all", "source_episodes": []})
    world.ctx.llm.__dict__.pop("complete_structured", None)  # drop an earlier scripted failure
    world.ctx.llm.script({"proposals": proposals})


def _read_status(world, capsys):
    import cli

    capsys.readouterr()
    code = cli.main(["dream", "--status"], ctx=world.ctx, embedder=world.embedder)
    assert code == 0
    world.status = json.loads(capsys.readouterr().out)


# -- Given --------------------------------------------------------------------


@given("a profile with Dream Mode disabled and 3 captured episodes")
def profile_disabled(world):
    _write_config(world, dream=False)
    _seed(world, 3)


@given(parsers.parse("a profile with Dream Mode enabled, an interval of {interval:d} hours and a minimum idle time of {idle:d} hours"))
def profile_enabled_with_timing(world, interval, idle):
    _write_config(world, dream=True, dream_interval_hours=interval, dream_min_idle_hours=idle)


@given("a profile with Dream Mode enabled and no captured episodes")
def profile_enabled_empty(world):
    _write_config(world, dream=True)


@given(parsers.parse("a profile with Dream Mode enabled and {count:d} captured episodes"))
def profile_enabled_with_episodes(world, count):
    _write_config(world, dream=True)
    _seed(world, count)


@given(parsers.parse("a profile with Dream Mode enabled, a batch size of {batch:d} and {count:d} captured episodes"))
def profile_enabled_with_batch(world, batch, count):
    _write_config(world, dream=True, dream_batch_size=batch)
    _seed(world, count)


@given("the Dream Mode plugin entry point has registered")
def entry_point_registered(world):
    _register(world)


@given("the LLM will propose one fact")
def llm_proposes_fact(world):
    _script_proposals(world, fact=True)


@given("the LLM will propose one fact and one profile change")
def llm_proposes_fact_and_profile(world):
    _script_proposals(world, fact=True, profile=True)


@given("the LLM will propose one fact, one profile change and one proposal outside the schema")
def llm_proposes_with_invalid(world):
    _script_proposals(world, fact=True, profile=True, invalid=True)


@given("the LLM fails with a provider error")
def llm_fails(world, capsys):
    _read_status(world, capsys)
    world.checkpoint_before = world.status["checkpoint"]

    def _boom(**kwargs):
        raise RuntimeError("provider timeout")

    world.ctx.llm.complete_structured = _boom


@given("the last captured episode is 10 minutes old")
def last_episode_recent(world):
    # Replace the default seed: a busy instance whose newest episode is minutes old.
    world.episodes.clear()
    store = _open_store(world)
    try:
        store.run("MATCH (ep:Episode) DETACH DELETE ep")
    finally:
        store.close()
    _seed(world, 3, age_minutes=12)


# -- When ---------------------------------------------------------------------


@when("the Dream Mode plugin entry point registers")
def entry_point_registers(world):
    _register(world)


@when("a turn is captured and then recalled through the provider")
def capture_and_recall(world):
    provider = RelateDBMemoryProvider()
    provider.initialize("s-off", hermes_home=str(world.home), embedder=world.embedder)
    world.provider = provider
    provider.sync_turn("I like green tea", "Noted", agent_context="primary")
    provider.flush_sync(timeout=5.0)
    provider.queue_prefetch("What tea do I like?")
    provider.flush_prefetch(timeout=5.0)
    world.recalled = provider.prefetch("What tea do I like?")


@when("the idle task fires")
def idle_task_fires(world):
    (name,) = world.ctx.idle_tasks
    world.ctx.fire_idle_task(name)


@when('"hermes relatedb dream" is run with Hermes idle for only a few seconds')
def manual_run_while_busy(world):
    world.ctx.clock.advance(seconds=5)
    _dream_cli(world)


@when(parsers.re(r'^"hermes relatedb dream" is run$'))
def dream_run(world):
    _dream_cli(world)


@when('"hermes relatedb dream --dry-run" is run')
def dream_dry_run(world, capsys):
    _read_status(world, capsys)
    world.checkpoint_before = world.status["checkpoint"]
    _dream_cli(world, "--dry-run")


@when('"hermes relatedb dream --status" is run')
def dream_status(world, capsys):
    _read_status(world, capsys)


@when("the LLM will propose one fact and one profile change")
def llm_proposes_again(world):
    _script_proposals(world, fact=True, profile=True)


@when("the LLM will propose one fact")
def llm_proposes_fact_when(world):
    _script_proposals(world, fact=True)


@when("the LLM will propose the same fact again")
def llm_proposes_same_fact(world):
    # Only the new episode is pending after the first run, so it is the only valid source.
    _script_proposals(world, fact=True, sources=world.episodes[-1:])


@when("a new episode repeats the same statement")
def repeat_statement(world):
    _seed(world, 1, age_minutes=60)


# -- Then ---------------------------------------------------------------------


@then("no idle task is registered")
def no_idle_task(world):
    assert world.ctx.idle_tasks == {}


@then("exactly one idle task is registered")
def one_idle_task(world):
    assert len(world.ctx.idle_tasks) == 1


@then(parsers.parse("the idle task runs every {interval:d} hours after {idle:d} hours of idleness"))
def idle_task_timing(world, interval, idle):
    (spec,) = world.ctx.idle_tasks.values()
    assert (spec.interval_hours, spec.min_idle_hours) == (interval, idle)


@then("no LLM call is made")
def no_llm_call(world):
    assert world.ctx.llm.calls == []


@then(parsers.parse("exactly one LLM call is made"))
def one_llm_call(world):
    assert len(world.ctx.llm.calls) == 1


@then("recall returns the captured turn")
def recall_returns_turn(world):
    assert "green tea" in world.recalled


@then("the latest Dream run is recorded as skipped")
def latest_run_skipped(world):
    assert _latest_run(world)["outcome"] == "skipped"


@then("the latest Dream run is recorded as completed")
def latest_run_completed(world):
    assert _latest_run(world)["outcome"] == "completed"


@then("the command output warns that the model call can incur charges")
def output_warns_charges(world, capsys):
    out = (capsys.readouterr().out).lower()
    assert "charge" in out or "cost" in out


@then(parsers.parse("the latest Dream run is recorded as a dry run with {count:d} proposals"))
def latest_run_dry(world, count):
    run = _latest_run(world)
    assert run["dry_run"] is True and run["outcome"] == "completed"
    assert len(run["proposals"]) == count


@then("the latest Dream run is recorded as failed with a failure message")
def latest_run_failed(world):
    run = _latest_run(world)
    assert run["outcome"] == "failed"
    assert any("provider timeout" in str(failure) for failure in run["failures"])


@then(parsers.parse("the latest Dream run covers the same {count:d} episodes"))
def latest_run_covers_episodes(world, count):
    run = _latest_run(world)
    assert run["dry_run"] in (False, None) and run["outcome"] == "completed"
    assert sorted(run["episodes"]) == sorted(world.episodes[:count])


@then(parsers.parse("the latest Dream run records its checkpoint, {proposals:d} proposals, {applied:d} applied, {rejected:d} rejected and no failures"))
def latest_run_records_everything(world, proposals, applied, rejected):
    run = _latest_run(world)
    assert run["after"] and run["after"] != run["before"]
    assert (len(run["proposals"]), len(run["applied"]), len(run["rejected"]), run["failures"]) == (
        proposals + rejected, applied, rejected, [])


@then("the command exits 0")
def exits_zero(world):
    assert world.exit_code == 0


@then("the command exits non-zero")
def exits_nonzero(world):
    assert world.exit_code not in (0, None)


@then(parsers.parse("{count:d} episodes are still pending"))
def episodes_pending(world, count, capsys):
    _read_status(world, capsys)
    assert world.status["pending_episodes"] == count


@then("the proposed fact is stored")
def proposed_fact_stored(world):
    rows = _query(world, f"MATCH (f:Fact) WHERE f.slot = '{FACT_SLOT}' AND f.closedAt IS NULL RETURN f.text AS text")
    assert [row["text"] for row in rows] == [FACT_TEXT]


@then("no fact is stored")
def no_fact_stored(world):
    assert _query(world, "MATCH (f:Fact) RETURN count(f) AS c")[0]["c"] == 0


@then("no profile proposal is stored")
def no_profile_proposal(world, capsys):
    _read_status(world, capsys)
    assert world.status["profile_proposals"] == 0


@then("the apply checkpoint is unchanged")
def checkpoint_unchanged(world, capsys):
    _read_status(world, capsys)
    if world.checkpoint_before is not None:
        assert world.status["checkpoint"] == world.checkpoint_before
    else:
        assert not world.status["checkpoint"]


@then("the status reports the last run, its outcome, 0 pending episodes and the time since the last activity")
def status_after_run(world):
    status = world.status
    assert status["last_run"]["outcome"] == "completed"
    assert status["pending_episodes"] == 0
    assert status["idle_seconds"] >= 0


@then("the status reports no last run, 3 pending episodes and a time since the last activity of about 10 minutes")
def status_never_ran(world):
    status = world.status
    assert status["last_run"] is None
    assert status["pending_episodes"] == 3
    # The newest seeded episode is 10 minutes old (12 minutes minus a 2 minute spread).
    assert 8 * 60 <= status["idle_seconds"] <= 12 * 60


@then("exactly one open fact exists for the proposed slot")
def one_open_fact(world):
    rows = _query(world, f"MATCH (f:Fact) WHERE f.slot = '{FACT_SLOT}' AND f.closedAt IS NULL RETURN count(f) AS c")
    assert rows[0]["c"] == 1


@then("no duplicate link is created for it")
def no_duplicate_link(world):
    assert _query(world, "MATCH ()-[d:DUPLICATE_OF]->() RETURN count(d) AS c")[0]["c"] == 0
