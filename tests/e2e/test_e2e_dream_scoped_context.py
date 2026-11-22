"""Acceptance scenarios for scoped decisions and fresh-session context (#59, part of #33).

The scenarios live in ``features/dream_scoped_context.feature``; this module
binds each step to the public seams only. It pins the contract proposed in
ADR-0013 (Proposed); wording changes in the feature file are the review surface::

    dream.register(ctx, provider)              # registers idle task "relatedb-dream"
    ctx.fire_idle_task("relatedb-dream")       # one Dream Mode pass over recent episodes
    provider.initialize(sid, hermes_home=..., embedder=..., project="project-a")
    provider.prefetch(query) -> str            # recall for the session's scope
    provider.dream_proposals() -> list[dict]   # {"id", "target": "USER.md", "text", "status"}
    provider.approve_dream_proposal(id)        # the only path that writes USER.md
    provider.dream_context() -> str            # maintained context for the session's scope
    provider.handle_tool_call("relatedb_as_of", {"slot": "dream/<scope>/<topic>", "on": ...})

The language model is scripted through the fake Hermes context from the
harness (``fake_ctx``); a pass returns ``{"observations": [{"scope", "kind",
"topic", "text"}]}`` where ``scope`` is null for personal preferences.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider

scenarios("features/dream_scoped_context.feature")

EMBEDDING_DIM = 4
TASK = "relatedb-dream"
SCOPED_TOPIC = "database"


@pytest.fixture
def world(tmp_path, fake_ctx, monkeypatch):
    state = SimpleNamespace(
        home=tmp_path,
        ctx=fake_ctx,
        embedder=FakeEmbedder(dim=EMBEDDING_DIM),
        monkeypatch=monkeypatch,
        providers=[],
        answers={},
        proposals=[],
        episodes=0,
        baseline=None,
        admin=None,
    )
    yield state
    for provider in state.providers:
        try:
            provider.shutdown()
        except Exception:
            pass


# -- helpers (public seams only) ----------------------------------------------


def _provider(world, project=None, session="s-fresh"):
    # One process owns the store at a time (single writer), so a new session replaces the last one.
    for previous in world.providers:
        try:
            previous.shutdown()
        except Exception:
            pass
    world.providers.clear()
    world.admin = None
    provider = RelateDBMemoryProvider()
    kwargs = dict(hermes_home=str(world.home), embedder=world.embedder)
    if project is not None:
        kwargs["project"] = project
    provider.initialize(session, **kwargs)
    world.providers.append(provider)
    return provider


def _admin(world):
    """The provider that owns the store the Dream Mode pass runs against."""
    if world.admin is None:
        world.admin = _provider(world, session="s-admin")
    return world.admin


def _run_pass(world, observations, at=None):
    from relatedb_memory import dream  # not implemented yet: fails until the Phase 2a story lands

    provider = _admin(world)
    world.episodes += 1
    when_iso = at or "2026-03-01T10:00:00Z"
    provider.store.record_episode(
        episode_id=f"ep-{world.episodes}", session="s-admin", kind="message", at=when_iso,
        text="session transcript", mentions=[],
    )
    world.ctx.llm.script({"observations": observations})
    dream.register(world.ctx, provider)
    world.ctx.fire_idle_task(TASK)
    return provider


def _decision(text, project, topic=SCOPED_TOPIC):
    return {"scope": project, "kind": "decision", "topic": topic, "text": text}


def _preference(text):
    return {"scope": None, "kind": "preference", "topic": "style", "text": text}


def _user_md(world):
    return world.home / "memories" / "USER.md"


def _day_iso(day):
    return f"2026-03-{int(day):02d}T10:00:00Z"


# -- Given --------------------------------------------------------------------


@given(parsers.parse('a Dream Mode run that recorded the decision "{text}" in project "{project}"'))
def run_recorded_decision(world, text, project):
    _run_pass(world, [_decision(text, project)])


@given(parsers.parse('a Dream Mode run on {day:d} March that recorded the decision "{text}" in project "{project}"'))
def dated_run_recorded_decision(world, day, text, project):
    _run_pass(world, [_decision(text, project)], at=_day_iso(day))


@given(parsers.parse('a USER.md containing "{text}"'))
def user_md_containing(world, text):
    path = _user_md(world)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


@given(parsers.parse('a Dream Mode run that observed the durable preference "{text}"'))
def run_observed_preference(world, text):
    _run_pass(world, [_preference(text)])
    world.proposals = _admin(world).dream_proposals()


@given("the user approves that proposal")
def given_approves(world):
    _approve_first(world)


@given("Dream Mode is turned off")
def dream_off(world):
    world.monkeypatch.setenv("RELATEDB_DREAM", "0")


@given(parsers.parse('a stored fact "{text}" recorded before Dream Mode existed'))
def stored_phase1_fact(world, text):
    provider = _admin(world)
    provider.store.record_episode(
        episode_id="ep-p1", session="s-admin", kind="message", at="2026-03-01T10:00:00Z", text=text, mentions=[]
    )
    provider.store.record_fact(
        fact_id="f-p1", text=text, slot="billing/database", valid_from="2026-03-01T10:00:00Z",
        recorded_at="2026-03-01T10:00:00Z", episode_id="ep-p1", about=["billing"],
        embedding=world.embedder.embed_one("Which database does billing use?"),
    )
    world.baseline = _provider(world, session="s-baseline").prefetch("Which database does billing use?")


@given(parsers.parse("a context size budget of {chars:d} characters"))
def size_budget(world, chars):
    world.monkeypatch.setenv("RELATEDB_DREAM_CONTEXT_CHARS", str(chars))


@given(parsers.parse('a Dream Mode run that recorded {count:d} distinct decisions in project "{project}"'))
def run_recorded_many(world, count, project):
    observations = [_decision(f"Decision {i}: use component number {i} for subsystem {i}", project, topic=f"topic-{i}")
                    for i in range(count)]
    _run_pass(world, observations)


# -- When ---------------------------------------------------------------------


@when(parsers.parse('a fresh session in project "{project}" asks "{query}"'))
def fresh_session_asks(world, project, query):
    world.answers[project] = _provider(world, project=project).prefetch(query)


@when("the user approves that proposal")
def when_approves(world):
    _approve_first(world)


@when("a Dream Mode run is attempted")
def run_attempted(world):
    from relatedb_memory import dream

    dream.register(world.ctx, _admin(world))
    if TASK in world.ctx.idle_tasks:
        world.ctx.fire_idle_task(TASK)


def _approve_first(world):
    provider = _admin(world)
    proposals = provider.dream_proposals()
    assert proposals, "expected at least one USER.md proposal to approve"
    provider.approve_dream_proposal(proposals[0]["id"])


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('the answer in project "{project}" contains "{text}"'))
def answer_contains(world, project, text):
    assert text in world.answers[project]


@then(parsers.parse('the answer in project "{project}" does not contain "{text}"'))
def answer_lacks(world, project, text):
    assert text not in world.answers[project]


@then(parsers.parse('no USER.md proposal mentions "{text}"'))
def no_proposal_mentions(world, text):
    proposals = _admin(world).dream_proposals()
    assert all(text not in p["text"] for p in proposals)
    assert not _user_md(world).exists() or text not in _user_md(world).read_text(encoding="utf-8")


@then(parsers.parse('one USER.md proposal contains "{text}"'))
def one_proposal_contains(world, text):
    matching = [p for p in _admin(world).dream_proposals() if text in p["text"]]
    assert len(matching) == 1
    assert matching[0]["target"] == "USER.md" and matching[0]["status"] == "pending"


@then(parsers.parse('USER.md still contains only "{text}"'))
def user_md_unchanged(world, text):
    assert _user_md(world).read_text(encoding="utf-8").strip() == text


@then(parsers.parse('USER.md contains "{first}" and "{second}"'))
def user_md_contains_both(world, first, second):
    content = _user_md(world).read_text(encoding="utf-8")
    assert first in content and second in content


@then(parsers.parse('the history of the billing decision on {day:d} March shows "{text}"'))
def history_shows(world, day, text):
    raw = _admin(world).handle_tool_call(
        "relatedb_as_of", {"slot": f"dream/project-a/{SCOPED_TOPIC}", "on": _day_iso(day)}
    )
    assert text in json.loads(raw)["trueOn"]


@then(parsers.parse('the answer in project "{project}" is identical to the Phase 1 answer'))
def identical_to_phase1(world, project):
    assert world.answers[project] == world.baseline


@then("the language model was never called")
def llm_never_called(world):
    assert world.ctx.llm.calls == []


@then(parsers.parse('the maintained context for project "{project}" is at most {chars:d} characters'))
def context_within_budget(world, project, chars):
    context = _provider(world, project=project).dream_context()
    assert 0 < len(context) <= chars
