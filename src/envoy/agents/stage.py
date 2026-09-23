"""Run one model-driven stage: render prompt, call model, validate JSON, retry once."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..models.base import ChatModel, ModelError

T = TypeVar("T", bound=BaseModel)
_JSON = re.compile(r"\{.*\}", re.DOTALL)


class StageError(RuntimeError):
    def __init__(self, role: str, reason: str) -> None:
        super().__init__(f"{role}: {reason}")
        self.role = role
        self.reason = reason


def parse_json(text: str, schema: type[T]) -> T:
    m = _JSON.search(text)
    if not m:
        raise ValueError("no JSON object in output")
    return schema.model_validate(json.loads(m.group(0)))


async def run_stage(
    model: ChatModel,
    role: str,
    schema: type[T],
    system: str,
    user: str,
    context: dict[str, Any] | None = None,
) -> T:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = ""
    for attempt in range(2):
        try:
            text = await asyncio.to_thread(
                model.generate, messages, role=role, schema=schema, context=context
            )
        except ModelError as e:
            raise StageError(role, str(e)) from e
        try:
            return parse_json(text, schema)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            last_error = str(e)[:400]
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "That was not a valid JSON object matching the "
                                                f"schema. Error: {last_error}. Reply with the "
                                                "corrected JSON object only."},
                ]
    raise StageError(role, f"invalid output after retry: {last_error}")


def schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False)
