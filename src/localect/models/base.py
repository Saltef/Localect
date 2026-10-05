from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

Message = dict[str, str]


class ModelError(RuntimeError):
    pass


@runtime_checkable
class ChatModel(Protocol):
    name: str

    def generate(
        self,
        messages: list[Message],
        *,
        role: str,
        schema: type[BaseModel] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str: ...


class FakeModel:
    """Replays queued replies. For tests of prompt assembly and parsing."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.name = "fake"
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    def generate(self, messages, *, role, schema=None, context=None) -> str:
        self.calls.append({"role": role, "messages": messages, "context": context})
        if not self.replies:
            raise ModelError("fake model has no reply queued")
        return self.replies.pop(0)
