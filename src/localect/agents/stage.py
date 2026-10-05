"""Run one model-driven stage: render prompt, call model, validate JSON, retry once."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
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


Normalizer = Callable[[dict[str, Any]], dict[str, Any]]


class SchemaEcho(ValueError):
    """The model returned the JSON schema it was shown instead of an instance
    of it (smaller models do this when the schema is the last thing in the
    prompt)."""


def looks_like_schema(raw: Any, schema: type[BaseModel]) -> bool:
    if not isinstance(raw, dict):
        return False
    fields = set(schema.model_fields)
    if fields & set(raw):
        return False
    if raw.get("type") == "object" and isinstance(raw.get("properties"), dict):
        return True
    return "$defs" in raw and "properties" in raw


def parse_json(text: str, schema: type[T], normalize: Normalizer | None = None) -> T:
    m = _JSON.search(text)
    if not m:
        raise ValueError("no JSON object in output")
    raw = json.loads(m.group(0))
    if looks_like_schema(raw, schema):
        raise SchemaEcho("the output is the schema itself, not an object that matches it")
    if normalize is not None and isinstance(raw, dict):
        raw = normalize(raw)
    return schema.model_validate(raw)


def retry_message(error: str, schema: type[BaseModel], echoed: bool) -> str:
    keys = ", ".join(schema.model_fields)
    if echoed:
        return ("You repeated the schema. Do not describe the format; fill it in. Reply with "
                f"one JSON object whose keys are exactly: {keys}. Each value must be the "
                "answer for this message, not a type or a description.")
    return (f"That was not a valid JSON object matching the schema. Error: {error}. Reply "
            f"with the corrected JSON object only, with these keys: {keys}.")


async def run_stage(
    model: ChatModel,
    role: str,
    schema: type[T],
    system: str,
    user: str,
    context: dict[str, Any] | None = None,
    normalize: Normalizer | None = None,
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
            return parse_json(text, schema, normalize)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            last_error = str(e)[:400]
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user",
                     "content": retry_message(last_error, schema, isinstance(e, SchemaEcho))},
                ]
    raise StageError(role, f"invalid output after retry: {last_error}")


def schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False)
