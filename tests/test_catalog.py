"""Invariants on the BAYERN_DATASETS catalog.

These catch accidental regressions (missing keys, illegal kinds, wrong
extensions) rather than verifying the live server — a mismatched URL is
caught by test_tile_generation.py / the probe tool.
"""
from __future__ import annotations

import pytest

from backend.downloader import BAYERN_DATASETS, BAYERN_CATEGORY_LABELS


RAW_REQUIRED_KEYS = {"label", "category", "description", "ext", "kind", "url_path"}
WMS_REQUIRED_KEYS = {"label", "category", "description", "ext", "kind", "base_url", "layer", "mime"}
ALLOWED_CATEGORIES = set(BAYERN_CATEGORY_LABELS.keys())


@pytest.mark.parametrize("key,meta", list(BAYERN_DATASETS.items()))
def test_entry_has_correct_shape(key, meta):
    assert meta["kind"] in {"raw", "wms"}, f"{key}: unknown kind {meta.get('kind')!r}"
    assert meta["category"] in ALLOWED_CATEGORIES, f"{key}: category not in catalog labels"
    required = RAW_REQUIRED_KEYS if meta["kind"] == "raw" else WMS_REQUIRED_KEYS
    missing = required - set(meta)
    assert not missing, f"{key}: missing required fields {missing}"
    assert meta["ext"].startswith("."), f"{key}: ext must start with a dot"


@pytest.mark.parametrize("key,meta", [(k, v) for k, v in BAYERN_DATASETS.items() if v["kind"] == "raw"])
def test_raw_entry_layout_defaults(key, meta):
    # url_path is required and must not start/end with slash.
    assert "/" not in (meta["url_path"][:1] + meta["url_path"][-1:]), \
        f"{key}: url_path must not start or end with '/'"
    # grid_km default 1; tile_prefix default "32". Overrides must be sane.
    grid = meta.get("grid_km", 1)
    assert grid in (1, 2), f"{key}: unexpected grid_km={grid}"
    prefix = meta.get("tile_prefix", "32")
    assert prefix in ("", "32"), f"{key}: unexpected tile_prefix={prefix!r}"


def test_probe_candidates_include_current_path():
    """Every raw entry's probe_candidates list should at least mention its current path."""
    for key, meta in BAYERN_DATASETS.items():
        if meta["kind"] != "raw":
            continue
        candidates = meta.get("probe_candidates", [])
        # Current path being probeable is just a useful sanity signal; we don't
        # strictly require it — the API injects it automatically — but the
        # catalog author should be explicit.
        assert meta["url_path"] in candidates, (
            f"{key}: probe_candidates should list the current url_path "
            f"({meta['url_path']!r}); got {candidates}"
        )


def test_known_verified_datasets():
    """Regression guard: these were verified against the live server."""
    for key in ("dop20", "lod2"):
        meta = BAYERN_DATASETS[key]
        assert meta.get("verified", True), f"{key} should stay verified"


def test_laser_marked_unverified():
    """Until we pin the laser path, keep the warning on."""
    assert BAYERN_DATASETS["laser"].get("verified", True) is False
