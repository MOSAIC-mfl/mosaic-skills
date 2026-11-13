"""Fixtures of the skill's tests: the mosaic-standard checkout (required) and the catalogue (optional)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest


def _standard() -> Path | None:
    if os.environ.get("MOSAIC_STANDARD"):
        return Path(os.environ["MOSAIC_STANDARD"]).resolve()
    sibling = Path(__file__).resolve().parents[4] / "mosaic-standard"  # next to the mosaic-skills checkout
    if (sibling / "schema" / "landscape").is_dir():
        return sibling
    saved = Path.home() / ".mosaic" / "workspace.json"
    if saved.exists():
        return Path(json.loads(saved.read_text(encoding="utf-8"))["standard"])
    return None


_found = _standard()
if not _found or not (_found / "schema" / "landscape").is_dir():
    pytest.skip(
        "needs a mosaic-standard checkout: set MOSAIC_STANDARD (or run scripts/setup.py)", allow_module_level=True
    )
STANDARD: Path = _found


@pytest.fixture
def catalog() -> Iterator[Path]:
    path = os.environ.get("MOSAIC_CATALOG")
    if not path or not (Path(path) / "records").is_dir() or not (Path(path) / "landscapes").is_dir():
        pytest.skip("needs a catalogue checkout (records/ and landscapes/): set MOSAIC_CATALOG")
    yield Path(path)
