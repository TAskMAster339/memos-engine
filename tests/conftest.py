import pytest

from memos.core.db import get_connection, run_migrations


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    run_migrations(c)
    yield c
    c.close()
