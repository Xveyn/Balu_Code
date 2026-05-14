"""Maps Balu_Code project_id <-> opencode session_id.

Persists in projects.opencode_session_id (added by Task 11 migration).
On first chat to a project, calls the injected create_session() to ask
opencode for a fresh session id, then stores it. Subsequent calls return
the stored id.

NOTE: opencode v1.14.50's POST /session does not accept a directory parameter;
the session inherits the working directory from the opencode server's CWD
(set at server spawn). Project-to-session 1:1 mapping is preserved by
restarting the server in the right CWD when a project becomes active —
that's a Task 13 concern.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .project_store import ProjectStore


@dataclass
class SessionBridge:
    store: ProjectStore
    create_session: Callable[[], Awaitable[str]]  # async () -> session_id

    async def get_or_create(self, project_id: int) -> str:
        project = self.store.get_project(project_id)
        if project.opencode_session_id:
            return project.opencode_session_id
        session_id = await self.create_session()
        self.store.set_opencode_session_id(project_id, session_id)
        return session_id


__all__ = ["SessionBridge"]
