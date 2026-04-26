"""GPU hardware info via amd-smi / rocm-smi / nvidia-smi."""
from __future__ import annotations

import json
import subprocess


def _run(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=2, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _parse_amd_smi(output: str) -> dict | None:
    try:
        data = json.loads(output)
        if not isinstance(data, list) or not data:
            return None
        gpu = data[0]
        util = (gpu.get("gfx") or {}).get("activity")
        mem = gpu.get("mem") or {}
        vram_used = mem.get("vram_used")
        vram_total = mem.get("vram_total")
        if util is None or vram_used is None or vram_total is None:
            return None
        return {
            "available": True,
            "backend": "rocm",
            "utilization_pct": int(str(util).rstrip("%")),
            "vram_used_bytes": int(vram_used),
            "vram_total_bytes": int(vram_total),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _parse_rocm_smi(output: str) -> dict | None:
    try:
        data = json.loads(output)
        card = next(iter(data.values()), {})
        util = card.get("gpu_busy_percent")
        vram = card.get("vram") or {}
        vram_used = vram.get("mem_used")
        vram_total = vram.get("mem_total")
        if util is None or vram_used is None or vram_total is None:
            return None
        return {
            "available": True,
            "backend": "rocm",
            "utilization_pct": int(str(util).rstrip("%")),
            "vram_used_bytes": int(vram_used),
            "vram_total_bytes": int(vram_total),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, StopIteration):
        return None


def _parse_nvidia_smi(output: str) -> dict | None:
    try:
        parts = [p.strip() for p in output.strip().split(",")]
        if len(parts) < 3:
            return None
        util, mem_used_mb, mem_total_mb = int(parts[0]), int(parts[1]), int(parts[2])
        return {
            "available": True,
            "backend": "nvidia",
            "utilization_pct": util,
            "vram_used_bytes": mem_used_mb * 1_000_000,
            "vram_total_bytes": mem_total_mb * 1_000_000,
        }
    except (ValueError, IndexError):
        return None


def get_gpu_info() -> dict | None:
    """Return GPU utilization + VRAM info, or None if no GPU tool is available."""
    out = _run(["amd-smi", "metric", "--json"])
    if out:
        result = _parse_amd_smi(out)
        if result:
            return result

    out = _run(["rocm-smi", "--json", "--showuse", "--showmeminfo", "vram"])
    if out:
        result = _parse_rocm_smi(out)
        if result:
            return result

    out = _run([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if out:
        result = _parse_nvidia_smi(out)
        if result:
            return result

    return None


__all__ = ["get_gpu_info"]
