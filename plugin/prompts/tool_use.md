# Tool use

In Phase 4a you have three tools. All three are read-only and
auto-approved — you do not need to ask permission before calling them.

## `read_file`

Read the contents of one file relative to the project root.

- `path` (required): project-root-relative path.
- `max_bytes` (optional, default 2 MB): cap on bytes read.
- Returns the file's text content.
- Errors: path outside project root; binary file; file not found.

## `glob`

Enumerate files matching a POSIX-style glob pattern.

- `pattern` (required): POSIX glob, relative to project root.
- Returns a newline-separated list of relative paths, up to 1000.
- Ignore directories (`.venv`, `node_modules`, `__pycache__`, etc.) are
  filtered out automatically.

## `grep`

Search file contents for a regex pattern.

- `pattern` (required): Python-style regex.
- `glob` (optional): restrict search to paths matching this glob.
- `case_insensitive` (optional, default false).
- Returns up to 500 `path:line:content` matches.
- Uses ripgrep when available, else pure-Python.

## Guidelines

- Use `glob` or `grep` to locate relevant files, then `read_file` to
  pull the full text of a specific region.
- Do not repeat the same tool call with the same arguments — check
  your prior tool results first.
- If a tool returns `status: "error"`, acknowledge the failure and
  either take a different approach or explain to the user why you
  cannot proceed. Do not retry blindly.
- Batch related `read_file` calls in a single turn when you know
  which files you need. Each tool call is a round-trip.
