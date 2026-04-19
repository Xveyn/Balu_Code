"""Build the OpenAI-style message array for one agent-loop turn.

Order: system prompt → tool-use prompt → repo-map block → RAG block →
session history → current user message. If the resulting total exceeds
``context_window``, drop in this order:
  (a) oldest history turns, one at a time,
  (b) lowest-score RAG chunks,
  (c) lowest-rank repo-map file blocks (block = chunk delimited by
      lines starting with ``=== ``).
System prompt, tool-use prompt, and the current user message are never
dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from plugin.services.rag_index import SearchHit
from plugin.services.tokenizer import count_messages_tokens, count_tokens


@dataclass(frozen=True)
class AssembledContext:
    messages: list[dict]
    context_tokens: int
    repo_map_tokens: int
    rag_tokens: int
    history_tokens: int
    truncated_files: list[str]
    dropped_turns: int
    dropped_chunks: int


def _format_rag_hits(hits: list[SearchHit]) -> str:
    blocks = [
        f"=== {h.chunk.file_path}:{h.chunk.start_line}-{h.chunk.end_line}\n{h.chunk.text}"
        for h in hits
    ]
    return "\n\n".join(blocks)


def _trim_rag(hits: list[SearchHit], budget_tokens: int) -> tuple[str, list[SearchHit]]:
    """Return (rendered_text, kept_hits). Drops lowest-score first."""
    sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
    kept = list(sorted_hits)
    while kept:
        text = _format_rag_hits(kept)
        if count_tokens(text) <= budget_tokens:
            return text, kept
        kept.pop()
    return "", []


def _trim_repo_map(repo_map_text: str, budget_tokens: int) -> tuple[str, list[str]]:
    """Return (trimmed_text, truncated_file_paths). Drops trailing ``=== path`` blocks."""
    if count_tokens(repo_map_text) <= budget_tokens:
        return repo_map_text, []
    blocks: list[str] = []
    current: list[str] = []
    for line in repo_map_text.splitlines(keepends=True):
        if line.startswith("=== ") and current:
            blocks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("".join(current))
    truncated: list[str] = []
    while blocks and count_tokens("".join(blocks)) > budget_tokens:
        dropped = blocks.pop()
        first_line = dropped.splitlines()[0] if dropped else ""
        if first_line.startswith("=== "):
            header = first_line[4:].split(" ", 1)[0]
            truncated.append(header)
    return "".join(blocks), truncated


async def assemble_context(
    *,
    system_prompt: str,
    tool_use_prompt: str,
    repo_map_text: str,
    rag_hits: list[SearchHit],
    history: list[dict],
    user_message: str,
    context_window: int,
    repo_map_budget: int,
    rag_budget: int,
) -> AssembledContext:
    repo_map_trimmed, truncated_files = _trim_repo_map(repo_map_text, repo_map_budget)
    rag_text, kept_hits = _trim_rag(rag_hits, rag_budget)
    dropped_chunks = len(rag_hits) - len(kept_hits)

    def build(history_slice: list[dict]) -> list[dict]:
        msgs: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": tool_use_prompt},
        ]
        if repo_map_trimmed:
            msgs.append({"role": "system", "content": repo_map_trimmed})
        if rag_text:
            msgs.append({"role": "system", "content": rag_text})
        msgs.extend(history_slice)
        msgs.append({"role": "user", "content": user_message})
        return msgs

    history_slice = list(history)
    dropped_turns = 0
    messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and history_slice:
        history_slice.pop(0)
        dropped_turns += 1
        messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and kept_hits:
        kept_hits.pop()
        dropped_chunks += 1
        rag_text = _format_rag_hits(kept_hits)
        messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and repo_map_trimmed:
        new_budget = max(0, count_tokens(repo_map_trimmed) - 500)
        repo_map_trimmed, more_truncated = _trim_repo_map(repo_map_trimmed, new_budget)
        truncated_files.extend(more_truncated)
        if not more_truncated and repo_map_trimmed:
            repo_map_trimmed = ""
        messages = build(history_slice)

    repo_tokens = count_tokens(repo_map_trimmed) if repo_map_trimmed else 0
    rag_tokens = count_tokens(rag_text) if rag_text else 0
    hist_tokens = count_messages_tokens(history_slice)

    return AssembledContext(
        messages=messages,
        context_tokens=count_messages_tokens(messages),
        repo_map_tokens=repo_tokens,
        rag_tokens=rag_tokens,
        history_tokens=hist_tokens,
        truncated_files=truncated_files,
        dropped_turns=dropped_turns,
        dropped_chunks=dropped_chunks,
    )


__all__ = ["AssembledContext", "assemble_context"]
