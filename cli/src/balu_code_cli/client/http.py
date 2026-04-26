"""BaluCodeHttpClient — httpx-based REST wrapper."""

from __future__ import annotations

import httpx


class BaluCodeHttpClient:
    def __init__(self, server_url: str, api_key: str) -> None:
        self._base = server_url.rstrip("/") + "/api/plugins/balu_code"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _get(self, path: str) -> dict:
        with httpx.Client(headers=self._headers, timeout=10) as client:
            r = client.get(self._base + path)
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        with httpx.Client(headers=self._headers, timeout=10) as client:
            r = client.post(self._base + path, json=json or {})
            r.raise_for_status()
            return r.json()

    def health(self) -> dict:
        return self._get("/health")

    def list_models(self) -> list[str]:
        data = self._get("/models")
        return [m["name"] for m in data.get("models", [])]

    def create_project(self, name: str, root_path: str) -> dict:
        return self._post("/projects", {"name": name, "root_path": root_path})

    def start_index(self, project_id: int) -> dict:
        return self._post(f"/projects/{project_id}/index")

    def index_status(self, project_id: int, job_id: str) -> dict:
        return self._get(f"/projects/{project_id}/index/status/{job_id}")


__all__ = ["BaluCodeHttpClient"]
