"""Versioned, idempotent schema migrations (SQLite locally, PostgreSQL in production).

Each migration runs once and is recorded in schema_migrations. Every statement is also written defensively
(IF NOT EXISTS / column checks) so a half-applied migration can be re-run safely.
"""
from __future__ import annotations
import json
import logging

from . import geo, indices

log = logging.getLogger('rawaa.migrations')


def _add_columns(db, cols_of, table, spec):
    have = cols_of(db, table)
    for name, ddl in spec:
        if name not in have:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def m001_observation_provenance(db, cols_of, ctx):
    _add_columns(db, cols_of, 'observations', [
        ('origin', "TEXT"), ('reliability', "TEXT"), ('acquired_at', "TEXT"), ('scene_ids', "TEXT"),
        ('provenance', "TEXT"), ('boundary_version', "INTEGER"), ('veg_fraction', "REAL"), ('ndvi_veg', "REAL"),
        ('clear_pixels', "INTEGER"), ('processing_version', "TEXT")])
    # Backfill origin for existing rows. Old Copernicus rows were 30-day mosaics without scene IDs.
    db.execute("UPDATE observations SET origin='demo' WHERE origin IS NULL AND is_demo=1")
    db.execute("UPDATE observations SET origin='satellite' WHERE origin IS NULL AND source LIKE 'Copernicus%'")
    db.execute("UPDATE observations SET origin='imported' WHERE origin IS NULL AND source LIKE 'Imported%'")
    db.execute("UPDATE observations SET origin='manual' WHERE origin IS NULL")
    legacy = json.dumps({'kind': 'legacy_30day_composite', 'processing_version': 'rawaa-s2-v1',
                         'api': 'Sentinel Hub Statistical API', 'collection': indices.COLLECTION,
                         'note': 'Created before provenance tracking: 30-day mosaic (mostRecent), SCL classes 0,1,3,6,8,9,10,11 masked, '
                                 'scene IDs not recorded. Re-sync to replace with scene-level readings.'})
    db.execute("UPDATE observations SET provenance=?, processing_version='rawaa-s2-v1' WHERE provenance IS NULL AND origin='satellite'", (legacy,))
    for r in db.execute('SELECT id, origin, valid_pixels_pct FROM observations WHERE reliability IS NULL').fetchall():
        db.execute('UPDATE observations SET reliability=? WHERE id=?',
                   (indices.classify_reliability(r['origin'], r['valid_pixels_pct']), r['id']))
    db.execute('UPDATE observations SET boundary_version=1 WHERE boundary_version IS NULL')
    db.execute('CREATE INDEX IF NOT EXISTS ix_obs_area_date ON observations(area_id, measured_at)')


def m002_boundaries(db, cols_of, ctx):
    _add_columns(db, cols_of, 'areas', [
        ('boundary_status', "TEXT"), ('boundary_source', "TEXT"), ('boundary_version', "INTEGER DEFAULT 1"),
        ('area_m2', "REAL"), ('perimeter_m', "REAL"), ('vegetated_area_m2', "REAL"), ('boundary_reviewed_by', "INTEGER"),
        ('boundary_reviewed_at', "TEXT"), ('boundary_notes', "TEXT")])
    db.executescript('''
        CREATE TABLE IF NOT EXISTS boundary_history(
          id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, version INTEGER NOT NULL, geometry TEXT NOT NULL,
          source TEXT, status TEXT NOT NULL, action TEXT NOT NULL, user_id INTEGER, notes TEXT DEFAULT '',
          area_m2 REAL, created_at TEXT NOT NULL, FOREIGN KEY(area_id) REFERENCES areas(id))
    ''')
    source_for = ctx.get('source_for', lambda name: None)
    for a in db.execute('SELECT id, name_en, geometry, boundary_status FROM areas').fetchall():
        g = json.loads(a['geometry'])
        rep = geo.validate(g)
        src = source_for(a['name_en']) or 'user-supplied'
        status = a['boundary_status'] or (geo.initial_status(src, rep.get('placeholder', False)) if rep['valid'] else 'needs_review')
        db.execute('UPDATE areas SET boundary_status=?, boundary_source=COALESCE(boundary_source,?), boundary_version=COALESCE(boundary_version,1), area_m2=?, perimeter_m=? WHERE id=?',
                   (status, src, rep.get('area_m2'), rep.get('perimeter_m'), a['id']))
        if not db.execute('SELECT 1 FROM boundary_history WHERE area_id=?', (a['id'],)).fetchone():
            db.execute('INSERT INTO boundary_history(area_id,version,geometry,source,status,action,user_id,notes,area_m2,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (a['id'], 1, a['geometry'], src, status, 'initial', None, 'Recorded by migration 002', rep.get('area_m2'), ctx['now']()))


def m003_predictions_schedule(db, cols_of, ctx):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, generated_at TEXT NOT NULL, base_date TEXT NOT NULL,
          target_date TEXT NOT NULL, horizon_days INTEGER NOT NULL, model TEXT NOT NULL, ndvi_pred REAL NOT NULL,
          low80 REAL, high80 REAL, skill_pct REAL, mae_backtest REAL, mae_naive REAL, n_used INTEGER,
          actual_ndvi REAL, actual_date TEXT, abs_error REAL, naive_abs_error REAL, dedupe_key TEXT NOT NULL UNIQUE,
          FOREIGN KEY(area_id) REFERENCES areas(id));
        CREATE TABLE IF NOT EXISTS monitoring_schedule(
          id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, cycle_key TEXT NOT NULL, next_check TEXT NOT NULL,
          priority TEXT NOT NULL, decision_priority TEXT NOT NULL, reason_ar TEXT NOT NULL, reason_en TEXT NOT NULL,
          assignee_id INTEGER, status TEXT NOT NULL DEFAULT 'scheduled', reassess_at TEXT NOT NULL, basis_date TEXT,
          task_id INTEGER, alert_id INTEGER, notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          completed_at TEXT, completed_by INTEGER,
          FOREIGN KEY(area_id) REFERENCES areas(id));
        CREATE UNIQUE INDEX IF NOT EXISTS ux_schedule_cycle ON monitoring_schedule(area_id, cycle_key);
        CREATE TABLE IF NOT EXISTS pipeline_runs(
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, trigger TEXT NOT NULL,
          user_id INTEGER, summary TEXT, error TEXT)
    ''')


def m004_alert_task_followup(db, cols_of, ctx):
    _add_columns(db, cols_of, 'alerts', [('dedupe_key', 'TEXT'), ('auto', 'INTEGER DEFAULT 0'), ('evidence', 'TEXT'),
                                         ('observation_id', 'INTEGER')])
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_dedupe ON alerts(dedupe_key)')
    _add_columns(db, cols_of, 'tasks', [
        ('schedule_id', 'INTEGER'), ('baseline_ndvi', 'REAL'), ('baseline_date', 'TEXT'), ('notes_before', 'TEXT'),
        ('notes_after', 'TEXT'), ('completed_at', 'TEXT'), ('review_outcome', 'TEXT'), ('review_notes', 'TEXT'),
        ('reviewed_by', 'INTEGER'), ('reviewed_at', 'TEXT')])


def m005_login_audit(db, cols_of, ctx):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS login_attempts(
          email TEXT NOT NULL, ip TEXT NOT NULL, at INTEGER NOT NULL, ok INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_login_attempts ON login_attempts(email, at)
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS ix_activity_target ON activity(target)')


MIGRATIONS = [
    (1, 'observation_provenance', m001_observation_provenance),
    (2, 'boundaries', m002_boundaries),
    (3, 'predictions_schedule', m003_predictions_schedule),
    (4, 'alert_task_followup', m004_alert_task_followup),
    (5, 'login_audit', m005_login_audit),
]


def run(connect, cols_of, ctx) -> list[int]:
    applied = []
    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)')
        done = {r[0] for r in db.execute('SELECT version FROM schema_migrations').fetchall()}
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        with connect() as db:  # one transaction per migration
            fn(db, cols_of, ctx)
            db.execute('INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)', (version, name, ctx['now']()))
        log.info('Applied migration %03d %s', version, name)
        applied.append(version)
    return applied
