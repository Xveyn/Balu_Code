# Installing Balu Code

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| BaluHost | 1.30.0 | plugin manifest version 1 |
| Python | 3.11 | server-side only |
| Ollama | 0.32.12 | must be on `127.0.0.1:11434` on the BaluHost server. That release is the one that added `qwen3.8`; older 0.3.x/0.2x builds cannot load it |
| GPU VRAM | 16 GB | for `qwen2.5-coder:14b-instruct-q4_K_M` at q4. See the qwen3.8 section below for the 27B model |
| GPU driver | ROCm ≥ 6.1 or CUDA ≥ 12.1 | |

**Reference hardware:** AMD RX 7900 XT (20 GB GDDR6, ROCm 6.2), Ryzen 5 5600GT, 16 GB RAM, Debian 13.

## 1. Set up Ollama

Install Ollama following the [official guide](https://ollama.com/download), then pull the two models Balu Code uses by default:

```bash
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
ollama pull nomic-embed-text
```

Verify Ollama is accessible from the BaluHost server:

```bash
curl http://127.0.0.1:11434/api/tags
```

**ROCm note (RX 7900 XT):** the official ROCm build detects gfx1100 on its own — on the
reference box no override was needed. Set `HSA_OVERRIDE_GFX_VERSION=11.0.0` in the Ollama
systemd unit only if the card stays invisible.

### 1a. Running qwen3.8:27b on 20 GB (reference setup)

`qwen3.8:27b` is a 27.8B hybrid-attention vision model, 18 GB at the default q4_K_M and
256K context. It fits a 20 GB card, but only with a quantised KV cache — and only while
nothing else large is on the GPU. Measured on the reference box: **17 GB resident at a
32K context, `100% GPU`, ~450 tok/s prefill, ~37 tok/s generation**, first load from disk
~35 s (with 16 GB RAM there is no page cache for a 17 GB file).

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'CONF'
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
CONF
sudo systemctl daemon-reload && sudo systemctl restart ollama
ollama pull qwen3.8:27b
```

Ollama's Modelfile is the only place where sampling parameters stick, since the plugin
forwards just `num_ctx`, `temperature` and `think`:

```bash
printf 'FROM qwen3.8:27b\nPARAMETER num_ctx 32768\nPARAMETER temperature 0.7\nPARAMETER top_p 0.8\nPARAMETER top_k 20\nPARAMETER repeat_penalty 1.0\n' > /tmp/Modelfile
ollama create qwen3.8-code -f /tmp/Modelfile
```

Then set `chat_model: qwen3.8-code:latest`, `context_window: 32768` and **`think: false`**
in the Config tab. Thinking is on by default for this model at its longest trace level;
on the reference box the same coding task cost 2493 output tokens / 65.8 s with the trace
and 1096 / 27.7 s without.

Verify the model actually fits — a CPU share in `PROCESSOR` means layers spilled to system
RAM, which on a 16 GB box degrades far worse than it sounds:

```bash
ollama ps     # PROCESSOR must read "100% GPU", CONTEXT must match context_window
```

Without `rocm-smi` or `amd-smi` installed, the System tab's VRAM bar stays empty
(`plugin/services/system.py` probes those two plus `nvidia-smi`). The kernel exposes the
same numbers directly:

```bash
cat /sys/class/drm/card*/device/mem_info_vram_used
```

## 2. Install the plugin

1. Download `balu_code-0.1.0.bhplugin` from the [GitHub Releases page](https://github.com/Xveyn/Balu_Code/releases).
2. In the BaluHost web UI, go to **Plugins → Install plugin** and upload the `.bhplugin` file.
3. BaluHost installs and activates the plugin automatically. The sidebar shows a **Balu Code** entry.

## 3. Smoke test

Replace `<host>` and `<key>` with your BaluHost hostname and an API key:

```bash
curl -s -H "Authorization: Bearer <key>" https://<host>/api/plugins/balu_code/health
```

Expected response:

```json
{"status": "ok", "plugin": "balu_code", "version": "0.1.0"}
```

## 4. Install the CLI

On any machine that can reach the BaluHost server:

```bash
pip install balu-code-cli
balu-code auth login --server https://<host> --key <key>
```

See [cli.md](cli.md) for the full CLI reference.
