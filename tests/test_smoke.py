"""Sprint 0 exit criterion: the package installs and imports cleanly, and pytest
runs green from an otherwise-empty test suite.
"""

import vixharvest


def test_package_imports():
    assert vixharvest.__version__
