"""Acceptance scenarios for pattern inference (#60, part of #33).

The scenarios live in ``features/dream_pattern_inference.feature``; this module
binds each step to the public seams only. It pins the contract proposed in
ADR-0014 (Proposed); wording changes in the feature file are the review surface::

    dream.register(ctx, provider)              # also registers "relatedb-dream-patterns" when patterns are on
    ctx.fire_idle_task("relatedb-dream-patterns")
    provider.dream_patterns(include_closed=False) -> list[dict]
        # {"id", "topic", "text", "type": "pattern", "status": "open" | "closed", "support", "sources"}
    provider.prefetch(query) -> str            # renders a pattern as "Inference (...)"
    provider.system_prompt_block() -> str
    provider.handle_tool_call("relatedb_cypher" | "relatedb_as_of" | "relatedb_remember", ...)

Typed observations (ADR-0011, in review) are modelled as facts in the slot
``observation/<id>`` whose episode is the episode they cite. The model is
scripted through the fake Hermes context (``fake_ctx``); a pattern pass
returns ``{"patterns": [{"topic", "text", "evidence": [observation ids]}],
"retire": [{"pattern": id, "statement": fact id}]}``. Support is counted by
the code as distinct source episodes of open evidence, never taken from the model.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider

scenarios("features/dream_pattern_inference.feature")

EMBEDDING_DIM = 4
OBS_TASK = "relatedb-dream"
PATTERN_TASK = "relatedb-dream-patterns"
PATTERN_TOPIC = "answer-order"
OBSERVED_TEXT = "Asks for the migration plan before any code"
INSTRUCTION_WORDS = re.compile(r"\b(always|never|must|should|ensure|remember to|do not|don't)\b", re.IGNORECASE)


@pytest.fixture
def world(tmp_path, fake_ctx, monkeypatch):
    state = SimpleNamespace(
        home=tmp_path, ctx=fake_ctx, embedder=FakeEmbedder(dim=EMBEDDING_DIM), monkeypatch=monkeypatch,
        provider=None, observations=[], episodes=set(), min_support=3, pattern_text=None, line="",
    )
    yield state
    if state.provider is not None:
        try:
            state.provider.shutdown()
        except Exception:
            pass


# -- helpers (public seams only) ----------------------------------------------


def _provider(world):
    if world.provider is None:
        provider = RelateDBMemoryProvider()
        provider.initialize("s-admin", hermes_home=str(world.home), embedder=world.embedder)
        world.provider = provider
    return world.provider


def _day(n):
    return f"2026-03-{int(n):02d}T10:00:00Z"


def _observe(world, text, episode, slot=None):
    """Record one observation fact that cites ``episode``; returns its id."""
    provider = _provider(world)
    index = len(world.observations) + 1
    if episode not in world.episodes:
        world.episodes.add(episode)
        provider.store.record_episode(
            episode_id=episode, session=f"s-{episode}", kind="message", at=_day(len(world.episodes)),
            text="session transcript", mentions=[],
        )
    fact_id = f"obs-{index}"
    provider.store.record_fact(
        fact_id=fact_id, text=text, slot=slot or f"observation/{fact_id}", valid_from=_day(len(world.episodes)),
        recorded_at=_day(len(world.episodes)), episode_id=episode, about=[], embedding=world.embedder.embed_one(text),
        origin="turn",
    )
    world.observations.append(SimpleNamespace(id=fact_id, text=text, episode=episode, slot=slot or f"observation/{fact_id}"))
    return fact_id


def _infer(world, text, evidence_ids):
    from relatedb_memory import dream  # not implemented yet: fails until the pattern story lands

    provider = _provider(world)
    world.ctx.llm.script({"patterns": [{"topic": PATTERN_TOPIC, "text": text, "evidence": list(evidence_ids)}], "retire": []})
    dream.register(world.ctx, provider)
    world.ctx.fire_idle_task(PATTERN_TASK)
    world.pattern_text = text


def _patterns(world, include_closed=False):
    return _provider(world).dream_patterns(include_closed=include_closed)


def _pattern(world, include_closed=False):
    found = [p for p in _patterns(world, include_closed) if p["text"] == world.pattern_text]
    assert len(found) == 1, f"expected exactly one pattern {world.pattern_text!r}, got {found}"
    return found[0]


def _user_md(world):
    return world.home / "memories" / "USER.md"


def _supported_pattern(world, text, episodes):
    for i in range(1, episodes + 1):
        _observe(world, f"Observation {i}: asks for the migration plan first", f"ep-{i}")
    _infer(world, text, [o.id for o in world.observations])


def _cypher(world, query, **params):
    raw = _provider(world).handle_tool_call("relatedb_cypher", {"query": query, "params": params})
    return json.loads(raw)["rows"]


# -- Given --------------------------------------------------------------------


@given("Dream Mode is on")
def dream_on(world):
    world.monkeypatch.setenv("RELATEDB_DREAM", "1")
    world.monkeypatch.setenv("RELATEDB_DREAM_PATTERNS", "1")


@when("the plugin setup fields are listed")
def setup_fields(world):
    world.setup_fields = {f["key"]: f for f in RelateDBMemoryProvider().get_config_schema()}


@then(parsers.parse('the setup offers "{key}" as a separate choice from "{other}"'))
def setup_offers(world, key, other):
    assert key in world.setup_fields and other in world.setup_fields and key != other


@then(parsers.parse('the default of "{key}" is off'))
def setup_default_off(world, key):
    assert world.setup_fields[key]["default"] in (False, "false", "0", 0)


@then("no pattern task is registered until the user turns it on")
def no_pattern_task_by_default(world):
    from relatedb_memory import dream

    world.monkeypatch.delenv("RELATEDB_DREAM_PATTERNS", raising=False)
    world.monkeypatch.setenv("RELATEDB_DREAM", "1")
    dream.register(world.ctx)
    assert not any("pattern" in key for key in world.ctx.aux_tasks)


@given("pattern inference is turned off")
def patterns_off(world):
    world.monkeypatch.setenv("RELATEDB_DREAM_PATTERNS", "0")


@given(parsers.parse("a pattern needs at least {count:d} distinct episodes"))
def min_support(world, count):
    world.min_support = count
    world.monkeypatch.setenv("RELATEDB_DREAM_PATTERN_MIN_EPISODES", str(count))


@given(parsers.parse('the observation "{text}" in episode "{episode}"'))
def given_observation(world, text, episode):
    _observe(world, text, episode)


@given(parsers.parse('a summary observation "{text}" of episode "{episode}"'))
def given_summary(world, text, episode):
    # A summary cites the episode it summarises, so it is the same evidence, not new support.
    _observe(world, text, episode)


@given(parsers.parse('a pattern "{text}" supported by {count:d} episodes'))
def given_pattern(world, text, count):
    _supported_pattern(world, text, count)


@given(parsers.parse('a USER.md containing "{text}"'))
def user_md_containing(world, text):
    path = _user_md(world)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


# -- When ---------------------------------------------------------------------


@when(parsers.parse('Dream Mode infers the pattern "{text}" from all observations'))
def when_infer(world, text):
    _infer(world, text, [o.id for o in world.observations])


@when(parsers.parse('a session asks "{query}"'))
def when_asks(world, query):
    world.answer = _provider(world).prefetch(query)


@when(parsers.parse("{count:d} more episodes support the pattern"))
def when_more_support(world, count):
    start = len(world.episodes)
    for i in range(start + 1, start + count + 1):
        _observe(world, f"Observation {i}: asks for the migration plan first", f"ep-{i}")
    _infer(world, world.pattern_text, [o.id for o in world.observations])


@when(parsers.parse('the user states "{text}" and Dream Mode retires the pattern because of it'))
def when_contradicted(world, text):
    from relatedb_memory import dream

    provider = _provider(world)
    raw = provider.handle_tool_call("relatedb_remember", {"text": text, "slot": "prefs/answer-order"})
    statement_id = json.loads(raw)["fact_id"]
    world.ctx.llm.script({"patterns": [], "retire": [{"pattern": _pattern(world)["id"], "statement": statement_id}]})
    dream.register(world.ctx, provider)
    world.ctx.fire_idle_task(PATTERN_TASK)
    world.answer = provider.prefetch(world.pattern_text)
    world.statement = text


@when(parsers.parse("Dream Mode is told that an observation contradicts the pattern"))
def when_observation_given_as_statement(world):
    from relatedb_memory import dream

    provider = _provider(world)
    world.ctx.llm.script(
        {"patterns": [], "retire": [{"pattern": _pattern(world)["id"], "statement": world.observations[0].id}]}
    )
    dream.register(world.ctx, provider)
    world.ctx.fire_idle_task(PATTERN_TASK)


@when(parsers.parse("{count:d} of its supporting observations are superseded"))
def when_superseded(world, count):
    provider = _provider(world)
    for obs in world.observations[:count]:
        provider.store.record_fact(
            fact_id=f"{obs.id}-v2", text=f"Corrected: {obs.text}", slot=obs.slot, valid_from=_day(20),
            recorded_at=_day(20), episode_id=obs.episode, about=[], embedding=world.embedder.embed_one(obs.text),
            origin="turn",
        )


@when("Dream Mode runs again")
def when_runs_again(world):
    from relatedb_memory import dream

    world.ctx.llm.script({"patterns": [], "retire": []})
    dream.register(world.ctx, _provider(world))
    world.ctx.fire_idle_task(PATTERN_TASK)


@when("a Dream Mode run is attempted")
def when_attempted(world):
    from relatedb_memory import dream

    provider = _provider(world)
    provider.store.record_episode(
        episode_id="ep-1", session="s-ep-1", kind="message", at=_day(1), text="session transcript", mentions=[]
    )
    world.ctx.llm.script({"observations": [
        {"scope": None, "kind": "observation", "topic": "answer-order", "text": OBSERVED_TEXT}
    ]})
    dream.register(world.ctx, _provider(world))
    if OBS_TASK in world.ctx.idle_tasks:
        world.ctx.fire_idle_task(OBS_TASK)


# -- Then ---------------------------------------------------------------------


@then(parsers.parse("one pattern is proposed with {count:d} supporting episodes"))
def one_pattern(world, count):
    patterns = _patterns(world)
    assert len(patterns) == 1
    assert patterns[0]["support"] == count and patterns[0]["status"] == "open"


@then("no pattern is proposed")
def no_pattern(world):
    assert _patterns(world, include_closed=True) == []


@then(parsers.parse('the recalled line for "{text}" is labelled as an inference'))
def line_is_inference(world, text):
    lines = [line for line in world.answer.splitlines() if text in line]
    assert len(lines) == 1, f"expected one recalled line for the pattern, got {lines}"
    world.line = lines[0]
    assert "inference" in world.line.lower()


@then(parsers.parse("that line states {count:d} sources"))
def line_states_sources(world, count):
    assert re.search(rf"\b{count}\s+sources\b", world.line)


@then("that line does not read as an instruction")
def line_not_instruction(world):
    label = world.line.replace(world.pattern_text, "")
    assert not INSTRUCTION_WORDS.search(label), f"recall wording reads as an instruction: {world.line!r}"
    assert not world.line.lstrip(" -*").lower().startswith(("always", "never", "do ", "use "))


@then(parsers.parse("the pattern is derived from its {observations:d} observations and their {episodes:d} episodes"))
def pattern_derived_from(world, observations, episodes):
    rows = _cypher(
        world,
        "MATCH (p:Fact {kind: 'pattern'})-[:DERIVED_FROM]->(s) WHERE p.closedAt IS NULL RETURN labels(s)[0] AS label, s.id AS id",
    )
    facts = {r["id"] for r in rows if r["label"] == "Fact"}
    eps = {r["id"] for r in rows if r["label"] == "Episode"}
    assert facts == {o.id for o in world.observations} and len(facts) == observations
    assert eps == world.episodes and len(eps) == episodes


@then(parsers.parse('USER.md still contains only "{text}"'))
def user_md_unchanged(world, text):
    assert _user_md(world).read_text(encoding="utf-8").strip() == text


@then(parsers.parse('the system prompt block does not mention "{text}"'))
def prompt_lacks(world, text):
    assert text not in _provider(world).system_prompt_block()


@then(parsers.parse('no USER.md proposal mentions "{text}"'))
def no_proposal(world, text):
    proposals = _provider(world).dream_proposals()
    assert all(text not in p["text"] for p in proposals)


@then(parsers.parse("the pattern has {count:d} supporting episodes"))
def pattern_support(world, count):
    assert _pattern(world)["support"] == count


@then("the pattern is still an inference")
def still_inference(world):
    pattern = _pattern(world)
    assert pattern["type"] == "pattern" and pattern["status"] == "open"
    rows = _cypher(world, "MATCH (f:Fact {kind: 'pattern'}) WHERE f.closedAt IS NULL RETURN f.id AS id")
    assert len(rows) == 1


@then(parsers.parse('no decision or statement mentions "{text}"'))
def no_promotion(world, text):
    provider = _provider(world)
    assert not any(text in f["text"] for f in provider.store.open_facts_with_slot_prefix("dream/"))
    rows = _cypher(
        world,
        "MATCH (f:Fact) WHERE f.closedAt IS NULL AND (f.kind IS NULL OR f.kind <> 'pattern') "
        "AND NOT f.slot STARTS WITH 'observation/' AND f.text CONTAINS $text RETURN f.id AS id",
        text=text,
    )
    assert rows == []


@then("recall no longer shows the pattern")
def recall_lacks_pattern(world):
    assert world.pattern_text not in world.answer


@then("the pattern is closed, not deleted, with its supporting links kept")
def pattern_closed(world):
    assert _patterns(world) == []
    closed = _pattern(world, include_closed=True)
    assert closed["status"] == "closed"
    raw = _provider(world).handle_tool_call(
        "relatedb_as_of", {"slot": f"pattern/{PATTERN_TOPIC}", "on": "2026-12-31T00:00:00Z"}
    )
    timeline = json.loads(raw)["timeline"]
    assert any(row["text"] == world.pattern_text and row["closedAt"] is not None for row in timeline)
    links = _cypher(world, "MATCH (p:Fact {kind: 'pattern'})-[:DERIVED_FROM]->(s) RETURN count(s) AS n")
    assert links[0]["n"] > 0


@then("no pattern task is registered")
def no_pattern_task(world):
    assert PATTERN_TASK not in world.ctx.idle_tasks
    assert OBS_TASK in world.ctx.idle_tasks


@then("the language model made no pattern call")
def no_pattern_call(world):
    assert [c for c in world.ctx.llm.calls if c.task == PATTERN_TASK or "pattern" in (c.purpose or "")] == []


@then(parsers.parse('the observation "{text}" is recorded by the run'))
def observation_recorded(world, text):
    rows = _cypher(world, "MATCH (f:Fact) WHERE f.text CONTAINS $text RETURN f.text AS text", text=text)
    assert rows, "typed observation extraction did not run with pattern inference off"


@then("the statement is still recalled")
def statement_recalled(world):
    assert world.statement in _provider(world).prefetch(world.statement)


@then("the pattern is still open")
def pattern_open(world):
    assert _pattern(world)["status"] == "open"
