"""End-to-end: satellite readings → validation → analysis → priority → alert → task → follow-up, plus security."""
import json
from datetime import date, timedelta

import pytest

from test_sentinel import FakeCopernicus, day


def area_id(core, name='Prince Majid Park'):
    with core.connect() as db:
        return db.execute('SELECT id FROM areas WHERE name_en=?', (name,)).fetchone()['id']


def insert_satellite(core, aid, values, end=None, valid=93.0, bv=1):
    """Insert synthetic satellite rows (tests only) ending a few days ago."""
    end = end or (date.today() - timedelta(days=4))
    with core.connect() as db:
        for i, v in enumerate(values):
            d = (end - timedelta(days=30 * (len(values) - 1 - i))).isoformat()
            db.execute('''INSERT INTO observations(area_id,measured_at,acquired_at,ndvi,ndmi,valid_pixels_pct,source,origin,reliability,
                          boundary_version,is_demo,created_at,provenance) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)''',
                       (aid, d, d, v, v - 0.15, valid, 'TEST synthetic satellite', 'satellite',
                        'reliable' if valid >= 80 else 'limited', bv, core.utcnow(), json.dumps({'kind': 'test'})))


# ---------------------------------------------------------------- security
def test_requires_login_and_roles(core, op):
    from fastapi.testclient import TestClient
    anon = TestClient(core.app)
    for path in ('/api/dashboard', '/api/intel/areas', '/api/schedule', '/api/forecast-accuracy'):
        assert anon.get(path).status_code == 401
    assert op.post('/api/pipeline/run', json={}).status_code == 403
    assert op.post(f'/api/areas/{area_id(core)}/boundary/review', json={'decision': 'approve'}).status_code == 403
    assert op.get('/api/reports/audit.csv').status_code == 403


def test_login_rate_limit(core):
    from fastapi.testclient import TestClient
    c = TestClient(core.app)
    for _ in range(8):
        assert c.post('/api/login', json={'email': 'nobody@rawaa.local', 'password': 'x'}).status_code == 401
    assert c.post('/api/login', json={'email': 'nobody@rawaa.local', 'password': 'x'}).status_code == 429


def test_health(core):
    from fastapi.testclient import TestClient
    r = TestClient(core.app).get('/healthz').json()
    assert r['ok'] and r['schema_version'] == 5


# ---------------------------------------------------------------- boundaries
def test_boundary_status_and_approval(core, reg):
    approx = area_id(core, 'Al Huda Garden')
    b = reg.get(f'/api/areas/{approx}/boundary').json()
    assert b['status'] == 'needs_review' and b['validation']['placeholder'] and not b['final_results']
    # approving a placeholder needs a justification
    assert reg.post(f'/api/areas/{approx}/boundary/review', json={'decision': 'approve'}).status_code == 400
    osm = area_id(core, 'Al Saja Gardens')
    assert reg.get(f'/api/areas/{osm}/boundary').json()['status'] == 'pending_approval'
    assert reg.post(f'/api/areas/{osm}/boundary/review', json={'decision': 'approve', 'notes': 'Checked against municipality plan'}).json()['status'] == 'approved'
    b = reg.get(f'/api/areas/{osm}/boundary').json()
    assert b['final_results'] and b['history'][0]['action'] == 'review'


def test_invalid_boundary_rejected(core, reg):
    aid = area_id(core, 'Al Ajwad New Park')
    bowtie = {'type': 'Polygon', 'coordinates': [[[39.25, 21.59], [39.26, 21.60], [39.26, 21.59], [39.25, 21.60], [39.25, 21.59]]]}
    r = reg.put(f'/api/areas/{aid}/boundary', json={'geometry': bowtie, 'source': 'survey'})
    assert r.status_code == 400


# ---------------------------------------------------------------- full workflow
def test_full_workflow_is_idempotent(core, reg, op):
    aid = area_id(core)
    insert_satellite(core, aid, [0.52, 0.53, 0.51, 0.52, 0.53, 0.52, 0.51, 0.41, 0.37, 0.33])
    # Imported values must never trigger anything for another park.
    other = area_id(core, 'Validation site 1')
    csv_text = 'date,ndvi,ndmi,valid_pixels_pct\n' + '\n'.join(f'2026-0{m}-01,{0.6 - m * 0.08:.2f},0.2,99' for m in range(1, 8))
    assert reg.post(f'/api/areas/{other}/import-csv', json={'csv_text': csv_text}).json()['reliability'] == 'unverified'

    r1 = reg.post('/api/pipeline/run', json={}).json()
    assert r1['alerts_created'] == 1
    intel = reg.get(f'/api/areas/{aid}/intel').json()
    assert intel['decision']['priority'] == 'urgent' and intel['decision']['provisional']
    assert intel['forecast']['available'] and intel['forecast']['kind'] == 'forecast'
    assert all(p['kind'] == 'actual' for p in intel['series'])
    assert intel['schedule']['priority'] == 'high'
    o = reg.get(f'/api/areas/{other}/intel').json()
    assert o['decision']['priority'] == 'insufficient' and o['readings_summary']['unverified_imported_or_manual'] == 7

    # Re-running (or restarting the server and running migrations again) never duplicates anything.
    from rawaa_core import migrations
    migrations.run(core.connect, core.table_columns, {'now': core.utcnow})
    r2 = reg.post('/api/pipeline/run', json={}).json()
    assert r2['alerts_created'] == 0 and r2['schedules_created'] == 0 and r2['predictions'] == 0
    with core.connect() as db:
        assert db.execute("SELECT count(*) FROM alerts WHERE area_id=? AND auto=1", (aid,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM monitoring_schedule WHERE area_id=? AND status IN ('scheduled','in_progress')", (aid,)).fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM alerts WHERE area_id=?', (other,)).fetchone()[0] == 0
        alert = dict(db.execute('SELECT * FROM alerts WHERE area_id=? AND auto=1', (aid,)).fetchone())
    assert 'مبدئية' in alert['reason_ar'] and json.loads(alert['evidence'])['reasons_ar']

    # Regulator assigns → task carries the baseline reading and the scheduled date.
    tid = reg.post(f"/api/alerts/{alert['id']}/assign", json={'priority': 'high'}).json()['id']
    task = next(t for t in reg.get('/api/tasks').json() if t['id'] == tid)
    assert task['baseline_ndvi'] == pytest.approx(0.33) and task['due_at'] == intel['schedule']['next_check']
    sched = reg.get('/api/schedule').json()
    s = next(x for x in sched if x['area_id'] == aid)
    assert s['status'] == 'in_progress' and s['task_id'] == tid

    # Operator works the task with before/after notes; regulator closes and reviews.
    assert op.patch(f'/api/tasks/{tid}', json={'status': 'in_progress', 'notes_before': 'Dry patches on the east lawn'}).status_code == 200
    assert op.patch(f'/api/tasks/{tid}', json={'due_at': '2030-01-01'}).status_code == 403
    assert op.patch(f'/api/tasks/{tid}', json={'status': 'pending_review', 'actual_cause': 'Broken lateral', 'action': 'Replaced pipe',
                                               'notes_after': 'Pipe replaced, schedule restored', 'confirmed_cause': 'patchy_damage'}).status_code == 200
    assert reg.patch(f'/api/tasks/{tid}', json={'status': 'closed'}).status_code == 200
    assert reg.post(f'/api/tasks/{tid}/review', json={'outcome': 'inconclusive', 'notes': 'Wait for next readings'}).status_code == 200
    assert reg.get(f'/api/tasks/{tid}/impact').json()['verdict'] == 'awaiting_readings'
    with core.connect() as db:
        assert db.execute('SELECT status FROM monitoring_schedule WHERE id=?', (s['id'],)).fetchone()[0] == 'done'
        verbs = {r[0] for r in db.execute('SELECT verb FROM activity')}
    assert {'auto_alert', 'assign_task', 'update_task', 'task_review'} <= verbs

    # Reports
    for path in ('decisions', 'schedule', 'predictions', 'audit', 'tasks'):
        r = reg.get(f'/api/reports/{path}.csv')
        assert r.status_code == 200 and r.headers['content-type'].startswith('text/csv')
    assert 'urgent' in reg.get('/api/reports/decisions.csv').text


def test_operator_scope(core, op, reg):
    aid = area_id(core)
    assert op.get(f'/api/areas/{aid}/intel').status_code == 200  # demo operator is assigned to all sites
    sid = reg.get('/api/schedule').json()[0]['id']
    assert op.patch(f'/api/schedule/{sid}', json={'next_check': '2030-01-01'}).status_code == 403


def test_boundary_change_excludes_old_readings(core, reg):
    aid = area_id(core, 'Middle Corniche Park')
    insert_satellite(core, aid, [0.30, 0.31, 0.30, 0.29, 0.30, 0.31])
    assert reg.get(f'/api/areas/{aid}/intel').json()['decision']['priority'] == 'stable'
    g = reg.get(f'/api/areas/{aid}/boundary').json()['geometry']
    r = reg.put(f'/api/areas/{aid}/boundary', json={'geometry': g, 'source': 'Municipality survey 2026', 'notes': 'redrawn'}).json()
    assert r['version'] == 2
    intel = reg.get(f'/api/areas/{aid}/intel').json()
    assert intel['decision']['priority'] == 'insufficient' and intel['readings_summary']['older_boundary_version'] == 6
    obs = reg.get(f'/api/areas/{aid}/observations').json()
    assert all(not o['used_in_analysis'] and 'older boundary' in o['excluded_reason'] for o in obs)


def test_provenance_endpoint(core, reg):
    aid = area_id(core)
    obs = reg.get(f'/api/areas/{aid}/observations').json()
    p = reg.get(f"/api/observations/{obs[-1]['id']}/provenance").json()
    assert p['origin'] == 'satellite' and p['provenance'] == {'kind': 'test'} and 'ndvi' in p['formulas']


def test_sync_endpoint_with_mocked_copernicus(core, reg, monkeypatch):
    aid = area_id(core, 'Validation site 2')
    today = date.today()
    days = []
    for k in range(8, 0, -1):
        d = (today.replace(day=10) - timedelta(days=30 * k)).replace(day=10)
        days.append(day(d.isoformat(), 0.30, 0.95))
    fake = FakeCopernicus(days, [{'id': f'S2A_TEST_{x["interval"]["from"][:10]}', 'properties': {'datetime': x['interval']['from'], 'eo:cloud_cover': 1}} for x in days])
    monkeypatch.setenv('COPERNICUS_CLIENT_ID', 'id'); monkeypatch.setenv('COPERNICUS_CLIENT_SECRET', 'secret')
    monkeypatch.setattr(core, '_copernicus_access_token', lambda: 'TOKEN')
    monkeypatch.setattr(core, 'api_json', fake)
    monkeypatch.setattr(core, 'sync_thermal', lambda *a, **k: 0)
    r = reg.post(f'/api/areas/{aid}/sync-satellite', json={'start_date': (today - timedelta(days=300)).isoformat(), 'end_date': today.isoformat()}).json()
    assert r['saved_intervals'] == 8 and r['report']['reliable'] == 8 and 'run_id' in r['pipeline']
    obs = reg.get(f'/api/areas/{aid}/observations').json()
    assert all(o['scene_ids'].startswith('S2A_TEST_') for o in obs)
    # Placeholder boundary (needs_review): readings are analysed but no automatic alert is allowed
    intel = reg.get(f'/api/areas/{aid}/intel').json()
    assert not intel['decision']['automatic_actions_allowed']
    # second sync of the same period → upsert, no duplicate rows
    reg.post(f'/api/areas/{aid}/sync-satellite', json={'start_date': (today - timedelta(days=300)).isoformat(), 'end_date': today.isoformat()})
    assert len(reg.get(f'/api/areas/{aid}/observations').json()) == 8


def test_dashboard_and_legacy_endpoints_still_work(reg, op):
    d = reg.get('/api/dashboard').json()
    assert d['counts']['total'] == 8 and 'briefing' in d
    assert op.get('/api/dashboard').status_code == 200
    assert reg.get('/api/areas').status_code == 200
    assert reg.get('/').status_code == 200
