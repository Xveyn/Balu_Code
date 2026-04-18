"""Build the `.bhplugin` archive from plugin/ + vendored shared/.

Usage (CLI):
    python -m scripts.build_bhplugin --repo-root . --dist dist/

Importable:
    from scripts.build_bhplugin import build_bhplugin
    artefact = build_bhplugin(Path("."), Path("dist"))
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

_EXCLUDE_TOPLEVEL = {"tests", "pyproject.toml", "__pycache__"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _should_include(relpath: Path) -> bool:
    parts = relpath.parts
    if not parts:
        return False
    if parts[0] in _EXCLUDE_TOPLEVEL:
        return False
    if any(p == "__pycache__" for p in parts):
        return False
    if relpath.suffix in _EXCLUDE_SUFFIXES:
        return False
    return True


def _iter_plugin_files(plugin_dir: Path):
    for p in plugin_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(plugin_dir)
        if _should_include(rel):
            yield p, rel


def _iter_shared_files(shared_dir: Path):
    """Yield files under shared/src/balu_code_shared to be vendored at archive root."""
    src_root = shared_dir / "src" / "balu_code_shared"
    for p in src_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in _EXCLUDE_SUFFIXES:
            continue
        if "__pycache__" in p.parts:
            continue
        rel = Path("balu_code_shared") / p.relative_to(src_root)
        yield p, rel


def build_bhplugin(repo_root: Path, dist_dir: Path) -> Path:
    """Produce `<dist>/balu_code-<version>.bhplugin` and its .sha256 sidecar.

    Returns the path to the .bhplugin file.
    """
    plugin_dir = repo_root / "plugin"
    shared_dir = repo_root / "shared"
    manifest = json.loads((plugin_dir / "plugin.json").read_text())
    version = manifest["version"]
    name = manifest["name"]

    dist_dir.mkdir(parents=True, exist_ok=True)
    artefact = dist_dir / f"{name}-{version}.bhplugin"
    if artefact.exists():
        artefact.unlink()

    with zipfile.ZipFile(artefact, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel in _iter_plugin_files(plugin_dir):
            zf.write(src, rel.as_posix())
        for src, rel in _iter_shared_files(shared_dir):
            zf.write(src, rel.as_posix())

    digest = hashlib.sha256(artefact.read_bytes()).hexdigest()
    sidecar = artefact.with_suffix(artefact.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {artefact.name}\n")

    return artefact


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build balu_code .bhplugin archive")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    out = build_bhplugin(args.repo_root.resolve(), args.dist.resolve())
    print(f"Built {out}")


if __name__ == "__main__":
    _main()
