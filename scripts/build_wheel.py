"""Build the `balu-code-cli` wheel with vendored balu_code_shared.

The released wheel must not have a runtime dependency on the separate
`balu-code-shared` package (it lives in the same monorepo). We copy the
shared source into `cli/src/balu_code_cli/_vendored/balu_code_shared/`
right before the build and remove it right after, so source control
never contains the vendored tree.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_vendored(shared_dir: Path, cli_src: Path) -> Path:
    src = shared_dir / "src" / "balu_code_shared"
    dest = cli_src / "balu_code_cli" / "_vendored"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text('"""Auto-vendored at build time; do not commit."""\n')
    target = dest / "balu_code_shared"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    return dest


def _remove_vendored(vendored_dir: Path) -> None:
    if vendored_dir.exists():
        shutil.rmtree(vendored_dir)


def _patch_pyproject_dependency(cli_pyproject: Path) -> str:
    """Temporarily strip the `balu-code-shared` dep from cli/pyproject.toml.

    Returns the original text so we can restore it.
    """
    original = cli_pyproject.read_text()
    patched = "\n".join(
        line for line in original.splitlines() if line.strip() != '"balu-code-shared",'
    )
    cli_pyproject.write_text(patched + "\n")
    return original


def _restore_pyproject(cli_pyproject: Path, original: str) -> None:
    cli_pyproject.write_text(original)


def build_wheel(repo_root: Path, dist_dir: Path) -> Path:
    """Build cli/ wheel with vendored shared. Returns the wheel path."""
    shared_dir = repo_root / "shared"
    cli_dir = repo_root / "cli"
    cli_src = cli_dir / "src"
    cli_pyproject = cli_dir / "pyproject.toml"

    dist_dir.mkdir(parents=True, exist_ok=True)

    vendored = _copy_vendored(shared_dir, cli_src)
    original_pyproject = _patch_pyproject_dependency(cli_pyproject)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(dist_dir.resolve()),
                str(cli_dir),
            ],
            check=True,
        )
    finally:
        _remove_vendored(vendored)
        _restore_pyproject(cli_pyproject, original_pyproject)

    wheels = sorted(dist_dir.glob("balu_code_cli-*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheel found in {dist_dir}")
    return wheels[-1]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build balu-code-cli wheel")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    out = build_wheel(args.repo_root.resolve(), args.dist.resolve())
    print(f"Built {out}")


if __name__ == "__main__":
    _main()
