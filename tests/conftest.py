import pytest

from envoy import db
from envoy.config import Settings
from envoy.demo import seed_demo
from envoy.locales import seed_locales


@pytest.fixture
def con():
    c = db.connect()
    seed_locales(c)
    return c


@pytest.fixture
def demo_con(con):
    seed_demo(con)
    return con


@pytest.fixture
def settings():
    return Settings(provider="stub", user_name="Safea", user_language="en")
