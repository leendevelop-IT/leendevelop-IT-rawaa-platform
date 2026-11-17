"""Sentinel-2 L2A spectral indices — one reference definition used by both Python and the evalscript.

The Python functions are the reference implementation used in the tests; the JavaScript evalscript sent to
Copernicus is generated from the same constants, and the tests run it in Node to prove both give identical results.

Spectral inputs are L2A surface reflectances (0–1, Sentinel Hub "REFLECTANCE" units). SCL and dataMask are requested
in "DN" units: SCL class codes 0–11 exist only as DN, and Copernicus rejects the script if SCL is asked for in
REFLECTANCE.

Statistical API rules the evalscript follows (Copernicus Data Space Ecosystem, Sentinel Hub documentation):
- each output is aggregated over the pixels its mask keeps; a NaN that is not masked turns the whole mean into NaN;
- the dataMask output may carry one named band per output, so every output gets its own mask (OUTPUT_MASKS below).

v2 never produced a reading: it asked for SCL in REFLECTANCE units and was rejected with HTTP 400.
"""
from __future__ import annotations
import hashlib
import math

PROCESSING_VERSION = 'rawaa-s2-v3'
COLLECTION = 'sentinel-2-l2a'

# Scene Classification Layer (SCL) classes from the L2A processor (ESA Sen2Cor).
SCL_CLASSES = {
    0: 'No data', 1: 'Saturated or defective', 2: 'Topographic/casted shadows (dark area pixels)',
    3: 'Cloud shadows', 4: 'Vegetation', 5: 'Not vegetated', 6: 'Water', 7: 'Unclassified',
    8: 'Cloud medium probability', 9: 'Cloud high probability', 10: 'Thin cirrus', 11: 'Snow or ice',
}
# Pixels in these classes are excluded from every statistic: no-data, defective, shadows (2, 3),
# water (6, not vegetation), clouds (8, 9), cirrus (10) and snow (11).
SCL_EXCLUDED = (0, 1, 2, 3, 6, 8, 9, 10, 11)

# A pixel counts as "vegetated" (part of the analysable green area) when its NDVI is at least this value.
VEGETATION_NDVI_MIN = 0.25
SAVI_L = 0.5

# Reading reliability thresholds (share of clear pixels inside the park polygon, and absolute pixel count).
RELIABLE_VALID_PCT = 80.0
LIMITED_VALID_PCT = 60.0
MIN_CLEAR_PIXELS = 20

FORMULAS = {
    'ndvi': '(B08 - B04) / (B08 + B04)',
    'ndmi': '(B08 - B11) / (B08 + B11)',
    'ndre': '(B8A - B05) / (B8A + B05)',
    'savi': '1.5 * (B08 - B04) / (B08 + B04 + 0.5)',
    'ndwi': '(B03 - B08) / (B03 + B08)   (McFeeters)',
    'salinity': 'sqrt(B02 * B04)   (brightness salinity index SI, approximate)',
}

MEANINGS = {
    'ndvi': ('كثافة الغطاء الأخضر وحيويته. أعلى من 0.5 خضرة كثيفة، 0.2–0.35 خضرة متوسطة، أقل من 0.1 غالبًا ممرات وتربة.',
             'Green cover density and vigour. >0.5 dense, 0.2–0.35 moderate, <0.1 mostly paths and soil.'),
    'ndmi': ('محتوى الماء في أوراق النبات. انخفاضه المستمر قد يرتبط بالعطش، ويحتاج تحققًا ميدانيًا.',
             'Leaf water content. A sustained drop can relate to water shortage; needs field verification.'),
    'ndre': ('حساس للكلوروفيل في الغطاء الكثيف؛ انخفاضه قد يسبق انخفاض NDVI.',
             'Sensitive to chlorophyll in dense canopy; a drop can precede an NDVI drop.'),
    'savi': ('مثل NDVI مع تقليل أثر التربة المكشوفة، مفيد للحدائق ذات الغطاء المتفرق.',
             'Like NDVI with reduced bare-soil influence; useful for sparse cover.'),
    'ndwi': ('يرتفع مع الماء المكشوف أو التربة المشبعة.', 'Rises with open water or saturated soil.'),
    'salinity': ('مؤشر سطوع تقريبي يرتفع مع القشور الملحية والتربة المكشوفة.', 'Approximate brightness index; rises with salt crusts and bare soil.'),
}


def _nd(a: float, b: float) -> float:
    s = a + b
    return (a - b) / s if s != 0 else 0.0


def ndvi(b04, b08): return _nd(b08, b04)
def ndmi(b08, b11): return _nd(b08, b11)
def ndre(b05, b8a): return _nd(b8a, b05)
def ndwi(b03, b08): return _nd(b03, b08)
def savi(b04, b08, L=SAVI_L):
    d = b08 + b04 + L
    return (1 + L) * (b08 - b04) / d if d != 0 else 0.0
def salinity(b02, b04): return math.sqrt(max(0.0, b02 * b04))


def pixel_is_clear(scl: int, data_mask: int = 1) -> bool:
    return data_mask == 1 and int(scl) not in SCL_EXCLUDED


INPUT_BANDS = ('B02', 'B03', 'B04', 'B05', 'B08', 'B8A', 'B11', 'SCL', 'dataMask')
INPUT_UNITS = ('REFLECTANCE',) * 7 + ('DN', 'DN')
OUTPUTS = ('ndvi', 'ndmi', 'ndwi', 'savi', 'ndre', 'salinity', 'valid', 'veg', 'ndvi_veg')
# The pixels each output is aggregated over (its band in the evalscript's dataMask output):
#   clear     inside the polygon, with data, SCL class not excluded
#   data      inside the polygon, with data, any SCL class (so the mean of `valid` is the clear share)
#   vegetated clear and NDVI >= VEGETATION_NDVI_MIN
# `veg` is averaged over clear pixels, so veg_fraction is the vegetated share of the area that could be seen.
OUTPUT_MASKS = {'ndvi': 'clear', 'ndmi': 'clear', 'ndwi': 'clear', 'savi': 'clear', 'ndre': 'clear',
                'salinity': 'clear', 'valid': 'data', 'veg': 'clear', 'ndvi_veg': 'vegetated'}


def evaluate_pixel(px: dict) -> dict:
    """Python twin of the evalscript's evaluatePixel: one value per output (NaN where the output does not apply)
    and `dataMask`, the per-output masks in OUTPUTS order."""
    has_data = px.get('dataMask', 1) == 1
    good = pixel_is_clear(px['SCL'], px.get('dataMask', 1))
    nan = float('nan')
    v = ndvi(px['B04'], px['B08'])
    vegetated = good and v >= VEGETATION_NDVI_MIN
    masks = {'clear': int(good), 'data': int(has_data), 'vegetated': int(vegetated)}
    return {
        'ndvi': v if good else nan,
        'ndmi': ndmi(px['B08'], px['B11']) if good else nan,
        'ndwi': ndwi(px['B03'], px['B08']) if good else nan,
        'savi': savi(px['B04'], px['B08']) if good else nan,
        'ndre': ndre(px['B05'], px['B8A']) if good else nan,
        'salinity': salinity(px['B02'], px['B04']) if good else nan,
        'valid': 1 if good else 0,
        'veg': 1 if vegetated else 0,
        'ndvi_veg': v if vegetated else nan,
        'dataMask': [masks[OUTPUT_MASKS[k]] for k in OUTPUTS],
    }


def build_evalscript() -> str:
    excluded = ','.join(str(c) for c in SCL_EXCLUDED)
    bands = ','.join(f'"{b}"' for b in INPUT_BANDS)
    units = ','.join(f'"{u}"' for u in INPUT_UNITS)
    outputs = ',\n              '.join(f'{{id:"{k}",bands:1,sampleType:"FLOAT32"}}' for k in OUTPUTS)
    mask_names = ','.join(f'"{k}"' for k in OUTPUTS)
    js_mask = {'clear': 'c', 'data': 'm', 'vegetated': 'g'}
    mask_values = ','.join(js_mask[OUTPUT_MASKS[k]] for k in OUTPUTS)
    return f'''//VERSION=3
// RAWAA {PROCESSING_VERSION}: per-acquisition statistics inside the park polygon.
// SCL classes excluded: [{excluded}] (no data, defective, shadows, water, clouds, cirrus, snow).
// Spectral bands in REFLECTANCE (0-1); SCL and dataMask in DN. Each output has its own mask (a named band of the
// dataMask output): clear pixels for the indices and veg, every pixel with data for valid, vegetated pixels for ndvi_veg.
function setup() {{
  return {{ input: [{{bands:[{bands}],
             units:[{units}]}}],
    output: [ {outputs},
              {{id:"dataMask",bands:[{mask_names}]}} ] }};
}}
var EXCLUDED = [{excluded}];
function nd(a,b){{ return (a+b)!==0 ? (a-b)/(a+b) : 0; }}
function evaluatePixel(s) {{
  var data = s.dataMask===1;
  var good = data && EXCLUDED.indexOf(s.SCL)===-1;
  var N = NaN;
  var v = nd(s.B08,s.B04);
  var d = s.B08+s.B04+{SAVI_L};
  var sv = d!==0 ? {1 + SAVI_L}*(s.B08-s.B04)/d : 0;
  var veg = good && v>={VEGETATION_NDVI_MIN};
  var c = good?1:0, m = data?1:0, g = veg?1:0;
  return {{ndvi:[good?v:N], ndmi:[good?nd(s.B08,s.B11):N], ndwi:[good?nd(s.B03,s.B08):N], savi:[good?sv:N],
          ndre:[good?nd(s.B8A,s.B05):N], salinity:[good?Math.sqrt(Math.max(0,s.B02*s.B04)):N],
          valid:[c], veg:[g], ndvi_veg:[veg?v:N], dataMask:[{mask_values}]}};
}}
'''


EVALSCRIPT = build_evalscript()
EVALSCRIPT_SHA256 = hashlib.sha256(EVALSCRIPT.encode()).hexdigest()


def classify_reliability(origin: str, valid_pct, clear_pixels=None) -> str:
    """'reliable' | 'limited' | 'unreliable' for satellite readings; 'unverified' for imported/manual; 'demo'."""
    if origin == 'demo':
        return 'demo'
    if origin != 'satellite':
        return 'unverified'
    if valid_pct is None or not math.isfinite(valid_pct):
        return 'unreliable'
    if clear_pixels is not None and clear_pixels < MIN_CLEAR_PIXELS:
        return 'unreliable'
    if valid_pct >= RELIABLE_VALID_PCT:
        return 'reliable'
    if valid_pct >= LIMITED_VALID_PCT:
        return 'limited'
    return 'unreliable'
