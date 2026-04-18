# Balu Code

Self-hosted coding agent for [BaluHost](https://github.com/Xveyn/Baluhost). Runs against a local Ollama instance and is driven from a terminal CLI.

See [`docs/superpowers/specs/2026-04-18-balu-code-design.md`](docs/superpowers/specs/2026-04-18-balu-code-design.md) for the v1 design.

## Layout

| Dir | Purpose | Distribution |
|---|---|---|
| `plugin/` | BaluHost server plugin (`balu_code`) | `.bhplugin` ZIP → BaluHost Plugin Marketplace |
| `cli/` | Terminal client (`balu-code`) | `balu-code-cli` wheel → PyPI |
| `shared/` | Pydantic event schemas shared by both sides | path-dep in dev, vendored on build |

## Status

Pre-alpha. Phase 1 (foundation) in progress — see `docs/superpowers/plans/`.

## License

MIT — see `LICENSE`.
