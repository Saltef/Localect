import pytest

from localect import db
from localect.config import Settings
from localect.demo import seed_demo
from localect.locales import seed_locales


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
