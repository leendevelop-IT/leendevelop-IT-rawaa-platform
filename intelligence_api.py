"""RAWAA intelligence layer: validated readings → decision → forecast → schedule → alert → task → follow-up.

Installed onto the existing FastAPI app by app.py (install(core)), so it reuses the same database adapter,
sessions and role checks. All automatic steps are idempotent: re-running (or a server restart) never duplicates
alerts, schedule entries or predictions, because each one carries a unique key in the database.
"""
from __future__ import annotations
import csv
import io
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field

from rawaa_core import decision as decision_mod, forecast as forecast_mod, geo, indices, scheduler, sentinel
from rawaa_core.series import trusted_series, to_points, reading_date

log = logging.getLogger('rawaa.intel')
core = None  # the app module, set by install()

OBS_COLS = ('id,area_id,measured_at,acquired_at,ndvi,ndmi,ndwi,savi,ndre,salinity,ndvi_std,valid_pixels_pct,clear_pixels,'
            'veg_fraction,ndvi_veg,source,origin,reliability,scene_ids,boundary_version,processing_version,is_demo')


def _today():
    return datetime.now(timezone.utc).date()


def _activity(db, user_id, verb, target, details):
    db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',
               (user_id, verb, str(target), details if isinstance(details, str) else json.dumps(details, ensure_ascii=False), core.utcnow()))


# ------------------------------------------------------------------------------------------------ analysis
def observations(db, area_id):
    return [dict(r) for r in db.execute(f'SELECT {OBS_COLS} FROM observations WHERE area_id=? ORDER BY measured_at', (area_id,))]


def analyse_area(area: dict, rows: list, today: date | None = None) -> dict:
    today = today or _today()
    bv = area.get('boundary_version') or 1
    series = trusted_series(rows, bv)
    used_ids = {r['id'] for r in series}
    unverified = sum(1 for r in rows if r.get('origin') in ('imported', 'manual'))
    dec = decision_mod.summarize(series, area.get('boundary_status') or 'needs_review', unverified, today)
    fc = forecast_mod.forecast(to_points(series), today)
    plan = scheduler.plan(dec, fc, today)
    other_boundary = sum(1 for r in rows if r.get('origin') == 'satellite' and (r.get('boundary_version') or 1) != bv)
    return {'area_id': area['id'], 'decision': dec, 'forecast': fc, 'plan': plan,
            'series': [{'date': reading_date(r), 'ndvi': round(r['ndvi'], 4), 'valid_pixels_pct': r.get('valid_pixels_pct'),
                        'reliability': r.get('reliability'), 'kind': 'actual', 'observation_id': r['id']} for r in series],
            'readings_summary': {'total': len(rows), 'used': len(used_ids),
                                 'satellite': sum(1 for r in rows if r.get('origin') == 'satellite'),
                                 'unreliable': sum(1 for r in rows if r.get('reliability') == 'unreliable'),
                                 'unverified_imported_or_manual': unverified, 'demo': sum(1 for r in rows if r.get('origin') == 'demo'),
                                 'older_boundary_version': other_boundary}}


def _scoped_areas(db, user):
    clause, params = core.in_scope_clause(user)
    return [dict(r) for r in db.execute('SELECT a.* FROM areas a' + clause + ' ORDER BY a.id', params)]


def _active_schedule(db, area_id):
    r = db.execute("SELECT * FROM monitoring_schedule WHERE area_id=? AND status IN ('scheduled','in_progress') ORDER BY id DESC", (area_id,)).fetchone() \
        or db.execute("SELECT * FROM monitoring_schedule WHERE area_id=? AND status<>'superseded' ORDER BY id DESC", (area_id,)).fetchone()
    return _sched_out(dict(r)) if r else None


def _sched_out(s):
    if s and s.get('status') == 'scheduled' and s.get('next_check') and s['next_check'] < _today().isoformat():
        s['overdue'] = True
    else:
        s['overdue'] = False
    return s


# ------------------------------------------------------------------------------------------------ pipeline
_PIPE_LOCK = threading.Lock()


def _store_predictions(db, area_id, fc, now):
    if not fc.get('available'):
        return 0
    base = fc['last_actual']['date']
    n = 0
    for h in fc['horizons']:
        key = f"{area_id}:{base}:{h['days']}"
        if db.execute('SELECT 1 FROM predictions WHERE dedupe_key=?', (key,)).fetchone():
            continue
        db.execute('''INSERT INTO predictions(area_id,generated_at,base_date,target_date,horizon_days,model,ndvi_pred,low80,high80,
                      skill_pct,mae_backtest,mae_naive,n_used,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (area_id, now, base, h['target_date'], h['days'], fc['model'], h['ndvi'], h['low80'], h['high80'],
                    fc['backtest']['skill_pct'], fc['backtest']['mae'], fc['backtest']['mae_naive'], fc['n'], key))
        n += 1
    return n


def _evaluate_predictions(db, area_id, series):
    pts = [(date.fromisoformat(reading_date(r)), r['ndvi']) for r in series]
    if not pts:
        return 0
    n = 0
    for p in db.execute('SELECT * FROM predictions WHERE area_id=? AND actual_ndvi IS NULL', (area_id,)).fetchall():
        p = dict(p)
        target = date.fromisoformat(p['target_date'])
        tol = 4 if p['horizon_days'] <= 7 else 10
        near = [(abs((d - target).days), d, v) for d, v in pts if abs((d - target).days) <= tol and d > date.fromisoformat(p['base_date'])]
        if not near:
            continue
        _, d, v = min(near)
        base_v = next((bv for bd, bv in pts if bd == date.fromisoformat(p['base_date'])), None)
        db.execute('UPDATE predictions SET actual_ndvi=?, actual_date=?, abs_error=?, naive_abs_error=? WHERE id=?',
                   (v, d.isoformat(), abs(p['ndvi_pred'] - v), abs(base_v - v) if base_v is not None else None, p['id']))
        n += 1
    return n


def _upsert_schedule(db, area, plan, now):
    """Returns (schedule_id, created). Same (area, cycle_key) never inserted twice."""
    row = db.execute('SELECT id FROM monitoring_schedule WHERE area_id=? AND cycle_key=?', (area['id'], plan['cycle_key'])).fetchone()
    if row:
        return row['id'], False
    db.execute("UPDATE monitoring_schedule SET status='superseded', updated_at=? WHERE area_id=? AND status='scheduled'", (now, area['id']))
    c = db.execute('''INSERT INTO monitoring_schedule(area_id,cycle_key,next_check,priority,decision_priority,reason_ar,reason_en,assignee_id,
                      status,reassess_at,basis_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (area['id'], plan['cycle_key'], plan['next_check'], plan['priority'], plan['decision_priority'], plan['reason_ar'],
                    plan['reason_en'], area.get('assigned_operator'), 'scheduled', plan['reassess_at'], plan['basis_date'], now, now))
    return c.lastrowid, True


def _auto_alert(db, area, dec, schedule_id, now):
    if not dec.get('automatic_actions_allowed'):
        return None
    basis = dec['current']['date']
    key = f"auto:{area['id']}:{basis}"
    if db.execute('SELECT 1 FROM alerts WHERE dedupe_key=?', (key,)).fetchone():
        return None
    if db.execute("SELECT 1 FROM alerts WHERE area_id=? AND status<>'closed'", (area['id'],)).fetchone():
        return None  # one open alert per park; the existing one already carries the follow-up
    sev = 'high' if dec['priority'] == 'urgent' else 'monitor'
    prov_ar = ' (نتيجة مبدئية: الحدود غير معتمدة)' if dec.get('provisional') else ''
    reason_ar = f"{dec['priority_ar']}: NDVI {dec['current']['ndvi']:.3f} ({dec.get('anomaly_pct')}% عن المتوقع)، تراجع في {dec.get('persistence')} قراءات متتالية. موثوقية {dec['reliability_ar']}{prov_ar}."
    reason_en = f"{dec['priority_en']}: NDVI {dec['current']['ndvi']:.3f} ({dec.get('anomaly_pct')}% vs expected), {dec.get('persistence')} consecutive declining readings. Reliability {dec['reliability']}."
    evidence = json.dumps({'reasons_ar': dec['reasons_ar'], 'reasons_en': dec['reasons_en'], 'current': dec['current'],
                           'expected_ndvi': dec.get('expected_ndvi'), 'baseline_kind': dec.get('baseline_kind')}, ensure_ascii=False)
    c = db.execute('''INSERT INTO alerts(area_id,severity,reason_ar,reason_en,status,created_at,dedupe_key,auto,evidence,observation_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?)''', (area['id'], sev, reason_ar, reason_en, 'new', now, key, 1, evidence,
                                                       dec['current'].get('observation_id')))
    db.execute('UPDATE monitoring_schedule SET alert_id=? WHERE id=?', (c.lastrowid, schedule_id))
    _activity(db, None, 'auto_alert', c.lastrowid, f"area {area['id']} — {dec['priority']} (basis {basis})")
    return c.lastrowid


def run_pipeline(trigger='manual', user_id=None, area_ids=None):
    if not _PIPE_LOCK.acquire(blocking=False):
        return {'skipped': True, 'reason': 'A pipeline run is already in progress'}
    try:
        started = core.utcnow()
        summary = {'areas': 0, 'predictions': 0, 'evaluated': 0, 'schedules_created': 0, 'alerts_created': 0, 'by_priority': {}}
        with core.connect() as db:
            c = db.execute('INSERT INTO pipeline_runs(started_at,trigger,user_id) VALUES(?,?,?)', (started, trigger, user_id))
            run_id = c.lastrowid
        try:
            with core.connect() as db:
                areas = [dict(r) for r in db.execute('SELECT * FROM areas ORDER BY id')]
                for area in areas:
                    if area_ids and area['id'] not in area_ids:
                        continue
                    rows = observations(db, area['id'])
                    res = analyse_area(area, rows)
                    now = core.utcnow()
                    series = trusted_series(rows, area.get('boundary_version') or 1)
                    summary['evaluated'] += _evaluate_predictions(db, area['id'], series)
                    summary['predictions'] += _store_predictions(db, area['id'], res['forecast'], now)
                    sid, created = _upsert_schedule(db, area, res['plan'], now)
                    summary['schedules_created'] += int(created)
                    if _auto_alert(db, area, res['decision'], sid, now):
                        summary['alerts_created'] += 1
                    summary['areas'] += 1
                    p = res['decision']['priority']
                    summary['by_priority'][p] = summary['by_priority'].get(p, 0) + 1
            with core.connect() as db:
                db.execute('UPDATE pipeline_runs SET finished_at=?, summary=? WHERE id=?', (core.utcnow(), json.dumps(summary), run_id))
            log.info('pipeline run %s (%s): %s', run_id, trigger, summary)
            return {'run_id': run_id, **summary}
        except Exception as ex:
            log.exception('pipeline run %s failed', run_id)
            with core.connect() as db:
                db.execute('UPDATE pipeline_runs SET finished_at=?, error=? WHERE id=?', (core.utcnow(), str(ex)[:500], run_id))
            raise
    finally:
        _PIPE_LOCK.release()


def _background_loop(hours: float):
    time.sleep(60)
    while True:
        try:
            run_pipeline('scheduled')
        except Exception:
            log.exception('scheduled pipeline run failed')
        time.sleep(max(0.25, hours) * 3600)


# ------------------------------------------------------------------------------------------------ models
class PipelineRun(BaseModel):
    area_ids: list[int] | None = None


class SchedulePatch(BaseModel):
    status: str | None = Field(default=None, pattern=r'^(scheduled|in_progress|done|cancelled)$')
    next_check: str | None = None
    assignee_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)


class BoundaryUpdate(BaseModel):
    geometry: dict
    source: str = Field(min_length=2, max_length=200)
    notes: str = Field(default='', max_length=1000)


class BoundaryReview(BaseModel):
    decision: str = Field(pattern=r'^(approve|reject|needs_review)$')
    notes: str = Field(default='', max_length=1000)


class TaskReview(BaseModel):
    outcome: str = Field(pattern=r'^(effective|not_effective|inconclusive)$')
    notes: str = Field(default='', max_length=1000)


# ------------------------------------------------------------------------------------------------ routes
def install(app_module):
    global core
    core = app_module
    app = core.app

    @app.get('/healthz')
    def healthz():
        try:
            with core.connect() as db:
                v = db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
            return {'ok': True, 'db': 'postgres' if core.IS_PG else 'sqlite', 'schema_version': v,
                    'copernicus_configured': bool(os.getenv('COPERNICUS_CLIENT_ID') and os.getenv('COPERNICUS_CLIENT_SECRET'))}
        except Exception as ex:
            log.exception('health check failed')
            return Response(json.dumps({'ok': False, 'error': type(ex).__name__}), status_code=503, media_type='application/json')

    @app.get('/api/intel/areas')
    def intel_areas(req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            out = []
            for a in _scoped_areas(db, u):
                res = analyse_area(a, observations(db, a['id']))
                res.pop('series', None)
                res.update(name_ar=a['name_ar'], name_en=a['name_en'], boundary_status=a.get('boundary_status'),
                           area_m2=a.get('area_m2'), schedule=_active_schedule(db, a['id']),
                           assignee=a.get('assigned_operator'))
                out.append(res)
            counts = {p: sum(1 for x in out if x['decision']['priority'] == p) for p in decision_mod.PRIORITIES}
            last = db.execute('SELECT id,started_at,finished_at,trigger,summary,error FROM pipeline_runs ORDER BY id DESC').fetchone()
        return {'areas': out, 'counts': counts, 'last_run': dict(last) if last else None, 'today': _today().isoformat(),
                'auto_pipeline': os.getenv('RAWAA_AUTO_PIPELINE') == '1'}

    @app.get('/api/areas/{area_id}/intel')
    def area_intel(area_id: int, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            a = dict(core.area_access(db, u, area_id))
            res = analyse_area(a, observations(db, area_id))
            res['schedule'] = _active_schedule(db, area_id)
            res['predictions'] = [dict(r) for r in db.execute('SELECT * FROM predictions WHERE area_id=? ORDER BY id DESC LIMIT 24', (area_id,))]
            res['boundary'] = {'status': a.get('boundary_status'), 'source': a.get('boundary_source'), 'version': a.get('boundary_version'),
                               'area_m2': a.get('area_m2'), 'vegetated_area_m2': a.get('vegetated_area_m2'),
                               'reviewed_at': a.get('boundary_reviewed_at'), 'notes': a.get('boundary_notes')}
        return res

    @app.post('/api/pipeline/run')
    def pipeline_run(v: PipelineRun, req: Request):
        u = core.current_user(req); core.require_regulator(u)
        res = run_pipeline('manual', u['id'], v.area_ids)
        if res.get('skipped'):
            raise HTTPException(409, res['reason'])
        return res

    @app.get('/api/pipeline/runs')
    def pipeline_runs(req: Request):
        u = core.current_user(req); core.require_regulator(u)
        with core.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 30')]

    @app.get('/api/schedule')
    def schedule_list(req: Request, include_history: int = 0):
        u = core.current_user(req)
        with core.connect() as db:
            q = 'SELECT s.*, a.name_ar, a.name_en FROM monitoring_schedule s JOIN areas a ON a.id=s.area_id'
            cond, params = [], []
            if not include_history:
                cond.append("s.status IN ('scheduled','in_progress')")
            if u['role'] == 'operator':
                cond.append('a.assigned_operator=?'); params.append(u['id'])
            if cond:
                q += ' WHERE ' + ' AND '.join(cond)
            return [_sched_out(dict(r)) for r in db.execute(q + ' ORDER BY s.next_check, s.id', params)]

    @app.patch('/api/schedule/{sid}')
    def schedule_patch(sid: int, v: SchedulePatch, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            s = db.execute('SELECT s.*, a.assigned_operator FROM monitoring_schedule s JOIN areas a ON a.id=s.area_id WHERE s.id=?', (sid,)).fetchone()
            if not s:
                raise HTTPException(404, 'Schedule entry not found')
            if u['role'] == 'operator':
                if s['assigned_operator'] != u['id']:
                    raise HTTPException(403, 'Outside your scope')
                if v.next_check or v.assignee_id is not None or v.status == 'cancelled':
                    raise HTTPException(403, 'Only the regulator can reschedule, reassign or cancel')
            fields = {}
            if v.status:
                fields['status'] = v.status
                if v.status == 'done':
                    fields['completed_at'] = core.utcnow(); fields['completed_by'] = u['id']
            if v.next_check:
                try:
                    date.fromisoformat(v.next_check)
                except ValueError:
                    raise HTTPException(400, 'next_check must be YYYY-MM-DD')
                fields['next_check'] = v.next_check
            if v.assignee_id is not None:
                if not db.execute("SELECT 1 FROM users WHERE id=? AND role='operator'", (v.assignee_id,)).fetchone():
                    raise HTTPException(400, 'Operator not found')
                fields['assignee_id'] = v.assignee_id
            if v.notes is not None:
                fields['notes'] = v.notes
            if not fields:
                raise HTTPException(400, 'No fields supplied')
            fields['updated_at'] = core.utcnow()
            db.execute('UPDATE monitoring_schedule SET ' + ', '.join(f'{k}=?' for k in fields) + ' WHERE id=?', [*fields.values(), sid])
            _activity(db, u['id'], 'schedule_update', sid, fields)
            return _sched_out(dict(db.execute('SELECT * FROM monitoring_schedule WHERE id=?', (sid,)).fetchone()))

    # ---- boundaries
    @app.get('/api/areas/{area_id}/boundary')
    def boundary_get(area_id: int, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            a = dict(core.area_access(db, u, area_id))
            hist = [dict(r) for r in db.execute('SELECT id,version,source,status,action,user_id,notes,area_m2,created_at FROM boundary_history WHERE area_id=? ORDER BY id DESC', (area_id,))]
            veg = db.execute("SELECT veg_fraction FROM observations WHERE area_id=? AND origin='satellite' AND veg_fraction IS NOT NULL AND reliability IN ('reliable','limited') AND boundary_version=? ORDER BY measured_at DESC", (area_id, a.get('boundary_version') or 1)).fetchone()
        g = json.loads(a['geometry'])
        rep = geo.validate(g)
        vf = veg['veg_fraction'] if veg else None
        return {'area_id': area_id, 'status': a.get('boundary_status'), 'source': a.get('boundary_source'), 'version': a.get('boundary_version'),
                'reviewed_at': a.get('boundary_reviewed_at'), 'reviewed_by': a.get('boundary_reviewed_by'), 'notes': a.get('boundary_notes'),
                'validation': rep, 'geometry': g, 'history': hist,
                'vegetated_fraction': vf, 'vegetated_area_m2': round(rep['area_m2'] * vf, 1) if (vf is not None and rep.get('area_m2')) else None,
                'non_vegetated_area_m2': round(rep['area_m2'] * (1 - vf), 1) if (vf is not None and rep.get('area_m2')) else None,
                'vegetation_rule': f'pixels with NDVI ≥ {indices.VEGETATION_NDVI_MIN} in the latest trusted clear reading',
                'final_results': a.get('boundary_status') == 'approved'}

    @app.put('/api/areas/{area_id}/boundary')
    def boundary_update(area_id: int, v: BoundaryUpdate, req: Request):
        u = core.current_user(req); core.require_regulator(u)
        rep = geo.validate(v.geometry)
        if not rep['valid']:
            raise HTTPException(400, {'message': 'Invalid boundary', 'errors': rep['errors']})
        with core.connect() as db:
            a = dict(core.area_access(db, u, area_id))
            ver = (a.get('boundary_version') or 1) + 1
            status = geo.initial_status(v.source, rep['placeholder'])
            db.execute('''UPDATE areas SET geometry=?, boundary_version=?, boundary_status=?, boundary_source=?, area_m2=?, perimeter_m=?,
                          vegetated_area_m2=NULL, boundary_notes=?, boundary_reviewed_by=NULL, boundary_reviewed_at=NULL WHERE id=?''',
                       (json.dumps(v.geometry), ver, status, v.source, rep['area_m2'], rep['perimeter_m'], v.notes, area_id))
            db.execute('INSERT INTO boundary_history(area_id,version,geometry,source,status,action,user_id,notes,area_m2,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (area_id, ver, json.dumps(v.geometry), v.source, status, 'update', u['id'], v.notes, rep['area_m2'], core.utcnow()))
            _activity(db, u['id'], 'boundary_update', area_id, f'v{ver} {v.source} {rep["area_m2"]} m²')
        return {'version': ver, 'status': status, 'validation': rep,
                'note': 'Readings computed on earlier boundary versions are excluded from comparisons; sync satellite data again.'}

    @app.post('/api/areas/{area_id}/boundary/review')
    def boundary_review(area_id: int, v: BoundaryReview, req: Request):
        u = core.current_user(req); core.require_regulator(u)
        status = {'approve': 'approved', 'reject': 'rejected', 'needs_review': 'needs_review'}[v.decision]
        with core.connect() as db:
            a = dict(core.area_access(db, u, area_id))
            g = json.loads(a['geometry'])
            rep = geo.validate(g)
            if status == 'approved' and not rep['valid']:
                raise HTTPException(400, 'Cannot approve an invalid polygon')
            if status == 'approved' and rep.get('placeholder') and not v.notes.strip():
                raise HTTPException(400, 'This boundary looks like a placeholder rectangle; add a note explaining why it is approved')
            db.execute('UPDATE areas SET boundary_status=?, boundary_reviewed_by=?, boundary_reviewed_at=?, boundary_notes=? WHERE id=?',
                       (status, u['id'], core.utcnow(), v.notes, area_id))
            db.execute('INSERT INTO boundary_history(area_id,version,geometry,source,status,action,user_id,notes,area_m2,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (area_id, a.get('boundary_version') or 1, a['geometry'], a.get('boundary_source'), status, 'review', u['id'], v.notes, rep.get('area_m2'), core.utcnow()))
            _activity(db, u['id'], 'boundary_review', area_id, f'{status}: {v.notes[:200]}')
        return {'status': status}

    # ---- readings and provenance
    @app.get('/api/areas/{area_id}/observations')
    def area_observations(area_id: int, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            a = dict(core.area_access(db, u, area_id))
            rows = observations(db, area_id)
        used = {r['id'] for r in trusted_series(rows, a.get('boundary_version') or 1)}
        for r in rows:
            r['used_in_analysis'] = r['id'] in used
            r['excluded_reason'] = None if r['used_in_analysis'] else (
                'demo' if r.get('origin') == 'demo' else 'unverified source (imported/manual)' if r.get('origin') in ('imported', 'manual')
                else 'low clear-sky share or too few clear pixels' if r.get('reliability') == 'unreliable'
                else 'computed on an older boundary version' if (r.get('boundary_version') or 1) != (a.get('boundary_version') or 1)
                else 'another reading of the same month was clearer')
        return rows

    @app.get('/api/observations/{obs_id}/provenance')
    def provenance(obs_id: int, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            r = db.execute(f'SELECT {OBS_COLS}, provenance FROM observations WHERE id=?', (obs_id,)).fetchone()
            if not r:
                raise HTTPException(404, 'Observation not found')
            core.area_access(db, u, r['area_id'])
        d = dict(r)
        try:
            d['provenance'] = json.loads(d['provenance']) if d.get('provenance') else None
        except ValueError:
            pass
        d['formulas'] = indices.FORMULAS
        return d

    # ---- forecast accuracy
    @app.get('/api/forecast-accuracy')
    def forecast_accuracy(req: Request):
        core.current_user(req)
        with core.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT horizon_days, abs_error, naive_abs_error FROM predictions WHERE actual_ndvi IS NOT NULL')]
            pending = db.execute('SELECT count(*) FROM predictions WHERE actual_ndvi IS NULL').fetchone()[0]
        out = {'pending': pending, 'horizons': []}
        for h in (7, 30):
            rs = [r for r in rows if r['horizon_days'] == h]
            if not rs:
                out['horizons'].append({'days': h, 'evaluated': 0}); continue
            mae = sum(r['abs_error'] for r in rs) / len(rs)
            nv = [r['naive_abs_error'] for r in rs if r['naive_abs_error'] is not None]
            out['horizons'].append({'days': h, 'evaluated': len(rs), 'mae': round(mae, 4),
                                    'mae_naive': round(sum(nv) / len(nv), 4) if nv else None})
        return out

    # ---- maintenance follow-up
    @app.get('/api/tasks/{task_id}/impact')
    def task_impact(task_id: int, req: Request):
        u = core.current_user(req)
        with core.connect() as db:
            t = dict(core.checked_task(db, u, task_id))
            a = dict(db.execute('SELECT * FROM areas WHERE id=?', (t['area_id'],)).fetchone())
            series = trusted_series(observations(db, t['area_id']), a.get('boundary_version') or 1)
        start = (t.get('created_at') or '')[:10]
        done = (t.get('completed_at') or (t['updated_at'] if t['status'] == 'closed' else '') or '')[:10]
        before = [r for r in series if reading_date(r) <= start][-3:]
        after = [r for r in series if done and reading_date(r) > done][:3]
        res = {'task_id': task_id, 'before': [{'date': reading_date(r), 'ndvi': r['ndvi'], 'valid_pixels_pct': r['valid_pixels_pct']} for r in before],
               'after': [{'date': reading_date(r), 'ndvi': r['ndvi'], 'valid_pixels_pct': r['valid_pixels_pct']} for r in after],
               'baseline_ndvi_at_assignment': t.get('baseline_ndvi'), 'completed_at': done or None}
        if before and after:
            b = sum(r['ndvi'] for r in before) / len(before); a_ = sum(r['ndvi'] for r in after) / len(after)
            res.update(mean_before=round(b, 3), mean_after=round(a_, 3), change=round(a_ - b, 3),
                       verdict='improved' if a_ - b >= 0.02 else 'declined' if a_ - b <= -0.02 else 'no_clear_change',
                       note_ar='المقارنة بين متوسط آخر 3 قراءات موثوقة قبل المهمة وأول 3 بعد إنجازها. قد يحتاج التعافي عدة أسابيع، والتغير الموسمي يؤثر.',
                       note_en='Mean of the last 3 trusted readings before the task vs the first 3 after completion. Recovery can take weeks; seasonality matters.')
        else:
            res.update(verdict='awaiting_readings', note_ar='لا توجد بعد قراءات فضائية موثوقة كافية قبل المهمة وبعدها للمقارنة.',
                       note_en='Not enough trusted readings before and after the task yet.')
        return res

    @app.post('/api/tasks/{task_id}/review')
    def task_review(task_id: int, v: TaskReview, req: Request):
        u = core.current_user(req); core.require_regulator(u)
        with core.connect() as db:
            t = core.checked_task(db, u, task_id)
            if t['status'] not in ('pending_review', 'closed'):
                raise HTTPException(409, 'Task must be completed before reviewing the intervention')
            db.execute('UPDATE tasks SET review_outcome=?, review_notes=?, reviewed_by=?, reviewed_at=?, updated_at=? WHERE id=?',
                       (v.outcome, v.notes, u['id'], core.utcnow(), core.utcnow(), task_id))
            _activity(db, u['id'], 'task_review', task_id, f'{v.outcome}: {v.notes[:200]}')
        return {'ok': True}

    # ---- reports
    def _csv(rows, fields, name):
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
        return Response('﻿' + out.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @app.get('/api/reports/decisions.csv')
    def report_decisions(req: Request):
        data = intel_areas(req)
        rows = []
        for x in data['areas']:
            d, f, s = x['decision'], x['forecast'], x.get('schedule') or {}
            h = {h_['days']: h_ for h_ in f.get('horizons', [])} if f.get('available') else {}
            rows.append({'area_id': x['area_id'], 'name_ar': x['name_ar'], 'name_en': x['name_en'], 'boundary_status': x['boundary_status'],
                         'area_m2': x['area_m2'], 'priority': d['priority'], 'priority_ar': d['priority_ar'], 'reliability': d['reliability'],
                         'current_date': (d.get('current') or {}).get('date'), 'current_ndvi': (d.get('current') or {}).get('ndvi'),
                         'previous_ndvi': (d.get('previous') or {}).get('ndvi'), 'expected_ndvi': d.get('expected_ndvi'),
                         'anomaly_pct': d.get('anomaly_pct'), 'persistence': d.get('persistence'), 'trend': d.get('trend', {}).get('direction'),
                         'reasons_ar': ' | '.join(d['reasons_ar']), 'action_ar': d['action_ar'],
                         'forecast_7d': h.get(7, {}).get('ndvi'), 'forecast_30d': h.get(30, {}).get('ndvi'),
                         'forecast_30d_low80': h.get(30, {}).get('low80'), 'forecast_30d_high80': h.get(30, {}).get('high80'),
                         'forecast_model': f.get('model'), 'forecast_skill_pct': (f.get('backtest') or {}).get('skill_pct'),
                         'decline_probability_pct': f.get('decline_probability_pct'), 'next_check': s.get('next_check'),
                         'schedule_status': s.get('status'), 'reassess_at': s.get('reassess_at')})
        return _csv(rows, list(rows[0].keys()) if rows else ['area_id'], 'rawaa-decisions.csv')

    @app.get('/api/reports/schedule.csv')
    def report_schedule(req: Request):
        rows = schedule_list(req, include_history=1)
        return _csv(rows, ['id', 'area_id', 'name_ar', 'name_en', 'next_check', 'priority', 'decision_priority', 'status', 'overdue', 'assignee_id',
                           'reassess_at', 'basis_date', 'reason_ar', 'reason_en', 'task_id', 'alert_id', 'notes', 'created_at', 'completed_at'], 'rawaa-schedule.csv')

    @app.get('/api/reports/predictions.csv')
    def report_predictions(req: Request):
        u = core.current_user(req); core.require_regulator(u)
        with core.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM predictions ORDER BY area_id, base_date, horizon_days')]
        return _csv(rows, ['id', 'area_id', 'generated_at', 'base_date', 'target_date', 'horizon_days', 'model', 'ndvi_pred', 'low80', 'high80',
                           'skill_pct', 'mae_backtest', 'mae_naive', 'n_used', 'actual_date', 'actual_ndvi', 'abs_error', 'naive_abs_error'], 'rawaa-predictions.csv')

    @app.get('/api/reports/audit.csv')
    def report_audit(req: Request):
        u = core.current_user(req); core.require_regulator(u)
        with core.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 5000')]
        return _csv(rows, ['id', 'created_at', 'user_id', 'verb', 'target', 'details'], 'rawaa-audit-log.csv')

    if os.getenv('RAWAA_AUTO_PIPELINE') == '1':
        hours = float(os.getenv('RAWAA_PIPELINE_HOURS', '12'))
        threading.Thread(target=_background_loop, args=(hours,), daemon=True, name='rawaa-pipeline').start()
        log.info('automatic pipeline enabled every %.1f h', hours)


# ------------------------------------------------------------------------------------------------ satellite sync
def sync_area(area_id, start, end, token, post_json, user_id):
    """Fetch scene-level Sentinel-2 readings for one park and store them (idempotent upsert)."""
    with core.connect() as db:
        a = dict(db.execute('SELECT * FROM areas WHERE id=?', (area_id,)).fetchone())
    geom = json.loads(a['geometry'])
    readings, report = sentinel.fetch_readings(post_json, token, geom, start, end, a.get('boundary_version') or 1)
    now = core.utcnow()
    with core.connect() as db:
        for r in readings:
            db.execute(f'''INSERT INTO observations(area_id,measured_at,acquired_at,ndvi,ndmi,ndwi,savi,ndre,salinity,ndvi_std,valid_pixels_pct,
                    clear_pixels,veg_fraction,ndvi_veg,source,origin,reliability,scene_ids,boundary_version,processing_version,provenance,is_demo,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
                    ON CONFLICT(area_id,measured_at,source) DO UPDATE SET acquired_at=excluded.acquired_at, ndvi=excluded.ndvi, ndmi=excluded.ndmi,
                    ndwi=excluded.ndwi, savi=excluded.savi, ndre=excluded.ndre, salinity=excluded.salinity, ndvi_std=excluded.ndvi_std,
                    valid_pixels_pct=excluded.valid_pixels_pct, clear_pixels=excluded.clear_pixels, veg_fraction=excluded.veg_fraction,
                    ndvi_veg=excluded.ndvi_veg, origin=excluded.origin, reliability=excluded.reliability, scene_ids=excluded.scene_ids,
                    boundary_version=excluded.boundary_version, processing_version=excluded.processing_version, provenance=excluded.provenance''',
                       (area_id, r['measured_at'], r['acquired_at'], r['ndvi'], r['ndmi'], r['ndwi'], r['savi'], r['ndre'], r['salinity'], r['ndvi_std'],
                        r['valid_pixels_pct'], r['clear_pixels'], r['veg_fraction'], r['ndvi_veg'], r['source'], r['origin'], r['reliability'],
                        r['scene_ids'], r['boundary_version'], r['processing_version'], r['provenance'], now))
        trusted = [r for r in readings if r['reliability'] in ('reliable', 'limited') and r.get('veg_fraction') is not None]
        if trusted and report.get('boundary_area_m2'):
            db.execute('UPDATE areas SET vegetated_area_m2=? WHERE id=?', (round(report['boundary_area_m2'] * trusted[-1]['veg_fraction'], 1), area_id))
        _activity(db, user_id, 'satellite_sync', area_id, report)
    return report
