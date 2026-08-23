"""Guards for the plugin UI bundle's host contract.

BaluHost renders plugin UIs inside an iframe created with
``sandbox="allow-scripts"`` and deliberately without ``allow-same-origin``.
In that opaque origin there is no ``window.React``, reading ``localStorage``
throws, and a direct ``fetch`` leaves as a credential-less cross-origin
request. The bundle must therefore go through ``window.BaluHost`` — React and
hooks from its surface, HTTP through its proxied api.

The bundle shipped that way for months and failed with
"TypeError: React is undefined", which renders the whole plugin page blank
with nothing in the server log. A grep-level check is crude, but it catches
exactly that regression without pulling a JS toolchain into this test suite.
"""

from __future__ import annotations

import re
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "ui" / "bundle.js"


def _code_without_comments() -> str:
    """Bundle source minus block and line comments.

    The file's own header documents the forbidden patterns by name, so the
    checks below would trip over the explanation rather than real code.
    """
    src = BUNDLE.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    return src


def test_bundle_exists_and_default_exports_a_component():
    src = _code_without_comments()
    assert "export default" in src, "the runtime imports the bundle and mounts its default export"


def test_bundle_takes_react_from_the_host_surface():
    src = _code_without_comments()
    assert "window.BaluHost" in src
    assert (
        "window.React" not in src
    ), "window.React does not exist inside the plugin sandbox — take React from window.BaluHost"


def test_bundle_does_not_reach_for_browser_credentials_or_fetch():
    src = _code_without_comments()
    assert (
        "localStorage" not in src
    ), "localStorage throws in an opaque-origin iframe; the host proxies API calls instead"
    assert (
        "fetch(" not in src
    ), "a direct fetch is cross-origin without credentials here; use window.BaluHost.api"


def test_bundle_only_calls_removed_endpoints_never():
    """/turns/current and /index/{id} were removed in 0.2.0 (see CHANGELOG)."""
    src = _code_without_comments()
    assert "/turns/current" not in src
    assert "/index/" not in src
