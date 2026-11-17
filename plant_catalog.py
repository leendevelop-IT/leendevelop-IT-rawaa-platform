"""Approved plant list for Jeddah landscaping (team PDF): category, Arabic name, scientific name, use, indicative irrigation.
Used by the platform to (1) record which species grow in each park, (2) pick the right maintenance programme,
(3) weigh water-stress findings by the species' water needs, and (4) suggest salt-tolerant replacements."""

# irrigation levels: low=1, low-medium=1.5, medium=2, medium-high=2.5, high=3
_IRR = {'منخفض': 1, 'منخفض–متوسط': 1.5, 'متوسط': 2, 'متوسط–مرتفع': 2.5, 'مرتفع': 3}
_IRR_EN = {1: 'Low', 1.5: 'Low–medium', 2: 'Medium', 2.5: 'Medium–high', 3: 'High'}
CATEGORY_TYPE = {'أشجار': 'Tree', 'نخيل': 'Palm', 'شجيرات': 'Shrub', 'مغطيات تربة': 'GroundCover',
                 'صباريات وعصاريات': 'Succulent', 'مسطحات خضراء': 'Lawn'}

_ROWS = [
 ('أشجار','الكافور الليموني','Eucalyptus citriodora','تشجير مساحات مفتوحة','منخفض–متوسط'),
 ('أشجار','فيكس كبير الأوراق','Ficus macrophylla','ظل في الحدائق والساحات الكبيرة','متوسط–مرتفع'),
 ('أشجار','فيكس نيتيدا','Ficus nitida','أسيجة شجرية وظل','متوسط'),
 ('أشجار','فيكس لسان العصفور','Ficus religiosa','ظل ومواقع مفتوحة','متوسط'),
 ('أشجار','جاكراندا','Jacaranda mimosifolia','أشجار مزهرة للشوارع والحدائق','متوسط'),
 ('أشجار','الزنزلخت / الليلك الهندي','Melia azedarach','ظل وتجميل طرق واسعة','منخفض–متوسط'),
 ('أشجار','الباركنسونيا','Parkinsonia aculeata','تشجير جاف ومناطق مفتوحة','منخفض'),
 ('أشجار','البيلتوفوروم','Peltophorum pterocarpum','أشجار ظل وزهور صفراء','متوسط'),
 ('أشجار','تابيبويا صفراء / ذهبية','Tabebuia aurea','أشجار مزهرة للحدائق والطرق','منخفض–متوسط'),
 ('أشجار','تابيبويا وردية','Tabebuia impetiginosa','أشجار مزهرة للحدائق والشوارع','متوسط'),
 ('أشجار','اللوز الهندي','Terminalia catappa','ظل للواجهات البحرية والحدائق','متوسط'),
 ('أشجار','البورتيا','Thespesia populnea','تشجير ساحلي وأحزمة خضراء','منخفض–متوسط'),
 ('أشجار','كاسيا نودوزا','Cassia nodosa','شجرة مزهرة للحدائق','متوسط'),
 ('أشجار','كاسيا جلوكا','Cassia glauca','أزهار صفراء وتشجير تجميلي','منخفض–متوسط'),
 ('أشجار','بونسيانا ملكية','Delonix regia','ظل ومظهر زهري للشوارع الواسعة','متوسط'),
 ('نخيل','جوز الهند','Cocos nucifera','تنسيق المناطق الساحلية والمنتجعات','مرتفع'),
 ('نخيل','نخيل البلح','Phoenix dactylifera','هوية الشوارع والميادين','متوسط'),
 ('شجيرات','الرغل الملحي','Atriplex halimus','أحواض منخفضة وأسيجة ومواقع مالحة','منخفض'),
 ('شجيرات','أبوتيلون','Abutilon vitifolium','شجيرة مزهرة للحدائق','متوسط'),
 ('شجيرات','الجهنمية الملساء','Bougainvillea glabra','أسيجة ومتسلقات وتجميل الأسوار','منخفض–متوسط'),
 ('شجيرات','الجهنمية','Bougainvillea spectabilis','أسيجة ومتسلقات وتجميل المداخل','منخفض–متوسط'),
 ('شجيرات','سيزالبينيا جيليسي','Caesalpinia gilliesii','كتل مزهرة للمواقع المفتوحة','منخفض–متوسط'),
 ('شجيرات','البندق الهندي / طاووس الزهور','Caesalpinia pulcherrima','شجيرات مزهرة وألوان موسمية','متوسط'),
 ('شجيرات','فرشاة الزجاج','Callistemon citrinus','شجيرة مزهرة للأحواض والأسيجة','متوسط'),
 ('شجيرات','الشمعدان الأصفر','Cassia alata','شجيرة مزهرة وتجميل الحدائق','متوسط'),
 ('شجيرات','الدودونيا','Dodonaea viscosa','أسيجة ومصدات رياح ومناطق قليلة الري','منخفض'),
 ('شجيرات','الهبسكس / الورد الصيني','Hibiscus rosa-sinensis','أسيجة مزهرة وحدائق','متوسط–مرتفع'),
 ('شجيرات','إكسورا','Ixora coccinea','كتل مزهرة ومداخل','متوسط'),
 ('شجيرات','ليلك الهندي','Lagerstroemia indica','شجيرة أو شجرة صغيرة مزهرة','متوسط'),
 ('شجيرات','توبيرا','Pittosporum tobira','أسيجة دائمة الخضرة وتحديد أحواض','متوسط'),
 ('شجيرات','رصاصية زرقاء','Plumbago capensis','أسيجة مزهرة وتغطية حواف','متوسط'),
 ('شجيرات','ورد سنتيفوليا','Rosa centifolia','أحواض ورد وزراعة تجميلية','متوسط–مرتفع'),
 ('شجيرات','تيكوما صفراء','Tecoma stans','شجيرة أو شجرة صغيرة مزهرة','منخفض–متوسط'),
 ('مغطيات تربة','كاريسا كبيرة الثمار','Carissa macrocarpa','أسيجة منخفضة وكتل نباتية','منخفض–متوسط'),
 ('مغطيات تربة','غازانيا','Gazania krebsiana','تغطية منخفضة وأحواض زهور','منخفض–متوسط'),
 ('مغطيات تربة','كرمة الشاطئ','Ipomoea pes-caprae','تغطية رملية وساحلية وتثبيت التربة','منخفض–متوسط'),
 ('مغطيات تربة','موهلنبرجيا','Muhlenbergia dumosa','أعشاب زينة وكتل منخفضة','منخفض–متوسط'),
 ('مغطيات تربة','ثيوم / بنيسيتوم','Pennisetum setaceum','أعشاب زينة في الجزر والأحواض','منخفض–متوسط'),
 ('مغطيات تربة','إكليل الجبل','Rosmarinus officinalis','أحواض عطرية وأسيجة منخفضة','منخفض'),
 ('مغطيات تربة','ويديليا','Wedelia trilobata','غطاء أرضي سريع الانتشار','متوسط'),
 ('صباريات وعصاريات','ورد الصحراء / الأدينيوم','Adenium obesum','نقطة تركيز وأحواض منخفضة الري','منخفض'),
 ('صباريات وعصاريات','أغاف أمريكي','Agave americana','تشكيل صحراوي ونقاط تركيز','منخفض'),
 ('صباريات وعصاريات','أغاف سيزال','Agave sisalana','تشكيل صحراوي وأحواض واسعة','منخفض'),
 ('صباريات وعصاريات','ألوة شجرية','Aloe arborescens','أحواض عصاريات وكتل معمارية','منخفض'),
 ('صباريات وعصاريات','ألوة فيروكس','Aloe ferox','نقطة تركيز بالحدائق الصخرية','منخفض'),
 ('صباريات وعصاريات','تاج الشوك','Euphorbia milii','أحواض زينة ومراكن','منخفض'),
 ('صباريات وعصاريات','بندانس مبرقش','Pandanus veitchii','كتل استوائية ومداخل','متوسط'),
 ('صباريات وعصاريات','جلد النمر / سانسيفيريا','Sansevieria trifasciata','أحواض ونقاط تنسيق محمية','منخفض'),
 ('صباريات وعصاريات','يوكا جلوريوسا','Yucca gloriosa','نقطة تركيز وحدائق قليلة الري','منخفض'),
 ('مسطحات خضراء','نجيل باسبالم (Paspalum)','Paspalum vaginatum','نجيل الحدائق العامة، المسطحات الساحلية والمناطق المفتوحة','مرتفع'),
 ('مسطحات خضراء','نجيل C2000','C2000','الحدائق العامة، المنتزهات، المساحات الخضراء الترفيهية','متوسط'),
]
# Coastal / saline suitability as stated in the list's "use" column
_COASTAL_WORDS = ('ساحل', 'مالحة', 'البحرية')

PLANTS = [{'category_ar': c, 'type': CATEGORY_TYPE[c], 'name_ar': n, 'scientific': s, 'use_ar': u,
           'irrigation_ar': i, 'irrigation_en': _IRR_EN[_IRR[i]], 'irrigation_level': _IRR[i],
           'coastal': any(w in u for w in _COASTAL_WORDS)} for c, n, s, u, i in _ROWS]
BY_SCI = {p['scientific'].lower(): p for p in PLANTS}


def parse_species(text):
    """Return catalog entries named in an area's 'plants' field (scientific or Arabic names, comma separated)."""
    if not text:
        return []
    out = []
    for tok in [t.strip() for t in str(text).replace('،', ',').split(',') if t.strip()]:
        p = BY_SCI.get(tok.lower()) or next((x for x in PLANTS if x['name_ar'] == tok), None)
        if p and p not in out:
            out.append(p)
    return out


def species_summary(species):
    if not species:
        return None
    lv = [p['irrigation_level'] for p in species]
    thirsty = [p for p in species if p['irrigation_level'] >= 2.5]
    return {'count': len(species), 'max_irrigation': _IRR_EN[max(lv)], 'avg_irrigation': round(sum(lv) / len(lv), 2),
            'thirsty_ar': [p['name_ar'] for p in thirsty], 'types': sorted({p['type'] for p in species}),
            'coastal_ready_ar': [p['name_ar'] for p in species if p['coastal']]}


def salt_tolerant(limit=6):
    return [p for p in PLANTS if p['coastal']][:limit]
