"""Shared e2e configuration.

Any marker named ``pending_<n>`` (a ``@pending_<n>`` tag in a feature file)
becomes a strict xfail with reason ``Pending #<n>``. Each implementing story
removes its tag from the feature file, so a premature pass fails the suite
instead of going unnoticed.

The ``fake_ctx`` fixture exposes the fake Hermes plugin context from
``dream_support`` for Dream Mode scenarios.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Make ``dream_support`` importable from here and from every step module.
sys.path.insert(0, str(Path(__file__).parent))

_PENDING = re.compile(r"^pending_(\d+)$")
_FEATURE_TAG = re.compile(r"@(pending_\d+)\b")


def pytest_configure(config):
    """Register every ``@pending_<n>`` tag used in a feature file, so strict markers keep working."""
    declared = {line.split(":")[0].strip() for line in config.getini("markers")}
    for feature in (Path(__file__).parent / "features").glob("*.feature"):
        for tag in sorted(set(_FEATURE_TAG.findall(feature.read_text(encoding="utf-8")))):
            if tag not in declared:
                config.addinivalue_line("markers", f"{tag}: acceptance scenario awaiting its story; strict xfail")
                declared.add(tag)


def pytest_collection_modifyitems(items):
    for item in items:
        seen = set()
        for marker in item.iter_markers():
            match = _PENDING.match(marker.name)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                item.add_marker(pytest.mark.xfail(strict=True, reason=f"Pending #{match.group(1)}"))


@pytest.fixture
def fake_ctx():
    from dream_support import FakePluginContext  # lazy: a harness error must not break unrelated e2e tests

    return FakePluginContext()
