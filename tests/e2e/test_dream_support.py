"""Self-test for the shared Dream Mode harness (``dream_support`` and the pending marker)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dream_support import (
    FakeClock,
    FakePluginContext,
    PluginLlmTrustError,
    PluginLlmUsage,
    UnscriptedLlmCall,
)

E2E_DIR = Path(__file__).parent


def test_llm_returns_scripted_responses_in_order_and_records_calls(fake_ctx):
    fake_ctx.llm.script({"n": 1}).script({"n": 2}, usage=PluginLlmUsage(input_tokens=7, output_tokens=3))
    schema = {"type": "object"}
    first = fake_ctx.llm.complete_structured(instructions="a", input=["x"], json_schema=schema, purpose="p1")
    second = fake_ctx.llm.complete_structured(instructions="b", input=["y"], json_schema=schema)
    assert (first.parsed, second.parsed) == ({"n": 1}, {"n": 2})
    assert first.content_type == "json" and first.audit["purpose"] == "p1"
    assert [c.instructions for c in fake_ctx.llm.calls] == ["a", "b"]
    assert fake_ctx.llm.calls[0].json_schema == schema and fake_ctx.llm.calls[0].input == ("x",)
    assert second.usage.total_tokens == 10
    assert fake_ctx.llm.usage.total_tokens == 25
    fake_ctx.llm.assert_exhausted()


def test_llm_fails_loudly_on_unscripted_call(fake_ctx):
    with pytest.raises(UnscriptedLlmCall):
        fake_ctx.llm.complete_structured(instructions="a", input=[])
    assert len(fake_ctx.llm.calls) == 1  # the attempt is still recorded


def test_llm_assert_exhausted_flags_unused_script(fake_ctx):
    fake_ctx.llm.script({})
    with pytest.raises(AssertionError):
        fake_ctx.llm.assert_exhausted()


def test_llm_task_must_be_a_registered_auxiliary_task(fake_ctx):
    fake_ctx.llm.script({"ok": True}).script({"ok": True})
    with pytest.raises(PluginLlmTrustError):
        fake_ctx.llm.complete_structured(instructions="a", input=[], task="dream")
    fake_ctx.register_auxiliary_task("dream", display_name="Dream", description="d")
    result = fake_ctx.llm.complete_structured(instructions="a", input=[], json_mode=True, task="dream")
    assert result.audit["task"] == "dream"
    assert fake_ctx.llm.calls[-1].task == "dream"


def test_idle_task_registration_mirrors_hermes_validation(fake_ctx):
    spec = fake_ctx.register_idle_task("dream", lambda run: None, interval_hours=0.1, min_idle_hours=-3)
    assert (spec.interval_hours, spec.min_idle_hours, spec.first_run) == (1.0, 0.0, "defer")
    with pytest.raises(ValueError):
        fake_ctx.register_idle_task("Bad Name", lambda run: None, interval_hours=2)
    with pytest.raises(ValueError):
        fake_ctx.register_idle_task("ok", "not callable", interval_hours=2)
    with pytest.raises(ValueError):
        fake_ctx.register_idle_task("ok", lambda run: None, interval_hours=2, first_run="never")
    with pytest.raises(ValueError):
        fake_ctx.register_idle_task("ok", lambda run: None, interval_hours=float("inf"))


def test_idle_task_fires_with_run_metadata_and_clock(fake_ctx):
    seen = []
    fake_ctx.register_idle_task("dream", lambda run: seen.append(run) or "done", interval_hours=24, min_idle_hours=2)
    assert fake_ctx.fire_idle_task("dream") == "done"
    fake_ctx.clock.advance(hours=24)
    fake_ctx.fire_idle_task("dream", idle_for_seconds=5)
    assert (seen[0].run_count, seen[0].last_run_at, seen[0].idle_for_seconds) == (0, None, 7200.0)
    assert (seen[1].run_count, seen[1].idle_for_seconds) == (1, 5.0)
    assert seen[1].last_run_at == "2026-01-01T00:00:00+00:00"
    with pytest.raises(KeyError):
        fake_ctx.fire_idle_task("missing")


def test_clock_is_injectable():
    clock = FakeClock()
    ctx = FakePluginContext(clock=clock)
    clock.advance(minutes=90)
    assert ctx.clock.now().isoformat() == "2026-01-01T01:30:00+00:00"


def _run_pytest(tmp_path, body: str):
    (tmp_path / "conftest.py").write_text((E2E_DIR / "conftest.py").read_text())
    (tmp_path / "dream_support.py").write_text((E2E_DIR / "dream_support.py").read_text())
    (tmp_path / "test_sample.py").write_text(textwrap.dedent(body))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rxX", "-q", str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    return proc.returncode, proc.stdout


def test_pending_marker_passing_test_fails_the_suite(tmp_path):
    code, out = _run_pytest(tmp_path, """
        import pytest

        @pytest.mark.pending_999
        def test_passes():
            assert True
    """)
    assert code != 0
    assert "XPASS(strict)" in out or "FAILED" in out


def test_pending_marker_failing_test_is_xfail_with_reason(tmp_path):
    code, out = _run_pytest(tmp_path, """
        import pytest

        @pytest.mark.pending_999
        def test_fails():
            assert False
    """)
    assert code == 0
    assert "XFAIL" in out and "Pending #999" in out


def test_llm_parses_scripted_raw_text_when_json_is_requested(fake_ctx):
    fake_ctx.llm.script(text='{"facts": []}').script(text="not json").script(text='{"facts": []}')
    parsed = fake_ctx.llm.complete_structured(instructions="a", input=["x"], json_mode=True)
    assert parsed.parsed == {"facts": []} and parsed.content_type == "json"
    plain = fake_ctx.llm.complete_structured(instructions="a", input=["x"], json_mode=True)
    assert plain.parsed is None and plain.content_type == "text"
    unrequested = fake_ctx.llm.complete_structured(instructions="a", input=["x"])
    assert unrequested.parsed is None and unrequested.content_type == "text"


def test_llm_does_not_mutate_a_reused_usage_object(fake_ctx):
    usage = PluginLlmUsage(input_tokens=7, output_tokens=3)
    fake_ctx.llm.script({}, usage=usage).script({}, usage=usage)
    for _ in range(2):
        fake_ctx.llm.complete_structured(instructions="a", input=["x"], json_mode=True)
    assert usage.total_tokens == 0
    assert fake_ctx.llm.usage.total_tokens == 20


def test_idle_task_that_raises_still_counts_as_a_run(fake_ctx):
    seen = []

    def boom(run):
        seen.append(run.run_count)
        raise RuntimeError("boom")

    fake_ctx.register_idle_task("dream", boom, interval_hours=1, min_idle_hours=1)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            fake_ctx.fire_idle_task("dream")
    assert seen == [0, 1]
