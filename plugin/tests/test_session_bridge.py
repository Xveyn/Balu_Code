"""Tests for SessionBridge."""

from __future__ import annotations

import pytest

from plugin.services.project_store import ProjectStore
from plugin.services.session_bridge import SessionBridge


@pytest.mark.asyncio
async def test_get_or_create_returns_stored_id_when_set(tmp_path):
    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project(name="p1", root_path=str(tmp_path), config_yaml=None)
    store.set_opencode_session_id(project.id, "ses_existing")

    async def fail_create() -> str:
        raise AssertionError("must not create when session exists")

    bridge = SessionBridge(store=store, create_session=fail_create)
    sid = await bridge.get_or_create(project.id)
    assert sid == "ses_existing"
    store.close()


@pytest.mark.asyncio
async def test_get_or_create_creates_when_missing(tmp_path):
    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project(name="p2", root_path=str(tmp_path), config_yaml=None)

    async def fake_create() -> str:
        return "ses_new"

    bridge = SessionBridge(store=store, create_session=fake_create)
    sid = await bridge.get_or_create(project.id)
    assert sid == "ses_new"
    reloaded = store.get_project(project.id)
    assert reloaded.opencode_session_id == "ses_new"
    store.close()
