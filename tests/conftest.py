"""Test setup: an isolated temporary SQLite database for every test session (never the production DB)."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix='rawaa-test-')
os.environ['RAWAA_NO_DOTENV'] = '1'  # never let a developer's .env point the tests at a real database
os.environ['RAWAA_DB'] = os.path.join(_tmp, 'test.sqlite3')
os.environ.pop('DATABASE_URL', None)
# Optional: run the same suite on a THROWAWAY PostgreSQL database (its public schema is wiped first).
_pg = os.environ.get('RAWAA_TEST_DATABASE_URL')
if _pg:
    import psycopg
    with psycopg.connect(_pg, autocommit=True) as c:
        c.execute('DROP SCHEMA public CASCADE'); c.execute('CREATE SCHEMA public')
    os.environ['DATABASE_URL'] = _pg
os.environ.pop('COPERNICUS_CLIENT_ID', None)
os.environ.pop('COPERNICUS_CLIENT_SECRET', None)
os.environ['RAWAA_AUTO_PIPELINE'] = '0'
os.environ['RAWAA_TILE_CACHE'] = os.path.join(_tmp, 'tiles')


@pytest.fixture(scope='session')
def core():
    import app
    return app


@pytest.fixture()
def reg(core):
    from fastapi.testclient import TestClient
    c = TestClient(core.app)
    assert c.post('/api/login', json={'email': 'regulator@rawaa.local', 'password': 'Rawaa2026!'}).status_code == 200
    return c


@pytest.fixture()
def op(core):
    from fastapi.testclient import TestClient
    c = TestClient(core.app)
    assert c.post('/api/login', json={'email': 'operator@rawaa.local', 'password': 'Rawaa2026!'}).status_code == 200
    return c
