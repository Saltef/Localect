import pytest

from envoy.agents.stage import StageError, parse_json, run_stage
from envoy.models.base import FakeModel
from envoy.schemas import Reading


def test_parse_json_tolerates_prose_and_fences():
    text = 'Sure:\n```json\n{"language":"ar","gloss":"hi","intent":"x"}\n```'
    assert parse_json(text, Reading).language == "ar"


async def test_retry_then_success():
    m = FakeModel(["not json", '{"language":"es","gloss":"g","intent":"i"}'])
    r = await run_stage(m, "reader", Reading, "sys", "user")
    assert r.language == "es"
    assert len(m.calls) == 2 and "not a valid JSON" in m.calls[1]["messages"][-1]["content"]


async def test_second_failure_raises_stage_error():
    m = FakeModel(["nope", "still nope"])
    with pytest.raises(StageError) as e:
        await run_stage(m, "reader", Reading, "sys", "user")
    assert e.value.role == "reader"
