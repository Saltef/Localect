"""Turn one past message into dated facts."""

from __future__ import annotations

from ..models.base import ChatModel
from ..prompts import render
from ..schemas import Extraction
from .stage import run_stage, schema_text

SYSTEM = ("You extract facts from correspondence. You list only what the message states, "
          "verbatim, with a stable topic key. You never invent or infer.")


def normalize_extraction(raw: dict) -> dict:
    facts = []
    for f in raw.get("facts") or []:
        if not isinstance(f, dict) or not str(f.get("statement", "")).strip():
            continue
        facts.append({"topic": str(f.get("topic", "")).strip().lower() or "untitled",
                      "statement": str(f["statement"]).strip(),
                      "value": str(f.get("value") or "").strip()})
    return {"facts": facts}


async def extract(model: ChatModel, text: str, *, who: str, when: str, subject: str = ""
                  ) -> Extraction:
    user = render("extractor", who=who, when=when or "an unknown date",
                  subject=f', subject "{subject}"' if subject else "", text=text,
                  schema=schema_text(Extraction))
    return await run_stage(model, "extractor", Extraction, SYSTEM, user,
                           context={"text": text, "who": who, "when": when},
                           normalize=normalize_extraction)
