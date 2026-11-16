"""Scenarios tagged ``@pending_4`` are strict xfails until #4 lands.

#4 removes the tag from the feature file, so a premature pass fails the suite
instead of going unnoticed.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("pending_4"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #4"))
