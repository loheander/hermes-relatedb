"""Scenarios tagged ``@pending_4``, ``@pending_6``, ``@pending_7``, ``@pending_8``, ``@pending_9``, or ``@pending_10`` are strict xfails until their story lands.

Each implementing story removes its tag from the feature file, so a premature
pass fails the suite instead of going unnoticed.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("pending_4"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #4"))
        if item.get_closest_marker("pending_6"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #6"))
        if item.get_closest_marker("pending_7"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #7"))
        if item.get_closest_marker("pending_8"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #8"))
        if item.get_closest_marker("pending_9"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #9"))
        if item.get_closest_marker("pending_10"):
            item.add_marker(pytest.mark.xfail(strict=True, reason="Pending #10"))
