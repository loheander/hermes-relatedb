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

from dream_support import FakePluginContext  # noqa: E402

_PENDING = re.compile(r"^pending_(\d+)$")


def pytest_collection_modifyitems(items):
    for item in items:
        for marker in item.iter_markers():
            match = _PENDING.match(marker.name)
            if match:
                item.add_marker(pytest.mark.xfail(strict=True, reason=f"Pending #{match.group(1)}"))


@pytest.fixture
def fake_ctx():
    return FakePluginContext()
