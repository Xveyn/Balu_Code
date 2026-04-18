"""Tests for plugin.schemas Pydantic models."""
from __future__ import annotations

from plugin.schemas import RepoMapResponse


def test_repo_map_response_round_trip():
    original = RepoMapResponse(
        text="=== a.py\n",
        file_count=1,
        truncated_files=["b.py"],
        total_bytes=11,
    )
    data = original.model_dump()
    restored = RepoMapResponse.model_validate(data)
    assert restored == original


def test_repo_map_response_defaults_to_empty_truncated_list():
    r = RepoMapResponse(text="", file_count=0, total_bytes=0)
    assert r.truncated_files == []


def test_repo_map_response_rejects_negative_counts():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepoMapResponse(text="x", file_count=-1, total_bytes=1)
    with pytest.raises(ValidationError):
        RepoMapResponse(text="x", file_count=0, total_bytes=-1)
