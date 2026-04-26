# Tool use

You have the following tools available. To call a tool, output a fenced
code block tagged `tool_call` containing a JSON object with `"name"` and
`"arguments"` keys — nothing else in that block:

```tool_call
{"name": "<tool>", "arguments": {<args>}}
```

The result will be returned in the next message as a `tool_result` block.
You may call one tool per response. Wait for the result before calling
the next tool.

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

## `write_file`

Write or overwrite a file relative to the project root.

- `path` (required): project-root-relative path.
- `content` (required): full file content to write.

## `apply_patch`

Apply a unified diff patch to a file.

- `path` (required): project-root-relative path.
- `patch` (required): unified diff string.

## `run_bash`

Run a shell command in the project root directory.

- `command` (required): shell command string.
- `timeout` (optional, default 30s).

## `web_fetch`

Fetch the text content of a URL.

- `url` (required): URL to fetch.

## Guidelines

- Use `glob` or `grep` to locate relevant files, then `read_file` to
  pull the full text of a specific region.
- Do not repeat the same tool call with the same arguments — check
  your prior tool results first.
- If a tool returns an error, acknowledge the failure and either take a
  different approach or explain to the user why you cannot proceed.
- When you have all the information you need, respond directly without
  calling any more tools.
