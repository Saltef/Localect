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


SCHEMA_ECHO = ('{"description": "The Reader", "properties": {"language": {"type": "string"}}, '
               '"required": ["language"], "title": "Reading", "type": "object"}')


async def test_schema_echo_is_named_and_the_retry_asks_for_an_instance():
    m = FakeModel([SCHEMA_ECHO, '{"language":"ja","gloss":"g","intent":"i"}'])
    r = await run_stage(m, "reader", Reading, "sys", "user")
    assert r.language == "ja"
    ask = m.calls[1]["messages"][-1]["content"]
    assert "repeated the schema" in ask and "language, language_name, region_guess" in ask


async def test_schema_echo_twice_is_a_stage_error_that_says_so():
    m = FakeModel([SCHEMA_ECHO, SCHEMA_ECHO])
    with pytest.raises(StageError) as e:
        await run_stage(m, "reader", Reading, "sys", "user")
    assert "schema itself" in e.value.reason


def test_an_instance_with_a_properties_key_is_not_mistaken_for_the_schema():
    text = '{"language":"en","gloss":"properties","intent":"x","properties":{}}'
    assert parse_json(text, Reading).language == "en"
