"""Model adapters. One interface; the pipeline never knows which is behind it."""

from .base import ChatModel, FakeModel, ModelError
from .stub import StubModel


def build_model(settings) -> ChatModel:
    if settings.provider == "stub":
        return StubModel()
    if settings.provider == "openai":
        from .openai_compat import OpenAICompatModel

        return OpenAICompatModel(settings.endpoint, settings.model, settings.api_key)
    raise ModelError(f"unknown provider {settings.provider!r}")


__all__ = ["ChatModel", "FakeModel", "ModelError", "StubModel", "build_model"]
