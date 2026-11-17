"""Spectral index formulas, cloud/shadow masking and the evalscript sent to Copernicus."""
import json
import math
import random
import shutil
import subprocess

import pytest

from rawaa_core import indices


def test_formulas_on_known_reflectances():
    # Healthy grass: red 0.04, NIR 0.40, SWIR1 0.20, red-edge 0.12, NIR narrow 0.38
    assert indices.ndvi(0.04, 0.40) == pytest.approx(0.36 / 0.44)
    assert indices.ndmi(0.40, 0.20) == pytest.approx(0.20 / 0.60)
    assert indices.ndre(0.12, 0.38) == pytest.approx(0.26 / 0.50)
    assert indices.savi(0.04, 0.40) == pytest.approx(1.5 * 0.36 / 0.94)
    assert indices.ndwi(0.06, 0.40) == pytest.approx(-0.34 / 0.46)
    # Bare soil has low NDVI
    assert indices.ndvi(0.25, 0.30) < 0.1
    # Zero denominators never divide by zero
    assert indices.ndvi(0, 0) == 0 and indices.savi(-0.25, -0.25) == 0


def test_masking_excludes_clouds_shadows_water_snow():
    for scl in (0, 1, 2, 3, 6, 8, 9, 10, 11):
        assert not indices.pixel_is_clear(scl)
    for scl in (4, 5, 7):
        assert indices.pixel_is_clear(scl)
    assert not indices.pixel_is_clear(4, data_mask=0)  # outside the polygon


def test_reliability_classes():
    assert indices.classify_reliability('satellite', 95, 500) == 'reliable'
    assert indices.classify_reliability('satellite', 70, 500) == 'limited'
    assert indices.classify_reliability('satellite', 40, 500) == 'unreliable'
    assert indices.classify_reliability('satellite', 99, 5) == 'unreliable'  # too few clear pixels
    assert indices.classify_reliability('imported', 99) == 'unverified'
    assert indices.classify_reliability('manual', 99) == 'unverified'
    assert indices.classify_reliability('demo', 99) == 'demo'


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_evalscript_matches_python_reference():
    """Run the exact evalscript in Node on 400 random pixels and compare with the Python reference."""
    rnd = random.Random(42)
    pixels = []
    for _ in range(400):
        pixels.append({b: round(rnd.uniform(0, 0.6), 4) for b in ('B02', 'B03', 'B04', 'B05', 'B08', 'B8A', 'B11')}
                      | {'SCL': rnd.choice(range(12)), 'dataMask': rnd.choice([1, 1, 1, 0])})
    out = run_evalscript(pixels)
    for p, j in zip(pixels, out):
        py = indices.evaluate_pixel(p)
        assert j['dataMask'] == py['dataMask'], p
        for k, v in py.items():
            if k == 'dataMask':
                continue
            if isinstance(v, float) and math.isnan(v):
                assert j[k][0] is None, k
            else:
                assert j[k][0] == pytest.approx(v, abs=1e-9), (k, p)


def run_evalscript(pixels, script=None):
    """evaluatePixel for each pixel in Node; NaN comes back as None."""
    js = (script or indices.EVALSCRIPT) + '\nconst px=' + json.dumps(pixels) + ';\nconsole.log(JSON.stringify(px.map(p=>{const r=evaluatePixel(p);const o={};for(const k in r)o[k]=r[k].map(x=>Number.isNaN(x)?null:x);return o;})));'
    return json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)


def run_setup(script):
    js = script + '\nconsole.log(JSON.stringify(setup()));'
    return json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)


def check_masks_cover_outputs(setup):
    outputs = [o['id'] for o in setup['output'] if o['id'] != 'dataMask']
    mask = next(o for o in setup['output'] if o['id'] == 'dataMask')
    assert mask['bands'] == outputs  # one named mask band per output, in the same order


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_evalscript_units_and_per_output_masks():
    """Copernicus rejects SCL in REFLECTANCE units (HTTP 400, seen in production); SCL and dataMask must be DN."""
    s = run_setup(indices.EVALSCRIPT)
    inp = s['input'][0]
    assert len(inp['units']) == len(inp['bands'])
    units = dict(zip(inp['bands'], inp['units']))
    assert units.pop('SCL') == 'DN' and units.pop('dataMask') == 'DN'
    assert set(units.values()) == {'REFLECTANCE'}
    check_masks_cover_outputs(s)
    assert [o['id'] for o in s['output'] if o['id'] != 'dataMask'] == list(indices.OUTPUTS)


def simulate_statistics(rows, outputs):
    """Aggregate per-pixel results the way the Statistical API documents it: each output's statistics use only the
    pixels its mask band keeps; sampleCount counts every pixel in the bounding box, noDataCount the masked ones."""
    res = {}
    for i, k in enumerate(outputs):
        vals = [r[k][0] for r in rows if r['dataMask'][i] == 1]
        assert None not in vals, k  # a NaN that reached the statistics would turn the mean into NaN
        mean = sum(vals) / len(vals) if vals else 'NaN'
        res[k] = {'bands': {'B0': {'stats': {'mean': mean, 'stDev': 0.0, 'sampleCount': len(rows),
                                              'noDataCount': len(rows) - len(vals)}}}}
    return res


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_masked_statistics_give_the_expected_reading():
    """One synthetic acquisition through the evalscript, the documented aggregation rules and parse_daily."""
    from rawaa_core import sentinel
    rnd = random.Random(7)
    pixels = []
    for i in range(600):
        inside = i < 450  # 150 pixels of the bounding box fall outside the polygon (dataMask 0)
        scl = rnd.choice([4, 4, 4, 5, 7, 3, 8, 9, 6]) if inside else 0
        pixels.append({b: round(rnd.uniform(0.01, 0.5), 4) for b in ('B02', 'B03', 'B04', 'B05', 'B08', 'B8A', 'B11')}
                      | {'SCL': scl, 'dataMask': 1 if inside else 0})
    rows = run_evalscript(pixels)
    item = {'interval': {'from': '2026-03-14T00:00:00Z', 'to': '2026-03-15T00:00:00Z'},
            'outputs': simulate_statistics(rows, indices.OUTPUTS)}
    [c] = sentinel.parse_daily({'data': [item]})

    ref = [indices.evaluate_pixel(p) for p in pixels]
    clear = [r for r in ref if r['valid'] == 1]
    veg = [r for r in clear if r['veg'] == 1]
    assert c['usable'] and c['pixels_in_polygon'] == 450 and c['clear_pixels'] == len(clear)
    assert c['valid_pct'] == round(100 * len(clear) / 450, 1)
    assert c['ndvi'] == pytest.approx(sum(r['ndvi'] for r in clear) / len(clear))
    assert c['ndmi'] == pytest.approx(sum(r['ndmi'] for r in clear) / len(clear))
    assert c['veg_fraction'] == pytest.approx(len(veg) / len(clear))
    assert c['ndvi_veg'] == pytest.approx(sum(r['ndvi_veg'] for r in veg) / len(veg))


def test_evalscript_is_versioned_and_hashed():
    assert indices.PROCESSING_VERSION in indices.EVALSCRIPT
    assert len(indices.EVALSCRIPT_SHA256) == 64
    assert '[0,1,2,3,6,8,9,10,11]' in indices.EVALSCRIPT.replace(' ', '')
