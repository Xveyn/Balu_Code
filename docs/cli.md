# CLI

Balu Code v0.2.0 no longer ships a bespoke CLI. The embedded opencode
runtime (downloaded automatically into `~/.local/share/balu-code/runtime/`
on first plugin start) doubles as a fully featured terminal client:

    ~/.local/share/balu-code/runtime/opencode-linux-x86_64 --help

Common invocations:

    # Interactive TUI (default mode)
    opencode-linux-x86_64

    # One-shot prompt
    opencode-linux-x86_64 run "explain main.py"

    # List configured models
    OPENCODE_CONFIG_DIR=~/.local/share/balu-code \
      opencode-linux-x86_64 models

For most workflows, the BaluHost web UI is the recommended entry point.
The HTTP `POST /api/plugins/balu_code/chat/v2/{project_id}` route is the
programmatic equivalent.
