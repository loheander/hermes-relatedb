"""Acceptance scenarios for Dream Mode model routing and transparency (#56).

The scenarios live in ``features/dream_model_routing.feature`` as
Given/When/Then text; this module binds each step to the public seams only:
the fake Hermes plugin context (``dream_support``), the CLI and the store.

The steps pin the contract the implementing story must satisfy (proposed in
ADR-0010, open to review together with the feature file)::

    relatedb_memory.dream.register(ctx)
      - registers the auxiliary task key ``relatedb_consolidation`` with
        ``ctx.register_auxiliary_task``
    cli.main(argv, ctx=ctx) -> int
      - dream [--path <store>] [--limit N] [--timeout SECONDS] [--retries N]
      - dream --dry-run [--path <store>]
      - dream --status [--path <store>]
      ``ctx`` is the Hermes plugin context; Dream calls go through
      ``ctx.llm.complete_structured(..., task="relatedb_consolidation")``.

Simulation notes. The fake context does not model the user's Hermes config, so
"the slot resolves to a model" is simulated by writing ``provider`` and
``model`` into the registered task's ``defaults``; an unset slot has empty
defaults. The batch is the ``--limit`` oldest episodes. Episodes are sent as
``input`` items that are mappings with ``id`` and ``text`` keys.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from dream_support import LlmCall

scenarios("features/dream_model_routing.feature")

SLOT = "relatedb_consolidation"
CHAT_PROVIDER = "chat-cloud"
CHAT_MODEL = "chat-premium"
PROPOSAL = {"proposals": [{"summary": "Note a preference", "episodes": ["ep-1"]}]}
FACT_TEXT = "Ada works at Orchid Labs"
NODE_COUNT = "MATCH (n) RETURN count(n) AS n"


@pytest.fixture
def world(tmp_path, fake_ctx):
    state = SimpleNamespace(
        ctx=fake_ctx,
        store_dir=tmp_path / "memory",
        exit_code=None,
        stdout="",
        stderr="",
        nodes_before=None,
        chat=(CHAT_PROVIDER, CHAT_MODEL),
    )
    return state


def _store(world):
    from relatedb_memory.config import RelateDBConfig
    from relatedb_memory.store import RelateStore

    cfg = RelateDBConfig(hermes_home=world.store_dir.parent, db_path=world.store_dir, snapshot_format="json")
    return RelateStore.open(cfg, embedding_dim=4)


def _node_count(world) -> int:
    with _store(world) as store:
        return int(store.run(NODE_COUNT)[0]["n"])


def _run_cli(world, capsys, *argv):
    import cli

    world.exit_code = cli.main(["dream", "--path", str(world.store_dir), *argv], ctx=world.ctx)
    captured = capsys.readouterr()
    world.stdout, world.stderr = captured.out, captured.err


def _install_llm_behaviour(world, outcomes):
    """Replace ``complete_structured`` with a scripted sequence of results or exceptions.

    The last outcome repeats. Every attempt is recorded in ``ctx.llm.calls``.
    """
    llm = world.ctx.llm
    original = llm.complete_structured
    attempts = {"n": 0}

    def complete_structured(**kwargs):
        outcome = outcomes[min(attempts["n"], len(outcomes) - 1)]
        attempts["n"] += 1
        if isinstance(outcome, BaseException):
            fields = LlmCall.__dataclass_fields__
            llm.calls.append(LlmCall(**{k: (tuple(kwargs[k]) if k == "input" else kwargs.get(k)) for k in fields}))
            raise outcome
        llm.script(PROPOSAL)
        return original(**kwargs)

    llm.complete_structured = complete_structured


def _all_text(call: LlmCall) -> str:
    return json.dumps([call.instructions, call.system_prompt, list(call.input)], default=str)


# -- Given --------------------------------------------------------------------


@given("a Dream Mode plugin context with the relatedb-memory plugin registered")
def plugin_registered(world):
    from relatedb_memory import dream

    dream.register(world.ctx)
    assert SLOT in world.ctx.aux_tasks


@given("a memory store with these episodes, oldest first:")
def store_with_episodes(world, datatable):
    rows = datatable[1:]
    world.episode_texts = {episode_id: text for episode_id, text in rows}
    with _store(world) as store:
        for index, (episode_id, text) in enumerate(rows):
            store.record_episode(
                episode_id=episode_id, session="s1", kind="message",
                at=f"2026-03-0{index + 1}T00:00:00Z", text=text, mentions=["ada"],
            )
        store.record_fact(
            fact_id="f1", text=FACT_TEXT, slot="ada/employer",
            valid_from="2026-03-01T00:00:00Z", recorded_at="2026-03-01T00:00:00Z",
            episode_id=rows[0][0], about=["ada"], embedding=[1.0, 0.0, 0.0, 0.0],
        )
    world.nodes_before = _node_count(world)


@given(parsers.parse('the Hermes chat model is "{model}" from provider "{provider}"'))
def chat_model(world, model, provider):
    world.chat = (provider, model)


@given(parsers.parse('the consolidation slot resolves to model "{model}" from provider "{provider}"'))
def slot_resolves(world, model, provider):
    world.ctx.aux_tasks[SLOT]["defaults"].update(provider=provider, model=model)


@given("the consolidation slot has no provider or model chosen")
def slot_unset(world):
    world.ctx.aux_tasks[SLOT]["defaults"].clear()


@given("the model returns one valid proposal")
def model_returns_proposal(world):
    _install_llm_behaviour(world, [None])


@given(parsers.parse('the model always fails with "{message}"'))
def model_always_fails(world, message):
    _install_llm_behaviour(world, [RuntimeError(message)])


@given("the model always times out")
def model_always_times_out(world):
    _install_llm_behaviour(world, [TimeoutError("timed out")])


@given("the model times out once and then returns one valid proposal")
def model_times_out_once(world):
    _install_llm_behaviour(world, [TimeoutError("timed out"), None])


# -- When ---------------------------------------------------------------------


@when("Dream Mode runs")
def run_dream(world, capsys):
    _run_cli(world, capsys)


@when(parsers.parse("Dream Mode runs with {retries:d} retries"))
def run_dream_with_retries(world, capsys, retries):
    _run_cli(world, capsys, "--retries", str(retries))


@when(parsers.parse("Dream Mode runs with a {timeout:d} second timeout and {retries:d} retries"))
def run_dream_with_timeout_and_retries(world, capsys, timeout, retries):
    _run_cli(world, capsys, "--timeout", str(timeout), "--retries", str(retries))


@when(parsers.parse("Dream Mode runs with a batch of {limit:d} episodes"))
def run_dream_with_batch(world, capsys, limit):
    _run_cli(world, capsys, "--limit", str(limit))


@when("Dream Mode runs with --dry-run")
def run_dream_dry_run(world, capsys):
    _run_cli(world, capsys, "--dry-run")


@when("Dream Mode status is requested")
def request_status(world, capsys):
    _run_cli(world, capsys, "--status")


# -- Then ---------------------------------------------------------------------


@then("the run succeeds")
def run_succeeds(world):
    assert world.exit_code == 0, world.stderr or world.stdout


@then("the run fails")
def run_fails(world):
    assert world.exit_code not in (None, 0)


@then("the run is refused with a message naming the consolidation slot and how to set it")
def run_refused(world):
    assert world.exit_code not in (None, 0)
    message = (world.stdout + world.stderr).lower()
    assert SLOT in message
    assert "auxiliary" in message and ("set" in message or "configure" in message)


@then(parsers.parse("exactly {count:d} model call was made"))
@then(parsers.parse("exactly {count:d} model calls were made"))
def model_call_count(world, count):
    assert len(world.ctx.llm.calls) == count


@then("every model call went through the consolidation slot")
def calls_use_slot(world):
    assert world.ctx.llm.calls, "no model call was made"
    assert all(call.task == SLOT for call in world.ctx.llm.calls)


@then("no model call used the chat model")
def calls_avoid_chat_model(world):
    chat_provider, chat_model_name = world.chat
    for call in world.ctx.llm.calls:
        assert call.task == SLOT
        assert call.provider != chat_provider and call.model != chat_model_name


@then("the store has no consolidation proposals")
def store_unchanged(world):
    assert _node_count(world) == world.nodes_before


@then(parsers.parse('Dream Mode status records the failure "{message}" for model "{model}"'))
def status_records_failure(world, capsys, message, model):
    _run_cli(world, capsys, "--status")
    output = world.stdout + world.stderr
    assert message in output and model in output


@then(parsers.parse('the run report names provider "{provider}" and model "{model}"'))
def report_names_model(world, provider, model):
    assert provider in world.stdout and model in world.stdout


@then(parsers.parse('the output names the consolidation slot, provider "{provider}" and model "{model}"'))
def output_names_slot(world, provider, model):
    assert SLOT in world.stdout
    assert provider in world.stdout and model in world.stdout


@then("the output says no Dream Mode model is chosen")
def output_says_unset(world):
    output = (world.stdout + world.stderr).lower()
    assert SLOT in output and "no " in output and "model" in output and "chosen" in output


@then(parsers.parse("every model call carried a {timeout:d} second timeout"))
def calls_carry_timeout(world, timeout):
    assert world.ctx.llm.calls
    assert all(call.timeout == timeout for call in world.ctx.llm.calls)


@then(parsers.parse('the model received the text of "{first}" and "{second}" as quoted data'))
def model_received_batch(world, first, second):
    texts = {
        item["text"]
        for call in world.ctx.llm.calls
        for item in call.input
        if isinstance(item, dict) and "text" in item
    }
    assert {world.episode_texts[first], world.episode_texts[second]} <= texts
    assert all(isinstance(item, dict) and {"id", "text"} <= set(item) for call in world.ctx.llm.calls for item in call.input)


@then(parsers.parse('the model did not receive the text of "{episode_id}"'))
def model_missed_episode(world, episode_id):
    assert world.ctx.llm.calls
    assert all(world.episode_texts[episode_id] not in _all_text(call) for call in world.ctx.llm.calls)


@then("the instructions to the model contain no episode text")
def instructions_hold_no_episode_text(world):
    for call in world.ctx.llm.calls:
        for text in ("Lund office", "call me Ada"):
            assert text not in (call.instructions or "") and text not in (call.system_prompt or "")


@then("the model received no stored facts or entities beyond the proposal schema")
def model_received_no_store_content(world):
    assert world.ctx.llm.calls
    assert all(FACT_TEXT not in _all_text(call) for call in world.ctx.llm.calls)
