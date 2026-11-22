"""Fake Hermes plugin context for Dream Mode e2e scenarios.

Modelled on the installed Hermes Agent v0.23.2 (2026.9.24), read from
``agent/plugin_llm.py`` (``PluginLlm.complete_structured``,
``PluginLlmStructuredResult``, ``PluginLlmUsage``, ``_check_task``),
``hermes_cli/plugins_idle_tasks.py`` (``PluginIdleTaskCtxMixin.register_idle_task``,
``build_idle_task_spec``, ``IdleTaskRun``) and ``hermes_cli/plugins_context.py``
(``PluginContext.register_auxiliary_task``).

Deliberate simplifications: the trust policy is reduced to "a task key must
have been registered through ``register_auxiliary_task``" (built-in task keys
and ``allow_*_override`` flags are not modelled); no state file, idle polling,
or threading; JSON schema validation of scripted responses is not performed.
Only the sync ``complete_structured`` is provided.

Nothing here implements Dream Mode behaviour.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence

MIN_INTERVAL_HOURS = 1.0
_FIRST_RUN = ("defer", "immediate")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class UnscriptedLlmCall(AssertionError):
    """The code under test called ``ctx.llm`` with no response queued."""


class PluginLlmTrustError(PermissionError):
    """Mirrors ``agent.plugin_llm.PluginLlmTrustError`` for unregistered task keys."""


@dataclass
class PluginLlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Optional[float] = None


@dataclass
class PluginLlmStructuredResult:
    text: str
    provider: str
    model: str
    agent_id: str
    usage: PluginLlmUsage = field(default_factory=PluginLlmUsage)
    parsed: Optional[Any] = None
    content_type: str = "text"
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IdleTaskRun:
    name: str
    idle_for_seconds: float
    last_run_at: Optional[str]
    run_count: int


class FakeClock:
    """Injectable clock; ``advance`` moves it, nothing else does."""

    def __init__(self, start: Optional[datetime] = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, *, hours: float = 0, minutes: float = 0, seconds: float = 0) -> datetime:
        self._now += timedelta(hours=hours, minutes=minutes, seconds=seconds)
        return self._now


@dataclass(frozen=True)
class LlmCall:
    """One recorded ``complete_structured`` call: every keyword the real method takes."""

    instructions: str
    input: tuple
    json_schema: Optional[Any]
    json_mode: bool
    schema_name: Optional[str]
    system_prompt: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    temperature: Optional[float]
    max_tokens: Optional[int]
    timeout: Optional[float]
    agent_id: Optional[str]
    profile: Optional[str]
    purpose: Optional[str]
    task: Optional[str]  # the model slot: a registered auxiliary task key, or None for the main model


class FakeLlm:
    """Scripted ``ctx.llm``: returns queued responses in order and records every call."""

    def __init__(self, aux_tasks: Optional[dict[str, dict[str, Any]]] = None, plugin_id: str = "relatedb-memory") -> None:
        self._aux_tasks = aux_tasks if aux_tasks is not None else {}
        self._plugin_id = plugin_id
        self._queue: list[dict[str, Any]] = []
        self.calls: list[LlmCall] = []
        self.usage = PluginLlmUsage()

    def script(self, parsed: Any = None, *, text: Optional[str] = None, usage: Optional[PluginLlmUsage] = None,
               provider: str = "fake-provider", model: str = "fake-model") -> "FakeLlm":
        """Queue one response. ``parsed`` is serialised to ``text`` unless ``text`` is given."""
        if text is None:
            text = json.dumps(parsed)
        self._queue.append(dict(parsed=parsed, text=text, usage=usage, provider=provider, model=model))
        return self

    @property
    def pending(self) -> int:
        return len(self._queue)

    def assert_exhausted(self) -> None:
        assert not self._queue, f"{len(self._queue)} scripted LLM response(s) were never consumed"

    def complete_structured(
        self, *, instructions: str, input: Sequence[Any], json_schema: Optional[Any] = None,
        json_mode: bool = False, schema_name: Optional[str] = None, system_prompt: Optional[str] = None,
        provider: Optional[str] = None, model: Optional[str] = None, temperature: Optional[float] = None,
        max_tokens: Optional[int] = None, timeout: Optional[float] = None, agent_id: Optional[str] = None,
        profile: Optional[str] = None, purpose: Optional[str] = None, task: Optional[str] = None,
    ) -> PluginLlmStructuredResult:
        slot = (task or "").strip()
        if slot and slot.lower() != "auto" and slot not in self._aux_tasks:
            raise PluginLlmTrustError(
                f"Plugin {self._plugin_id!r} cannot route through auxiliary task {slot!r}: "
                "it was not registered via ctx.register_auxiliary_task()"
            )
        call = LlmCall(instructions, tuple(input), json_schema, json_mode, schema_name, system_prompt, provider,
                       model, temperature, max_tokens, timeout, agent_id, profile, purpose, task)
        self.calls.append(call)
        if not self._queue:
            raise UnscriptedLlmCall(
                f"unscripted ctx.llm.complete_structured call #{len(self.calls)} "
                f"(purpose={purpose!r}, task={task!r}); queue a response with ctx.llm.script(...)"
            )
        scripted = self._queue.pop(0)
        usage = scripted["usage"] or PluginLlmUsage(input_tokens=10, output_tokens=5)
        if not usage.total_tokens:
            # Copy: never mutate an object the test passed in and may reuse.
            usage = replace(usage, total_tokens=usage.input_tokens + usage.output_tokens)
        for name in ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens"):
            setattr(self.usage, name, getattr(self.usage, name) + getattr(usage, name))
        if usage.cost_usd is not None:
            self.usage.cost_usd = (self.usage.cost_usd or 0.0) + usage.cost_usd
        parsed, is_json = None, False
        if json_mode or json_schema is not None:
            parsed = scripted["parsed"]
            is_json = parsed is not None
            if not is_json:
                # Like the real host, parse scripted raw text; text that is not JSON stays text.
                try:
                    parsed = json.loads(scripted["text"])
                    is_json = True
                except ValueError:
                    parsed = None
        return PluginLlmStructuredResult(
            text=scripted["text"], provider=scripted["provider"], model=scripted["model"],
            agent_id=agent_id or "default", usage=usage, parsed=parsed,
            content_type="json" if is_json else "text",
            audit={"plugin_id": self._plugin_id, "purpose": purpose or "", "profile": profile or "",
                   "schema_name": schema_name or "", "task": slot if slot.lower() != "auto" else ""},
        )


@dataclass(frozen=True)
class IdleTaskSpec:
    name: str
    fn: Callable[[IdleTaskRun], Optional[str]]
    interval_hours: float
    min_idle_hours: float
    first_run: str


class FakePluginContext:
    """Stand-in for the Hermes ``PluginContext`` a plugin's ``register(ctx)`` receives."""

    def __init__(self, clock: Optional[FakeClock] = None, plugin_id: str = "relatedb-memory") -> None:
        self.plugin_id = plugin_id
        self.clock = clock or FakeClock()
        self.aux_tasks: dict[str, dict[str, Any]] = {}
        self.idle_tasks: dict[str, IdleTaskSpec] = {}
        self.llm = FakeLlm(self.aux_tasks, plugin_id)
        self._runs: dict[str, tuple[Optional[datetime], int]] = {}

    def register_idle_task(
        self, name: str, fn: Callable[[IdleTaskRun], Optional[str]], *, interval_hours: float,
        min_idle_hours: float = 2.0, first_run: str = "defer",
    ) -> IdleTaskSpec:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"idle task name {name!r} must match {_NAME_RE.pattern}")
        if not callable(fn):
            raise ValueError(f"idle task {name!r}: fn must be callable")
        if first_run not in _FIRST_RUN:
            raise ValueError(f"idle task {name!r}: first_run must be one of {_FIRST_RUN}")
        try:
            interval, idle = float(interval_hours), float(min_idle_hours)
        except (TypeError, ValueError):
            raise ValueError(f"idle task {name!r}: interval_hours and min_idle_hours must be numbers") from None
        if not (math.isfinite(interval) and math.isfinite(idle)):
            raise ValueError(f"idle task {name!r}: interval_hours and min_idle_hours must be finite")
        interval = max(interval, MIN_INTERVAL_HOURS)
        spec = IdleTaskSpec(name, fn, interval, idle if idle >= 0 else 0.0, first_run)
        self.idle_tasks[name] = spec
        self._runs.pop(name, None)
        return spec

    def register_auxiliary_task(
        self, key: str, *, display_name: str, description: str,
        defaults: Optional[dict[str, Any]] = None, inherit_from: Optional[str] = None,
    ) -> dict[str, Any]:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("auxiliary task key must be a non-empty string")
        entry = dict(key=key, display_name=display_name, description=description,
                     defaults=dict(defaults or {}), inherit_from=inherit_from)
        self.aux_tasks[key] = entry
        return entry

    def fire_idle_task(self, name: str, *, idle_for_seconds: Optional[float] = None) -> Optional[str]:
        """Run a registered idle task now, as the host would once it is due.

        Does not enforce ``interval_hours`` or ``min_idle_hours``; tests assert
        those through ``idle_tasks[name]`` and the clock. ``idle_for_seconds``
        defaults to ``min_idle_hours`` of the spec.
        """
        if name not in self.idle_tasks:
            raise KeyError(f"no idle task {name!r} registered; have {sorted(self.idle_tasks)}")
        spec = self.idle_tasks[name]
        last, count = self._runs.get(name, (None, 0))
        idle = spec.min_idle_hours * 3600 if idle_for_seconds is None else idle_for_seconds
        run = IdleTaskRun(name=name, idle_for_seconds=float(idle),
                          last_run_at=last.isoformat() if last else None, run_count=count)
        try:
            return spec.fn(run)
        finally:
            # The real host records the run whether ``fn`` returns or raises. It logs the
            # exception; this fake re-raises it so a failing task fails the test.
            self._runs[name] = (self.clock.now(), count + 1)
