"""Main agent-loop runtime.

One ``run_turn`` call drives a single user-message turn end-to-end:
assembles context, streams from Ollama, dispatches tool calls,
accumulates history, emits WS events via the provided callback. The
function never raises; all failures become an ``Error`` event plus
``TurnEnd(stop_reason="error")``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

_log = logging.getLogger(__name__)
from dataclasses import dataclass
from pathlib import Path

from balu_code_shared.events import (
    Approval,
    ApprovalRequest,
    Error,
    Event,
    Token,
    ToolCall,
    ToolResult,
    TurnEnd,
    TurnStart,
)
from pydantic import ValidationError

from ..config import BaluCodePluginConfig
from .audit import AuditLogger
from .cancel import CancelToken
from .context_assembler import assemble_context
from .ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from .project_store import Project
from .rag_index import RagIndex
from .repo_map import RepoMap
from .tokenizer import count_messages_tokens, count_tokens
from .tools import ToolRegistry
from .tools.base import ToolContext

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system.md"
_TOOL_USE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "tool_use.md"

_SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text()
_TOOL_USE_PROMPT = _TOOL_USE_PROMPT_PATH.read_text()


@dataclass
class TurnDeps:
    """Dependencies a turn needs. Mutable only for the config field in tests."""

    ollama: OllamaClient
    tool_registry: ToolRegistry
    project: Project
    repo_map: RepoMap
    rag: RagIndex
    config: BaluCodePluginConfig
    audit_log: AuditLogger
    system_prompt: str = _SYSTEM_PROMPT
    tool_use_prompt: str = _TOOL_USE_PROMPT


@dataclass
class TurnContext:
    """Per-turn mutable state passed from the WS handler into run_turn."""

    turn_id: str
    cancel_token: CancelToken
    pending_approvals: dict[str, asyncio.Future[Approval]]
    username: str


Emitter = Callable[[Event], Awaitable[None]]


def _new_tool_call_id(iteration: int, suffix: int) -> str:
    return f"tc_{iteration}_{suffix}"


_TOOL_CALL_RE = re.compile(
    r"```tool_call\s*\n(.*?)\n```",
    re.DOTALL,
)


def _extract_tool_call(content: str) -> list[dict] | None:
    """Extract a ```tool_call ... ``` block from model output.

    Also handles models that return raw JSON objects (qwen2.5-coder style).
    Returns a list in Ollama tool_calls format, or None.
    """
    m = _TOOL_CALL_RE.search(content)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                return [{"function": {"name": obj["name"], "arguments": obj["arguments"]}}]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: bare JSON object covering the whole content
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                return [{"function": {"name": obj["name"], "arguments": obj["arguments"]}}]
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _rechunk(text: str, size: int = 64) -> list[str]:
    """Split text into chunks for streaming after buffering."""
    return [text[i : i + size] for i in range(0, len(text), size)] if text else []


async def run_turn(
    user_message: str,
    history: list[dict],
    deps: TurnDeps,
    emit: Emitter,
    ctx: TurnContext,
) -> None:
    """Drive one turn. Appends to ``history`` in place. Never raises."""
    turn_id = ctx.turn_id
    try:
        repo_map_text = await _resolve_repo_map(deps)
    except Exception as exc:
        await emit(Error(code="repo_map_failed", message=str(exc)))
        await emit(TurnEnd(turn_id=turn_id, total_tokens=0, iterations=0, stop_reason="error"))
        return

    try:
        rag_hits = await deps.rag.search(user_message, top_k=deps.config.rag_top_k)
    except Exception:
        rag_hits = []

    history_snapshot = list(history)
    history.append({"role": "user", "content": user_message})

    try:
        assembled = await assemble_context(
            system_prompt=deps.system_prompt,
            tool_use_prompt=deps.tool_use_prompt,
            repo_map_text=repo_map_text,
            rag_hits=rag_hits,
            history=history[:-1],
            user_message=user_message,
            context_window=deps.config.context_window,
            repo_map_budget=deps.config.repo_map_budget,
            rag_budget=deps.config.rag_budget,
        )
    except Exception as exc:
        history[:] = history_snapshot
        await emit(Error(code="context_assembly_failed", message=str(exc)))
        await emit(TurnEnd(turn_id=turn_id, total_tokens=0, iterations=0, stop_reason="error"))
        return

    messages = list(assembled.messages)
    await emit(
        TurnStart(
            turn_id=turn_id,
            model=deps.config.chat_model,
            context_tokens=assembled.context_tokens,
        )
    )

    total_tokens = assembled.context_tokens
    iterations = 0
    for _iteration in range(deps.config.max_iterations):
        iterations += 1

        # Per-iteration token re-accumulation (4a carryover fix).
        total_tokens = assembled.context_tokens + count_messages_tokens(messages)
        if total_tokens > deps.config.max_total_tokens_per_turn:
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="max_tokens",
                )
            )
            return

        try:
            ctx.cancel_token.check()
        except asyncio.CancelledError:
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="cancelled",
                )
            )
            return

        buffered_content = ""
        tool_calls_from_stream: list[dict] | None = None

        _log.warning(
            "[agent_loop] iteration=%d msgs=%d total_tokens=%d",
            iterations, len(messages), total_tokens,
        )

        try:
            async for frame in deps.ollama.chat_stream(
                deps.config.chat_model,
                messages,
                options={"temperature": deps.config.temperature},
            ):
                try:
                    ctx.cancel_token.check()
                except asyncio.CancelledError:
                    await emit(
                        TurnEnd(
                            turn_id=turn_id,
                            total_tokens=total_tokens,
                            iterations=iterations,
                            stop_reason="cancelled",
                        )
                    )
                    return
                if frame.get("error"):
                    _log.warning("[agent_loop] Ollama error frame: %r", frame["error"])
                    history[:] = history_snapshot
                    await emit(Error(code="ollama_error", message=str(frame["error"])))
                    await emit(TurnEnd(
                        turn_id=turn_id,
                        total_tokens=total_tokens,
                        iterations=iterations,
                        stop_reason="error",
                    ))
                    return
                message = frame.get("message") or {}
                content_piece = message.get("content") or ""
                if content_piece:
                    buffered_content += content_piece
                maybe_tool_calls = message.get("tool_calls")
                if maybe_tool_calls:
                    tool_calls_from_stream = list(maybe_tool_calls)
                if frame.get("done"):
                    _log.warning(
                        "[agent_loop] stream done — buffered=%d bytes",
                        len(buffered_content),
                    )
                    break

            _log.warning(
                "[agent_loop] after stream — buffered=%d chars, native_tool_calls=%s",
                len(buffered_content), bool(tool_calls_from_stream),
            )

            # Detect tool calls from text output (prompt-based tool calling).
            # Models that don't support native function calling output a
            # ```tool_call``` block or raw JSON object in their response.
            if not tool_calls_from_stream and buffered_content:
                promoted = _extract_tool_call(buffered_content)
                _log.warning(
                    "[agent_loop] _extract_tool_call -> %s (preview: %r)",
                    "TOOL" if promoted else "text",
                    buffered_content[:120],
                )
                if promoted:
                    tool_calls_from_stream = promoted
                    buffered_content = ""
                else:
                    # Real text response — stream tokens to client now.
                    for piece in _rechunk(buffered_content):
                        await emit(Token(content=piece))
        except OllamaUnreachable as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_unreachable", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except OllamaTimeoutError as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_timeout", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except OllamaRateLimited as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_rate_limited", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except Exception as exc:
            history[:] = history_snapshot
            await emit(Error(code="internal", message=f"{type(exc).__name__}: {exc}"))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return

        total_tokens += count_tokens(buffered_content)

        if not tool_calls_from_stream:
            history.append({"role": "assistant", "content": buffered_content})
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="done",
                )
            )
            return

        assistant_msg: dict = {"role": "assistant", "content": buffered_content}
        assistant_msg["tool_calls"] = tool_calls_from_stream
        history.append(assistant_msg)
        messages.append(assistant_msg)

        tool_ctx = ToolContext(
            project_root=Path(deps.project.root_path),
            project_id=deps.project.id,
            turn_id=turn_id,
            cancel_token=ctx.cancel_token,
        )

        for call_index, call in enumerate(tool_calls_from_stream):
            try:
                ctx.cancel_token.check()
            except asyncio.CancelledError:
                await emit(
                    TurnEnd(
                        turn_id=turn_id,
                        total_tokens=total_tokens,
                        iterations=iterations,
                        stop_reason="cancelled",
                    )
                )
                return
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_args = function.get("arguments")
            try:
                args_dict = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            except (json.JSONDecodeError, ValueError):
                args_dict = {}
            tc_id = _new_tool_call_id(iterations, call_index)

            try:
                tool = deps.tool_registry.get(name)
            except KeyError:
                msg = f"unknown tool '{name}'"
                await emit(
                    ToolCall(tool_call_id=tc_id, tool=name, args=args_dict, auto_approved=True)
                )
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                history.append({"role": "tool", "name": name, "content": f"error: {msg}"})
                messages.append({"role": "tool", "name": name, "content": f"error: {msg}"})
                await deps.audit_log.record_tool_call(
                    tool=name,
                    user=ctx.username,
                    turn_id=turn_id,
                    tool_call_id=tc_id,
                    args=args_dict,
                    status="error",
                    bytes_out=0,
                    error=msg,
                    approved=True,
                    auto_approved=True,
                )
                continue

            auto_approved = tool.risk == "read"
            await emit(
                ToolCall(tool_call_id=tc_id, tool=name, args=args_dict, auto_approved=auto_approved)
            )

            approved = auto_approved
            if not auto_approved:
                await emit(
                    ApprovalRequest(tool_call_id=tc_id, tool=name, args=args_dict, risk=tool.risk)
                )
                loop = asyncio.get_running_loop()
                future: asyncio.Future[Approval] = loop.create_future()
                ctx.pending_approvals[tc_id] = future
                try:
                    decision = await future
                except asyncio.CancelledError:
                    ctx.pending_approvals.pop(tc_id, None)
                    await emit(
                        TurnEnd(
                            turn_id=turn_id,
                            total_tokens=total_tokens,
                            iterations=iterations,
                            stop_reason="cancelled",
                        )
                    )
                    return
                finally:
                    ctx.pending_approvals.pop(tc_id, None)

                approved = decision.approved
                if not approved:
                    reason = decision.reason or "no reason"
                    msg = f"user rejected: {reason}"
                    await emit(
                        ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg)
                    )
                    tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                    history.append(tool_msg)
                    messages.append(tool_msg)
                    await deps.audit_log.record_tool_call(
                        tool=name,
                        user=ctx.username,
                        turn_id=turn_id,
                        tool_call_id=tc_id,
                        args=args_dict,
                        status="error",
                        bytes_out=0,
                        error=msg,
                        approved=False,
                        auto_approved=False,
                    )
                    continue

            try:
                parsed = tool.args_schema.model_validate(args_dict)
            except ValidationError as exc:
                msg = f"invalid args: {exc}"
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                await deps.audit_log.record_tool_call(
                    tool=name,
                    user=ctx.username,
                    turn_id=turn_id,
                    tool_call_id=tc_id,
                    args=args_dict,
                    status="error",
                    bytes_out=0,
                    error=msg,
                    approved=approved,
                    auto_approved=auto_approved,
                )
                continue

            try:
                result = await tool.execute(parsed, tool_ctx)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                await deps.audit_log.record_tool_call(
                    tool=name,
                    user=ctx.username,
                    turn_id=turn_id,
                    tool_call_id=tc_id,
                    args=args_dict,
                    status="error",
                    bytes_out=0,
                    error=msg,
                    approved=approved,
                    auto_approved=auto_approved,
                )
                continue

            await emit(
                ToolResult(
                    tool_call_id=tc_id,
                    status=result.status,
                    bytes_out=result.bytes_out,
                    error=result.error,
                )
            )
            tool_msg = {"role": "tool", "name": name, "content": result.text}
            history.append(tool_msg)
            messages.append(tool_msg)
            total_tokens += count_tokens(result.text)
            await deps.audit_log.record_tool_call(
                tool=name,
                user=ctx.username,
                turn_id=turn_id,
                tool_call_id=tc_id,
                args=args_dict,
                status=result.status,
                bytes_out=result.bytes_out,
                error=result.error,
                approved=approved,
                auto_approved=auto_approved,
            )

    await emit(
        TurnEnd(
            turn_id=turn_id,
            total_tokens=total_tokens,
            iterations=iterations,
            stop_reason="max_iter",
        )
    )


async def _resolve_repo_map(deps: TurnDeps) -> str:
    """Walk the project + render a repo_map under the configured budget."""
    files = await asyncio.to_thread(deps.repo_map.walk_and_cache)
    rendered = deps.repo_map.render(files, budget_tokens=deps.config.repo_map_budget)
    return rendered.text


__all__ = ["TurnContext", "TurnDeps", "run_turn"]
