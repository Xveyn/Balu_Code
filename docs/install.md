# Installing Balu Code

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| BaluHost | 1.30.0 | plugin manifest version 1 |
| Python | 3.11 | server-side only |
| Ollama | 0.3.x | must be on `127.0.0.1:11434` on the BaluHost server |
| GPU VRAM | 16 GB | for `qwen2.5-coder:14b-instruct-q4_K_M` at q4 |
| GPU driver | ROCm ≥ 6.1 or CUDA ≥ 12.1 | |

**Reference hardware:** AMD RX 7900 XT (20 GB GDDR6, ROCm 6.2). Both default models run comfortably with headroom for the OS.

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

**ROCm note (RX 7900 XT):** Set `HSA_OVERRIDE_GFX_VERSION=11.0.0` in your Ollama systemd unit if the card is not auto-detected.

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
