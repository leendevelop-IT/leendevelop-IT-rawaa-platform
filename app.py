"""Rawaa MVP — bilingual green-space operations and optional Sentinel-2 statistics.

Demo observations are explicitly labeled and never silently promoted to live readings.
The app is a local MVP, not production-certified or a validated ML forecasting service.
"""
from __future__ import annotations
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import logging
import re
from maintenance_engine import maintenance_engine, MONTHLY_MAINTENANCE, ndvi_drop_activities
from plant_catalog import PLANTS, parse_species, species_summary, salt_tolerant
import rawaa_ml
import narrative
import math
import os
import secrets
import sqlite3
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import parse, request, error

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rawaa_core import geo as rgeo, indices as rindices, migrations as rmigrations

# Local development: read settings from a .env file next to app.py if one exists.
# Real environment variables (e.g. on Render) always take precedence; tests set RAWAA_NO_DOTENV=1.
if os.getenv('RAWAA_NO_DOTENV')!='1':
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent/'.env',override=False)
    except ImportError:
        pass

logging.basicConfig(level=os.getenv('RAWAA_LOG_LEVEL', 'INFO'),
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('rawaa')

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('RAWAA_DB') or ROOT / 'data' / 'rawaa.sqlite3')
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Rawaa | رَوَاء API', version='0.2.0')
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

@app.middleware('http')
async def _revalidate_static(request, call_next):
    """Make browsers re-check the page and its scripts on every visit (cheap ETag check),
    so a new deployment shows up immediately instead of an old cached copy."""
    t0=time.perf_counter();rid=secrets.token_hex(6)
    try:
        response=await call_next(request)
    except Exception:
        log.exception('request %s %s %s failed',rid,request.method,request.url.path)
        return JSONResponse({'detail':'Internal server error','request_id':rid},status_code=500)
    path=request.url.path
    if path=='/' or path.endswith(('.js','.css','.html')):
        response.headers['Cache-Control']='no-cache'
    response.headers['X-Request-ID']=rid
    if path.startswith('/api/') and not path.startswith('/api/tiles/'):
        lvl=logging.WARNING if response.status_code>=500 else logging.INFO
        log.log(lvl,'%s %s %s %d %.0fms',rid,request.method,path,response.status_code,(time.perf_counter()-t0)*1000)
    return response
DB_LOCK = threading.RLock()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

# --- Database: SQLite locally (RAWAA_DB), PostgreSQL in production when DATABASE_URL is set (e.g. Neon). ---
DATABASE_URL=os.getenv('DATABASE_URL','').strip()
IS_PG=DATABASE_URL.startswith(('postgres://','postgresql://'))
_TABLES_WITH_ID={'users','sessions','areas','observations','alerts','tasks','activity','thermal','labels',
                 'boundary_history','predictions','monitoring_schedule','pipeline_runs'}

class _Row(dict):
    """Row usable like sqlite3.Row: row['col'], row[0], dict(row)."""
    __slots__=('_vals',)
    def __init__(self,cols,vals):
        super().__init__(zip(cols,vals));self._vals=list(vals)
    def __getitem__(self,k):
        return self._vals[k] if isinstance(k,int) else dict.__getitem__(self,k)
    def keys(self): return list(dict.keys(self))

class _PGCursor:
    def __init__(self,cur,lastrowid=None):
        self._c=cur;self.lastrowid=lastrowid
        self._cols=[d.name for d in cur.description] if cur.description else []
    def fetchone(self):
        r=self._c.fetchone();return _Row(self._cols,r) if r is not None else None
    def fetchall(self): return [_Row(self._cols,r) for r in self._c.fetchall()]
    def __iter__(self): return iter(self.fetchall())

class _PGConn:
    """Thin adapter so the app's SQLite-style SQL ('?' placeholders, lastrowid) runs on PostgreSQL."""
    def __init__(self,conn): self._conn=conn
    def execute(self,sql,params=()):
        q=sql.replace('%','%%').replace('?','%s')
        m=re.match(r"\s*INSERT\s+INTO\s+(\w+)",q,re.I)
        want_id=bool(m and m.group(1).lower() in _TABLES_WITH_ID and 'RETURNING' not in q.upper())
        if want_id: q=q.rstrip().rstrip(';')+' RETURNING id'
        cur=self._conn.cursor();cur.execute(q,tuple(params))
        rid=None
        if want_id:
            r=cur.fetchone();rid=r[0] if r else None
        return _PGCursor(cur,rid)
    def executescript(self,script):
        for stmt in [x.strip() for x in script.split(';') if x.strip()]:
            self._conn.execute(_pg_ddl(stmt))
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()

def _pg_ddl(stmt):
    stmt=re.sub(r'\bid INTEGER PRIMARY KEY\b','id SERIAL PRIMARY KEY',stmt)
    return stmt.replace(' BLOB',' BYTEA')

_PG_CONN=None
def _pg():
    global _PG_CONN
    import psycopg
    if _PG_CONN is not None and not _PG_CONN.closed:
        try:
            _PG_CONN.execute('SELECT 1');_PG_CONN.commit();return _PG_CONN
        except Exception:
            try:_PG_CONN.close()
            except Exception:pass
    _PG_CONN=psycopg.connect(DATABASE_URL,connect_timeout=15)
    return _PG_CONN

def table_columns(db,table):
    if IS_PG:
        return {r[0] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_name=?',(table,))}
    return {r[1] for r in db.execute(f'PRAGMA table_info({table})')}

@contextmanager
def connect():
    with DB_LOCK:
        if IS_PG:
            raw=_pg();db=_PGConn(raw)
            try:
                yield db
                raw.commit()
            except Exception:
                raw.rollback();raise
            return
        db = sqlite3.connect(DB_PATH, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        finally:
            db.close()


def asdict(row): return dict(row) if row is not None else None

def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 260_000)
    return salt.hex()+':'+dk.hex()

def password_ok(password, encoded):
    try:
        s, expected = encoded.split(':')
        actual = password_hash(password, bytes.fromhex(s)).split(':')[1]
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def square(lng, lat, d=0.002):
    return {'type':'Polygon','coordinates':[[
        [lng-d,lat-d*.68],[lng+d,lat-d*.68],[lng+d,lat+d*.68],
        [lng-d,lat+d*.68],[lng-d,lat-d*.68]
    ]]}


def init_db():
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, display TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('regulator','operator')),
              pw_hash TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(
              id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL,
              expires INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS areas(
              id INTEGER PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT 'Park', assigned_operator INTEGER,
              geometry TEXT NOT NULL, irrigation TEXT DEFAULT '', plants TEXT DEFAULT '',
              planting_date TEXT, demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
              FOREIGN KEY(assigned_operator) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS observations(
              id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, measured_at TEXT NOT NULL,
              ndvi REAL, ndmi REAL, valid_pixels_pct REAL NOT NULL, source TEXT NOT NULL,
              is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
              UNIQUE(area_id, measured_at, source), FOREIGN KEY(area_id) REFERENCES areas(id));
            CREATE TABLE IF NOT EXISTS alerts(
              id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, severity TEXT NOT NULL,
              reason_ar TEXT NOT NULL, reason_en TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL,
              FOREIGN KEY(area_id) REFERENCES areas(id));
            CREATE TABLE IF NOT EXISTS tasks(
              id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, alert_id INTEGER,
              title_ar TEXT NOT NULL, title_en TEXT NOT NULL, assigned_to INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'medium',
              due_at TEXT, action TEXT DEFAULT '', actual_cause TEXT DEFAULT '',
              notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(area_id) REFERENCES areas(id),
              FOREIGN KEY(alert_id) REFERENCES alerts(id),
              FOREIGN KEY(assigned_to) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS task_photos(
              task_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('before','after')),
              filename TEXT NOT NULL, mime TEXT NOT NULL, uploaded_by INTEGER NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(task_id,kind), FOREIGN KEY(task_id) REFERENCES tasks(id));
            CREATE TABLE IF NOT EXISTS activity(
              id INTEGER PRIMARY KEY, user_id INTEGER, verb TEXT NOT NULL, target TEXT NOT NULL,
              details TEXT DEFAULT '', created_at TEXT NOT NULL);
        ''')
        if db.execute('SELECT count(*) FROM users').fetchone()[0]: return
        db.execute('INSERT INTO users(email,display,role,pw_hash,created_at) VALUES (?,?,?,?,?)',
                   ('regulator@rawaa.local','Jeddah Municipality — Demo','regulator',password_hash('Rawaa2026!'),utcnow()))
        db.execute('INSERT INTO users(email,display,role,pw_hash,created_at) VALUES (?,?,?,?,?)',
                   ('operator@rawaa.local','Operations Contractor — Demo','operator',password_hash('Rawaa2026!'),utcnow()))
        # Geographic polygons are illustrative placeholders only, NOT official project borders.
        names = [('منطقة تجريبية A','Demo Zone A',21.548,39.164,'Sprinkler','Grass & trees'),
                 ('منطقة تجريبية B','Demo Zone B',21.574,39.184,'Drip','Shrubs & palms'),
                 ('منطقة تجريبية C','Demo Zone C',21.523,39.207,'Sprinkler','Grass'),
                 ('منطقة تجريبية D','Demo Zone D',21.601,39.156,'Drip','Trees & shrubs'),
                 ('منطقة تجريبية E','Demo Zone E',21.497,39.177,'Mixed','Palms & trees')]
        trends = [[.54,.55,.56,.54,.55,.56],[.56,.55,.53,.51,.50,.47],
                  [.55,.53,.49,.44,.40,.36],[.49,.48,.49,.50,.51,.52],[.52,.51,.50,.49,.48,.48]]
        thismonth = date.today().replace(day=1)
        for index,(ar,en,lat,lng,irrig,plants) in enumerate(names):
            cur = db.execute('INSERT INTO areas(name_ar,name_en,category,assigned_operator,geometry,irrigation,plants,planting_date,demo,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ar,en,'Green space',2,json.dumps(square(lng,lat)),irrig,plants,'2025-01-01',1,utcnow()))
            area_id=cur.lastrowid
            for monthidx,val in enumerate(trends[index]):
                d=(thismonth-timedelta(days=(5-monthidx)*30)).isoformat()
                db.execute('INSERT INTO observations(area_id,measured_at,ndvi,ndmi,valid_pixels_pct,source,is_demo,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (area_id,d,val,round(val-.16,3),91,'DEMO — synthetic sample',1,utcnow()))
        for area_id,severity,ar,en in [
            (2,'monitor','مؤشر نباتي منخفض مقارنة بالفترة السابقة','Vegetation index lower than baseline'),
            (3,'high','انخفاض متكرر في مؤشر الغطاء النباتي','Repeated vegetation-index decline')]:
            cur=db.execute('INSERT INTO alerts(area_id,severity,reason_ar,reason_en,status,created_at) VALUES (?,?,?,?,?,?)',
                (area_id,severity,ar,en,'new',utcnow()))
            db.execute('INSERT INTO tasks(area_id,alert_id,title_ar,title_en,assigned_to,status,priority,due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (area_id,cur.lastrowid,'زيارة تحقق ميداني','Field verification visit',2,'open','high' if severity=='high' else 'medium',
                 (date.today()+timedelta(days=4)).isoformat(),utcnow(),utcnow()))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES (?,?,?,?,?)',
            (1,'seed','system','Initial DEMO content — not satellite observations',utcnow()))

init_db()

# Real Jeddah sites. Boundaries marked "OSM" come from OpenStreetMap (© OpenStreetMap contributors, ODbL);
# "approx" boundaries are a ~200 x 150 m rectangle around the Google Maps pin until the real outline is drawn.
# No synthetic readings are attached to any of them: they only show what Copernicus Sentinel-2 returns.
OSM_RINGS = {"majid":[[39.181215,21.590235],[39.181659,21.589014],[39.185624,21.590207],[39.18501,21.592798],[39.184919,21.592876],[39.184829,21.592905],[39.183348,21.592545],[39.183229,21.59248],[39.181239,21.590371],[39.181215,21.590235]],"corniche":[[39.149704,21.522834],[39.149701,21.522635],[39.149728,21.522507],[39.150007,21.522122],[39.150252,21.521875],[39.150361,21.521794],[39.150511,21.521727],[39.15119,21.521505],[39.1513,21.521436],[39.151355,21.521365],[39.152012,21.519627],[39.152167,21.519267],[39.152226,21.519043],[39.152665,21.518426],[39.152866,21.518173],[39.152661,21.517818],[39.153044,21.516969],[39.15364,21.517187],[39.150853,21.523589],[39.150784,21.523905],[39.150796,21.524127],[39.150865,21.524408],[39.150988,21.524639],[39.151063,21.524735],[39.151344,21.525055],[39.151745,21.525448],[39.152315,21.525915],[39.152683,21.526192],[39.153174,21.526532],[39.15318,21.526572],[39.154136,21.527167],[39.154175,21.527159],[39.155497,21.527946],[39.15551,21.527984],[39.156067,21.528322],[39.156757,21.528705],[39.15676,21.528733],[39.157332,21.52898],[39.157876,21.529191],[39.157913,21.529185],[39.158147,21.529302],[39.158218,21.52935],[39.15838,21.529504],[39.158473,21.529635],[39.158575,21.529869],[39.158598,21.530067],[39.158183,21.530166],[39.158177,21.530225],[39.158098,21.530279],[39.157992,21.530266],[39.157987,21.530181],[39.157848,21.530187],[39.157835,21.530156],[39.157693,21.530124],[39.157425,21.530129],[39.156471,21.5302],[39.156411,21.530065],[39.156376,21.530081],[39.156225,21.529772],[39.156244,21.529761],[39.155648,21.528975],[39.155386,21.528813],[39.154762,21.528285],[39.15467,21.528175],[39.154682,21.528159],[39.154422,21.527936],[39.154206,21.527785],[39.154218,21.527762],[39.153956,21.527563],[39.153712,21.527413],[39.153724,21.527378],[39.153404,21.527125],[39.153234,21.526961],[39.153249,21.52694],[39.153078,21.526819],[39.152998,21.52672],[39.152918,21.526672],[39.152932,21.526653],[39.152803,21.526578],[39.152713,21.526461],[39.152591,21.526382],[39.152607,21.526356],[39.151663,21.525752],[39.151595,21.525482],[39.151556,21.525437],[39.151137,21.525127],[39.151104,21.525066],[39.151104,21.524996],[39.151077,21.524977],[39.151101,21.524953],[39.150889,21.524781],[39.150828,21.524693],[39.150843,21.524666],[39.150713,21.5245],[39.150717,21.524466],[39.150605,21.524402],[39.150529,21.524337],[39.150493,21.524193],[39.150531,21.523837],[39.150511,21.523778],[39.150104,21.523056],[39.149763,21.522898],[39.149704,21.522834]],"saja":[[39.185792,21.527631],[39.185831,21.527557],[39.185896,21.527514],[39.18683,21.527534],[39.186851,21.527514],[39.186968,21.524557],[39.188075,21.524599],[39.187865,21.528056],[39.187851,21.528091],[39.187817,21.52811],[39.187524,21.528072],[39.185896,21.527783],[39.185842,21.527749],[39.185803,21.527685],[39.185792,21.527631]],"tihamah":[[39.208188,21.54982],[39.208477,21.548486],[39.209049,21.548591],[39.209059,21.548697],[39.209095,21.548739],[39.209153,21.54876],[39.209242,21.548736],[39.209301,21.548638],[39.209885,21.548747],[39.209599,21.550091],[39.208188,21.54982]],"ajwad":[[39.252292,21.59362],[39.252354,21.592868],[39.2525,21.592229],[39.252517,21.592047],[39.252494,21.591656],[39.25255,21.5916],[39.252588,21.591598],[39.25338,21.591739],[39.253421,21.591784],[39.253433,21.591852],[39.253168,21.592939],[39.253155,21.593271],[39.25318,21.59345],[39.25329,21.59381],[39.253533,21.594281],[39.253781,21.594687],[39.253946,21.595058],[39.254068,21.595391],[39.254181,21.595872],[39.254213,21.596361],[39.254187,21.596388],[39.253942,21.596309],[39.253429,21.595899],[39.25303,21.595438],[39.252717,21.595013],[39.252377,21.594372],[39.252292,21.59362]]}

def _poly(key=None, lat=None, lng=None):
    if key: return {'type':'Polygon','coordinates':[OSM_RINGS[key]]}
    return square(lng,lat,0.001)

# (name_en key, name_ar, category, role_ar, role_en, geometry, boundary source)
REAL_SITES = [
    # Five case-study parks (one per case type in the project plan)
    ('Prince Majid Park','حديقة الأمير ماجد','Case study',
     'حالة ١ · حديقة مرجعية ممتازة: شكل NDVI الطبيعي (حي الربوة، نحو ٨ كم من البحر)',
     'Case 1 · Excellent reference park: normal NDVI shape (Ar Rabwah, ~8 km from the sea)',_poly('majid'),'OSM way 1074269189'),
    ('Al Huda Garden','حديقة الهدى','Case study',
     'حالة ٢ · مرشّحة لإجهاد مائي/موت نباتات (حي المروة). الترشيح من تقييمات الزوار العامة ويحتاج تأكيد الأمانة',
     'Case 2 · Candidate water stress / plant loss (Al Marwah). Based on public visitor reviews; needs municipality confirmation',_poly(lat=21.6105335,lng=39.2171712),'approx'),
    ('Middle Corniche Park','حديقة الكورنيش الأوسط','Case study',
     'حالة ٣ · ساحلية ملاصقة للبحر: اختبار الملوحة (حي الحمراء)',
     'Case 3 · Coastal, on the seafront: salinity test (Al Hamra)',_poly('corniche'),'OSM way 628514686'),
    ('Al Saja Gardens','حدائق السجى','Case study',
     'حالة ٤ · داخلية على نفس خط العرض وتبعد نحو ٤ كم عن البحر: شاهد (Control) للحالة ٣ (حي الشرفية)',
     'Case 4 · Inland at the same latitude, ~4 km from the sea: control for case 3 (Ash Sharafiyah)',_poly('saja'),'OSM way 165769855'),
    ('Abruq Al-Rughamah Garden','حديقة أبرق الرغامة','Case study',
     'حالة ٥ · مرشّحة لإجهاد حيوي/تشبع مائي وإهمال (حي أبرق الرغامة). الترشيح من تقييمات الزوار العامة ويحتاج تأكيد الأمانة',
     'Case 5 · Candidate biotic stress / waterlogging and neglect (Abruq Al-Rughamah). Based on public reviews; needs municipality confirmation',_poly(lat=21.5008814,lng=39.2719418),'approx'),
    # Field-validation sites supplied by the team, to compare with the municipality's own records
    ('Validation site 1','حديقة تهامة (موقع التحقق ١)','Validation site',
     'موقع تحقق للمقارنة مع نتائج الأمانة (حي العزيزية)','Validation site for comparison with municipality results (Al Aziziyah)',_poly('tihamah'),'OSM way 628578775'),
    ('Validation site 2','موقع التحقق ٢','Validation site',
     'موقع تحقق للمقارنة مع نتائج الأمانة (حي الشاطئ، قرب الساحل)','Validation site for comparison with municipality results (Ash Shati, near the coast)',_poly(lat=21.6531027,lng=39.1083515),'approx'),
    ('Al Ajwad New Park','حديقة الأجواد الجديدة','Validation site',
     'موقع تحقق للمقارنة مع نتائج الأمانة (حي الأجواد)','Validation site for comparison with municipality results (Al Ajwad)',_poly('ajwad'),'OSM way 1491780911'),
]
SITE_INFO = {r[0]:{'role_ar':r[3],'role_en':r[4],'boundary_source':r[6]} for r in REAL_SITES}

def ensure_validation_sites():
    with connect() as db:
        for en,ar,cat,_ra,_re,geom,src in REAL_SITES:
            row=db.execute('SELECT * FROM areas WHERE name_en=?',(en,)).fetchone()
            if row:
                # Never overwrite a boundary that was edited (version > 1) or reviewed by the authority.
                if ('boundary_version' in row.keys() and ((row['boundary_version'] or 1)>1 or row['boundary_status'] in ('approved','rejected'))):
                    db.execute('UPDATE areas SET name_ar=?,category=? WHERE id=?',(ar,cat,row['id']))
                else:
                    db.execute('UPDATE areas SET name_ar=?,category=?,geometry=? WHERE id=?',(ar,cat,json.dumps(geom),row['id']))
                continue
            db.execute('INSERT INTO areas(name_ar,name_en,category,assigned_operator,geometry,irrigation,plants,planting_date,demo,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ar,en,cat,2,json.dumps(geom),'','',None,0,utcnow()))
            db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES (?,?,?,?,?)',
                (1,'seed','area',f'{cat} added: {en} - boundary: {src}',utcnow()))

ensure_validation_sites()

def purge_demo_areas():
    """Remove the synthetic demo zones (A-E) with their readings, alerts and tasks; only real sites remain.
    Set RAWAA_KEEP_DEMO=1 to keep them (used by the automated tests)."""
    if os.getenv('RAWAA_KEEP_DEMO')=='1': return
    with connect() as db:
        ids=[r[0] for r in db.execute('SELECT id FROM areas WHERE demo=1')]
        if not ids: return
        q=','.join('?'*len(ids))
        db.execute(f'DELETE FROM task_photos WHERE task_id IN (SELECT id FROM tasks WHERE area_id IN ({q}))',ids)
        db.execute(f'DELETE FROM tasks WHERE area_id IN ({q})',ids)
        db.execute(f'DELETE FROM alerts WHERE area_id IN ({q})',ids)
        db.execute(f'DELETE FROM observations WHERE area_id IN ({q}) OR is_demo=1',ids)
        for tb in ('thermal','labels','boundary_history','predictions','monitoring_schedule'):
            if table_columns(db,tb): db.execute(f'DELETE FROM {tb} WHERE area_id IN ({q})',ids)
        db.execute(f'DELETE FROM areas WHERE id IN ({q})',ids)


EXTRA_INDEX_COLUMNS = ('ndwi','savi','ndre','salinity','ndvi_std')
def migrate_spectral_columns():
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS thermal(
              id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, measured_at TEXT NOT NULL,
              lst_park REAL, lst_ring REAL, valid_pixels_pct REAL, created_at TEXT NOT NULL,
              UNIQUE(area_id, measured_at), FOREIGN KEY(area_id) REFERENCES areas(id));
            CREATE TABLE IF NOT EXISTS labels(
              id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, observed_on TEXT NOT NULL, cause TEXT NOT NULL,
              source TEXT NOT NULL, notes TEXT DEFAULT '', task_id INTEGER, created_at TEXT NOT NULL,
              FOREIGN KEY(area_id) REFERENCES areas(id));
        ''')
        if 'confirmed_cause' not in table_columns(db,'tasks'):
            db.execute("ALTER TABLE tasks ADD COLUMN confirmed_cause TEXT DEFAULT ''")
        have=table_columns(db,'observations')
        for col in EXTRA_INDEX_COLUMNS:
            if col not in have: db.execute(f'ALTER TABLE observations ADD COLUMN {col} REAL')
        if 'data' not in table_columns(db,'task_photos'):
            db.execute('ALTER TABLE task_photos ADD COLUMN data '+('BYTEA' if IS_PG else 'BLOB'))

migrate_spectral_columns()

# Versioned migrations (rawaa_core/migrations.py): provenance, boundaries, predictions, schedule, follow-up.
rmigrations.run(connect,table_columns,{'now':utcnow,'source_for':lambda name:SITE_INFO.get(name,{}).get('boundary_source')})

def backfill_boundaries():
    """Boundary metadata for parks added after the migration ran (new sites, user-created areas)."""
    with connect() as db:
        for a in db.execute('SELECT id,name_en,geometry,boundary_status,boundary_source FROM areas WHERE boundary_status IS NULL OR area_m2 IS NULL').fetchall():
            g=json.loads(a['geometry']);rep=rgeo.validate(g)
            src=a['boundary_source'] or SITE_INFO.get(a['name_en'],{}).get('boundary_source') or 'user-supplied'
            st=a['boundary_status'] or (rgeo.initial_status(src,rep.get('placeholder',False)) if rep['valid'] else 'needs_review')
            db.execute('UPDATE areas SET boundary_status=?,boundary_source=?,boundary_version=COALESCE(boundary_version,1),area_m2=?,perimeter_m=? WHERE id=?',
                       (st,src,rep.get('area_m2'),rep.get('perimeter_m'),a['id']))
            if not db.execute('SELECT 1 FROM boundary_history WHERE area_id=?',(a['id'],)).fetchone():
                db.execute('INSERT INTO boundary_history(area_id,version,geometry,source,status,action,user_id,notes,area_m2,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (a['id'],1,a['geometry'],src,st,'initial',None,'',rep.get('area_m2'),utcnow()))

backfill_boundaries()
purge_demo_areas()


def current_user(req: Request):
    cookie=req.cookies.get('rawaa_session','')
    if not cookie: raise HTTPException(401,'Login required')
    digest=hashlib.sha256(cookie.encode()).hexdigest()
    with connect() as db:
        r=db.execute('''SELECT u.id,u.email,u.display,u.role FROM sessions s
            JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>?''',
            (digest,int(time.time()))).fetchone()
    if not r: raise HTTPException(401,'Session expired')
    return dict(r)

def require_regulator(u):
    if u['role']!='regulator': raise HTTPException(403,'Regulator role required')

def area_access(db, user, area_id):
    area=db.execute('SELECT * FROM areas WHERE id=?', (area_id,)).fetchone()
    if not area: raise HTTPException(404,'Area not found')
    if user['role']=='operator' and area['assigned_operator']!=user['id']:
        raise HTTPException(403,'Area outside your scope')
    return area


def in_scope_clause(user, alias='a'):
    if user['role']=='operator': return (f' WHERE {alias}.assigned_operator=?', [user['id']])
    return ('',[])


def same_season(rows,latest):
    """Readings from the same time of year (±1 month) in earlier years; used once 24+ months exist,
    so a normal summer dip is not mistaken for decline."""
    if len(rows)<24: return []
    lm=int(latest['measured_at'][5:7]);ld=date.fromisoformat(latest['measured_at'])
    out=[r for r in rows if (ld-date.fromisoformat(r['measured_at'])).days>300 and min((int(r['measured_at'][5:7])-lm)%12,(lm-int(r['measured_at'][5:7]))%12)<=1]
    return out if len(out)>=2 else []

def metrics(area_id, db):
    rows=[dict(r) for r in db.execute('SELECT id,measured_at,acquired_at,ndvi,ndmi,ndwi,savi,ndre,salinity,ndvi_std,valid_pixels_pct,source,origin,reliability,scene_ids,boundary_version,is_demo FROM observations WHERE area_id=? ORDER BY measured_at', (area_id,))]
    return metrics_from_rows(rows)

def metrics_from_rows(rows):
    real=[r for r in rows if not r['is_demo'] and r['ndvi'] is not None]
    # Satellite readings take precedence; imported/manual values are only shown when no satellite data exists
    # and are never used by the automatic decision pipeline (intelligence_api.py).
    sat=[r for r in real if r.get('origin')=='satellite' and r.get('reliability')!='unreliable']
    if sat: real=sat
    series=real if real else [r for r in rows if r['is_demo']]
    quality=[r for r in series if r['valid_pixels_pct'] >= 60]
    # A minimum of 3 valid chronological observations is required for even a provisional label.
    if len(quality)<3:
        return {'status':'insufficient','baseline':None,'current_ndvi':quality[-1]['ndvi'] if quality else None,
                'change_pct':None,'forecast':None,'forecast_kind':None,
                'latest_date':quality[-1]['measured_at'] if quality else None,'demo':bool(series and series[0]['is_demo']),
                'source':series[-1]['source'] if series else None,'observations':series}
    latest=quality[-1]
    season=same_season(quality,latest)
    base=statistics.median([r['ndvi'] for r in season]) if season else statistics.median([r['ndvi'] for r in quality[:-2]])
    change_pct=(latest['ndvi']-base)/abs(base)*100 if base else None
    last2=[(r['ndvi']-base)/abs(base)*100 for r in quality[-2:]] if base else [0,0]
    if all(x<=-20 for x in last2): status='high'
    elif (change_pct is not None and change_pct<=-10): status='monitor'
    else: status='stable'
    # Simple descriptive extrapolation is NOT presented as a trained AI forecast.
    xs=[r['ndvi'] for r in quality[-3:]]
    monthly_delta=(xs[-1]-xs[0])/2
    forecast=[round(max(-1,min(1,latest['ndvi']+monthly_delta*i)),3) for i in (1,2)]
    return {'status':status,'baseline':round(base,3),'current_ndvi':latest['ndvi'],
            'change_pct':round(change_pct,1) if change_pct is not None else None,'baseline_kind':'seasonal' if season else 'rolling',
            'forecast':forecast,'forecast_kind':'illustrative_linear_trend',
            'latest_date':latest['measured_at'],'demo':bool(series[0]['is_demo']),
            'source':latest['source'],'observations':series}


# =====================================================================================================
# RAWAA intelligence engine: diagnosis -> forecast -> intervention recommendations.
# Transparent, rule-based and statistical (no black box): every conclusion carries the numbers,
# the reference it was compared with, and a plain-language explanation in Arabic and English.
# =====================================================================================================
COASTAL_SITES={'Middle Corniche Park','Validation site 2'}
_FLOOR={'ndvi':0.02,'ndmi':0.02,'ndwi':0.02,'ndre':0.015,'salinity':0.005,'ndvi_std':0.01}
_MONTHS_AR=['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

def _fin(x): return isinstance(x,(int,float)) and math.isfinite(x)

def _ref(rows,key):
    vals=[r[key] for r in rows if _fin(r.get(key))]
    if len(vals)<2: return None
    med=statistics.median(vals);sd=statistics.pstdev(vals)
    return {'median':med,'std':max(sd,_FLOOR[key]),'n':len(vals)}

def _z(v,ref): return (v-ref['median'])/ref['std'] if (ref and _fin(v)) else None

def _holt(y,alpha=0.5,beta=0.3,phi=0.85):
    """Damped-trend Holt smoothing. Returns one-step in-sample predictions and final level/trend."""
    level,trend=y[0],(y[1]-y[0]) if len(y)>1 else 0.0
    preds=[None]
    for t in range(1,len(y)):
        p=level+phi*trend;preds.append(p)
        new_level=alpha*y[t]+(1-alpha)*(level+phi*trend)
        trend=beta*(new_level-level)+(1-beta)*phi*trend;level=new_level
    return preds,level,trend

def _hw(y,alpha=0.4,beta=0.1,gamma=0.3,m=12):
    """Additive Holt-Winters (level + trend + 12-month season). Returns one-step predictions and a forecaster."""
    season=[y[i]-statistics.mean(y[:m]) for i in range(m)]
    level=statistics.mean(y[:m]);trend=(statistics.mean(y[m:2*m])-statistics.mean(y[:m]))/m if len(y)>=2*m else 0.0
    preds=[None]*len(y)
    for t in range(len(y)):
        if t>=m: preds[t]=level+trend+season[t%m]
        new_level=alpha*(y[t]-season[t%m])+(1-alpha)*(level+trend)
        trend=beta*(new_level-level)+(1-beta)*trend
        season[t%m]=gamma*(y[t]-new_level)+(1-gamma)*season[t%m];level=new_level
    n=len(y)
    return preds,(lambda h:level+h*trend+season[(n+h-1)%m])

def _candidates(y):
    """One-step predictions + h-step forecaster for each model that has enough history."""
    out={}
    out['naive']=([None]+y[:-1],lambda h,yy=y:yy[-1],'«نفس قيمة الشهر السابق»','Same as last month')
    if len(y)>=5:
        p,level,trend=_holt(y,phi=0.85)
        out['holt']=(p,(lambda h,l=level,tr=trend:l+sum(0.85**i for i in range(1,h+1))*tr),'Holt بالاتجاه المخمّد','Holt damped trend')
    if len(y)>=15:
        out['seasonal_naive']=([None]*12+y[:-12],(lambda h,yy=y:yy[len(yy)-12+(h-1)%12]),'«نفس الشهر من العام الماضي»','Same month last year')
    if len(y)>=24:
        p,f=_hw(y);out['holt_winters']=(p,f,'Holt-Winters الموسمي (اتجاه + موسم سنوي)','Seasonal Holt-Winters')
    return out

def _forecast(series,base):
    y=[r['ndvi'] for r in series]
    if len(y)<5: return {'available':False,'reason_ar':'يلزم 5 قراءات شهرية صالحة على الأقل للتنبؤ.','reason_en':'At least 5 valid monthly readings are needed to forecast.'}
    cands=_candidates(y)
    k=min(6,max(2,len(y)//4));test=range(len(y)-k,len(y))
    scores={}
    for name,(p,_f,_a,_e) in cands.items():
        errs=[abs(y[t]-p[t]) for t in test if p[t] is not None]
        if len(errs)==len(test): scores[name]=statistics.mean(errs)
    best=min(scores,key=scores.get);p,f,label_ar,label_en=cands[best]
    resid=[y[t]-p[t] for t in range(len(y)) if p[t] is not None][-12:]
    sd=max(statistics.pstdev(resid) if len(resid)>1 else 0.03,0.01)
    last=date.fromisoformat(series[-1]['measured_at']);out=[]
    for h in (1,2,3):
        v=max(-1,min(1,f(h)));w=1.96*sd*math.sqrt(h);d=last+timedelta(days=30*h)
        out.append({'h':h,'date':d.isoformat(),'month_ar':_MONTHS_AR[d.month-1],'ndvi':round(v,3),'low':round(v-w,3),'high':round(v+w,3)})
    threshold=base*0.85 if base and base>0 else None;risk=None
    if threshold is not None:
        zz=(threshold-out[-1]['ndvi'])/(sd*math.sqrt(3));risk=round(100*0.5*(1+math.erf(zz/math.sqrt(2))))
    slope=(out[-1]['ndvi']-y[-1])/3
    direction='declining' if slope<-0.005 else 'improving' if slope>0.005 else 'stable'
    dir_ar={'declining':'تراجع','improving':'تحسّن','stable':'استقرار'}[direction]
    level_ar='مرتفع' if (risk or 0)>=60 else 'متوسط' if (risk or 0)>=30 else 'منخفض'
    level_en='high' if (risk or 0)>=60 else 'medium' if (risk or 0)>=30 else 'low'
    naive=scores.get('naive');beats=best!='naive' and naive is not None and scores[best]<naive
    gain=round(100*(1-scores[best]/naive)) if (naive and best!='naive') else 0
    board=[{'model':n,'label_ar':cands[n][2],'label_en':cands[n][3],'mae':round(v,4),'chosen':n==best} for n,v in sorted(scores.items(),key=lambda x:x[1])]
    seasonal=best in ('holt_winters','seasonal_naive')
    return {'available':True,'method':label_en,'method_ar':label_ar,'model':best,'leaderboard':board,'months_used':len(y),'test_months':k,
      'points':out,'trend_per_month':round(slope,4),'direction':direction,'risk_pct':risk,'risk_level':level_en,
      'threshold':round(threshold,3) if threshold is not None else None,'mae_model':round(scores[best],3),'mae_naive':round(naive,3) if naive else None,
      'beats_naive':beats,'residual_sd':round(sd,3),'seasonal':seasonal,
      'explain_ar':(f"اعتمادًا على {len(y)} شهرًا من القراءات، الاتجاه المتوقع {dir_ar}. نتوقع بعد 3 أشهر ({out[-1]['month_ar']}) قيمة {out[-1]['ndvi']:.2f} "
                    f"ضمن نطاق {out[-1]['low']:.2f}–{out[-1]['high']:.2f} (ثقة 95%). احتمال أن ينخفض المؤشر تحت حد الإنذار ({threshold:.2f} = 85% من خط الأساس) هو {risk}% أي خطر {level_ar}. " if threshold is not None else f"الاتجاه المتوقع {dir_ar}. ")+
                   f"قارنّا {len(scores)} نماذج على آخر {k} أشهر واخترنا الأدق: {label_ar} (متوسط الخطأ {scores[best]:.3f}"+(f"، أدق بنسبة {gain}% من الطريقة البسيطة)." if beats else ")؛ لم يتفوّق أي نموذج على الطريقة البسيطة بعد، فالتنبؤ مؤشر اتجاه فقط.")+
                   (" النموذج يراعي التغير الموسمي السنوي (صيف/شتاء)." if seasonal else (" عند توفر 24 شهرًا أو أكثر يُضاف نموذج موسمي سنوي." if len(y)<24 else "")),
      'explain_en':f"Based on {len(y)} months; best of {len(scores)} models on the last {k} months: {label_en} (MAE {scores[best]:.3f}"+(f", {gain}% better than naive)." if beats else "); no model beats naive yet.")}

# Recommendations now come from maintenance_engine.py (team notebook), see build_insight().
_DX={'insufficient':('بيانات غير كافية للتشخيص','Not enough data to diagnose'),'healthy':('حالة سليمة ومستقرة','Healthy and stable'),
 'improving':('تحسّن في الغطاء النباتي','Vegetation improving'),'water_stress':('إجهاد مائي محتمل (نقص ري)','Probable water stress (under-irrigation)'),
 'waterlogging':('تشبّع مائي أو تسرّب محتمل','Probable waterlogging or leak'),'salinity':('إجهاد ملحي محتمل','Probable salinity stress'),
 'nutrition':('نقص تغذية/كلوروفيل محتمل','Probable nutrient / chlorophyll deficiency'),'patchy_damage':('تلف موضعي في أجزاء من الحديقة','Localised damage in parts of the park'),
 'maintenance':('انخفاض متوقّع بسبب صيانة مجدولة','Expected dip from scheduled maintenance'),'heat_stress':('إجهاد حراري محتمل','Probable heat stress'),'unexplained':('تراجع غير مفسَّر يحتاج تحققًا ميدانيًا','Unexplained decline needing a field check')}

def build_insight(area,peers=None):
    m=area['metrics'];obs=[r for r in m['observations'] if _fin(r.get('ndvi')) and (r.get('valid_pixels_pct') or 0)>=60]
    name=area.get('name_en','')
    res={'version':1,'generated_at':utcnow()}
    if len(obs)<3:
        res.update(diagnosis='insufficient',title_ar=_DX['insufficient'][0],title_en=_DX['insufficient'][1],confidence='low',evidence=[],alternatives=[],
          summary_ar='لا توجد 3 قراءات شهرية صالحة بعد. اضغطوا «جلب قراءات فضائية» لبدء التشخيص.',summary_en='Fewer than 3 valid monthly readings. Sync satellite readings to start.',
          forecast={'available':False,'reason_ar':'لا توجد قراءات كافية.','reason_en':'Not enough readings.'},recommendations=[],data_quality={'n':len(obs)},risk_score=0,
          maintenance_plan=maintenance_engine(tree_type=area.get('plants') or None,diagnosis='insufficient',confidence='Low',month=datetime.now(timezone.utc).month).to_dict())
        return res
    hist=obs[:-2] if len(obs)>=4 else obs[:-1];latest=obs[-1];prev=obs[-2]
    _ss=same_season(obs,latest)
    if len(_ss)>=3: hist=_ss
    refs={k:_ref(hist,k) for k in _FLOOR}
    z={k:_z(latest.get(k),refs[k]) for k in _FLOOR}
    base=m['baseline'] if _fin(m.get('baseline')) else refs['ndvi']['median']
    chg=m['change_pct'] if _fin(m.get('change_pct')) else ((latest['ndvi']-base)/abs(base)*100 if base else 0)
    month=int(latest['measured_at'][5:7]);prev_month=int(prev['measured_at'][5:7])
    maint=bool(ndvi_drop_activities(month,area.get('plants') or None) or ndvi_drop_activities(prev_month,area.get('plants') or None))
    lowveg=base is not None and base<0.15
    coastal=name in COASTAL_SITES
    # peer percentile of salinity index (city context)
    sal_pct=None
    if peers and _fin(latest.get('salinity')):
        vals=[p for p in peers if _fin(p)]
        if len(vals)>=3: sal_pct=round(100*sum(v<=latest['salinity'] for v in vals)/len(vals))
    ev=[]
    def add(key,label_ar,label_en,value,ref,verdict,why_ar,why_en):
        ev.append({'key':key,'label_ar':label_ar,'label_en':label_en,'value':None if value is None else round(value,3),'reference':ref,'verdict':verdict,'why_ar':why_ar,'why_en':why_en})
    decline=chg<=-10;strong=chg<=-20
    add('ndvi','NDVI (كثافة وصحة الغطاء)','NDVI (vegetation vigour)',latest['ndvi'],f"خط الأساس {base:.3f} · التغير {chg:+.1f}%",'bad' if decline else 'good' if chg>=10 else 'ok',
        f"NDVI الحالي {latest['ndvi']:.3f} مقابل خط أساس الحديقة {base:.3f} (وسيط قراءاتها السابقة)، أي تغير {chg:+.1f}%. "+("انخفاض 10% أو أكثر يُعدّ إشارة تستحق التفسير." if decline else "التغير ضمن النطاق الطبيعي (أقل من 10%)." if chg>-10 and chg<10 else "ارتفاع واضح."),
        f"NDVI {latest['ndvi']:.3f} vs this park’s baseline {base:.3f} (median of its past readings): {chg:+.1f}%. "+("A drop of 10%+ is a signal to explain." if decline else "Within normal range."))
    def zline(k,la,le,meaning_ar,meaning_en):
        if z[k] is None or not _fin(latest.get(k)): return None
        r=refs[k];zz=z[k]
        verdict='bad' if (zz<=-1 if k in ('ndmi','ndre') else zz>=1) else 'ok'
        add(k,la,le,latest[k],f"المعتاد {r['median']:.3f} ± {r['std']:.3f} · الانحراف {zz:+.1f}σ",verdict,
            f"{meaning_ar} القيمة الآن {latest[k]:.3f} والمعتاد لهذه الحديقة {r['median']:.3f}؛ أي {abs(zz):.1f} انحراف معياري {'تحت' if zz<0 else 'فوق'} المعتاد. "+("هذا انحراف ملحوظ (1σ أو أكثر)." if abs(zz)>=1 else "ضمن المعتاد."),
            f"{meaning_en} Now {latest[k]:.3f}; usual for this park {r['median']:.3f}: {zz:+.1f}σ. "+("Notable deviation (≥1σ)." if abs(zz)>=1 else "Within normal."))
        return zz
    zw=zline('ndmi','NDMI (رطوبة النبات)','NDMI (plant moisture)','NDMI يقيس الماء داخل أوراق النبات؛ انخفاضه قد يدل على عطش.','NDMI measures leaf water; a drop can indicate thirst.')
    zl=zline('ndwi','NDWI (الماء السطحي)','NDWI (surface water)','NDWI يرتفع مع الماء المكشوف أو التربة المشبعة.','NDWI rises with open water or saturated soil.')
    zc=zline('ndre','NDRE (الكلوروفيل)','NDRE (chlorophyll)','NDRE يعكس الكلوروفيل والتغذية؛ انخفاضه مع رطوبة طبيعية يشير لنقص تغذية.','NDRE reflects chlorophyll/nutrition.')
    zs=zline('salinity','SI (مؤشر الملوحة التقريبي)','SI (approx. salinity)','SI مؤشر سطوع يرتفع مع القشور الملحية والتربة المكشوفة، وهو تقريبي.','SI is a brightness index that rises with salt crusts and bare soil; approximate.')
    zp=zline('ndvi_std','تباين NDVI داخل الحديقة','Within-park NDVI variability','ارتفاع التباين قد يعني أن أجزاء من الحديقة تتدهور بينما أخرى سليمة.','Higher variability can mean some parts decline while others stay healthy.')
    # --- thermal (Landsat 8/9): park surface temperature and its cooling effect vs ~300 m surroundings
    th=[t for t in (area.get('thermal') or []) if _fin(t.get('lst_park'))]
    z_lst=None;cooling=None;z_cool=None
    if len(th)>=3:
        tl=th[-1];tm=int(tl['measured_at'][5:7])
        same=[t for t in th[:-1] if min((int(t['measured_at'][5:7])-tm)%12,(tm-int(t['measured_at'][5:7]))%12)<=1]
        ref_rows=same if len(same)>=2 else th[:-1]
        lst_ref={'median':statistics.median([t['lst_park'] for t in ref_rows]),'std':max(statistics.pstdev([t['lst_park'] for t in ref_rows]),0.7)}
        z_lst=(tl['lst_park']-lst_ref['median'])/lst_ref['std']
        add('lst','LST (حرارة سطح الحديقة °م)','LST (park surface °C)',tl['lst_park'],f"المعتاد لهذا الوقت {lst_ref['median']:.1f} ± {lst_ref['std']:.1f} · الانحراف {z_lst:+.1f}σ",'bad' if z_lst>=1 else 'ok',
            f"حرارة سطح الحديقة من القمر Landsat ({tl['measured_at'][:7]}) {tl['lst_park']:.1f}°م، والمعتاد لهذا الوقت من السنة {lst_ref['median']:.1f}°م؛ أي {abs(z_lst):.1f} انحراف معياري {'فوق' if z_lst>0 else 'تحت'} المعتاد. ارتفاعها قد يعني أن النبات يفقد قدرته على التبريد بالنتح.",
            f"Park surface temperature (Landsat) {tl['lst_park']:.1f}°C vs usual {lst_ref['median']:.1f}°C ({z_lst:+.1f}σ).")
        cools=[t['lst_ring']-t['lst_park'] for t in th if _fin(t.get('lst_ring'))]
        if _fin(tl.get('lst_ring')):
            cooling=tl['lst_ring']-tl['lst_park']
            if len(cools)>=3:
                cm=statistics.median(cools[:-1]);cs=max(statistics.pstdev(cools[:-1]),0.4);z_cool=(cooling-cm)/cs
                add('cooling','تأثير التبريد (°م أبرد من محيطها)','Cooling effect (°C cooler than surroundings)',cooling,f"المعتاد {cm:.1f}°م · الانحراف {z_cool:+.1f}σ",'bad' if z_cool<=-1 else 'good' if cooling>=1 else 'ok',
                    f"الحديقة أبرد من محيطها العمراني (حزام ~300 م) بـ {cooling:.1f}°م، والمعتاد {cm:.1f}°م. تراجع هذا الفرق يعني ضعف دور الحديقة في تلطيف الحرارة.",
                    f"Park is {cooling:.1f}°C cooler than its ~300 m surroundings (usual {cm:.1f}°C).")
    summer=month in (5,6,7,8,9,10)
    scores={}
    if decline and z_lst is not None and z_lst>=1 and (z_cool is None or z_cool<=-0.5):
        scores['heat_stress']=2+(0.5 if summer else 0)+(0.5 if z_lst>=1.5 else 0)
    if decline:
        if zw is not None and zw<=-1: scores['water_stress']=2+(1 if strong else 0)+(1 if zw<=-1.5 else 0)
        if zl is not None and zl>=1 and (zw is None or zw>-0.5): scores['waterlogging']=2+(1 if zl>=1.5 else 0)
        if zs is not None and (zs>=1 or (coastal and (sal_pct or 0)>=75)): scores['salinity']=1.5+(1 if coastal else 0)+(0.5 if zs>=1.5 else 0)
        if zc is not None and zc<=-1 and (zw is None or zw>-0.5): scores['nutrition']=2
        if zp is not None and zp>=1: scores['patchy_damage']=2+(0.5 if zp>=1.5 else 0)
        if maint: scores['maintenance']=1.5 if not strong else 0.8
        if not scores: scores['unexplained']=1
        dx=max(scores,key=scores.get)
    else:
        dx='improving' if chg>=10 else 'healthy'
        if zp is not None and zp>=1.5 and chg<=-5: dx='patchy_damage';scores[dx]=1.5
    agree=sum(1 for e in ev if e['verdict']=='bad')
    q_valid=latest.get('valid_pixels_pct') or 0
    conf_pts=(2 if agree>=3 else 1 if agree==2 else 0)+(1 if len(obs)>=8 else 0)-(1 if q_valid<70 else 0)-(1 if lowveg else 0)-(1 if dx in ('salinity','unexplained') else 0)
    if dx in ('healthy','improving'): conf_pts+=2
    confidence='high' if conf_pts>=3 else 'medium' if conf_pts>=2 else 'low'
    conf_ar={'high':'مرتفعة','medium':'متوسطة','low':'منخفضة'}[confidence]
    fc=_forecast(obs,base)
    alts=[{'key':k,'title_ar':_DX[k][0],'title_en':_DX[k][1],'score':round(v,1)} for k,v in sorted(scores.items(),key=lambda x:-x[1]) if k!=dx]
    notes_ar=[];notes_en=[]
    if lowveg: notes_ar.append('الغطاء النباتي في هذه الحديقة منخفض أصلًا (NDVI < 0.15)، أي أن جزءًا كبيرًا منها ممرات أو تربة؛ لذلك تتضخّم النسب المئوية للتغير.');notes_en.append('Low vegetation cover (NDVI < 0.15): percentage changes are amplified.')
    if maint and dx!='maintenance': notes_ar.append(f"شهر القراءة ({_MONTHS_AR[month-1]}) أو الذي قبله فيه صيانة مجدولة قد تخفض المؤشر مؤقتًا، وأُخذ ذلك في الحسبان.");notes_en.append('Scheduled maintenance this or last month can lower NDVI briefly; taken into account.')
    if coastal: notes_ar.append('موقع ساحلي: رذاذ البحر والملوحة عاملان محتملان.');notes_en.append('Coastal site: sea spray and salinity are plausible factors.')
    if q_valid<80: notes_ar.append(f"نسبة البكسلات الصافية في آخر قراءة {q_valid:.0f}% (أقل من 80%)، فموثوقية القراءة محدودة.");notes_en.append(f"Clear-sky share in the last reading was {q_valid:.0f}% (<80%): limited reliability.")
    title_ar,title_en=_DX[dx]
    top=[e for e in ev if e['verdict']=='bad'][:3]
    summary_ar=f"التشخيص: {title_ar} (ثقة {conf_ar}). "+(("الأدلة: "+"؛ ".join(f"{e['label_ar'].split(' (')[0]} {e['value']}" for e in top)+". ") if top else "")+ \
               ("الأرقام كلها ضمن المعتاد لهذه الحديقة." if dx in ('healthy',) else "")
    summary_en=f"Diagnosis: {title_en} ({confidence} confidence)."
    # Species from the approved plant list sharpen the interpretation and the plan.
    species=parse_species(area.get('plants'));sp_sum=species_summary(species)
    if sp_sum:
        if dx=='water_stress' and sp_sum['thirsty_ar']:
            notes_ar.append('أنواع عالية الاحتياج للري في هذه الحديقة وهي الأكثر تأثرًا بنقص الري: '+'، '.join(sp_sum['thirsty_ar'])+'.');notes_en.append('High-water species here are most sensitive to under-irrigation.')
        if dx=='water_stress' and sp_sum['avg_irrigation']<=1.5:
            notes_ar.append('معظم نباتات هذه الحديقة قليلة الاحتياج للري، فالإجهاد المائي أقل احتمالًا؛ تحقّقوا من أسباب أخرى أيضًا.');notes_en.append('Mostly low-water species: water stress is less likely; check other causes.')
        if dx=='waterlogging' and sp_sum['avg_irrigation']<=1.5:
            notes_ar.append('نباتات الحديقة قليلة الاحتياج للري؛ الري الزائد يضرها أكثر من غيرها.');notes_en.append('Low-water species are harmed most by over-watering.')
    # Maintenance Engine (team notebook) turns the diagnosis into a maintenance plan.
    now_month=datetime.now(timezone.utc).month
    plan=maintenance_engine(tree_type=area.get('plants') or None,diagnosis=dx,confidence=confidence.capitalize(),month=now_month).to_dict()
    pri={'High':'high','Medium':'medium','Low':'low'}.get(plan['priority'],'medium')
    recs=[{'order':i+1,'action_ar':a_ar,'action_en':a_en,'priority':pri,'timeframe_ar':plan['deadline_ar'],'timeframe_en':plan['deadline'],
           'owner_ar':plan['owner_ar'],'owner_en':plan['owner']} for i,(a_ar,a_en) in enumerate(zip(plan['ai_recommendations_ar'],plan['ai_recommendations']))]
    if fc.get('available') and (fc.get('risk_pct') or 0)>=60 and dx in ('healthy','improving','maintenance'):
        recs.append({'order':len(recs)+1,'action_ar':f"التنبؤ يشير لخطر {fc['risk_pct']}% بتراجع المؤشر تحت حد الإنذار خلال 3 أشهر: جدولة فحص وقائي للري قبل {fc['points'][0]['month_ar']}.",
                     'action_en':f"Forecast gives {fc['risk_pct']}% risk of falling below the alert line within 3 months: schedule a preventive irrigation check before {fc['points'][0]['date'][:7]}.",
                     'priority':'medium','timeframe_ar':'شهر','timeframe_en':'1 month','owner_ar':'الجهة الرقابية','owner_en':'Regulator'})
    if dx=='salinity' or (coastal and dx in ('water_stress','patchy_damage','unexplained')):
        names=[f"{p['name_ar']} ({p['scientific']})" for p in salt_tolerant()]
        recs.append({'order':len(recs)+1,'action_ar':'عند الاستبدال: اختيار أنواع مناسبة للمواقع الساحلية والمالحة من القائمة المعتمدة: '+'، '.join(names)+'.',
                     'action_en':'At replacement, choose coastal/saline-suited species from the approved list: '+', '.join(p['scientific'] for p in salt_tolerant())+'.',
                     'priority':'low','timeframe_ar':'عند الاستبدال','timeframe_en':'at replacement','owner_ar':'الجهة الرقابية','owner_en':'Regulator'})
    v_ar,v_en=plan['success_indicator_ar'],plan['success_indicator']
    sev={'water_stress':3,'waterlogging':3,'patchy_damage':3,'heat_stress':3,'salinity':2,'nutrition':2,'unexplained':3,'maintenance':1,'healthy':0,'improving':0}.get(dx,0)
    risk_score=min(100,round(sev*18+max(0,-chg)*0.8+((fc.get('risk_pct') or 0)*0.25 if fc.get('available') else 0)))
    res['features']={'ndvi_change_pct':chg,'z_ndmi':zw,'z_ndwi':zl,'z_ndre':zc,'z_salinity':zs,'z_ndvi_std':zp,'ndvi':latest['ndvi'],
        'z_lst':z_lst,'cooling':cooling,'coastal':1 if coastal else 0,'maint_month':1 if maint else 0,'summer':1 if summer else 0}
    res.update(diagnosis=dx,title_ar=title_ar,title_en=title_en,confidence=confidence,confidence_ar=conf_ar,evidence=ev,alternatives=alts,
      notes_ar=notes_ar,notes_en=notes_en,summary_ar=summary_ar,summary_en=summary_en,forecast=fc,recommendations=recs,verify_ar=v_ar,verify_en=v_en,
      maintenance_plan=plan,species=[{k:p[k] for k in ('name_ar','scientific','category_ar','irrigation_ar','irrigation_en','coastal')} for p in species],species_summary=sp_sum,risk_score=risk_score,latest_date=latest['measured_at'],baseline=round(base,3) if base is not None else None,change_pct=round(chg,1),
      data_quality={'n':len(obs),'latest_valid_pct':round(q_valid,1),'history_window':f"{hist[0]['measured_at'][:7]} → {hist[-1]['measured_at'][:7]}" if hist else None,'salinity_city_percentile':sal_pct},
      method_ar='يقارن التشخيص آخر قراءة بالسجل الخاص بالحديقة نفسها (الوسيط والانحراف المعياري لقراءاتها السابقة) لا بقيمة ثابتة، لأن كل حديقة تختلف في نوع نباتاتها وكثافتها. '
                'نعتبر الانحراف ملحوظًا إذا تجاوز 1σ، والتراجع إشارة إذا بلغ 10% من خط الأساس. تُرجَّح الأسباب حسب عدد الأدلة المتوافقة، ويُخصم من الثقة عند قلة القراءات أو الغيوم أو ضعف الغطاء النباتي. '
                'هذه قواعد شفافة قابلة للتدقيق وليست نموذجًا مدرَّبًا؛ التشخيص يحتاج تأكيدًا ميدانيًا.',
      method_en='Each reading is compared with the park’s own history (median and standard deviation), not fixed thresholds. Deviations ≥1σ are notable; a 10% drop vs baseline is a signal. '
                'Causes are ranked by agreeing evidence; confidence is reduced for few readings, clouds or sparse vegetation. Transparent rules, not a trained model; field confirmation required.')
    return res

def attach_insights(areas):
    peers=[(a['metrics']['observations'] or [{}])[-1].get('salinity') for a in areas if a['metrics']['observations']]
    for a in areas: a['insight']=build_insight(a,peers)
    st,clf=model_state(peers)
    for a in areas:
        ins=a['insight']
        if clf is not None and ins.get('features'):
            pred=rawaa_ml.predict(clf,ins['features'])
            ins['ml']={'trained':True,'predictions':pred,'agrees':pred[0]['cause']==ins['diagnosis'],'cv_accuracy':st.get('cv_accuracy'),
                       'rules_accuracy':st.get('rules_accuracy'),'labels':st['labels'],'importances':st.get('importances',[])[:3]}
        else:
            ins['ml']={'trained':False,'labels':st['labels'],'min_labels':st['min_labels'],'reason_ar':st.get('reason_ar')}
    for a in areas: a['insight']['story']=narrative.park_story(a)
    return areas

def label_samples(peers=None):
    """Pair each confirmed cause with the site's satellite features as they were on that date."""
    with connect() as db:
        labels=[dict(r) for r in db.execute('SELECT * FROM labels ORDER BY observed_on')]
        if not labels: return [],[]
        areas={r['id']:dict(r) for r in db.execute('SELECT * FROM areas')}
        obs={};th={}
        for r in db.execute('SELECT * FROM observations ORDER BY measured_at'): obs.setdefault(r['area_id'],[]).append(dict(r))
        for r in db.execute('SELECT * FROM thermal ORDER BY measured_at'): th.setdefault(r['area_id'],[]).append(dict(r))
    samples=[];rules=[]
    for lb in labels:
        a=areas.get(lb['area_id'])
        if not a: continue
        cut=lb['observed_on'][:10]
        rows=[r for r in obs.get(a['id'],[]) if r['measured_at']<=cut]
        area={**a,'metrics':metrics_from_rows(rows),'thermal':[t for t in th.get(a['id'],[]) if t['measured_at']<=cut]}
        ins=build_insight(area,peers)
        if ins.get('features'):
            samples.append((ins['features'],lb['cause']));rules.append(ins['diagnosis'])
    return samples,rules

def model_state(peers=None):
    samples,rules=label_samples(peers)
    return rawaa_ml.status(samples,rules)


def full_area(db,r):
    d=dict(r)
    d['geometry']=json.loads(d['geometry'])
    d['metrics']=metrics(d['id'],db)
    d['thermal']=[dict(x) for x in db.execute('SELECT measured_at,lst_park,lst_ring,valid_pixels_pct FROM thermal WHERE area_id=? ORDER BY measured_at',(d['id'],))]
    d.update(SITE_INFO.get(d['name_en'],{}))
    return d

class Login(BaseModel):
    email:str; password:str

@app.get('/')
def home(): return FileResponse(ROOT / 'static' / 'index.html')

LOGIN_WINDOW_S=15*60; LOGIN_MAX_FAILS=8

@app.post('/api/login')
def login(v:Login, req:Request, response:Response):
    email=v.email.lower().strip();ip=(req.client.host if req.client else '')[:64];now=int(time.time())
    with connect() as db:
        fails=db.execute('SELECT count(*) FROM login_attempts WHERE email=? AND ok=0 AND at>?',(email,now-LOGIN_WINDOW_S)).fetchone()[0]
        if fails>=LOGIN_MAX_FAILS: raise HTTPException(429,'Too many failed attempts; try again in 15 minutes')
        u=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        ok=bool(u and password_ok(v.password,u['pw_hash']))
        db.execute('INSERT INTO login_attempts(email,ip,at,ok) VALUES(?,?,?,?)',(email,ip,now,int(ok)))
        db.execute('DELETE FROM login_attempts WHERE at<?',(now-86400,))
        db.execute('DELETE FROM sessions WHERE expires<?',(now,))
    if not ok:
        log.warning('failed login for %s from %s',email,ip)
        raise HTTPException(401,'Invalid credentials')
    with connect() as db:
        token=secrets.token_urlsafe(40)
        db.execute('INSERT INTO sessions(user_id,token_hash,expires) VALUES (?,?,?)',
                   (u['id'],hashlib.sha256(token.encode()).hexdigest(),int(time.time())+86400))
    response.set_cookie('rawaa_session',token,httponly=True,samesite='lax',secure=os.getenv('RAWAA_SECURE_COOKIE')=='1',max_age=86400)
    return {'user':{'id':u['id'],'email':u['email'],'display':u['display'],'role':u['role']}}

@app.post('/api/logout')
def logout(req:Request,response:Response):
    token=req.cookies.get('rawaa_session','')
    if token:
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie('rawaa_session')
    return {'ok':True}

class DemoRoleChange(BaseModel):
    role: str


def demo_switch_enabled():
    # Explicitly disabled when deployed in production; never a real permission elevation feature.
    return os.getenv('RAWAA_ENV', 'development').lower() != 'production' and os.getenv('RAWAA_DEMO_SWITCH', '1') == '1'


@app.post('/api/demo/switch-role')
def switch_demo_role(v:DemoRoleChange, req:Request, response:Response):
    user = current_user(req)
    demo_emails = {'regulator': 'regulator@rawaa.local', 'operator': 'operator@rawaa.local'}
    if not demo_switch_enabled() or user['email'] not in demo_emails.values():
        raise HTTPException(403, 'Demo role switching is disabled for this account')
    if v.role not in demo_emails:
        raise HTTPException(400, 'Invalid demo role')
    with connect() as db:
        target = db.execute('SELECT id,email,display,role FROM users WHERE email=? AND role=?',
                            (demo_emails[v.role], v.role)).fetchone()
        if not target: raise HTTPException(404, 'Demo account not found')
        prev_token = req.cookies.get('rawaa_session', '')
        if prev_token:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(prev_token.encode()).hexdigest(),))
        token = secrets.token_urlsafe(40)
        db.execute('INSERT INTO sessions(user_id,token_hash,expires) VALUES (?,?,?)',
                   (target['id'], hashlib.sha256(token.encode()).hexdigest(), int(time.time()) + 86400))
    response.set_cookie('rawaa_session', token, httponly=True, samesite='lax',
                        secure=os.getenv('RAWAA_SECURE_COOKIE') == '1', max_age=86400)
    return {'user': dict(target), 'demo_only': True}


@app.get('/api/me')
def me(req:Request): return current_user(req)

@app.get('/api/dashboard')
def dashboard(req:Request):
    u=current_user(req)
    clause,params=in_scope_clause(u)
    with connect() as db:
        areas=attach_insights([full_area(db,r) for r in db.execute('SELECT a.* FROM areas a'+clause+' ORDER BY a.id',params)])
        tasks=[dict(r) for r in db.execute('SELECT t.*, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'before\') AS has_before_photo, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'after\') AS has_after_photo FROM tasks t JOIN areas a ON t.area_id=a.id'+clause+' ORDER BY t.created_at DESC',params)]
        alerts=[dict(r) for r in db.execute('SELECT al.* FROM alerts al JOIN areas a ON al.area_id=a.id'+clause+' ORDER BY al.created_at DESC',params)]
    return {'areas':areas,'tasks':tasks,'alerts':alerts,'briefing':narrative.city_briefing(areas),
        'counts':{'total':len(areas),'stable':sum(a['metrics']['status']=='stable' for a in areas),
                  'monitor':sum(a['metrics']['status']=='monitor' for a in areas),
                  'high':sum(a['metrics']['status']=='high' for a in areas),
                  'insufficient':sum(a['metrics']['status']=='insufficient' for a in areas),
                  'alerts':sum(a['status']!='closed' for a in alerts),
                  'tasks_open':sum(t['status'] not in ('closed',) for t in tasks)},
        'demo':any(a['metrics']['demo'] for a in areas),
        'integration':bool(os.getenv('COPERNICUS_CLIENT_ID') and os.getenv('COPERNICUS_CLIENT_SECRET')),
        'role_switch_enabled': demo_switch_enabled() and u['email'] in ('regulator@rawaa.local','operator@rawaa.local')}

@app.get('/api/areas')
def areas_list(req:Request):
    u=current_user(req);clause,params=in_scope_clause(u)
    with connect() as db:
        return attach_insights([full_area(db,r) for r in db.execute('SELECT a.* FROM areas a'+clause+' ORDER BY a.id',params)])

class AreaCreate(BaseModel):
    name_ar:str=Field(min_length=2,max_length=120)
    name_en:str=Field(min_length=2,max_length=120)
    geometry:dict
    irrigation:str=''; plants:str=''; planting_date:str|None=None
    assigned_operator:int=2

def validate_geometry(g):
    if g.get('type')!='Polygon': raise HTTPException(400,'Geometry must be a GeoJSON Polygon')
    try:
        rings=g['coordinates']
        assert isinstance(rings,list) and len(rings)>=1 and len(rings[0])>=4
        outer=rings[0]
        assert outer[0]==outer[-1], 'Polygon ring must be closed'
        for ring in rings:
            assert len(ring)>=4 and ring[0]==ring[-1]
            for p in ring:
                assert isinstance(p,list) and len(p)>=2
                assert -180<=float(p[0])<=180 and -90<=float(p[1])<=90
    except (ValueError,TypeError,KeyError,AssertionError,IndexError):
        raise HTTPException(400,'Invalid closed polygon coordinates')

@app.post('/api/areas',status_code=201)
def add_area(v:AreaCreate,req:Request):
    u=current_user(req);require_regulator(u);validate_geometry(v.geometry)
    with connect() as db:
        assigned=db.execute('SELECT id FROM users WHERE id=? AND role=\'operator\'',(v.assigned_operator,)).fetchone()
        if not assigned: raise HTTPException(400,'Operator not found')
        rep=rgeo.validate(v.geometry)
        if not rep['valid']: raise HTTPException(400,{'message':'Invalid boundary','errors':rep['errors']})
        c=db.execute('''INSERT INTO areas(name_ar,name_en,geometry,irrigation,plants,planting_date,assigned_operator,demo,created_at,
            boundary_status,boundary_source,boundary_version,area_m2,perimeter_m)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(v.name_ar,v.name_en,json.dumps(v.geometry),v.irrigation,v.plants,v.planting_date,v.assigned_operator,0,utcnow(),
            rgeo.initial_status('user-supplied',rep['placeholder']),'user-supplied',1,rep['area_m2'],rep['perimeter_m']))
        db.execute('INSERT INTO boundary_history(area_id,version,geometry,source,status,action,user_id,notes,area_m2,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (c.lastrowid,1,json.dumps(v.geometry),'user-supplied',rgeo.initial_status('user-supplied',rep['placeholder']),'create',u['id'],'',rep['area_m2'],utcnow()))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',(u['id'],'create_area',str(c.lastrowid),v.name_en,utcnow()))
        return full_area(db,db.execute('SELECT * FROM areas WHERE id=?',(c.lastrowid,)).fetchone())

@app.get('/api/plants')
def plants_catalog(req:Request):
    """Approved plant list (category, names, use, indicative irrigation)."""
    current_user(req);return PLANTS

class PlantsUpdate(BaseModel):
    plants:list[str]=Field(default_factory=list,max_length=60)

@app.patch('/api/areas/{area_id}/plants')
def set_area_plants(area_id:int,v:PlantsUpdate,req:Request):
    u=current_user(req);require_regulator(u)
    known={p['scientific'] for p in PLANTS}
    bad=[x for x in v.plants if x not in known]
    if bad: raise HTTPException(400,'Unknown species: '+', '.join(bad[:5]))
    with connect() as db:
        area_access(db,u,area_id)
        db.execute('UPDATE areas SET plants=? WHERE id=?',(', '.join(v.plants),area_id))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',(u['id'],'set_plants',str(area_id),f'{len(v.plants)} species',utcnow()))
    return {'ok':True,'count':len(v.plants)}

@app.get('/api/model')
def model_info(req:Request):
    """Learning-model status: labels, validation accuracy vs rules, top features."""
    current_user(req)
    st,_clf=model_state()
    st['causes']={k:{'ar':v[0],'en':v[1]} for k,v in rawaa_ml.CAUSES.items()}
    return st

class LabelIn(BaseModel):
    area_id:int;observed_on:str;cause:str;notes:str=''

@app.get('/api/labels')
def labels_list(req:Request):
    u=current_user(req);require_regulator(u)
    with connect() as db: return [dict(r) for r in db.execute('SELECT * FROM labels ORDER BY observed_on DESC')]

def _add_label(db,area_id,observed_on,cause,source,notes='',task_id=None):
    if cause not in rawaa_ml.CAUSES: raise HTTPException(400,'Unknown cause: '+cause)
    try: date.fromisoformat(observed_on[:10])
    except ValueError: raise HTTPException(400,'observed_on must be YYYY-MM-DD')
    if not db.execute('SELECT 1 FROM areas WHERE id=?',(area_id,)).fetchone(): raise HTTPException(404,'Area not found')
    db.execute('INSERT INTO labels(area_id,observed_on,cause,source,notes,task_id,created_at) VALUES(?,?,?,?,?,?,?)',
               (area_id,observed_on[:10],cause,source,notes[:400],task_id,utcnow()))

@app.post('/api/labels',status_code=201)
def labels_add(v:LabelIn,req:Request):
    u=current_user(req);require_regulator(u)
    with connect() as db: _add_label(db,v.area_id,v.observed_on,v.cause,'field',v.notes)
    return {'ok':True}

@app.delete('/api/labels/{label_id}')
def labels_delete(label_id:int,req:Request):
    u=current_user(req);require_regulator(u)
    with connect() as db: db.execute('DELETE FROM labels WHERE id=?',(label_id,))
    return {'ok':True}

class LabelsCSV(BaseModel):
    csv_text:str=Field(min_length=10,max_length=500_000)

@app.post('/api/labels/import-csv')
def labels_import(v:LabelsCSV,req:Request):
    """Municipality records: columns site (id, English or Arabic name), date (YYYY-MM-DD), cause, notes (optional)."""
    u=current_user(req);require_regulator(u)
    rows=list(csv.DictReader(io.StringIO(v.csv_text.strip())))
    ok=0;errors=[]
    with connect() as db:
        areas=[dict(r) for r in db.execute('SELECT id,name_en,name_ar FROM areas')]
        for i,r in enumerate(rows,start=2):
            site=(r.get('site') or r.get('area') or r.get('area_id') or '').strip()
            a=next((x for x in areas if site in (str(x['id']),x['name_en'],x['name_ar'])),None)
            if not a: errors.append(f'row {i}: unknown site {site!r}');continue
            try:_add_label(db,a['id'],(r.get('date') or '').strip(),(r.get('cause') or '').strip(),'import',(r.get('notes') or '').strip());ok+=1
            except HTTPException as ex: errors.append(f'row {i}: {ex.detail}')
    return {'imported':ok,'errors':errors[:20]}

@app.get('/api/maintenance-plan')
def maintenance_plan_api(req:Request,diagnosis:str,confidence:str='Medium',tree_type:str='',month:int=0):
    """Run the Maintenance Engine directly (same inputs as the team notebook)."""
    current_user(req)
    if month and not 1<=month<=12: raise HTTPException(400,'month must be 1-12')
    return maintenance_engine(tree_type=tree_type or None,diagnosis=diagnosis,confidence=confidence,month=month or None).to_dict()

@app.get('/api/areas/{area_id}')
def get_area(area_id:int,req:Request):
    u=current_user(req)
    with connect() as db:
        target=area_access(db,u,area_id)
        allareas=[full_area(db,r) for r in db.execute('SELECT * FROM areas ORDER BY id')]
    attach_insights(allareas)
    return next(a for a in allareas if a['id']==target['id'])

class CSVImport(BaseModel):
    csv_text:str=Field(min_length=10,max_length=1_000_000)

@app.post('/api/areas/{area_id}/import-csv')
def import_csv(area_id:int,v:CSVImport,req:Request):
    u=current_user(req);require_regulator(u)
    reader=csv.DictReader(io.StringIO(v.csv_text))
    wanted={'date','ndvi','ndmi','valid_pixels_pct'}
    if not reader.fieldnames or not {'date','ndvi','valid_pixels_pct'}.issubset(set(reader.fieldnames)):
        raise HTTPException(400,'Required columns: date,ndvi,valid_pixels_pct; optional: ndmi')
    clean=[]
    try:
        for row in reader:
            d=date.fromisoformat(row['date'].strip())
            ndvi=float(row['ndvi']);quality=float(row['valid_pixels_pct'])
            ndmi=float(row['ndmi']) if row.get('ndmi','').strip() else None
            if not (-1<=ndvi<=1 and 0<=quality<=100 and (ndmi is None or -1<=ndmi<=1)):
                raise ValueError('Out-of-range index or valid percentage')
            clean.append((d.isoformat(),ndvi,ndmi,quality))
        if not clean or len(clean)>2000: raise ValueError('CSV must contain 1–2000 rows')
    except (ValueError,TypeError,AttributeError,KeyError) as e:
        raise HTTPException(400,f'Invalid CSV row: {e}')
    with connect() as db:
        area_row=area_access(db,u,area_id)
        for d,ndvi,ndmi,q in clean:
            db.execute('''INSERT INTO observations(area_id,measured_at,ndvi,ndmi,valid_pixels_pct,source,is_demo,created_at,origin,reliability,boundary_version)
                VALUES(?,?,?,?,?,'Imported CSV (user supplied)',0,?,'imported','unverified',?)
                ON CONFLICT(area_id,measured_at,source) DO UPDATE SET ndvi=excluded.ndvi,
                ndmi=excluded.ndmi,valid_pixels_pct=excluded.valid_pixels_pct''',
                (area_id,d,ndvi,ndmi,q,utcnow(),area_row['boundary_version'] or 1))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',
                   (u['id'],'import_csv',str(area_id),f'{len(clean)} user-supplied records',utcnow()))
    return {'imported':len(clean),'origin':'imported','reliability':'unverified',
            'note':'Imported values are user-provided and kept separate from satellite readings: they are displayed but never drive automatic alerts, priorities or forecasts.'}

@app.get('/api/alerts')
def list_alerts(req:Request):
    u=current_user(req);clause,params=in_scope_clause(u)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT al.* FROM alerts al JOIN areas a ON a.id=al.area_id'+clause+' ORDER BY al.id DESC',params)]

class AssignAlert(BaseModel):
    due_at: str|None=None
    priority: str='medium'

@app.post('/api/alerts/{alert_id}/assign')
def assign_alert(alert_id:int,v:AssignAlert,req:Request):
    u=current_user(req);require_regulator(u)
    if v.priority not in ('low','medium','high'): raise HTTPException(400,'Invalid priority')
    with connect() as db:
        a=db.execute('''SELECT al.*, ar.assigned_operator FROM alerts al
            JOIN areas ar ON ar.id=al.area_id WHERE al.id=?''',(alert_id,)).fetchone()
        if not a: raise HTTPException(404,'Alert not found')
        if not a['assigned_operator']: raise HTTPException(400,'No operator assigned to this area')
        dup=db.execute('SELECT id FROM tasks WHERE alert_id=? AND status<>\'closed\'',(alert_id,)).fetchone()
        if dup: raise HTTPException(409,'Active task already exists for this alert')
        allareas=attach_insights([full_area(db,r) for r in db.execute('SELECT * FROM areas ORDER BY id')])
        ins=next((x['insight'] for x in allareas if x['id']==a['area_id']),None)
        recs=(ins or {}).get('recommendations') or []
        notes='\n'.join(f"{r['order']}. {r['action_ar']} ({r['timeframe_ar']})" for r in recs)
        if ins and ins.get('verify_ar'): notes+='\nالتحقق من النجاح: '+ins['verify_ar']
        title_ar='تحقق وصيانة — '+ins['title_ar'] if ins and ins['diagnosis'] not in ('insufficient','healthy','improving') else 'تحقق وصيانة'
        title_en='Inspection & maintenance — '+ins['title_en'] if ins and ins['diagnosis'] not in ('insufficient','healthy','improving') else 'Inspection & maintenance'
        # Snapshot of the latest trusted satellite reading, used later to compare before/after the intervention.
        import intelligence_api as _intel
        from rawaa_core.series import trusted_series as _ts, reading_date as _rd
        area_row=dict(db.execute('SELECT * FROM areas WHERE id=?',(a['area_id'],)).fetchone())
        tser=_ts(_intel.observations(db,a['area_id']),area_row.get('boundary_version') or 1)
        base=tser[-1] if tser else None
        sched=db.execute("SELECT id,next_check FROM monitoring_schedule WHERE area_id=? AND status IN ('scheduled','in_progress') ORDER BY id DESC",(a['area_id'],)).fetchone()
        due=v.due_at or (sched['next_check'] if sched else None)
        c=db.execute('''INSERT INTO tasks(area_id,alert_id,title_ar,title_en,assigned_to,status,priority,due_at,notes,created_at,updated_at,
            schedule_id,baseline_ndvi,baseline_date)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(a['area_id'],alert_id,title_ar,title_en,
             a['assigned_operator'],'open',v.priority,due,notes,utcnow(),utcnow(),
             sched['id'] if sched else None,base['ndvi'] if base else None,_rd(base) if base else None))
        if sched: db.execute("UPDATE monitoring_schedule SET task_id=?, status='in_progress', updated_at=? WHERE id=?",(c.lastrowid,utcnow(),sched['id']))
        db.execute('UPDATE alerts SET status=\'assigned\' WHERE id=?',(alert_id,))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',
                   (u['id'],'assign_task',str(c.lastrowid),f'alert {alert_id}',utcnow()))
    return {'id':c.lastrowid}

@app.get('/api/tasks')
def list_tasks(req:Request):
    u=current_user(req)
    with connect() as db:
        if u['role']=='operator':
            rows=db.execute('SELECT t.*, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'before\') AS has_before_photo, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'after\') AS has_after_photo FROM tasks t WHERE assigned_to=? ORDER BY id DESC',(u['id'],))
        else: rows=db.execute('SELECT t.*, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'before\') AS has_before_photo, EXISTS(SELECT 1 FROM task_photos p WHERE p.task_id=t.id AND p.kind=\'after\') AS has_after_photo FROM tasks t ORDER BY id DESC')
        return [dict(r) for r in rows]

class TaskPatch(BaseModel):
    status:str|None=None
    confirmed_cause:str|None=None
    actual_cause:str|None=Field(default=None,max_length=400)
    action:str|None=Field(default=None,max_length=400)
    notes:str|None=Field(default=None,max_length=1000)
    notes_before:str|None=Field(default=None,max_length=1000)
    notes_after:str|None=Field(default=None,max_length=1000)
    due_at:str|None=None
    priority:str|None=None

@app.patch('/api/tasks/{task_id}')
def patch_task(task_id:int,v:TaskPatch,req:Request):
    u=current_user(req)
    with connect() as db:
        t=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not t: raise HTTPException(404,'Task not found')
        if u['role']=='operator' and t['assigned_to']!=u['id']:
            raise HTTPException(403,'Task is not assigned to you')
        allowed_ops={'open':{'in_progress'},'in_progress':{'pending_review'},'reopened':{'in_progress'},'pending_review':set(),'closed':set()}
        allowed_reg={'pending_review':{'closed','reopened'},'open':{'reopened'},'in_progress':{'reopened'},'closed':set(),'reopened':set()}
        fields={k:val for k,val in v.model_dump(exclude_none=True).items() if k!='status'}
        if ('due_at' in fields or 'priority' in fields) and u['role']!='regulator':
            raise HTTPException(403,'Only the regulator can change due date or priority')
        if fields.get('priority') and fields['priority'] not in ('low','medium','high'): raise HTTPException(400,'Invalid priority')
        if v.status:
            allowed=(allowed_reg if u['role']=='regulator' else allowed_ops).get(t['status'],set())
            if v.status not in allowed: raise HTTPException(409,f'Invalid state transition: {t["status"]} -> {v.status}')
            if v.status=='pending_review' and not ((fields.get('actual_cause') or t['actual_cause']) and (fields.get('action') or t['action'])):
                raise HTTPException(400,'Actual cause and action are required for review')
            fields['status']=v.status
            if v.status=='pending_review': fields['completed_at']=utcnow()
        if not fields: raise HTTPException(400,'No fields supplied')
        fields['updated_at']=utcnow()
        sql='UPDATE tasks SET '+', '.join(f'{k}=?' for k in fields)+' WHERE id=?'
        db.execute(sql,[*fields.values(),task_id])
        if fields.get('confirmed_cause') and fields['confirmed_cause'] not in rawaa_ml.CAUSES:
            raise HTTPException(400,'Unknown confirmed cause')
        if v.status=='closed':
            cause=fields.get('confirmed_cause') or t['confirmed_cause']
            if cause: _add_label(db,t['area_id'],t['created_at'][:10],cause,'task',(t['actual_cause'] or '')[:400],task_id)
        if v.status=='closed' and t['alert_id']:
            db.execute('UPDATE alerts SET status=\'closed\' WHERE id=?',(t['alert_id'],))
        if v.status=='closed':
            db.execute("UPDATE monitoring_schedule SET status='done', completed_at=?, completed_by=?, updated_at=? WHERE task_id=? AND status IN ('scheduled','in_progress')",
                       (utcnow(),u['id'],utcnow(),task_id))
        if v.status=='reopened':
            db.execute("UPDATE monitoring_schedule SET status='in_progress', updated_at=? WHERE task_id=?",(utcnow(),task_id))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',
                   (u['id'],'update_task',str(task_id),json.dumps(fields,ensure_ascii=False),utcnow()))
        return asdict(db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone())

@app.get('/api/activity')
def activity(req:Request):
    u=current_user(req);require_regulator(u)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 100')]

@app.get('/api/reports/tasks.csv')
def export_tasks(req:Request):
    u=current_user(req)
    with connect() as db:
        if u['role']=='operator':
            rows=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE assigned_to=?',(u['id'],))]
        else: rows=[dict(r) for r in db.execute('SELECT * FROM tasks')]
    out=io.StringIO();fields=['id','area_id','alert_id','title_en','status','priority','due_at','actual_cause','action','created_at','updated_at']
    writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    return Response(out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="rawaa-tasks.csv"'})

# Months in the approved maintenance programme (Appendix 6) with work that can briefly lower NDVI
# (pruning, frond/offshoot removal, lawn aeration/de-thatching/top dressing, annuals replacement) or raise it (fertiliser).
MAINT_DROP_MONTHS = {1,2,3,5,9,10,11,12}
MAINT_FERT_MONTHS = {1,3,5,9,11}

@app.get('/api/reports/dataset.csv')
def export_dataset(req:Request, include_demo:int=0):
    """Per-site monthly spectral features for analysis / model training. Real Sentinel-2 rows only by default."""
    u=current_user(req);require_regulator(u)
    with connect() as db:
        areas={r['id']:dict(r) for r in db.execute('SELECT * FROM areas')}
        rows=[dict(r) for r in db.execute('SELECT * FROM observations ORDER BY area_id,measured_at')]
    out=io.StringIO()
    fields=['area_id','name_en','name_ar','category','role_en','boundary_source','lat','lng','date','month',
            'ndvi','ndvi_std','ndmi','ndwi','savi','ndre','salinity','valid_pixels_pct','maint_drop_month','maint_fert_month','source','is_demo']
    w=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for r in rows:
        if r['is_demo'] and not include_demo: continue
        a=areas.get(r['area_id']);
        if not a: continue
        ring=json.loads(a['geometry'])['coordinates'][0]
        xs=[float(p[0]) for p in ring];ys=[float(p[1]) for p in ring]
        m=int(r['measured_at'][5:7]);info=SITE_INFO.get(a['name_en'],{})
        w.writerow({**r,'name_en':a['name_en'],'name_ar':a['name_ar'],'category':a['category'],'role_en':info.get('role_en',''),
                    'boundary_source':info.get('boundary_source',''),'lat':round((min(ys)+max(ys))/2,6),'lng':round((min(xs)+max(xs))/2,6),
                    'date':r['measured_at'],'month':m,'maint_drop_month':int(m in MAINT_DROP_MONTHS),'maint_fert_month':int(m in MAINT_FERT_MONTHS)})
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="rawaa-training-dataset.csv"'})

# --- Copernicus Data Space — Sentinel Hub Statistical API, optional OAuth integration ---
# Legacy 30-day composite evalscript (rawaa-s2-v1) replaced by the scene-level one in rawaa_core/indices.py,
# which also masks SCL class 2 (shadows) and reports vegetated share. Kept as a name for backwards compatibility.
EVALSCRIPT = rindices.EVALSCRIPT

def api_json(url, data, headers, timeout=40):
    payload=parse.urlencode(data).encode() if isinstance(data,dict) and headers.get('Content-Type','').startswith('application/x-www-form-urlencoded') else json.dumps(data).encode()
    req=request.Request(url,data=payload,headers=headers,method='POST')
    try:
        with request.urlopen(req,timeout=timeout) as res: return json.load(res)
    except error.HTTPError as e:
        msg=e.read(900).decode(errors='replace')
        raise RuntimeError(f'Copernicus HTTP {e.code}: {msg}') from e
    except error.URLError as e:
        raise RuntimeError(f'Copernicus network error: {e.reason}') from e

@app.get('/api/integrations')
def integrations(req:Request):
    current_user(req)
    return {'copernicus_configured':bool(os.getenv('COPERNICUS_CLIENT_ID') and os.getenv('COPERNICUS_CLIENT_SECRET')),
            'source':'Copernicus Data Space / Sentinel Hub Statistical API',
            'required':'COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET on the server',
            'mode':'Real satellite statistics only when configured; otherwise sample data is DEMO.'}

class Sync(BaseModel):
    start_date:str|None=None; end_date:str|None=None

# --- Optional live Sentinel-2 imagery for web map, never exposed as a public credential ---
TRUE_COLOR_SCRIPT = """//VERSION=3
function setup(){return {input:[{bands:['B04','B03','B02','SCL','dataMask']}],output:{bands:4}}}
function evaluatePixel(s){
  if(s.dataMask===0 || [0,1,3,8,9,10,11].includes(s.SCL))return [0,0,0,0];
  return [Math.min(1,2.7*s.B04),Math.min(1,2.7*s.B03),Math.min(1,2.7*s.B02),1];
}
"""
NDVI_IMAGE_SCRIPT = """//VERSION=3
function setup(){return {input:[{bands:['B04','B08','SCL','dataMask']}],output:{bands:4}}}
function evaluatePixel(s){
  if(s.dataMask===0 || [0,1,3,6,8,9,10,11].includes(s.SCL))return [0,0,0,0];
  let v=(s.B08+s.B04)>0?(s.B08-s.B04)/(s.B08+s.B04):0;
  if(v>=0.55)return [0.08,0.50,0.23,0.85];
  if(v>=0.35)return [0.27,0.71,0.36,0.85];
  if(v>=0.20)return [0.92,0.77,0.23,0.85];
  if(v>=0.08)return [0.90,0.44,0.15,0.85];
  return [0.74,0.19,0.17,0.85];
}
"""
_MASK = "if(s.dataMask===0 || [0,1,3,8,9,10,11].includes(s.SCL)) return [0,0,0,0];"
def _layer_script(bands, body):
    return ("//VERSION=3\nfunction setup(){return {input:[{bands:%s}],output:{bands:4}}}\n"
            "function nd(a,b){return (a+b)!==0?(a-b)/(a+b):0}\n"
            "function evaluatePixel(s){%s %s}" % (json.dumps(bands+['SCL','dataMask']), _MASK, body))
LAYER_SCRIPTS = {
  'false_color': _layer_script(['B08','B04','B03'], "return [Math.min(1,2.5*s.B08),Math.min(1,2.5*s.B04),Math.min(1,2.5*s.B03),1];"),
  'urban': _layer_script(['B12','B11','B04'], "return [Math.min(1,2.5*s.B12),Math.min(1,2.5*s.B11),Math.min(1,2.5*s.B04),1];"),
  'swir': _layer_script(['B12','B8A','B04'], "return [Math.min(1,2.5*s.B12),Math.min(1,2.5*s.B8A),Math.min(1,2.5*s.B04),1];"),
  'moisture': _layer_script(['B8A','B11'], "let v=nd(s.B8A,s.B11);let c=colorBlend(v,[-0.8,-0.24,-0.032,0.032,0.24,0.8],[[0.5,0,0],[1,0,0],[1,1,0],[0,1,1],[0,0,1],[0,0,0.5]]);return [c[0],c[1],c[2],0.85];"),
  'ndwi': _layer_script(['B03','B08'], "let v=nd(s.B03,s.B08);let c=colorBlend(v,[-0.8,-0.3,0,0.2,0.5],[[0,0.4,0],[0.6,0.8,0.4],[1,1,1],[0.3,0.6,1],[0,0,0.6]]);return [c[0],c[1],c[2],0.85];"),
  'ndre': _layer_script(['B8A','B05'], "let v=nd(s.B8A,s.B05);let c=colorBlend(v,[0,0.15,0.3,0.45,0.6],[[0.74,0.19,0.17],[0.9,0.44,0.15],[0.92,0.77,0.23],[0.27,0.71,0.36],[0.08,0.5,0.23]]);return [c[0],c[1],c[2],0.85];"),
}

class ImageryRequest(BaseModel):
    month:str=Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    layer:str=Field(pattern=r'^(true_color|false_color|ndvi|moisture|ndwi|swir|urban|ndre)$')

_TOKEN_CACHE={'value':None,'expires':0.0}
_TOKEN_LOCK=threading.Lock()

def _copernicus_access_token():
    with _TOKEN_LOCK:
        if _TOKEN_CACHE['value'] and time.time()<_TOKEN_CACHE['expires']:
            return _TOKEN_CACHE['value']
        tok=_fetch_copernicus_token()
        _TOKEN_CACHE.update(value=tok,expires=time.time()+480)  # CDSE tokens live ~10 min
        return tok

def _fetch_copernicus_token():
    ident=os.getenv('COPERNICUS_CLIENT_ID')
    secret=os.getenv('COPERNICUS_CLIENT_SECRET')
    if not ident or not secret:
        raise HTTPException(422,'Copernicus not connected. Configure OAuth on the backend first.')
    return api_json('https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token',
                    {'grant_type':'client_credentials','client_id':ident,'client_secret':secret},
                    {'Content-Type':'application/x-www-form-urlencoded'})['access_token']

def _process_image(payload, token):
    req=request.Request('https://sh.dataspace.copernicus.eu/process/v1',
      data=json.dumps(payload).encode(),
      headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
    try:
        with request.urlopen(req,timeout=80) as r:
            b=r.read(2_100_000)
            if not r.headers.get('Content-Type','').startswith('image/png') or len(b)>2_000_000:
                raise RuntimeError('Unexpected imagery response')
            return b
    except error.HTTPError as exc:
        detail=exc.read(600).decode(errors='replace')
        raise RuntimeError(f'Copernicus HTTP {exc.code}: {detail}') from exc
    except error.URLError as exc:
        raise RuntimeError('Copernicus imagery service unavailable') from exc

@app.post('/api/areas/{area_id}/imagery')
def satellite_image(area_id:int,v:ImageryRequest,req:Request):
    u=current_user(req)
    with connect() as db:
        a=area_access(db,u,area_id)
        geom=json.loads(a['geometry'])
        validate_geometry(geom)
    try:
        period=date.fromisoformat(v.month+'-01')
    except ValueError:
        raise HTTPException(400,'Invalid month')
    if period>date.today().replace(day=1) or period.year<2018:
        raise HTTPException(400,'Month must be between 2018 and the current month')
    x=[float(p[0]) for ring in geom['coordinates'] for p in ring]
    y=[float(p[1]) for ring in geom['coordinates'] for p in ring]
    bbox=[min(x),min(y),max(x),max(y)]
    if bbox[2]-bbox[0] < 0.0001 or bbox[3]-bbox[1] < 0.0001 or bbox[2]-bbox[0] > 0.12 or bbox[3]-bbox[1] > 0.12:
        raise HTTPException(422,'Area must have a meaningful polygon no larger than 0.12 degrees in each direction')
    next_month=(period.replace(day=28)+timedelta(days=4)).replace(day=1)
    end=min(date.today(),next_month-timedelta(days=1))
    # True date-bounded imagery from Sentinel-2; if unavailable, provider will signal error.
    payload={
      'input':{'bounds':{'bbox':bbox,'geometry':geom,'properties':{'crs':'http://www.opengis.net/def/crs/OGC/1.3/CRS84'}},
                'data':[{'type':'sentinel-2-l2a','dataFilter':{'timeRange':{'from':period.isoformat()+'T00:00:00Z','to':end.isoformat()+'T23:59:59Z'},'mosaickingOrder':'leastCC'}}]},
      'output':{'width':512,'height':512,'responses':[{'identifier':'default','format':{'type':'image/png'}}]},
      'evalscript':NDVI_IMAGE_SCRIPT if v.layer=='ndvi' else TRUE_COLOR_SCRIPT if v.layer=='true_color' else LAYER_SCRIPTS[v.layer]}
    try:
        token=_copernicus_access_token()
        data=_process_image(payload,token)
    except RuntimeError as ex:
        raise HTTPException(502,str(ex)) from ex
    return {'image_data_url':'data:image/png;base64,'+base64.b64encode(data).decode('ascii'),
            'bounds':bbox,'month':v.month,'capture_date':None,'period_start':period.isoformat(),'period_end':end.isoformat(),'layer':v.layer,'provider':'Copernicus Data Space Sentinel Hub Process API',
            'note':'True Sentinel-2 L2A composite for requested period; not a single dated acquisition.'}

# --- Copernicus Browser-style basemap: Sentinel-2 L2A XYZ tiles rendered through the Process API ---
# Whole-scene rendering (clouds visible, like Copernicus Browser), restricted to the Jeddah region to protect quota.
def _map_script(bands, body):
    return ("//VERSION=3\nfunction setup(){return {input:[{bands:%s}],output:{bands:4}}}\n"
            "function nd(a,b){return (a+b)!==0?(a-b)/(a+b):0}\n"
            "function evaluatePixel(s){if(s.dataMask===0)return [0,0,0,0]; %s}" % (json.dumps(bands+['dataMask']), body))
_G=lambda b:'Math.min(1,2.5*s.%s)'%b
MAP_SCRIPTS={
  'true_color': _map_script(['B04','B03','B02'], f"return [{_G('B04')},{_G('B03')},{_G('B02')},1];"),
  'false_color': _map_script(['B08','B04','B03'], f"return [{_G('B08')},{_G('B04')},{_G('B03')},1];"),
  'urban': _map_script(['B12','B11','B04'], f"return [{_G('B12')},{_G('B11')},{_G('B04')},1];"),
  'swir': _map_script(['B12','B8A','B04'], f"return [{_G('B12')},{_G('B8A')},{_G('B04')},1];"),
  'ndvi': _map_script(['B04','B08'], "let v=nd(s.B08,s.B04);let c=colorBlend(v,[-0.5,-0.2,0,0.025,0.05,0.075,0.1,0.125,0.15,0.175,0.2,0.25,0.3,0.35,0.4,0.45,0.5,0.55,0.6,1],"
     "[[0.75,0.75,0.75],[0.86,0.86,0.86],[1,1,0.88],[1,0.98,0.8],[0.93,0.91,0.71],[0.87,0.85,0.61],[0.8,0.78,0.51],[0.74,0.72,0.42],[0.69,0.76,0.38],[0.64,0.8,0.35],"
     "[0.57,0.75,0.32],[0.5,0.7,0.28],[0.44,0.64,0.25],[0.38,0.59,0.21],[0.31,0.54,0.18],[0.25,0.49,0.14],[0.19,0.43,0.11],[0.13,0.38,0.07],[0.06,0.33,0.04],[0,0.27,0]]);return [c[0],c[1],c[2],1];"),
  'ndre': _map_script(['B8A','B05'], "let v=nd(s.B8A,s.B05);let c=colorBlend(v,[0,0.15,0.3,0.45,0.6],[[0.74,0.19,0.17],[0.9,0.44,0.15],[0.92,0.77,0.23],[0.27,0.71,0.36],[0.08,0.5,0.23]]);return [c[0],c[1],c[2],1];"),
  'moisture': _map_script(['B8A','B11'], "let v=nd(s.B8A,s.B11);let c=colorBlend(v,[-0.8,-0.24,-0.032,0.032,0.24,0.8],[[0.5,0,0],[1,0,0],[1,1,0],[0,1,1],[0,0,1],[0,0,0.5]]);return [c[0],c[1],c[2],1];"),
  'ndwi': _map_script(['B03','B08'], "let v=nd(s.B03,s.B08);let c=colorBlend(v,[-0.8,-0.3,0,0.2,0.5],[[0,0.4,0],[0.6,0.8,0.4],[1,1,1],[0.3,0.6,1],[0,0,0.6]]);return [c[0],c[1],c[2],1];"),
}
TILE_REGION=(38.95,21.15,39.45,21.95)   # lon/lat box around Jeddah
TILE_DIR=Path(os.getenv('RAWAA_TILE_CACHE','/tmp/rawaa-tiles'))
_EMPTY_PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4XmNgYGBgAAAABQABGWkDzwAAAABJRU5ErkJggg==')
_O=20037508.342789244

def _tile_bounds(z,x,y):
    size=2*_O/(2**z);minx=-_O+x*size;maxy=_O-y*size
    return [minx,maxy-size,minx+size,maxy]

def _merc_to_lonlat(mx,my):
    return mx/_O*180, math.degrees(2*math.atan(math.exp(my/_O*math.pi))-math.pi/2)

@app.get('/api/tiles/{layer}/{z}/{x}/{y}.png')
def sentinel_tile(layer:str,z:int,x:int,y:int,req:Request,month:str='',cc:int=30):
    current_user(req)
    if layer not in MAP_SCRIPTS: raise HTTPException(404,'Unknown layer')
    if not (9<=z<=17) or not (0<=x<2**z and 0<=y<2**z): raise HTTPException(404,'Zoom out of range')
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month or ''): raise HTTPException(400,'month=YYYY-MM required')
    cc=max(0,min(100,int(cc)))
    period=date.fromisoformat(month+'-01')
    if period>date.today().replace(day=1) or period.year<2017: raise HTTPException(400,'Month out of range')
    b=_tile_bounds(z,x,y);w,s_=_merc_to_lonlat(b[0],b[1]);e,n=_merc_to_lonlat(b[2],b[3])
    hdr={'Cache-Control':'private, max-age=86400'}
    if e<TILE_REGION[0] or w>TILE_REGION[2] or n<TILE_REGION[1] or s_>TILE_REGION[3]:
        return Response(_EMPTY_PNG,media_type='image/png',headers=hdr)
    path=TILE_DIR/layer/month/str(cc)/str(z)/str(x)/f'{y}.png'
    if path.exists(): return Response(path.read_bytes(),media_type='image/png',headers=hdr)
    next_month=(period.replace(day=28)+timedelta(days=4)).replace(day=1)
    end=min(date.today(),next_month-timedelta(days=1))
    payload={'input':{'bounds':{'bbox':b,'properties':{'crs':'http://www.opengis.net/def/crs/EPSG/0/3857'}},
             'data':[{'type':'sentinel-2-l2a','dataFilter':{'timeRange':{'from':period.isoformat()+'T00:00:00Z','to':end.isoformat()+'T23:59:59Z'},
                      'mosaickingOrder':'leastCC','maxCloudCoverage':cc}}]},
             'output':{'width':256,'height':256,'responses':[{'identifier':'default','format':{'type':'image/png'}}]},
             'evalscript':MAP_SCRIPTS[layer]}
    try:
        data=_process_image(payload,_copernicus_access_token())
    except RuntimeError as ex:
        raise HTTPException(502,str(ex)[:300]) from ex
    try:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    except OSError:
        pass
    return Response(data,media_type='image/png',headers=hdr)

LST_EVALSCRIPT = """//VERSION=3
// Land-surface temperature (°C) from Landsat 8/9 TIRS band 10 brightness temperature (Kelvin),
// corrected with NDVI-based emissivity (single-channel method). Cold pixels (<270 K, likely cloud) are excluded.
function setup(){return {input:[{bands:["B04","B05","B10","dataMask"]}],
  output:[{id:"lst",bands:1,sampleType:"FLOAT32"},{id:"valid",bands:1,sampleType:"FLOAT32"},{id:"dataMask",bands:1}]};}
function evaluatePixel(s){
  let bt=s.B10, ok=s.dataMask===1 && bt>270 && bt<345;
  if(!ok) return {lst:[NaN],valid:[0],dataMask:[s.dataMask]};
  let ndvi=(s.B05+s.B04)!==0?(s.B05-s.B04)/(s.B05+s.B04):0;
  let pv=Math.pow(Math.min(1,Math.max(0,(ndvi-0.2)/0.3)),2);
  let e= ndvi<0?0.991 : ndvi<0.2?0.966 : ndvi>0.5?0.99 : 0.004*pv+0.986;
  let lst=bt/(1+(10.895*bt/14388)*Math.log(e));
  return {lst:[lst-273.15],valid:[1],dataMask:[s.dataMask]};
}"""

def _ring_polygon(polygon,margin=0.003):
    """~300 m belt around the park (bbox grown by margin, park cut out as a hole) = its urban surroundings."""
    ring=polygon['coordinates'][0];xs=[float(p[0]) for p in ring];ys=[float(p[1]) for p in ring]
    x0,y0,x1,y1=min(xs)-margin,min(ys)-margin,max(xs)+margin,max(ys)+margin
    outer=[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]
    hole=list(reversed(ring)) if ring[0]==ring[-1] else list(reversed(ring+[ring[0]]))
    return {'type':'Polygon','coordinates':[outer,hole]}

def _thermal_stats(geometry,start,end,tok):
    req={'input':{'bounds':{'geometry':geometry,'properties':{'crs':'http://www.opengis.net/def/crs/EPSG/0/4326'}},
                  'data':[{'type':'landsat-ot-l1','dataFilter':{'maxCloudCoverage':40,'mosaickingOrder':'leastCC'}}]},
         'aggregation':{'timeRange':{'from':f'{start}T00:00:00Z','to':f'{end}T23:59:59Z'},'aggregationInterval':{'of':'P30D'},
                        'lastIntervalBehavior':'SHORTEN','evalscript':LST_EVALSCRIPT,'resx':0.0003,'resy':0.0003}}
    res=api_json('https://sh.dataspace.copernicus.eu/statistics/v1',req,{'Content-Type':'application/json','Authorization':'Bearer '+tok},timeout=120)
    out={}
    for item in res.get('data',[]):
        o=item.get('outputs',{})
        m=o.get('lst',{}).get('bands',{}).get('B0',{}).get('stats',{}).get('mean')
        v=o.get('valid',{}).get('bands',{}).get('B0',{}).get('stats',{}).get('mean')
        if isinstance(m,(int,float)) and math.isfinite(m) and isinstance(v,(int,float)) and math.isfinite(v):
            out[item['interval']['from'][:10]]=(m,v*100)
    return out

def sync_thermal(area_id,polygon,start,end,tok):
    park=_thermal_stats(polygon,start,end,tok);ring=_thermal_stats(_ring_polygon(polygon),start,end,tok)
    saved=0
    with connect() as db:
        for d,(lst,pct) in park.items():
            if pct<50: continue
            rl=ring.get(d,(None,0))
            db.execute('''INSERT INTO thermal(area_id,measured_at,lst_park,lst_ring,valid_pixels_pct,created_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(area_id,measured_at) DO UPDATE SET lst_park=excluded.lst_park,lst_ring=excluded.lst_ring,valid_pixels_pct=excluded.valid_pixels_pct''',
                (area_id,d,round(lst,2),round(rl[0],2) if rl[0] is not None and rl[1]>=50 else None,round(pct,1),utcnow()))
            saved+=1
    return saved

@app.post('/api/areas/{area_id}/sync-satellite')
def sync_satellite(area_id:int,v:Sync,req:Request):
    u=current_user(req);require_regulator(u)
    client_id=os.getenv('COPERNICUS_CLIENT_ID');secret=os.getenv('COPERNICUS_CLIENT_SECRET')
    if not client_id or not secret: raise HTTPException(422,'Configure Copernicus OAuth credentials in server environment first')
    end=date.fromisoformat(v.end_date) if v.end_date else date.today()
    start=date.fromisoformat(v.start_date) if v.start_date else end-timedelta(days=3*365)
    if start>=end or (end-start).days>4*365: raise HTTPException(400,'Date range must be 1–1460 days')
    with connect() as db:
        a=area_access(db,u,area_id)
        polygon=json.loads(a['geometry'])
    import intelligence_api as _intel
    try:
        tok=_copernicus_access_token()
        report=_intel.sync_area(area_id,start,end,tok,api_json,u['id'])
    except RuntimeError as ex:
        log.warning('Copernicus sync failed for area %s: %s',area_id,ex)
        raise HTTPException(502,str(ex)[:400])
    except ValueError as ex:
        raise HTTPException(422,str(ex))
    saved=report['months_saved'];skipped=report['unreliable']
    thermal_saved=0;thermal_err=None
    try:
        thermal_saved=sync_thermal(area_id,polygon,start,end,tok)
    except Exception as ex:  # thermal is optional; vegetation readings are already saved
        thermal_err=str(ex)[:200]
    try:
        pipeline=_intel.run_pipeline('after_sync',u['id'])
    except Exception as ex:
        log.exception('pipeline after sync failed');pipeline={'error':str(ex)[:200]}
    return {'thermal_intervals':thermal_saved,'thermal_error':thermal_err,'saved_intervals':saved,'excluded_intervals':skipped,
            'report':report,'pipeline':pipeline,'source':'Copernicus Sentinel-2 L2A',
            'note':'One real acquisition per month (the clearest over the park), with scene IDs and pixel counts stored for audit.'}


@app.post('/api/areas/{area_id}/scan')
def scan_area(area_id:int,req:Request):
    """Evaluate the selected area using transparent provisional thresholds, no ML."""
    u=current_user(req);require_regulator(u)
    with connect() as db:
        a=area_access(db,u,area_id)
        result=metrics(area_id,db)
        allareas=attach_insights([full_area(db,r) for r in db.execute('SELECT * FROM areas ORDER BY id')])
        ins=next(x for x in allareas if x['id']==area_id)['insight']
        if result['status'] not in ('high','monitor') and ins['diagnosis'] in ('healthy','improving','insufficient','maintenance'):
            raise HTTPException(409,'No provisional alert threshold currently met')
        existing=db.execute('SELECT id FROM alerts WHERE area_id=? AND status<>\'closed\'',(area_id,)).fetchone()
        if existing:
            raise HTTPException(409,'An active alert already exists for this area')
        cur=db.execute('''INSERT INTO alerts(area_id,severity,reason_ar,reason_en,status,created_at)
            VALUES(?,?,?,?,?,?)''',(area_id,result['status'] if result['status'] in ('high','monitor') else 'monitor',
              f"{ins['title_ar']} · ثقة {ins.get('confidence_ar','')} · NDVI {ins.get('change_pct')}% مقابل خط الأساس",
              f"{ins['title_en']} · {ins['confidence']} confidence · NDVI {ins.get('change_pct')}% vs baseline",'new',utcnow()))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES (?,?,?,?,?)',
            (u['id'],'scan',str(area_id),f'alert {cur.lastrowid} — {result["status"]}',utcnow()))
        return {'alert_id':cur.lastrowid,'status':result['status'],'message':'Provisional alert created; field verification required'}

# Before/after task photo evidence. Files are stored outside /static and require authorization.
class PhotoUpload(BaseModel):
    kind: str
    data_url: str

def checked_task(db, user, task_id):
    task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not task: raise HTTPException(404,'Task not found')
    if user['role']=='operator' and task['assigned_to']!=user['id']:
        raise HTTPException(403,'Task outside your scope')
    return task

@app.post('/api/tasks/{task_id}/photo')
def upload_photo(task_id:int,v:PhotoUpload,req:Request):
    u=current_user(req)
    if u['role']!='operator': raise HTTPException(403,'Only operator uploads photo evidence')
    if v.kind not in ('before','after'): raise HTTPException(400,'kind must be before or after')
    with connect() as db:
        task=checked_task(db,u,task_id)
        if task['status']=='closed': raise HTTPException(409,'Task is closed')
    try:
        header,body=v.data_url.split(',',1)
        if not header.startswith('data:image/') or ';base64' not in header:
            raise ValueError('Expected base64 image data URL')
        raw=base64.b64decode(body,validate=True)
    except (ValueError,binascii.Error) as ex:
        raise HTTPException(400,f'Invalid image encoding: {ex}')
    if len(raw)>3*1024*1024 or len(raw)<8: raise HTTPException(400,'Image size must be 8 bytes–3 MB')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime,ext='image/png','png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime,ext='image/jpeg','jpg'
    elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':
        mime,ext='image/webp','webp'
    else: raise HTTPException(400,'Only valid PNG/JPEG/WebP images are supported')
    file_name=secrets.token_hex(18)+'.'+ext
    photos_dir=ROOT / 'media';photos_dir.mkdir(exist_ok=True)
    (photos_dir / file_name).write_bytes(raw)
    with connect() as db:
        old=db.execute('SELECT filename FROM task_photos WHERE task_id=? AND kind=?',(task_id,v.kind)).fetchone()
        db.execute('''INSERT INTO task_photos(task_id,kind,filename,mime,uploaded_by,created_at,data)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id,kind) DO UPDATE SET
              filename=excluded.filename,mime=excluded.mime,uploaded_by=excluded.uploaded_by,created_at=excluded.created_at,data=excluded.data''',
              (task_id,v.kind,file_name,mime,u['id'],utcnow(),raw))
        db.execute('INSERT INTO activity(user_id,verb,target,details,created_at) VALUES(?,?,?,?,?)',
                   (u['id'],'task_photo',str(task_id),v.kind,utcnow()))
    if old:
        try:(photos_dir / old['filename']).unlink(missing_ok=True)
        except OSError:pass
    return {'uploaded':True,'kind':v.kind}

@app.get('/api/tasks/{task_id}/photo/{kind}')
def get_photo(task_id:int,kind:str,req:Request):
    u=current_user(req)
    if kind not in ('before','after'): raise HTTPException(404,'Photo kind not found')
    with connect() as db:
        checked_task(db,u,task_id)
        r=db.execute('SELECT filename,mime,data FROM task_photos WHERE task_id=? AND kind=?',(task_id,kind)).fetchone()
    if not r: raise HTTPException(404,'Photo not found')
    if r['data']: return Response(bytes(r['data']),media_type=r['mime'])
    path=ROOT / 'media' / r['filename']
    if not path.is_file(): raise HTTPException(404,'Photo file missing')
    return FileResponse(path,media_type=r['mime'])

import intelligence_api  # noqa: E402  (new decision / forecast / schedule endpoints)
intelligence_api.install(sys.modules[__name__])

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000)
