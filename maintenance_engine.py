"""RAWAA Maintenance Engine (from the team notebook Maintenance_Engine.ipynb), connected to the platform.

Input : tree_type + diagnosis + confidence + month   (diagnosis comes from the platform's diagnosis step)
Output: MaintenancePlan  -> priority, deadline, owner, scheduled maintenance for the month,
                           recommended actions, success indicator (Arabic + English).

Changes from the notebook:
  * MONTHLY_MAINTENANCE now follows the municipality's approved programme (Appendix 6,
    "البرنامج المقترح لعمليات الصيانة الزراعية") instead of placeholder months, and covers
    palms, trees, shrubs, ground covers and lawn.
  * Every rule carries Arabic text so the platform can explain itself to Arabic users.
  * Diagnosis keys accept the platform's names (waterlogging, patchy_damage, ...) as aliases.
"""
from dataclasses import dataclass, asdict, field
from datetime import datetime


@dataclass
class MaintenancePlan:
    diagnosis: str
    priority: str
    deadline: str
    owner: str
    confidence: str
    scheduled_maintenance: list
    ai_recommendations: list
    success_indicator: str
    # Arabic presentation (added for the platform)
    priority_ar: str = ''
    deadline_ar: str = ''
    owner_ar: str = ''
    scheduled_maintenance_ar: list = field(default_factory=list)
    ai_recommendations_ar: list = field(default_factory=list)
    success_indicator_ar: str = ''
    month: int = 0
    tree_types: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# Appendix 6 — approved monthly programme. (english, arabic, months, effect on NDVI: down/up/'')
_PROGRAMME = {
    'Palm': [
        ('Offshoot removal', 'إزالة ونقل فسائل النخيل', [2, 9], 'down'),
        ('Trunk cleaning (takreeb)', 'تكريب النخيل', [11, 12], ''),
        ('Pruning dry fronds', 'تقليم وإزالة السعف الجاف', [1, 2, 10, 11], 'down'),
        ('Thorn & old bunch removal', 'إزالة الأشواك والعذوق القديمة', [1, 2], ''),
        ('Pollination', 'التلقيح', [3, 4], ''),
        ('Bunch thinning', 'خف العذوق', [5], ''),
        ('Bunch bending', 'تقويس العذوق', [6], ''),
        ('Harvest', 'جني الثمار', [8, 9], ''),
        ('Hoeing / tilling', 'العزق / التقليب', [2, 6, 10], ''),
        ('Organic fertiliser 15–30 kg/palm', 'سماد عضوي ١٥–٣٠ كغ/نخلة', [1], 'up'),
        ('Chemical fertiliser 400–1200 g/palm', 'سماد كيميائي ٤٠٠–١٢٠٠ جم/نخلة', [3, 5, 9, 11], 'up'),
        ('Insecticide', 'مبيد حشري', [3, 6, 10], ''),
        ('Fungicide', 'مبيد فطري', [1, 12], ''),
        ('Pesticide restriction (summer)', 'حظر/تحذير استخدام المبيدات (الصيف)', [7, 8, 9], ''),
    ],
    'Tree': [
        ('Pruning', 'التقليم', [1, 2, 11, 12], 'down'),
        ('Hoeing / tilling', 'العزق / التقليب', [2, 6, 10], ''),
        ('Organic fertiliser 10–15 kg/tree', 'تسميد عضوي ١٠–١٥ كغ/شجرة', [1], 'up'),
        ('Chemical fertiliser 300–400 g/tree', 'تسميد كيميائي ٣٠٠–٤٠٠ جم/شجرة', [3, 5, 9, 11], 'up'),
        ('Insecticide', 'مبيد حشري', [3, 7, 11], ''),
        ('Fungicide', 'مبيد فطري', [1, 5, 9], ''),
    ],
    'Shrub': [
        ('Pruning', 'التقليم', [1, 2, 11, 12], 'down'),
        ('Hoeing / tilling', 'العزق / التقليب', [2, 6, 10], ''),
        ('Organic fertiliser 3–7 kg/shrub', 'تسميد عضوي ٣–٧ كغ/شجيرة', [1], 'up'),
        ('Chemical fertiliser 100–150 g/shrub', 'تسميد كيميائي ١٠٠–١٥٠ جم/شجيرة', [3, 5, 9, 11], 'up'),
        ('Insecticide', 'مبيد حشري', [3, 7, 11], ''),
        ('Fungicide', 'مبيد فطري', [1, 5, 9], ''),
    ],
    'GroundCover': [
        ('Seasonal annuals replacement', 'استبدال النباتات الحولية', [5, 10], 'down'),
        ('Hoeing / tilling', 'العزق / التقليب', [2, 6, 10], ''),
        ('Organic fertiliser 3 kg/m²', 'تسميد عضوي ٣ كغ/م²', [1], 'up'),
        ('Chemical fertiliser 100–150 g/m²', 'تسميد كيميائي ١٠٠–١٥٠ جم/م²', [3, 5, 9, 11], 'up'),
    ],
    'Lawn': [
        ('Aeration', 'التهوية', [3, 10], 'down'),
        ('De-thatching', 'إزالة طبقة الألياف المتراكمة (De-Thatching)', [3], 'down'),
        ('Top dressing', 'ترميم وتجديد النجيل (Top dressing)', [3, 10], 'down'),
        ('Organic fertiliser 1.5–3 kg/m²', 'تسميد عضوي ١٫٥–٣ كغ/م²', [1], 'up'),
        ('Chemical fertiliser 10–20 g/m²', 'تسميد كيميائي ١٠–٢٠ جم/م²', [3, 5, 9, 11], 'up'),
    ],
}

# Same shape as the notebook: MONTHLY_MAINTENANCE[tree_type][month] -> list of activities
MONTHLY_MAINTENANCE = {
    t: {m: [a[0] for a in acts if m in a[2]] for m in range(1, 13)} for t, acts in _PROGRAMME.items()
}
MONTHLY_MAINTENANCE_AR = {
    t: {m: [a[1] for a in acts if m in a[2]] for m in range(1, 13)} for t, acts in _PROGRAMME.items()
}
_TYPE_ALIASES = {'palm': 'Palm', 'palms': 'Palm', 'tree': 'Tree', 'trees': 'Tree', 'shrub': 'Shrub', 'shrubs': 'Shrub',
                 'groundcover': 'GroundCover', 'ground': 'GroundCover', 'lawn': 'Lawn', 'grass': 'Lawn',
                 'نخيل': 'Palm', 'نخل': 'Palm', 'أشجار': 'Tree', 'شجر': 'Tree', 'شجيرات': 'Shrub', 'مغطيات': 'GroundCover',
                 'نجيل': 'Lawn', 'ثيل': 'Lawn'}

_P_AR = {'High': 'عالية', 'Medium': 'متوسطة', 'Low': 'منخفضة'}
_O_AR = {'Operator': 'المشغّل', 'Regulator': 'الجهة الرقابية'}

# Notebook rules, kept as written, with Arabic added and a few platform-specific steps appended.
AI_RULES = {
    'water_stress': {
        'priority': 'High', 'deadline': '72 Hours', 'deadline_ar': '72 ساعة', 'owner': 'Operator',
        'actions': ['Inspect irrigation valves', 'Check emitters', 'Increase irrigation gradually', 'Measure soil moisture'],
        'actions_ar': ['فحص صمامات الري', 'فحص الرشاشات والنقاطات وتسليك المسدود منها',
                       'زيادة الري تدريجيًا (10–20%) فجرًا أو مساءً', 'قياس رطوبة التربة يدويًا في 3 نقاط على الأقل قبل زيادة الري'],
        'success': 'NDMI increases in the next observation.', 'success_ar': 'ارتفاع NDMI في القراءة الفضائية القادمة.'},
    'water_logging': {
        'priority': 'High', 'deadline': '48 Hours', 'deadline_ar': '48 ساعة', 'owner': 'Operator',
        'actions': ['Reduce irrigation', 'Inspect drainage system', 'Remove standing water'],
        'actions_ar': ['تقليل مدة الري في القطاعات المشبعة', 'فحص نظام التصريف والبحث عن تسربات وانكسارات', 'إزالة المياه المتجمعة'],
        'success': 'NDWI returns to normal.', 'success_ar': 'عودة NDWI إلى معدله الطبيعي.'},
    'salinity': {
        'priority': 'Medium', 'deadline': '1 Week', 'deadline_ar': 'أسبوع', 'owner': 'Operator',
        'actions': ['Test soil salinity', 'Flush salts', 'Review irrigation water quality'],
        'actions_ar': ['قياس ملوحة التربة (EC) بعينة ميدانية، لأن المؤشر الفضائي تقريبي', 'غسيل الأملاح بري متقطع إذا كان التصريف جيدًا',
                       'مراجعة جودة مياه الري ومصدرها'],
        'success': 'Salinity index decreases.', 'success_ar': 'انخفاض مؤشر الملوحة واستقرار NDVI.'},
    'nutrition': {
        'priority': 'Medium', 'deadline': '2 Weeks', 'deadline_ar': 'أسبوعان', 'owner': 'Operator',
        'actions': ['Apply fertilizer', 'Review nutrient levels'],
        'actions_ar': ['التسميد وفق البرنامج المعتمد (الكيميائي: مارس، مايو، سبتمبر، نوفمبر) أو تقديمه إن تأخر',
                       'مراجعة مستويات العناصر الغذائية وفحص اصفرار الأوراق'],
        'success': 'NDRE improves.', 'success_ar': 'تحسّن NDRE خلال 4–6 أسابيع.'},
    'localized_damage': {
        'priority': 'High', 'deadline': '48 Hours', 'deadline_ar': '48 ساعة', 'owner': 'Operator',
        'actions': ['Inspect affected area', 'Repair irrigation line', 'Check pest activity'],
        'actions_ar': ['معاينة البقع المتضررة (حددوها بطبقة NDVI على الخريطة)', 'إصلاح خط الري الفرعي المتضرر', 'فحص نشاط الآفات'],
        'success': 'NDVI variance decreases.', 'success_ar': 'انخفاض تباين NDVI داخل الحديقة.'},
    # added for the platform's other diagnoses
    'heat_stress': {
        'priority': 'High', 'deadline': '1 Week', 'deadline_ar': 'أسبوع', 'owner': 'Operator',
        'actions': ['Move irrigation to night / early morning', 'Add short extra cycles during heat waves',
                    'Mulch exposed beds to keep soil cool', 'Shade or relocate heat-sensitive species'],
        'actions_ar': ['نقل الري إلى الليل أو الفجر لتقليل الفقد بالتبخر', 'إضافة دورات ري قصيرة أثناء موجات الحر',
                       'تغطية الأحواض المكشوفة بالمَلش (Mulch) لتبريد التربة', 'تظليل الأنواع الحساسة للحرارة أو استبدالها بأنواع متحملة من القائمة المعتمدة'],
        'success': 'Park LST falls and its cooling effect vs surroundings recovers.', 'success_ar': 'انخفاض حرارة سطح الحديقة وعودة فرق التبريد مع محيطها.'},
    'maintenance': {
        'priority': 'Low', 'deadline': '1 Week', 'deadline_ar': 'أسبوع', 'owner': 'Operator',
        'actions': ['Confirm the scheduled maintenance was carried out', 'Re-measure next month'],
        'actions_ar': ['التأكد من تنفيذ أعمال الصيانة المجدولة لهذا الشهر', 'لا تدخل إضافي؛ إعادة القياس الشهر القادم'],
        'success': 'NDVI returns to baseline within 1–2 months.', 'success_ar': 'عودة NDVI إلى خط الأساس خلال 1–2 شهر.'},
    'healthy': {
        'priority': 'Low', 'deadline': '—', 'deadline_ar': '—', 'owner': 'Operator',
        'actions': ['Continue the approved maintenance programme'], 'actions_ar': ['الاستمرار وفق برنامج الصيانة المعتمد'],
        'success': 'NDVI stays near baseline.', 'success_ar': 'بقاء NDVI قرب خط الأساس.'},
    'improving': {
        'priority': 'Low', 'deadline': '—', 'deadline_ar': '—', 'owner': 'Regulator',
        'actions': ['Continue; document what drove the improvement'], 'actions_ar': ['الاستمرار وتوثيق ما أدى للتحسن لتعميمه'],
        'success': 'Continued rise.', 'success_ar': 'استمرار الارتفاع.'},
}
_DEFAULT = {'priority': 'Medium', 'deadline': '72 Hours', 'deadline_ar': '72 ساعة', 'owner': 'Operator',
            'actions': ['Schedule field inspection'], 'actions_ar': ['جدولة زيارة ميدانية شاملة لتحديد السبب'],
            'success': 'Root cause identified.', 'success_ar': 'تحديد السبب الجذري ميدانيًا.'}
# platform diagnosis name -> notebook rule name
DIAGNOSIS_ALIASES = {'waterlogging': 'water_logging', 'patchy_damage': 'localized_damage'}


def _types(tree_type):
    """tree_type: None (all groups), a group name, a list, or the park's species list
    (scientific/Arabic names from the approved plant list, comma separated)."""
    if not tree_type:
        return list(_PROGRAMME)
    items = tree_type if isinstance(tree_type, (list, tuple)) else str(tree_type).replace('،', ',').split(',')
    out, recognised = [], False
    try:
        from plant_catalog import parse_species
    except ImportError:  # notebook use without the catalog
        parse_species = lambda _x: []
    for t in (x.strip() for x in items if str(x).strip()):
        key = t if t in _PROGRAMME else _TYPE_ALIASES.get(t.lower())
        if not key:
            sp = parse_species(t)
            if sp:
                recognised = True
                key = sp[0]['type'] if sp[0]['type'] in _PROGRAMME else None  # succulents have no Appendix-6 programme
        if key:
            recognised = True
            if key not in out:
                out.append(key)
    return out if recognised else list(_PROGRAMME)


def maintenance_engine(tree_type, diagnosis, confidence, month=None):
    """Same signature as the notebook. tree_type may be one type, a list, or None (= all plant groups)."""
    if month is None:
        month = datetime.now().month
    types = _types(tree_type)
    routine, routine_ar = [], []
    for t in types:
        for en, ar in zip(MONTHLY_MAINTENANCE[t].get(month, []), MONTHLY_MAINTENANCE_AR[t].get(month, [])):
            label = en if len(types) == 1 else f'{en} ({t})'
            if label not in routine:
                routine.append(label)
                routine_ar.append(ar if len(types) == 1 else f'{ar} ({_TYPE_AR[t]})')
    ai = AI_RULES.get(DIAGNOSIS_ALIASES.get(diagnosis, diagnosis), _DEFAULT)
    return MaintenancePlan(
        diagnosis=diagnosis, priority=ai['priority'], deadline=ai['deadline'], owner=ai['owner'], confidence=confidence,
        scheduled_maintenance=routine, ai_recommendations=list(ai['actions']), success_indicator=ai['success'],
        priority_ar=_P_AR.get(ai['priority'], ''), deadline_ar=ai['deadline_ar'], owner_ar=_O_AR.get(ai['owner'], ''),
        scheduled_maintenance_ar=routine_ar, ai_recommendations_ar=list(ai['actions_ar']), success_indicator_ar=ai['success_ar'],
        month=month, tree_types=types)


_TYPE_AR = {'Palm': 'نخيل', 'Tree': 'أشجار', 'Shrub': 'شجيرات', 'GroundCover': 'مغطيات تربة', 'Lawn': 'نجيل'}


def ndvi_drop_activities(month, tree_type=None):
    """Scheduled activities this month that can briefly lower NDVI (used by the diagnosis step)."""
    return [(a[0], a[1]) for t in _types(tree_type) for a in _PROGRAMME[t] if month in a[2] and a[3] == 'down']


if __name__ == '__main__':
    plan = maintenance_engine(tree_type='Palm', diagnosis='water_stress', confidence='High', month=8)
    print(plan)
