"""Turns RAWAA numbers into plain-language information (Arabic first).
Each park gets: a one-line headline, a short story (what is happening, why, what next, what to do, how sure),
and the city gets a briefing. Numbers are translated into words; the exact figures stay one click away."""
from __future__ import annotations

def _cover(ndvi):
    if ndvi is None: return 'غير معروف'
    if ndvi < 0.1: return 'شبه خالية من الخضرة (ممرات وتربة في الغالب)'
    if ndvi < 0.2: return 'خضرة خفيفة'
    if ndvi < 0.35: return 'خضرة متوسطة'
    if ndvi < 0.5: return 'خضرة جيدة'
    return 'خضرة كثيفة'

def _trend(chg):
    if chg is None: return 'لا يمكن الحكم بعد'
    if chg >= 10: return 'تحسّن واضح عن المعتاد'
    if chg > -5: return 'مستقرة قرب مستواها الطبيعي'
    if chg > -10: return 'تراجع طفيف ضمن التذبذب الطبيعي'
    if chg > -20: return 'تراجع واضح عن مستواها الطبيعي'
    return 'تراجع حاد عن مستواها الطبيعي'

_EVIDENCE_WORDS = {
    'ndmi': ('رطوبة أوراق النبات', 'أقل', 'أعلى'), 'ndwi': ('الماء على السطح', 'أقل', 'أكثر'),
    'ndre': ('الكلوروفيل (لون الأوراق وتغذيتها)', 'أضعف', 'أقوى'), 'salinity': ('مؤشر الملوحة', 'أقل', 'أعلى'),
    'ndvi_std': ('التفاوت بين أجزاء الحديقة', 'أقل', 'أكبر'), 'lst': ('حرارة سطح الحديقة', 'أقل', 'أعلى'),
}

def _evidence_sentences(ins):
    out = []
    for e in ins.get('evidence', []):
        if e['verdict'] != 'bad' or e['key'] in ('ndvi', 'cooling'): continue
        w = _EVIDENCE_WORDS.get(e['key'])
        if not w: continue
        ref = e.get('reference') or ''
        strong = any(s in ref for s in ('+2', '-2', '+3', '-3', '+4', '-4', '+5', '-5'))
        lower = '-' in ref.split('الانحراف')[-1] if 'الانحراف' in ref else False
        direction = w[1] if lower else w[2]
        out.append(f"{w[0]} {direction} من المعتاد لهذه الحديقة{' بوضوح' if strong else ''}")
    cool = next((e for e in ins.get('evidence', []) if e['key'] == 'cooling'), None)
    if cool and cool['verdict'] == 'bad':
        out.append('الحديقة فقدت جزءًا من قدرتها على تبريد الحي المحيط بها')
    return out

_WHY = {
    'water_stress': 'والمؤشرات تتوافق مع نقص الماء لدى النبات، والفحص الميداني وحده يحدد إن كان السبب في الري أم غيره',
    'waterlogging': 'والمؤشرات تتوافق مع وجود ماء زائد (تسرب أو ري زائد أو ضعف تصريف محتمل)، ويحتاج ذلك تأكيدًا ميدانيًا',
    'salinity': 'وقد تكون الملوحة سببًا (تربة أو مياه ري مالحة)، وهذا يحتاج قياسًا ميدانيًا للتأكد',
    'nutrition': 'والمؤشرات تتوافق مع ضعف في التغذية، لأن الرطوبة طبيعية بينما لون الأوراق ضعف؛ يُؤكَّد ميدانيًا',
    'patchy_damage': 'والتراجع في أجزاء محددة من الحديقة وليس فيها كلها؛ سببه (خط ري فرعي أو آفة أو غيره) يُحدَّد بالفحص الميداني',
    'heat_stress': 'والمؤشرات تتوافق مع إجهاد حراري: الحديقة أسخن من المعتاد وتبرّد محيطها أقل',
    'maintenance': 'وغالبًا هذا أثر مؤقت لأعمال صيانة مجدولة هذا الشهر (تقليم أو تهوية أو استبدال)، ويُتوقع أن تتعافى',
    'unexplained': 'ولا تكفي بيانات القمر الصناعي وحدها لمعرفة السبب، فهي تحتاج زيارة ميدانية',
}
_CONF = {'high': 'والمؤشرات متسقة بدرجة جيدة (والسبب يُؤكَّد ميدانيًا)', 'medium': 'بثقة متوسطة', 'low': 'لكن الثقة منخفضة'}

def _within(d):
    return {'أسبوعان': 'أسبوعين'}.get(d, d)

def _parks(n):
    return {1: 'حديقة واحدة', 2: 'حديقتان'}.get(n, f'{n} حدائق' if 3 <= n <= 10 else f'{n} حديقة')

def park_story(area):
    ins = area.get('insight') or {}
    name = area.get('name_ar', '')
    dx = ins.get('diagnosis')
    if dx == 'insufficient' or not dx:
        return {'headline_ar': 'لم تُجمع قراءات كافية بعد',
                'story_ar': [f'لا يمكن الحكم على {name} حتى تتوفر 3 قراءات شهرية صافية على الأقل. اضغطوا «جلب قراءات فضائية».'],
                'tone': 'muted', 'action_ar': 'جلب القراءات الفضائية'}
    m = area.get('metrics', {})
    chg = ins.get('change_pct'); ndvi = m.get('current_ndvi')
    f = ins.get('forecast') or {}
    recs = ins.get('recommendations') or []
    plan = ins.get('maintenance_plan') or {}
    story = []
    # 1. what is happening
    story.append(f"{name} فيها {_cover(ndvi)}، وحالتها الآن: {_trend(chg)}.")
    # 2. why
    ev = _evidence_sentences(ins)
    if dx in ('healthy', 'improving'):
        story.append('كل المؤشرات الأخرى (الرطوبة، الماء، الكلوروفيل، الحرارة) ضمن المعتاد لهذه الحديقة، فلا توجد علامة على مشكلة.')
    else:
        s = ('لاحظنا أن ' + '، و'.join(ev) + '؛ ') if ev else ''
        story.append(s + _WHY.get(dx, '') + f" ({_CONF.get(ins.get('confidence'), '')}).")
    # 3. what next
    if f.get('available'):
        risk = f.get('risk_pct') or 0
        word = 'مرتفع' if risk >= 60 else 'متوسط' if risk >= 30 else 'منخفض'
        dir_ = {'declining': 'تواصل التراجع', 'improving': 'تتحسن', 'stable': 'تبقى مستقرة'}[f['direction']]
        if f['direction'] == 'stable' and dx not in ('healthy', 'improving'): dir_ = 'تبقى عند مستواها الحالي دون أن تتعافى وحدها'
        story.append(f"خلال الأشهر الثلاثة القادمة نتوقع أن {dir_}، واحتمال أن تصل لمستوى يستدعي الإنذار {word}.")
    # 4. what to do
    if dx in ('healthy', 'improving'):
        story.append('المطلوب: الاستمرار على برنامج الصيانة المعتاد' + (f"، وأعمال هذا الشهر: {'، '.join(plan.get('scheduled_maintenance_ar', [])[:3])}." if plan.get('scheduled_maintenance_ar') else '.'))
        action = 'لا يلزم تدخل'
    else:
        first = recs[0]['action_ar'] if recs else ''
        story.append(f"المطلوب أولًا خلال {_within(plan.get('deadline_ar', '—'))}: {first.rstrip('.')}." + (f" وعلامة نجاح التدخل: {plan.get('success_indicator_ar')}" if plan.get('success_indicator_ar') else ''))
        action = first
    ml = ins.get('ml') or {}
    if ml.get('trained') and not ml.get('agrees') and ml.get('predictions'):
        story.append(f"تنبيه: النموذج المدرَّب على سجلات الأمانة يرجّح سببًا آخر ({ml['predictions'][0]['label_ar']})، فتحقّقوا من الاحتمالين ميدانيًا.")
    tone = {'healthy': 'good', 'improving': 'good', 'maintenance': 'info'}.get(dx, 'bad' if (ins.get('risk_score') or 0) >= 60 else 'warn')
    headline = {'healthy': 'سليمة ولا تحتاج تدخلًا', 'improving': 'تتحسن', 'maintenance': 'تراجع مؤقت متوقع بسبب الصيانة'}.get(dx, ins.get('title_ar', ''))
    return {'headline_ar': headline, 'story_ar': story, 'tone': tone, 'action_ar': action}


def city_briefing(areas):
    ready = [a for a in areas if (a.get('insight') or {}).get('diagnosis') not in (None, 'insufficient')]
    waiting = [a for a in areas if a not in ready]
    problems = sorted([a for a in ready if a['insight']['diagnosis'] not in ('healthy', 'improving', 'maintenance')],
                      key=lambda a: -(a['insight'].get('risk_score') or 0))
    healthy = [a for a in ready if a['insight']['diagnosis'] in ('healthy', 'improving')]
    maint = [a for a in ready if a['insight']['diagnosis'] == 'maintenance']
    risky = [a for a in ready if ((a['insight'].get('forecast') or {}).get('risk_pct') or 0) >= 60]
    lines = []
    if not ready:
        return {'headline_ar': 'لا توجد قراءات كافية بعد', 'lines_ar': ['اجلبوا القراءات الفضائية للحدائق لتظهر الخلاصة.'], 'priorities': [], 'tone': 'muted'}
    parts = [f"{len(healthy)} سليمة", f"{len(problems)} تحتاج تدخلًا"] + ([f"{len(maint)} تراجعها مؤقت بسبب الصيانة"] if maint else []) + ([f"{len(waiting)} بانتظار قراءات كافية"] if waiting else [])
    lines.append(f"من أصل {len(areas)} مواقع مرصودة: " + '، '.join(parts) + '.')
    if problems:
        causes = {}
        for a in problems: causes[a['insight']['title_ar']] = causes.get(a['insight']['title_ar'], 0) + 1
        top = sorted(causes.items(), key=lambda x: -x[1])
        lines.append('أكثر المشكلات تكرارًا: ' + '، '.join(f"{k} ({v})" for k, v in top[:3]) + '.')
        lines.append(f"الأولوية القصوى: {problems[0]['name_ar']}، {problems[0]['insight']['title_ar']}.")
    else:
        lines.append('لا توجد حديقة تحتاج تدخلًا عاجلًا الآن.')
    if risky:
        lines.append('حدائق يُتوقع أن تتراجع خلال 3 أشهر وتستحق فحصًا وقائيًا: ' + '، '.join(a['name_ar'] for a in risky[:4]) + '.')
    hot = [a for a in ready if any(e['key'] == 'cooling' and e['verdict'] == 'bad' for e in a['insight'].get('evidence', []))]
    if hot:
        lines.append('حدائق ضعف دورها في تبريد الحي: ' + '، '.join(a['name_ar'] for a in hot[:4]) + '.')
    pri = [{'id': a['id'], 'name_ar': a['name_ar'], 'title_ar': a['insight']['title_ar'],
            'action_ar': (a['insight'].get('recommendations') or [{}])[0].get('action_ar', ''),
            'deadline_ar': _within((a['insight'].get('maintenance_plan') or {}).get('deadline_ar', ''))} for a in problems[:3]]
    tone = 'bad' if problems and (problems[0]['insight'].get('risk_score') or 0) >= 60 else 'warn' if problems else 'good'
    n = len(problems)
    headline = (f"{_parks(n)} {'تحتاجان' if n == 2 else 'تحتاج'} تدخلًا") if problems else 'الحدائق المرصودة بحالة جيدة'
    return {'headline_ar': headline, 'lines_ar': lines, 'priorities': pri, 'tone': tone}
