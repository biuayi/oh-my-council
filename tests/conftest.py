from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_docs(tmp_path: Path) -> Iterator[Path]:
    """A temporary docs/ directory for a test run."""
    docs = tmp_path / "docs"
    docs.mkdir()
    yield docs
