"""Pytest config for OpenMap_Unifier.

`needs_network` marks tests that hit live Bayern servers (DOM-Mesh SLPK range
requests). They are skipped unless the DOMMESH_LIVE env var is set, so the
default `pytest` run stays offline & fast.
"""
import os
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_network: hits live servers; "
                            "run only when DOMMESH_LIVE is set")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DOMMESH_LIVE"):
        return
    skip = pytest.mark.skip(reason="needs_network: set DOMMESH_LIVE=1 to run")
    for item in items:
        if "needs_network" in item.keywords:
            item.add_marker(skip)
