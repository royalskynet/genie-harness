"""Pytest bridge for the self-checks in this directory.

The test files here are written for the plain-python entry point
(`python3 router/test_router.py`, what CI runs): each `test_*` function takes
a `fails` list and appends human-readable failure lines instead of asserting,
so one run reports every failure at once. This fixture hands pytest the same
list and turns a non-empty list into a test failure at teardown, so
`python3 -m pytest router/test_router.py` runs the same checks instead of
erroring on a missing fixture.
"""
import pytest


@pytest.fixture
def fails():
    collected = []
    yield collected
    if collected:
        pytest.fail("FAIL (%d):\n  %s" % (len(collected), "\n  ".join(collected)),
                    pytrace=False)
