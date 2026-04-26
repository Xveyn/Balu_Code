"""Tests for run_turn (agent loop)."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from balu_code_shared.events import (
    Approval,
    ApprovalRequest,
    Error,
    Event,
    ToolCall,
    ToolResult,
    TurnEnd,
)

from plugin.config import BaluCodePluginConfig
from plugin.services.agent_loop import TurnContext, TurnDeps, run_turn
from plugin.services.cancel import CancelToken
from plugin.services.project_store import Project, ProjectStore
from plugin.services.repo_map import RepoMap
from plugin.services.tools import default_registry


class _NoopAuditLogger:
    async def record_tool_call(self, **kwargs) -> None:
        return None


class _FakeOllama:
    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)

    async def chat_stream(self, model, messages, tools=None, options=None):
        frames = self._scripted.pop(0)
        for f in frames:
            yield f

    async def close(self) -> None:
        pass

    async def list_models(self):
        return []

    async def embed(self, model, texts):
        return [[0.0] * 768 for _ in texts]


class _FakeRag:
    async def search(self, query, top_k=8, *, keyword_boost=0.15):
        return []


@pytest.fixture
def tmp_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def foo(): pass\n")
    return root


@pytest.fixture
def deps_factory(tmp_project, tmp_path):
    def make(scripted_frames: list[list[dict]]) -> TurnDeps:
        store = ProjectStore(tmp_path / "store.db")
        p = store.create_project(name="proj", root_path=str(tmp_project), config_yaml=None)
        project = Project(
            id=p.id,
            name=p.name,
            root_path=p.root_path,
            config_yaml=p.config_yaml,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        repo_map = RepoMap(tmp_project, store, p.id)
        return TurnDeps(
            ollama=_FakeOllama(scripted_frames),
            tool_registry=default_registry(),
            project=project,
            repo_map=repo_map,
            rag=_FakeRag(),
            config=BaluCodePluginConfig(),
            audit_log=_NoopAuditLogger(),
            system_prompt="sys",
            tool_use_prompt="tool",
        )

    return make


async def test_simple_turn_done_without_tool_calls(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [
            [
                {"message": {"content": "Hello", "tool_calls": None}, "done": False},
                {"message": {"content": " world", "tool_calls": None}, "done": True},
            ]
        ]
    )
    history: list[dict] = []
    await run_turn("hi", history, deps, emit, _make_ctx())

    types = [e.type for e in events]
    assert types[0] == "turn_start"
    assert "token" in types
    assert types[-1] == "turn_end"
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "done"


async def test_tool_call_dispatches_read_file(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [
            [
                {
                    "message": {
                        "content": "reading",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "a.py"},
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            ],
            [
                {"message": {"content": "done", "tool_calls": None}, "done": True},
            ],
        ]
    )
    history: list[dict] = []
    await run_turn("what is in a.py?", history, deps, emit, _make_ctx())

    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool == "read_file"
    assert tool_calls[0].auto_approved is True
    assert len(tool_results) == 1
    assert tool_results[0].status == "ok"
    assert tool_results[0].tool_call_id == tool_calls[0].tool_call_id


async def test_iteration_cap_yields_max_iter_stop_reason(deps_factory):
    frames_per_iter = [
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "glob", "arguments": {"pattern": "*.py"}}}],
            },
            "done": True,
        }
    ]
    deps = deps_factory([frames_per_iter for _ in range(13)])
    deps.config.max_iterations = 2
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    history: list[dict] = []
    await run_turn("loop forever", history, deps, emit, _make_ctx())
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "max_iter"


async def test_ollama_error_surfaces_as_error_event(deps_factory):
    from plugin.services.ollama_client import OllamaUnreachable

    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps_fresh = deps_factory([[]])

    class _BrokenOllama:
        async def chat_stream(self, *a, **kw):
            raise OllamaUnreachable("down")
            yield

        async def close(self):
            pass

    deps = replace(deps_fresh, ollama=_BrokenOllama())
    history: list[dict] = []
    await run_turn("hi", history, deps, emit, _make_ctx())
    errors = [e for e in events if isinstance(e, Error)]
    assert len(errors) == 1
    assert errors[0].code == "ollama_unreachable"
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "error"


async def test_unknown_tool_name_emits_error_tool_result(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [
            [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "no_such_tool", "arguments": {}}}],
                    },
                    "done": True,
                }
            ],
            [
                {"message": {"content": "ok", "tool_calls": None}, "done": True},
            ],
        ]
    )
    history: list[dict] = []
    await run_turn("use a tool", history, deps, emit, _make_ctx())
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].status == "error"




class _TrackingAuditLogger:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_tool_call(self, **kw) -> None:
        self.calls.append(kw)


@pytest.fixture
def fake_audit():
    return _TrackingAuditLogger()


def _make_ctx(turn_id: str = "t_1", username: str = "sven") -> TurnContext:
    return TurnContext(
        turn_id=turn_id,
        cancel_token=CancelToken(),
        pending_approvals={},
        username=username,
    )


def _registry_with_write():
    return default_registry()


class TestApprovalGateAndAudit:
    @pytest.mark.asyncio
    async def test_write_tool_emits_approval_request_and_awaits(
        self, deps_factory, tmp_project
    ):
        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "write_file",
                                        "arguments": {"path": "out.txt", "content": "hi"},
                                    }
                                }
                            ],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "done", "tool_calls": None}, "done": True}],
            ]
        )
        deps = replace(deps, tool_registry=_registry_with_write())

        events: list = []
        ctx = _make_ctx()

        async def emit(e):
            events.append(e)

        async def approver():
            # wait until ApprovalRequest is emitted
            while not any(isinstance(e, ApprovalRequest) for e in events):
                await asyncio.sleep(0.01)
            req = next(e for e in events if isinstance(e, ApprovalRequest))
            fut = ctx.pending_approvals.get(req.tool_call_id)
            if fut and not fut.done():
                fut.set_result(
                    Approval(tool_call_id=req.tool_call_id, approved=True, reason=None)
                )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(approver())
            tg.create_task(run_turn("write a file", [], deps, emit, ctx))

        types = [e.type for e in events]
        assert "turn_start" in types
        assert "tool_call" in types
        assert "approval_request" in types
        assert "tool_result" in types
        assert types[-1] == "turn_end"
        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "done"
        tool_call_ev = next(e for e in events if isinstance(e, ToolCall))
        assert tool_call_ev.auto_approved is False
        tool_result_ev = next(e for e in events if isinstance(e, ToolResult))
        assert tool_result_ev.status == "ok"

    @pytest.mark.asyncio
    async def test_rejected_approval_feeds_error_back(self, deps_factory):
        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "write_file",
                                        "arguments": {"path": "out.txt", "content": "hi"},
                                    }
                                }
                            ],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "ok", "tool_calls": None}, "done": True}],
            ]
        )
        deps = replace(deps, tool_registry=_registry_with_write())

        events: list = []
        ctx = _make_ctx()

        async def emit(e):
            events.append(e)

        async def rejecter():
            while not any(isinstance(e, ApprovalRequest) for e in events):
                await asyncio.sleep(0.01)
            req = next(e for e in events if isinstance(e, ApprovalRequest))
            fut = ctx.pending_approvals.get(req.tool_call_id)
            if fut and not fut.done():
                fut.set_result(
                    Approval(
                        tool_call_id=req.tool_call_id, approved=False, reason="no"
                    )
                )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(rejecter())
            tg.create_task(run_turn("write file", [], deps, emit, ctx))

        tool_result_ev = next(e for e in events if isinstance(e, ToolResult))
        assert tool_result_ev.status == "error"
        assert "user rejected: no" in (tool_result_ev.error or "")
        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "done"

    @pytest.mark.asyncio
    async def test_audit_logger_called_for_every_tool_result(
        self, deps_factory, fake_audit
    ):
        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "glob", "arguments": {"pattern": "*.py"}}},
                                {"function": {"name": "read_file", "arguments": {"path": "a.py"}}},
                            ],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "done", "tool_calls": None}, "done": True}],
            ]
        )
        deps = replace(deps, audit_log=fake_audit)

        events: list = []
        ctx = _make_ctx()

        async def emit(e):
            events.append(e)

        history: list[dict] = []
        await run_turn("list and read", history, deps, emit, ctx)

        assert len(fake_audit.calls) == 2
        tools = {c["tool"] for c in fake_audit.calls}
        assert "glob" in tools
        assert "read_file" in tools


class TestStopReasonMaxTokens:
    @pytest.mark.asyncio
    async def test_token_cap_trip_uses_max_tokens_reason(self, deps_factory):
        deps = deps_factory(
            [
                [{"message": {"content": "long reply", "tool_calls": None}, "done": True}]
            ]
        )
        deps.config.max_total_tokens_per_turn = 1  # cap lower than any context

        events: list = []

        async def emit(e):
            events.append(e)

        ctx = _make_ctx()
        await run_turn("hi", [], deps, emit, ctx)

        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "max_tokens"


class TestPerIterationTokenReAccumulation:
    @pytest.mark.asyncio
    async def test_messages_tokens_counted_each_iteration(self, deps_factory):
        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "glob", "arguments": {"pattern": "*.py"}}}
                            ],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "done", "tool_calls": None}, "done": True}],
            ]
        )

        events: list = []

        async def emit(e):
            events.append(e)

        ctx = _make_ctx()
        await run_turn("list files", [], deps, emit, ctx)

        from balu_code_shared.events import TurnStart

        start = next(e for e in events if isinstance(e, TurnStart))
        end = next(e for e in events if isinstance(e, TurnEnd))
        # After a tool call the messages list grew, so total_tokens > initial context_tokens
        assert end.total_tokens >= start.context_tokens


class TestCancelToken:
    @pytest.mark.asyncio
    async def test_cancel_between_iterations_ends_turn(self, deps_factory):
        ctx = _make_ctx()
        events: list = []

        async def emit(e):
            events.append(e)
            if isinstance(e, ToolResult):
                # Cancel right after the first tool result — next iteration check fires
                ctx.cancel_token.cancel()

        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "glob", "arguments": {"pattern": "*.py"}}}
                            ],
                        },
                        "done": True,
                    }
                ],
                # second stream should never be reached
                [{"message": {"content": "done", "tool_calls": None}, "done": True}],
            ]
        )

        await run_turn("x", [], deps, emit, ctx)

        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_during_ollama_stream_stops_streaming(self, deps_factory):
        ctx = _make_ctx()
        events: list = []

        async def emit(e):
            events.append(e)
            if e.type == "token":
                # Cancel after first token — next frame's cancel check should fire
                ctx.cancel_token.cancel()

        deps = deps_factory(
            [
                [
                    {"message": {"content": "chunk1", "tool_calls": None}, "done": False},
                    {"message": {"content": "chunk2", "tool_calls": None}, "done": False},
                    {"message": {"content": "chunk3", "tool_calls": None}, "done": True},
                ]
            ]
        )

        await run_turn("x", [], deps, emit, ctx)

        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "cancelled"
        # Only the first token should have reached emit
        tokens = [e for e in events if e.type == "token"]
        assert len(tokens) == 1

    @pytest.mark.asyncio
    async def test_cancel_while_awaiting_approval_ends_turn(self, deps_factory):
        deps = deps_factory(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "write_file",
                                        "arguments": {"path": "x.txt", "content": "hi"},
                                    }
                                }
                            ],
                        },
                        "done": True,
                    }
                ],
            ]
        )
        deps = replace(deps, tool_registry=_registry_with_write())

        ctx = _make_ctx()
        events: list = []

        async def emit(e):
            events.append(e)

        async def canceller():
            # Wait until we see ApprovalRequest, then cancel
            while not any(isinstance(e, ApprovalRequest) for e in events):
                await asyncio.sleep(0.01)
            ctx.cancel_token.cancel()
            for fut in list(ctx.pending_approvals.values()):
                if not fut.done():
                    fut.cancel()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(canceller())
            tg.create_task(run_turn("write", [], deps, emit, ctx))

        end = next(e for e in events if isinstance(e, TurnEnd))
        assert end.stop_reason == "cancelled"
