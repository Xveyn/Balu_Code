"""Tests for assemble_context."""

from __future__ import annotations

from plugin.services.context_assembler import AssembledContext, assemble_context
from plugin.services.rag_chunker import Chunk
from plugin.services.rag_index import SearchHit


def _hit(path: str, text: str, score: float) -> SearchHit:
    return SearchHit(
        chunk=Chunk(file_path=path, start_line=1, end_line=5, text=text),
        score=score,
    )


async def test_message_order_is_system_tool_use_repo_rag_history_user():
    ctx = await assemble_context(
        system_prompt="SYSPROMPT",
        tool_use_prompt="TOOLUSE",
        repo_map_text="=== foo.py ===",
        rag_hits=[_hit("foo.py", "hit text", 0.9)],
        history=[{"role": "assistant", "content": "earlier reply"}],
        user_message="current user ask",
        context_window=100_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    roles_and_hints = [(m["role"], m["content"][:40]) for m in ctx.messages]
    assert roles_and_hints[0] == ("system", "SYSPROMPT")
    assert roles_and_hints[1] == ("system", "TOOLUSE")
    assert "=== foo.py ===" in ctx.messages[2]["content"]
    assert "hit text" in ctx.messages[3]["content"]
    assert ctx.messages[4]["role"] == "assistant"
    assert ctx.messages[4]["content"] == "earlier reply"
    assert ctx.messages[5]["role"] == "user"
    assert ctx.messages[5]["content"] == "current user ask"


async def test_context_tokens_field_matches_messages_tokens():
    from plugin.services.tokenizer import count_messages_tokens

    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[],
        user_message="u",
        context_window=100_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    assert ctx.context_tokens == count_messages_tokens(ctx.messages)


async def test_system_and_tool_use_are_never_dropped():
    ctx = await assemble_context(
        system_prompt="SYSPROMPT",
        tool_use_prompt="TOOLUSE",
        repo_map_text="x" * 200_000,
        rag_hits=[_hit("a", "y" * 200_000, 0.5)],
        history=[{"role": "user", "content": "old"}, {"role": "assistant", "content": "old reply"}],
        user_message="current",
        context_window=500,
        repo_map_budget=100_000,
        rag_budget=100_000,
    )
    contents = [m["content"] for m in ctx.messages]
    assert any("SYSPROMPT" in c for c in contents)
    assert any("TOOLUSE" in c for c in contents)
    assert any(c == "current" for c in contents)


async def test_drops_oldest_history_turn_first():
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[
            {"role": "user", "content": "OLDEST" + "x" * 400},
            {"role": "assistant", "content": "MID"},
            {"role": "user", "content": "NEW"},
        ],
        user_message="current",
        context_window=60,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    texts = " ".join(m["content"] for m in ctx.messages)
    assert "OLDEST" not in texts
    assert ctx.dropped_turns >= 1


async def test_drops_lowest_score_rag_chunks():
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[
            _hit("a.py", "A" + "x" * 400, 0.9),
            _hit("b.py", "B" + "x" * 400, 0.1),
            _hit("c.py", "C" + "x" * 400, 0.5),
        ],
        history=[],
        user_message="u",
        context_window=150,
        repo_map_budget=10_000,
        rag_budget=10_000,
    )
    assert ctx.dropped_chunks >= 1


async def test_returns_AssembledContext():
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[],
        user_message="u",
        context_window=10_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    assert isinstance(ctx, AssembledContext)
