from __future__ import annotations

from ..models.base import ChatModel
from ..prompts import render
from ..schemas import Reading
from .stage import run_stage, schema_text

SYSTEM = "You are a precise, literal reader. You report; you never answer."


async def read(model: ChatModel, message: str, user_language_name: str) -> Reading:
    user = render("reader", user_language_name=user_language_name, message=message,
                  schema=schema_text(Reading))
    return await run_stage(model, "reader", Reading, SYSTEM, user,
                           context={"message": message, "user_language": user_language_name})
