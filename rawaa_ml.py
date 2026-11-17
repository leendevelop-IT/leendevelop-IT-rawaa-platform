"""RAWAA learning model: learns the real causes of decline from confirmed field records.

Labels come from (1) maintenance tasks closed with a confirmed cause, and (2) municipality records imported
as CSV (site, date, cause). Each label is paired with the satellite features of that site as they were on
that date. A RandomForest is trained once enough labels exist, validated with cross-validation, and compared
against the transparent rules on the same records. Until then the platform says how many records it still needs.
"""
from __future__ import annotations
import hashlib, json, statistics

CAUSES = {
    'water_stress': ('إجهاد مائي / نقص ري', 'Water stress / under-irrigation'),
    'waterlogging': ('تشبع مائي / تسرب', 'Waterlogging / leak'),
    'salinity': ('ملوحة', 'Salinity'),
    'nutrition': ('نقص تغذية', 'Nutrient deficiency'),
    'patchy_damage': ('تلف موضعي (عطل خط ري/آفة)', 'Localised damage (line break/pest)'),
    'heat_stress': ('إجهاد حراري', 'Heat stress'),
    'maintenance': ('أثر صيانة مجدولة', 'Scheduled maintenance effect'),
    'healthy': ('سليمة / لا مشكلة', 'Healthy / no issue'),
    'other': ('سبب آخر', 'Other cause'),
}
FEATURES = [
    ('ndvi_change_pct', 'تغير NDVI عن خط الأساس %', 'NDVI change vs baseline %'),
    ('z_ndmi', 'انحراف رطوبة النبات NDMI', 'NDMI deviation'),
    ('z_ndwi', 'انحراف الماء السطحي NDWI', 'NDWI deviation'),
    ('z_ndre', 'انحراف الكلوروفيل NDRE', 'NDRE deviation'),
    ('z_salinity', 'انحراف مؤشر الملوحة SI', 'Salinity index deviation'),
    ('z_ndvi_std', 'انحراف تباين NDVI', 'NDVI variability deviation'),
    ('ndvi', 'قيمة NDVI', 'NDVI value'),
    ('z_lst', 'انحراف حرارة السطح LST', 'Surface temperature deviation'),
    ('cooling', 'تأثير التبريد (°م)', 'Cooling effect (°C)'),
    ('coastal', 'موقع ساحلي', 'Coastal site'),
    ('maint_month', 'شهر صيانة مجدولة', 'Scheduled-maintenance month'),
    ('summer', 'أشهر الصيف', 'Summer month'),
]
MIN_LABELS = 10
_CACHE = {'key': None, 'model': None}


def vector(feat):
    return [float(feat.get(k) or 0.0) for k, _a, _e in FEATURES]


def status(samples, rule_predictions):
    """samples: list of (features dict, label). rule_predictions: rules' diagnosis for the same samples."""
    n = len(samples)
    classes = sorted({y for _f, y in samples})
    counts = {c: sum(1 for _f, y in samples if y == c) for c in classes}
    base = {'labels': n, 'min_labels': MIN_LABELS, 'classes': counts,
            'class_names_ar': {c: CAUSES.get(c, (c, c))[0] for c in classes}}
    rule_acc = round(100 * sum(1 for (f, y), r in zip(samples, rule_predictions) if y == r) / n) if n else None
    base['rules_accuracy'] = rule_acc
    if n < MIN_LABELS or len(classes) < 2:
        need = max(0, MIN_LABELS - n)
        base.update(trained=False, reason_ar=(f'النموذج يحتاج {need} سجلًا مؤكدًا إضافيًا على الأقل' if need else 'يحتاج سببين مختلفين على الأقل')
                    + ' (من إغلاق المهام بسبب مؤكد أو استيراد سجلات الأمانة) قبل أن يتدرّب.')
        return base, None
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
    except ImportError:
        base.update(trained=False, reason_ar='مكتبة scikit-learn غير مثبتة على الخادم.')
        return base, None
    key = hashlib.sha1(json.dumps([[vector(f), y] for f, y in samples]).encode()).hexdigest()
    X = np.array([vector(f) for f, _y in samples]); y = np.array([lab for _f, lab in samples])
    if _CACHE['key'] != key:
        clf = RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=1, class_weight='balanced', random_state=0)
        keep = [c for c, v in counts.items() if v >= 2]
        mask = np.isin(y, keep)
        k = min(5, min(counts[c] for c in keep)) if len(keep) >= 2 else 0
        cv_acc = None
        if k >= 2:
            pred = cross_val_predict(RandomForestClassifier(n_estimators=300, max_depth=4, class_weight='balanced', random_state=0),
                                     X[mask], y[mask], cv=StratifiedKFold(n_splits=k, shuffle=True, random_state=0))
            cv_acc = round(100 * float((pred == y[mask]).mean()))
        _CACHE['cv_n'] = int(mask.sum())
        clf.fit(X, y)
        _CACHE.update(key=key, model=clf, cv_acc=cv_acc, k=k)
    clf = _CACHE['model']
    imp = sorted(zip(FEATURES, clf.feature_importances_), key=lambda x: -x[1])
    base.update(trained=True, algorithm='RandomForest (300 trees, depth ≤ 4, balanced classes)', cv_folds=_CACHE['k'],
                cv_accuracy=_CACHE['cv_acc'],cv_samples=_CACHE.get('cv_n'),
                importances=[{'feature': f[0], 'label_ar': f[1], 'label_en': f[2], 'importance': round(float(v), 3)} for f, v in imp[:6]])
    return base, clf


def predict(clf, feat):
    import numpy as np
    proba = clf.predict_proba(np.array([vector(feat)]))[0]
    ranked = sorted(zip(clf.classes_, proba), key=lambda x: -x[1])[:3]
    return [{'cause': c, 'label_ar': CAUSES.get(c, (c, c))[0], 'label_en': CAUSES.get(c, (c, c))[1], 'probability': round(100 * float(p))} for c, p in ranked]
