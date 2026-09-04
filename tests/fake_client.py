"""Shared fake LLM client for offline tests (F3). No provider interface: duck-typed only."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, pin: int = 10, pout: int = 20):
        self.prompt_tokens = pin
        self.completion_tokens = pout


class _FakeResp:
    def __init__(self, payload: Any):
        self.choices = [_FakeChoice(payload if isinstance(payload, str) else json.dumps(payload))]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, parent: "FakeClient"):
        self._parent = parent

    async def create(self, **kwargs) -> _FakeResp:
        self._parent.calls.append(kwargs)
        handler = self._parent.handler
        if handler is None:
            raise AssertionError("FakeClient.handler not set")
        result = handler(kwargs)
        if isinstance(result, Exception):
            raise result
        if asyncio.iscoroutine(result):
            result = await result
        return _FakeResp(result)


class _FakeChat:
    def __init__(self, parent: "FakeClient"):
        self.completions = _FakeCompletions(parent)


class FakeClient:
    """Drop-in for complete_structured(client=...). Set .handler(messages_kwargs)->dict|str|Exception."""

    def __init__(self, handler: Callable[[dict], Any] | None = None):
        self.handler = handler
        self.calls: list[dict] = []
        self.chat = _FakeChat(self)

    @property
    def n_calls(self) -> int:
        return len(self.calls)

    def concurrent_peak(self) -> int:
        return int(getattr(self, "_peak", 0))
