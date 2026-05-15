"""Tests for the bare Ollama proxy helper (no FastAPI route surface)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from plugin.services.ollama_proxy import _HEADERS_TO_DROP, proxy_request


def test_headers_to_drop_covers_hop_by_hop_and_auth():
    for h in (
        "connection",
        "keep-alive",
        "transfer-encoding",
        "host",
        "content-length",
        "authorization",
    ):
        assert h in _HEADERS_TO_DROP
