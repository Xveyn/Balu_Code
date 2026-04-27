from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from plugin.services.system import get_gpu_info


def _mock_run(stdout: str, returncode: int = 0):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


# ── amd-smi ──────────────────────────────────────────────────────────────────

AMD_SMI_JSON = json.dumps(
    [
        {
            "gpu": 0,
            "gfx": {"activity": 42},
            "mem": {"vram_used": 10_500_000_000, "vram_total": 21_474_836_480},
        }
    ]
)


def test_get_gpu_info_amd_smi():
    with patch("subprocess.run", return_value=_mock_run(AMD_SMI_JSON)):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "rocm"
    assert info["utilization_pct"] == 42
    assert info["vram_used_bytes"] == 10_500_000_000
    assert info["vram_total_bytes"] == 21_474_836_480
    assert info["available"] is True


# ── rocm-smi fallback ─────────────────────────────────────────────────────────

ROCM_SMI_JSON = json.dumps(
    {
        "card0": {
            "gpu_busy_percent": "37",
            "vram": {"mem_used": 9_000_000_000, "mem_total": 21_474_836_480},
        }
    }
)


def test_get_gpu_info_rocm_smi_fallback():
    def _side_effect(cmd, **kwargs):
        if "amd-smi" in cmd[0]:
            raise FileNotFoundError
        return _mock_run(ROCM_SMI_JSON)

    with patch("subprocess.run", side_effect=_side_effect):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "rocm"
    assert info["utilization_pct"] == 37


# ── nvidia-smi fallback ───────────────────────────────────────────────────────


def test_get_gpu_info_nvidia_fallback():
    def _side_effect(cmd, **kwargs):
        if cmd[0] in ("amd-smi", "rocm-smi"):
            raise FileNotFoundError
        return _mock_run("65, 8192, 24576")

    with patch("subprocess.run", side_effect=_side_effect):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "nvidia"
    assert info["utilization_pct"] == 65
    assert info["vram_used_bytes"] == 8192 * 1_048_576
    assert info["vram_total_bytes"] == 24576 * 1_048_576


def test_get_gpu_info_returns_none_when_no_tools():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        info = get_gpu_info()
    assert info is None


def test_get_gpu_info_returns_none_on_bad_json():
    with patch("subprocess.run", return_value=_mock_run("not json")):
        info = get_gpu_info()
    assert info is None


def test_get_gpu_info_returns_none_on_nonzero_returncode():
    with patch("subprocess.run", return_value=_mock_run("", returncode=1)):
        info = get_gpu_info()
    assert info is None
