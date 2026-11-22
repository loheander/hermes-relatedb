"""Acceptance scenarios for correction detection and revision-checked apply (#58, ADR-0012).

The scenarios live in ``features/dream_correction_apply.feature``; this module
binds each step to the public seams only (provider, store, CLI, the fake Hermes
context). It pins this contract, which the implementing story must provide::

    provider.handle_tool_call("relatedb_correct", {"slot": <slot>, "text": <text>})
      - an explicit user correction: writes a fact with origin ``correction``
        in ``slot`` that supersedes the open fact(s) of that slot, now, with no
        Dream run; returns JSON with ``status`` and ``fact_id``
    cli.main(["dream"], *, ctx=None, embedder=None, provider=None) -> int
      - one manual Dream run; when ``provider`` is given the run writes through
        that provider's store (the single writer) and opens no other handle
    cli.main(["dream", "--rollback", <run id>], *, ctx, embedder, provider) -> int
    proposal schema (extends the closed Dream proposal schema)::

        {"proposals": [
          {"kind": "fact", "slot", "text", "source_episodes"},
          {"kind": "correction", "text", "corrects": [<fact id>], "certainty":
           "clear" | "ambiguous", "slot" (ambiguous only), "source_episodes"}]}

    graph: ``(:DreamRun)`` nodes with ``id``, ``startedAt``, ``outcome``,
    ``applied`` and ``rejected`` (JSON lists; each rejected entry is
    ``{"proposal": {...}, "reason": <code>}``) and ``rolledBackAt`` (null
    until rolled back); derived facts carry ``origin`` ``dream`` and
    ``runId``; rejection reason codes: ``contradicts_explicit_correction``,
    ``stale_revision``, ``source_missing``, ``source_closed``,
    ``already_covered``
    graph: ``(:Fact)-[:CONFLICTS_WITH {detectedAt}]->(:Fact)`` links a possible
    conflict; ``recall`` text for either side contains the word ``conflict``

No step reaches into a private helper of the implementation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory import config as relatedb_config
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider
from relatedb_memory.store import RelateStore

scenarios("features/dream_correction_apply.feature")

DIM = 4
T0 = "2026-01-01T00:00:00Z"


@pytest.fixture
def world(tmp_path, monkeypatch, fake_ctx):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / relatedb_config.CONFIG_FILENAME).write_text(
        yaml.safe_dump({"memory": {relatedb_config.PROVIDER_NAME: {"dream": True}}}), encoding="utf-8"
    )
    return SimpleNamespace(
        home=home, ctx=fake_ctx, embedder=FakeEmbedder(dim=DIM), provider=None, episodes=[],
        correction_id=None, recalled={}, opens=0, run_id=None, derived_slot=None, llm_calls_before=0,
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


def _provider(world):
    if world.provider is None:
        provider = RelateDBMemoryProvider()
        provider.initialize("s-e2e", hermes_home=str(world.home), embedder=world.embedder)
        world.provider = provider
    return world.provider


def _store(world):
    return _provider(world).store


def _query(world, cypher, **params):
    return _store(world).run(cypher, **params)


def _seed_fact(world, fact_id, slot, text):
    store = _store(world)
    episode_id = f"ep-{fact_id}"
    store.record_episode(episode_id=episode_id, session="s-e2e", kind="tool_call", at=T0, text=text)
    store.record_fact(fact_id=fact_id, text=text, slot=slot, valid_from=T0, recorded_at=T0,
                      episode_id=episode_id, embedding=world.embedder.embed_one(text), origin="remember")


def _seed_episodes(world, count, remark="The user chatted about Alpha."):
    store = _store(world)
    for _ in range(count):
        episode_id = f"ep-unprocessed-{len(world.episodes)}"
        store.record_episode(episode_id=episode_id, session="s-e2e", kind="message", at=T0,
                             text=f"User: {remark}\nAssistant: noted")
        world.episodes.append(episode_id)


def _correct(world, slot, text):
    out = json.loads(_provider(world).handle_tool_call("relatedb_correct", {"slot": slot, "text": text}))
    assert out.get("status") == "ok", out
    world.correction_id = out["fact_id"]
    return out["fact_id"]


def _script(world, *proposals):
    world.ctx.llm.__dict__.pop("complete_structured", None)
    world.ctx.llm.script({"proposals": [{**p, "source_episodes": list(world.episodes)} for p in proposals]})


def _dream(world, *argv):
    import cli

    code = cli.main(["dream", *argv], ctx=world.ctx, embedder=world.embedder, provider=_provider(world))
    assert code == 0


def _dream_counting_opens(world, monkeypatch):
    real_open = RelateStore.open.__func__

    def counting_open(cls, *args, **kwargs):
        world.opens += 1
        return real_open(cls, *args, **kwargs)

    monkeypatch.setattr(RelateStore, "open", classmethod(counting_open))
    _dream(world)


def _runs(world):
    rows = _query(world, "MATCH (r:DreamRun) RETURN r.id AS id, r.outcome AS outcome, r.applied AS applied, "
                         "r.rejected AS rejected, r.rolledBackAt AS rolled_back ORDER BY r.startedAt")
    for row in rows:
        for key in ("applied", "rejected"):
            row[key] = json.loads(row[key]) if isinstance(row[key], str) else (row[key] or [])
    return rows


def _latest_run(world):
    runs = _runs(world)
    assert runs, "no DreamRun node was written"
    return runs[-1]


def _rejections(run, text):
    return [r for r in run["rejected"] if r["proposal"].get("text") == text]


def _recall(world, query):
    block = _provider(world).prefetch(query)
    world.recalled[query] = block
    return block


def _recall_lines(block):
    return [line[2:] for line in block.splitlines() if line.startswith("- ")]


def _fact(world, text):
    rows = _query(world, "MATCH (f:Fact {text: $t}) RETURN f.id AS id, f.closedAt AS closed ORDER BY f.recordedAt", t=text)
    assert rows, f"no fact with text {text!r}"
    return rows[-1]


# -- Given --------------------------------------------------------------------


@given(parsers.parse('an open fact "{fact_id}" in slot "{slot}" saying "{text}"'))
def an_open_fact(world, fact_id, slot, text):
    _seed_fact(world, fact_id, slot, text)


@given(parsers.parse('the user explicitly corrected slot "{slot}" to "{text}"'))
def user_already_corrected(world, slot, text):
    _correct(world, slot, text)


@given(parsers.parse("Dream Mode is enabled with {count:d} unprocessed episode"))
@given(parsers.parse("Dream Mode is enabled with {count:d} unprocessed episodes"))
def dream_enabled(world, count):
    _seed_episodes(world, count)


@given(parsers.parse('Dream Mode is enabled with 1 unprocessed episode in which the user mentions "{word}" again in passing'))
def dream_enabled_with_passing_mention(world, word):
    _seed_episodes(world, 1, remark=f"{word} came up again.")


@given("Dream Mode is enabled with 1 unprocessed episode in which the user mentions VS Code for Alpha")
def dream_enabled_vscode(world):
    _seed_episodes(world, 1, remark="Someone opened Alpha in VS Code today.")


@given("Dream Mode is enabled with 1 unprocessed episode in which the user says Alpha moved to PostgreSQL")
def dream_enabled_moved(world):
    _seed_episodes(world, 1, remark="We moved Alpha to PostgreSQL last week.")


@given(parsers.parse('no fact named "{fact_id}" exists'))
def no_such_fact(world, fact_id):
    assert _query(world, "MATCH (f:Fact {id: $id}) RETURN f.id AS id", id=fact_id) == []


@given(parsers.parse('fact "{fact_id}" was retracted earlier'))
def fact_retracted(world, fact_id):
    _seed_fact(world, fact_id, "project/alpha/cache", "Alpha caches in Redis.")
    _store(world).retract_slot(slot="project/alpha/cache", valid_to=T0, closed_at=T0)


@given(parsers.parse('a completed Dream run derived the fact "{text}" in slot "{slot}"'))
def completed_run_derived_fact(world, text, slot):
    _script(world, {"kind": "fact", "slot": slot, "text": text})
    _dream(world)
    run = _latest_run(world)
    assert run["outcome"] == "completed" and run["applied"], run
    world.run_id, world.derived_slot, world.derived_text = run["id"], slot, text


# -- When ---------------------------------------------------------------------


@when(parsers.parse('the user explicitly corrects slot "{slot}" to "{text}" without any Dream run'))
def user_corrects(world, slot, text):
    _correct(world, slot, text)


@when(parsers.parse('the user explicitly states in slot "{slot}" that "{text}"'))
def user_states(world, slot, text):
    _correct(world, slot, text)


@when(parsers.parse('Dream Mode runs and the model proposes the inferred fact "{text}" in slot "{slot}"'))
def dream_proposes_inferred_fact(world, text, slot):
    _script(world, {"kind": "fact", "slot": slot, "text": text})
    _dream(world)


@when(parsers.parse('Dream Mode runs and the model proposes an ambiguous correction of "{target}" to "{text}" in slot "{slot}"'))
def dream_proposes_ambiguous(world, target, text, slot):
    _script(world, {"kind": "correction", "corrects": [target], "text": text, "slot": slot, "certainty": "ambiguous"})
    _dream(world)


@when(parsers.parse('Dream Mode runs, the model proposes a database fact and a language fact, and the user corrects slot "{slot}" to "{text}" while the run is in flight'))
def dream_run_with_inflight_correction(world, slot, text):
    _script(world, {"kind": "fact", "slot": "project/alpha/database", "text": "Alpha uses MariaDB."},
            {"kind": "fact", "slot": "project/alpha/language", "text": "Alpha is written in Python."})
    llm = world.ctx.llm
    scripted = type(llm).complete_structured.__get__(llm)

    def hooked(**kwargs):
        _correct(world, slot, text)  # lands after the run read the store, before it applies
        return scripted(**kwargs)

    llm.complete_structured = hooked
    try:
        _dream(world)
    finally:
        llm.__dict__.pop("complete_structured", None)


@when("Dream Mode runs again with the model re-proposing the database fact")
def dream_runs_again(world):
    world.llm_calls_before = len(world.ctx.llm.calls)
    _script(world, {"kind": "fact", "slot": "project/alpha/database", "text": "Alpha uses MariaDB."})
    _dream(world)
    assert len(world.ctx.llm.calls) > world.llm_calls_before, "the next run did not retry the rejected proposal"


@when("Dream Mode runs and the model proposes one fact")
def dream_proposes_one_fact(world, monkeypatch):
    _script(world, {"kind": "fact", "slot": "project/alpha/style", "text": "Alpha prefers short migrations."})
    _dream_counting_opens(world, monkeypatch)


@when("the user rolls back that run")
def user_rolls_back(world):
    import cli

    code = cli.main(["dream", "--rollback", world.run_id], ctx=world.ctx, embedder=world.embedder,
                    provider=_provider(world))
    assert code == 0


@when(parsers.parse('Dream Mode runs and the model proposes a correction of "{target}" to "{text}"'))
def dream_proposes_correction(world, target, text):
    _script(world, {"kind": "correction", "corrects": [target], "text": text, "certainty": "clear"})
    _dream(world)


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('recall for "{query}" shows "{text}"'))
def recall_shows(world, query, text):
    assert any(line.startswith(text) for line in _recall_lines(_recall(world, query))), world.recalled[query]


@then(parsers.parse('recall for "{query}" does not show "{text}"'))
def recall_hides(world, query, text):
    assert not any(line.startswith(text) for line in _recall_lines(_recall(world, query))), world.recalled[query]


@then(parsers.parse('fact "{fact_id}" is kept, closed, and still traces back to its original episode'))
def fact_kept_closed_with_provenance(world, fact_id):
    rows = _query(world, "MATCH (f:Fact {id: $id})-[:FROM]->(e:Episode) RETURN f.closedAt AS closed, e.id AS ep", id=fact_id)
    assert rows and rows[0]["closed"] is not None and rows[0]["ep"] == f"ep-{fact_id}", rows


@then(parsers.parse('fact "{fact_id}" is kept and closed'))
def fact_kept_and_closed(world, fact_id):
    rows = _query(world, "MATCH (f:Fact {id: $id}) RETURN f.closedAt AS closed", id=fact_id)
    assert rows and rows[0]["closed"] is not None, rows


@then(parsers.parse('the new fact supersedes fact "{fact_id}"'))
def new_fact_supersedes(world, fact_id):
    rows = _query(world, "MATCH (n:Fact {id: $new})-[:SUPERSEDES]->(o:Fact {id: $old}) RETURN o.id AS id",
                  new=world.correction_id, old=fact_id)
    assert rows, "no SUPERSEDES edge from the correction"


@then("the new fact is recorded as an explicit correction")
def new_fact_is_explicit(world):
    rows = _query(world, "MATCH (f:Fact {id: $id}) RETURN f.origin AS origin", id=world.correction_id)
    assert rows and rows[0]["origin"] == "correction", rows


@then("the proposal is recorded as rejected in the run history because it contradicts an explicit correction")
def proposal_rejected_vs_explicit(world):
    run = _latest_run(world)
    assert [r["reason"] for r in _rejections(run, "Alpha uses MySQL.")] == ["contradicts_explicit_correction"], run


@then("both statements are still open")
def both_open(world):
    for text in ("Alpha code is edited in vim.", "Alpha code is edited in VS Code."):
        assert _fact(world, text)["closed"] is None, text


@then("the two statements are linked as a possible conflict")
def linked_as_conflict(world):
    a, b = _fact(world, "Alpha code is edited in vim.")["id"], _fact(world, "Alpha code is edited in VS Code.")["id"]
    rows = _query(world, "MATCH (x:Fact)-[c:CONFLICTS_WITH]-(y:Fact) WHERE x.id = $a AND y.id = $b RETURN c.detectedAt AS at",
                  a=a, b=b)
    assert rows, "no CONFLICTS_WITH edge between the two statements"


@then(parsers.parse('recall for "{query}" shows both statements and marks them as a conflict'))
def recall_surfaces_conflict(world, query):
    lines = _recall_lines(_recall(world, query))
    for text in ("Alpha code is edited in vim.", "Alpha code is edited in VS Code."):
        matching = [line for line in lines if line.startswith(text)]
        assert matching and "conflict" in matching[0].lower(), (text, world.recalled[query])


@then(parsers.parse('fact "{fact_id}" is still open'))
def fact_still_open(world, fact_id):
    rows = _query(world, "MATCH (f:Fact {id: $id}) RETURN f.closedAt AS closed", id=fact_id)
    assert rows and rows[0]["closed"] is None, rows


@then("the two facts are not linked as a conflict")
def not_linked(world):
    assert _query(world, "MATCH (:Fact)-[c:CONFLICTS_WITH]-(:Fact) RETURN c") == []


@then("the database proposal is rejected as stale in the run history")
def database_rejected_stale(world):
    run = _latest_run(world)
    assert [r["reason"] for r in _rejections(run, "Alpha uses MariaDB.")] == ["stale_revision"], run


@then("the user's correction is preserved and still open")
def correction_preserved(world):
    rows = _query(world, "MATCH (f:Fact {id: $id}) RETURN f.closedAt AS closed, f.slot AS slot", id=world.correction_id)
    assert rows and rows[0]["closed"] is None, rows
    assert _fact(world, "Alpha uses PostgreSQL.")["closed"] is None


@then("the language proposal is applied")
def language_applied(world):
    assert _fact(world, "Alpha is written in Python.")["closed"] is None
    assert any(a.get("text") == "Alpha is written in Python." for a in _latest_run(world)["applied"])


@then("the database proposal is not applied over the correction")
def database_not_applied(world):
    assert _fact(world, "Alpha uses PostgreSQL.")["closed"] is None
    assert _query(world, "MATCH (f:Fact {text: 'Alpha uses MariaDB.'}) RETURN f.id AS id") == []


@then("the run applied its proposal")
def run_applied(world):
    run = _latest_run(world)
    assert run["outcome"] == "completed" and len(run["applied"]) == 1, run


@then("no store handle other than the provider's writer was opened during the run")
def no_second_writer(world):
    assert world.opens == 0, f"the run opened {world.opens} extra store handle(s)"


@then("the applied fact is in the provider's store")
def applied_in_provider_store(world):
    assert _fact(world, "Alpha prefers short migrations.")["closed"] is None


@then("the derived fact is closed and no longer recalled")
def derived_closed(world):
    assert _fact(world, world.derived_text)["closed"] is not None
    block = _recall(world, "how does Alpha handle migrations")
    assert not any(line.startswith(world.derived_text) for line in _recall_lines(block)), block


@then(parsers.parse('fact "{fact_id}" is still open and unchanged'))
def fact_open_unchanged(world, fact_id):
    rows = _query(world, "MATCH (f:Fact {id: $id}) RETURN f.closedAt AS closed, f.text AS text", id=fact_id)
    assert rows and rows[0]["closed"] is None and rows[0]["text"] == "Alpha uses MySQL.", rows


@then("the rolled-back run is still visible in the run history as rolled back")
def run_visible_as_rolled_back(world):
    runs = [r for r in _runs(world) if r["id"] == world.run_id]
    assert runs and runs[0]["rolled_back"] is not None, runs


@then("the correction is applied")
def correction_applied(world):
    run = _latest_run(world)
    assert run["applied"] and not run["rejected"], run


@then(parsers.parse('the correction is rejected in the run history with reason "{reason}"'))
def correction_rejected(world, reason):
    run = _latest_run(world)
    assert [r["reason"] for r in _rejections(run, "Alpha uses PostgreSQL.")] == [reason], run


@then("no new fact is written by that run")
def no_new_fact(world):
    run = _latest_run(world)
    assert run["applied"] == [], run
    assert _query(world, "MATCH (f:Fact) WHERE f.origin = 'dream' RETURN f.id AS id") == []
