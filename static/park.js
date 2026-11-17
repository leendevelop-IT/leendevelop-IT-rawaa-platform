/* RAWAA — park details page.
   Above the fold: status card (priority, two-line summary, why-chips, suggested action), four KPI cards,
   NDVI trend + 30-day outlook, map and a compact boundary card. Everything else (plain-language story, reasons,
   indices, model comparison, legacy diagnosis/plan, site data, maintenance programme) lives in the
   "View full analysis" side panel, so no information is lost. Presentation only. */
function parkPage(a){const id=a.id,c=PM.area[id]||PM.stale.area[id],reg=S.user.role==='regulator';if(!PM.area[id])setTimeout(()=>pmLoadArea(id),0);
 return `<div class="rw rw-park">${parkHead(a,reg)}${c?parkHero(a,c,reg)+parkKpis(a,c):parkSkeleton()}
 ${c?parkTrend(c):`<section class="rw-card rw-trend">${skel('30%',16,'margin:20px')}${skel('auto',250,'margin:0 20px 20px')}</section>`}
 <div class="rw-pair">${c?parkBoundary(a,c,reg):`<section class="rw-card rw-bcard">${skel('40%',16)}${skel('30%',30,'margin-top:16px')}${skel('100%',8,'margin-top:16px')}</section>`}<section class="rw-card rw-map-card"><div id="area-map" class="map-box rw-map"></div></section></div>
 <p class="rw-foot">${rwIcon('info',14)}<span>${L2('صور الأقمار الصناعية تكشف تراجع الغطاء النباتي ولا تحدد سببه؛ يُؤكَّد السبب بالفحص الميداني. المصدر: Copernicus Sentinel-2 L2A.','Satellite images reveal vegetation decline but not its cause; confirm the cause in the field. Source: Copernicus Sentinel-2 L2A.')}</span></p>
 ${drawerSlot()}</div>`}

/* In-place refresh used when fresh data arrives: everything is re-rendered except the map card, whose Leaflet map
   is kept alive (rebuilding it during its zoom animation makes Leaflet throw, and it would flicker). */
function softRenderPark(){const cur=document.querySelector('.rw-park'),a=selectedArea();if(!cur||!a||S.view!=='area'){render();return}
 const body=document.querySelector('#rw-drawer .rw-dr-body'),top=body?body.scrollTop:0;
 const tpl=document.createElement('template');tpl.innerHTML=parkPage(a).trim();const fresh=tpl.content.firstElementChild;
 const oldMap=cur.querySelector('.rw-map-card'),newMap=fresh.querySelector('.rw-map-card');if(oldMap&&newMap)newMap.replaceWith(oldMap);
 cur.replaceWith(fresh);const nb=document.querySelector('#rw-drawer .rw-dr-body');if(nb&&top)nb.scrollTop=top}

function parkHead(a,reg){const role=ar()?a.role_ar:a.role_en;
 const cat=a.category==='Validation site'?L2('موقع تحقق ميداني','Field validation site'):a.category==='Case study'?L2('دراسة حالة','Case study'):esc(a.category||'');
 const sub=`<span class="rw-sub" title="${esc(role||'')}">${cat}${role?` · ${esc(role)}`:''}</span>`;
 const actions=`<button type="button" class="btn" data-action="back-areas">${rwIcon(ar()?'chevR':'chevL',15)} ${t('areas')}</button>${reg?`<button type="button" class="btn primary" data-action="sync">${icon('satellite-dish',15)} ${t('sync')}</button>`:''}${rwMenu([
  reg&&{label:t('importCsv'),action:'import',icon:'file-up'},
  {label:L2('سجل القراءات ومصدر كل قراءة','Readings & provenance'),action:'pm-readings',id:a.id,icon:'database'},
  {label:L2('فتح في Copernicus Browser','Open in Copernicus Browser'),href:copernicusBrowserUrl(a,'ndvi'),icon:'sat'},
  reg&&{label:L2('تحديد نباتات الحديقة','Set park plants'),action:'edit-plants',icon:'leaf'}])}`;
 return heading(esc(areaLabel(a)),sub,actions)}

function parkSkeleton(){return `<section class="rw-card rw-hero n">${skel('150px',28)}${skel('72%',20,'margin-top:18px')}${skel('48%',20,'margin-top:10px')}${skel('100%',58,'margin-top:20px')}</section>
 <div class="rw-kpis">${`<div class="rw-card rw-kpi">${skel('45%',12)}${skel('55%',30,'margin-top:8px')}${skel('85%',12,'margin-top:auto')}</div>`.repeat(4)}</div>`}

function heroCta(a,reg){const al=(S.data.alerts||[]).find(x=>x.area_id===a.id&&x.status==='new'),tk=(S.data.tasks||[]).find(x=>x.area_id===a.id&&x.status!=='closed');
 if(tk)return `<button type="button" class="btn" data-view="tasks">${icon('clipboard-list',15)} ${L2('مهمة','Task')} #${tk.id} · ${esc(t(tk.status))}</button>`;
 if(al&&reg)return `<button type="button" class="btn primary" data-action="assign" data-id="${al.id}">${icon('clipboard-list',15)} ${L2('إسناد مهمة للمقاول','Assign to contractor')}</button>`;
 if(al)return `<span class="rw-flag warn">${icon('bell',14)}<span>${L2('تنبيه مفتوح','Open alert')}</span></span>`;
 return ''}

function parkHero(a,c,reg){const d=c.intel.decision,m=PRI[d.priority]||PRI.insufficient,rel=REL[d.reliability]||REL.low;
 const top=`${pill(d.priority,'lg')}<span class="rw-flag">${rwIcon('shield',14)}<span>${L2('موثوقية','Reliability')} ${L2(rel[0],rel[1])}</span></span>${d.provisional&&d.priority!=='insufficient'?`<span class="rw-flag warn">${rwIcon('pin',14)}<span>${L2('نتيجة مبدئية · الحدود غير معتمدة','Provisional · boundary not approved')}</span></span>`:''}`;
 return `<section class="rw-card rw-hero ${m.cls}"><div class="rw-hero-top">${top}<span class="rw-grow"></span><button type="button" class="btn rw-open" data-action="pm-drawer-open" data-id="${a.id}">${rwIcon('panel',16)} ${L2('عرض التحليل الكامل','View full analysis')}</button></div>
 <p class="rw-hero-summary">${rwSummary(d)}</p>${chipsHtml(rwWhy(d))}
 <div class="rw-action"><span class="rw-action-ic">${icon('wrench',17)}</span><div class="rw-grow"><small>${L2('الإجراء المقترح','Suggested action')}</small><b>${esc(rwShortAction(d))}</b></div>${heroCta(a,reg)}</div></section>`}

function kpi(label,tipText,main,sub){return `<div class="rw-card rw-kpi"><div class="rw-kpi-label">${label}${tipText?rwTip(tipText):''}</div>${main}<div class="rw-kpi-sub">${sub}</div></div>`}
function parkKpis(a,c){const d=c.intel.decision,s=c.intel.schedule,cur=d.current,prev=d.previous,ser=c.intel.series||[],rs=c.intel.readings_summary,legacy=!cur&&Number.isFinite(a.metrics?.current_ndvi);
 const k1=kpi(L2('NDVI الحالي','Current NDVI'),L2('NDVI لأحدث التقاط Sentinel-2 موثوق داخل حدود الحديقة، متوسطًا على كامل مساحتها بما فيها الممرات. أقل من 0.1 تربة وممرات، 0.2–0.35 خضرة متوسطة، وأعلى من 0.5 خضرة كثيفة.','NDVI of the latest trusted Sentinel-2 acquisition, averaged over the whole park. <0.1 soil/paths, 0.2–0.35 moderate, >0.5 dense.'),
  `<div class="rw-kpi-main"><span class="rw-kpi-value">${cur?num(cur.ndvi):legacy?num(a.metrics.current_ndvi):'—'}</span>${rwSpark(ser.map(x=>x.ndvi))}</div>`,
  cur?`<span class="rw-tag a">${L2('قراءة فعلية','Actual')}</span>${dlong(cur.date)}`:legacy?`<span class="rw-tag n">${L2('غير موثّقة','Unverified')}</span>${L2('لا تُستخدم في القرار','not used for decisions')}`:L2('لا توجد قراءة موثوقة بعد','No trusted reading yet'));
 const an=d.anomaly_pct,cls=an==null?'':an<=-10?'bad':an<0?'warn':an>=10?'good':'';
 const k2=kpi(d.baseline_kind==='seasonal'?L2('التغير عن المتوقع موسميًا','Change vs seasonal norm'):L2('التغير عن المعتاد','Change vs usual level'),L2('الفرق بين القراءة الحالية والقيمة المتوقعة لنفس الشهر في الأعوام السابقة، أو وسيط القراءات الأخيرة إن لم يتوفر عام سابق. تراجع 10% أو أكثر إشارة تستحق المتابعة.','Difference between the current reading and the value expected for the same month in earlier years (or the recent median if no prior year exists). A drop of 10% or more warrants follow-up.'),
  `<span class="rw-kpi-value ${cls}">${an==null?'—':`${rwIcon(an<0?'arrowDown':'arrowUp',22)}<bdi dir="ltr">${Math.abs(an).toFixed(1)}%</bdi>`}</span>`,
  an==null?L2('يلزم 4 قراءات موثوقة على الأقل','Needs at least 4 trusted readings'):`${L2('المتوقع','Expected')} ${num(d.expected_ndvi)}<span class="rw-sep">·</span>${L2('السابقة','Previous')} ${prev?num(prev.ndvi):'—'}`);
 const q=cur?.valid_pixels_pct,qc=q==null?'':q>=80?'':q>=60?'f':'u';
 const k3=kpi(L2('جودة البيانات','Data quality'),L2('نسبة بكسلات الحديقة الصافية (بلا غيوم أو ظلال أو ماء) في القراءة الحالية: 80% فأكثر موثوقة، 60–80% محدودة، وأقل من 60% تُستبعد. هي نسبة البيانات الصالحة، وليست نسبة دقة التحليل.','Share of clear park pixels (no cloud, shadow or water) in the current reading: ≥80% reliable, 60–80% limited, <60% excluded. This is valid-data share, not analysis accuracy.'),
  `<span class="rw-kpi-value">${q==null?'—':`<bdi dir="ltr">${Math.round(q)}%</bdi>`}</span><div class="rw-meter" role="img" aria-label="${q==null?'':Math.round(q)+'%'}"><i class="${qc}" style="width:${q||0}%"></i><em style="inset-inline-start:60%"></em><em style="inset-inline-start:80%"></em></div>`,
  `${L2('موثوقية','Reliability')} ${L2((REL[d.reliability]||REL.low)[0],(REL[d.reliability]||REL.low)[1])}<span class="rw-sep">·</span><bdi dir="ltr">${rs.used}/${rs.total}</bdi> ${L2('قراءة مستخدمة','readings used')}`);
 const k4=kpi(L2('الأولوية','Priority'),'',`<div class="rw-kpi-pill">${pill(d.priority,'lg')}</div>`,
  !s?L2('لا يوجد موعد متابعة بعد','No follow-up date yet'):s.status==='done'?`${L2('إعادة التقييم','Reassess')} <b>${dshort(s.reassess_at)}</b><span class="rw-sep">·</span>${L2('تم الفحص','inspected')}`
  :`${L2('الفحص القادم','Next check')} <b>${dshort(s.next_check)}</b><span class="rw-sep">·</span><span class="${s.overdue?'rw-bad':''}">${relDay(s.next_check)}</span>`);
 return `<div class="rw-kpis">${k1}${k2}${k3}${k4}</div>`}

function parkTrend(c){const d=c.intel.decision,f=c.intel.forecast,h=f.available?Object.fromEntries(f.horizons.map(z=>[z.days,z])):{},rel=REL[f.confidence]||REL.low;
 let tiles;
 if(f.available){const p=f.decline_probability_pct;
  const third=p!=null?`<div class="rw-fc-tile ${p>=50?'bad':''}"><small>${L2('احتمال استمرار التراجع','Chance decline continues')}</small><b>${pct(p)}</b><span>${L2('ثقة','Confidence')} ${L2(rel[0],rel[1])} · ${L2('أدق من المرجع','beats naive by')} <bdi dir="ltr">${f.backtest.skill_pct}%</bdi></span></div>`
   :`<div class="rw-fc-tile"><small>${L2('ثقة التوقع','Forecast confidence')}</small><b class="t">${L2(rel[0],rel[1])}</b><span>${f.backtest.beats_naive?`${L2('أدق من النموذج المرجعي بـ','Beats the naive reference by')} <bdi dir="ltr">${f.backtest.skill_pct}%</bdi>`:L2('لا يتفوّق على النموذج المرجعي بعد','Does not beat the naive reference yet')}</span></div>`;
  tiles=`<div class="rw-fc-tiles">${[7,30].map(k=>`<div class="rw-fc-tile"><small><i class="lg f"></i>${L2(`بعد ${k} ${k===7?'أيام':'يومًا'}`,`In ${k} days`)}</small><b>${num(h[k].ndvi)}</b><span>${rng(h[k].low80,h[k].high80)} · ${L2('نطاق','range')} ${pct(80)}</span></div>`).join('')}${third}</div>`}
 else tiles=`<div class="rw-fc-none">${rwIcon('info',16)}<span>${esc(ar()?f.reason_ar:f.reason_en)}</span></div>`;
 return `<section class="rw-card rw-trend"><div class="rw-card-head"><div><h3>${L2('اتجاه NDVI والتوقع','NDVI trend & outlook')}</h3><p>${L2('القراءات الفعلية الموثوقة وتوقع الثلاثين يومًا القادمة','Trusted actual readings and the next-30-day outlook')}</p></div>${chartLegend(d.expected_ndvi!=null,d.baseline_kind)}</div>
 ${rwChart(c.intel.series,f,d.expected_ndvi,{expLabel:expLabel(d),w:1200,h:280,fit:fitPage})}${tiles}</section>`}

function parkBoundary(a,c,reg){const b=c.bnd,v=b.validation||{},st=BND[b.status]||['n','—','—'],vf=b.vegetated_fraction,vp=vf!=null?Math.round(vf*100):null;
 const stack=vp!=null?`<div class="rw-stack" role="img" aria-label="${vp}%"><i style="width:${vp}%"></i><i style="width:${100-vp}%"></i></div><div class="rw-stack-legend"><span><i class="lg a"></i>${L2('نباتية','Vegetated')} <bdi dir="ltr">${vp}%</bdi> · ${ha(b.vegetated_area_m2)}</span><span>${L2('غير نباتية','Other')} <bdi dir="ltr">${100-vp}%</bdi></span></div>`
  :`<p class="rw-mini">${L2('تُحسب المساحة النباتية القابلة للتحليل بعد أول مزامنة فضائية.','The analysable vegetated share is computed after the first satellite sync.')}</p>`;
 const note=v.placeholder?`<div class="rw-note">${rwIcon('info',15)}<span>${L2('حدود تقريبية حول موقع الخريطة وقد تشمل شوارع ومباني؛ تُرسم الحدود الفعلية قبل الاعتماد.','Approximate outline around the map pin; may include streets and buildings. Draw the real outline before approval.')}</span></div>`
  :!b.final_results?`<div class="rw-note info">${rwIcon('info',15)}<span>${L2('النتائج مبدئية حتى تعتمد الجهة المخوّلة هذه الحدود.','Results stay provisional until the boundary is approved.')}</span></div>`:'';
 const acts=reg?`<div class="rw-bactions">${b.status!=='approved'?`<button type="button" class="btn primary tiny" data-action="pm-bnd-approve" data-id="${a.id}">${rwIcon('check',14)} ${L2('اعتماد الحدود','Approve boundary')}</button>`:''}${rwMenu([{label:L2('تعديل الحدود (GeoJSON)','Edit boundary (GeoJSON)'),action:'pm-bnd-edit',id:a.id,icon:'pencil'},b.status!=='rejected'&&{label:L2('رفض الحدود','Reject boundary'),action:'pm-bnd-reject',id:a.id,icon:'x',danger:true}])}</div>`:'';
 return `<section class="rw-card rw-bcard"><div class="rw-bhead"><h3>${L2('الحدود والمساحة','Boundary & area')}</h3>${bndPill(b.status)}</div>
 <div class="rw-big"><bdi dir="ltr">${v.area_ha!=null?v.area_ha.toFixed(2):'—'}</bdi><small>${L2('هكتار','ha')}</small></div>${stack}
 <div class="rw-meta"><div><small>${L2('المصدر','Source')}</small><b title="${esc(b.source||'')}">${esc(b.source||'—')}</b></div><div><small>${L2('الإصدار','Version')}</small><b>v${b.version||1}</b></div>
 <div><small>${L2('بكسلات Sentinel-2','Sentinel-2 pixels')}</small><b><bdi dir="ltr">${(v.s2_pixels_10m||0).toLocaleString('en')}</bdi></b></div><div><small>${L2('المحيط','Perimeter')}</small><b><bdi dir="ltr">${v.perimeter_m?Math.round(v.perimeter_m).toLocaleString('en'):'—'}</bdi> ${L2('م','m')}</b></div></div>${note}${acts}</section>`}

/* ---------------------------------------------------------------- full analysis side panel */
const PARK_TABS=[['summary','الملخص','Summary'],['indices','المؤشرات','Indices'],['forecast','التوقع والمتابعة','Forecast'],['diagnosis','التشخيص والخطة','Diagnosis & plan'],['site','الموقع والصيانة','Site & upkeep']];
function parkDrawer(dr){const a=getArea(dr.id),c=PM.area[dr.id]||PM.stale.area[dr.id];if(!a||!c)return null;const tab=dr.tab||'summary';
 const body=({summary:pdSummary,indices:pdIndices,forecast:pdForecast,diagnosis:pdDiagnosis,site:pdSite}[tab]||pdSummary)(a,c);
 return {title:areaLabel(a),html:drawerFrame({eyebrow:L2('التحليل الكامل','Full analysis'),title:esc(areaLabel(a)),badge:pill(c.intel.decision.priority),tabs:PARK_TABS.map(([k,x,y])=>[k,L2(x,y)]),tab,body})}}
const ACT_L={initial:['تسجيل أولي','Initial record'],create:['إنشاء','Created'],update:['تعديل الحدود','Boundary edited'],review:['مراجعة واعتماد','Review']};
const kv2=(label,value,sub='',cls='')=>`<div class="${cls}"><small>${label}</small><b class="t">${value}</b>${sub?`<span>${sub}</span>`:''}</div>`;

function pdSummary(a,c){const d=c.intel.decision,st=a.insight?.story,m=a.metrics;
 return `${st?`<section class="rw-dsec"><h4>${L2('الخلاصة بلغة بسيطة','In plain words')}</h4><p class="rw-lead">${esc(st.headline_ar)}</p>${(st.story_ar||[]).map(p=>`<p>${esc(p)}</p>`).join('')}</section>`:''}
 <section class="rw-dsec"><h4>${L2('سبب التصنيف','Reasons for this status')}</h4><ul class="rw-ul">${(ar()?d.reasons_ar:d.reasons_en).map(r=>`<li>${esc(r)}</li>`).join('')}</ul>${d.season_note_ar&&ar()?`<p class="rw-mini">${esc(d.season_note_ar)}</p>`:''}</section>
 <section class="rw-dsec"><h4>${L2('الإجراء المقترح كاملًا','Suggested action in full')}</h4><p>${esc(ar()?d.action_ar:d.action_en)}</p></section>
 <section class="rw-dsec"><h4>${L2('المقارنة بخط الأساس العام','Comparison with the general baseline')}</h4><div class="rw-kv">
  <div><small>${t('latest')} ${tip('latest',a)}</small><b>${num(m.current_ndvi)}</b><span>${m.latest_date?dlong(m.latest_date):'—'}</span></div>
  <div><small>${t('baseline')} ${tip('baseline',a)}</small><b>${num(m.baseline)}</b></div>
  <div><small>${t('change')} ${tip('change',a)}</small><b>${m.change_pct==null?'—':`<bdi dir="ltr">${m.change_pct}%</bdi>`}</b></div>
  <div><small>${L2('الحالة العامة','General status')} ${tip('status',a)}</small><b class="t">${badge(m.status)}</b></div></div>
  <div class="provenance" style="margin-top:12px">${icon('database',15)} ${esc(m.source||t('empty'))} ${origin(a)} ${tip('source',a)}</div></section>
 ${validationNote(a)}`}

function pdIndices(a,c){const ix=c.intel.decision.indices||[];
 return `<section class="rw-dsec"><h4>${L2('معنى المؤشرات في القراءة الحالية','What the indices mean in the current reading')}</h4>${ix.length?`<div class="rw-ix">${ix.map(i=>`<div class="rw-ix-row"><div class="rw-ix-k"><b>${i.key.toUpperCase()}</b><span class="rw-num">${num(i.value)}</span></div><p>${esc(ar()?i.meaning_ar:i.meaning_en)}</p><code dir="ltr">${esc(i.formula)}</code></div>`).join('')}</div>`:`<p>${L2('لا توجد قراءة موثوقة بعد.','No trusted reading yet.')}</p>`}</section>
 <section class="rw-dsec rw-legacy">${spectralBlock(a)||''}</section>`}

function pdForecast(a,c){const f=c.intel.forecast,s=c.intel.schedule,preds=(c.intel.predictions||[]);let out='';
 if(f.available){const rel=REL[f.confidence]||REL.low;
  out+=`<section class="rw-dsec"><h4>${L2('التوقع (تقدير وليس قياسًا)','Forecast (an estimate, not a measurement)')}</h4><table class="rw-mini-table"><thead><tr><th>${L2('الأفق','Horizon')}</th><th>${L2('التاريخ','Date')}</th><th>NDVI</th><th>80%</th><th>95%</th></tr></thead><tbody>
  ${f.horizons.map(h=>`<tr><td>${L2(`${h.days} ${h.days===7?'أيام':'يومًا'}`,`${h.days} days`)}</td><td>${dshort(h.target_date)}</td><td><b>${num(h.ndvi)}</b></td><td>${rng(h.low80,h.high80)}</td><td>${rng(h.low95,h.high95)}</td></tr>`).join('')}</tbody></table>
  <div class="rw-kv" style="margin-top:12px">${kv2(L2('ثقة التوقع','Confidence'),L2(rel[0],rel[1]),esc(ar()?f.model_ar:f.model_en))}${kv2(L2('مقارنة بالمرجع','Versus naive'),f.backtest.beats_naive?`<bdi dir="ltr">+${f.backtest.skill_pct}%</bdi>`:'—',L2(`على ${f.backtest.origins} اختبارات تاريخية`,`over ${f.backtest.origins} backtests`))}
  ${kv2(L2('احتمال استمرار التراجع','Chance decline continues'),f.decline_probability_pct!=null?pct(f.decline_probability_pct):'—',f.decline_probability_pct!=null?L2('خلال 30 يومًا','within 30 days'):esc(ar()?f.decline_probability_reason_ar||'':f.decline_probability_reason_en||''),'span2')}</div>
  <p class="rw-mini">${esc(ar()?f.explain_ar:f.explain_en)}</p></section>
  <section class="rw-dsec"><h4>${L2('مقارنة النماذج على السجل التاريخي (Backtesting)','Model comparison on history (backtesting)')}</h4><table class="rw-mini-table"><thead><tr><th>${L2('النموذج','Model')}</th><th>MAE</th><th>${L2('مقابل المرجع','vs naive')}</th></tr></thead><tbody>
  ${f.backtest.leaderboard.map(b=>`<tr class="${b.model===f.model?'on':''}"><td>${esc(ar()?b.label_ar:b.label_en)}${b.model===f.model?` <span class="rw-tag a">${L2('المختار','chosen')}</span>`:''}</td><td>${num(b.mae,4)}</td><td><bdi dir="ltr">${b.skill_pct>0?'+':''}${b.skill_pct}%</bdi></td></tr>`).join('')}</tbody></table></section>`}
 else out+=`<section class="rw-dsec"><h4>${L2('التوقع','Forecast')}</h4><p>${esc(ar()?f.reason_ar:f.reason_en)}</p></section>`;
 out+=`<section class="rw-dsec"><h4>${L2('جدولة المتابعة','Monitoring schedule')}</h4>${s?`<div class="rw-kv">${kv2(L2('موعد الفحص','Inspection date'),dlong(s.next_check),`<span class="${s.overdue?'rw-bad':''}">${relDay(s.next_check)}</span>`)}${kv2(L2('الحالة','Status'),schTag(s),s.assignee_id?`${t('operator')} #${s.assignee_id}`:'')}${kv2(L2('إعادة التقييم','Reassessment'),dlong(s.reassess_at),esc(ar()?s.reason_ar:s.reason_en),'span2')}</div>`:`<p>—</p>`}</section>`;
 if(preds.length)out+=`<section class="rw-dsec"><h4>${L2('سجل التوقعات ومقارنتها بالقراءة الفعلية','Forecast log vs actual readings')}</h4><table class="rw-mini-table"><thead><tr><th>${L2('الهدف','Target')}</th><th>${L2('الأفق','Horizon')}</th><th>${L2('التوقع','Forecast')}</th><th>${L2('الفعلي','Actual')}</th><th>${L2('الخطأ','Error')}</th></tr></thead><tbody>
  ${preds.slice(0,10).map(p=>`<tr><td>${dshort(p.target_date)}</td><td>${p.horizon_days}</td><td>${num(p.ndvi_pred)}</td><td>${p.actual_ndvi!=null?num(p.actual_ndvi):`<span class="rw-faint">${L2('بانتظار','pending')}</span>`}</td><td>${p.abs_error!=null?num(p.abs_error):'—'}</td></tr>`).join('')}</tbody></table></section>`;
 return out}

function pdDiagnosis(a){return `<p class="rw-mini" style="margin-top:0">${L2('تحليل تفصيلي بالقواعد الشفافة: تشخيص محتمل يحتاج تأكيدًا ميدانيًا، وتنبؤ ثلاثة أشهر بالطريقة الشهرية، وخطة صيانة من محرك الصيانة.','Detailed transparent-rules analysis: a probable diagnosis needing field confirmation, a 3-month monthly forecast and a maintenance plan.')}</p><div class="rw-legacy">${diagnosisCard(a)}${forecastCard(a)}${planCard(a)}</div>`}

function pdSite(a,c){const b=c.bnd,v=b.validation||{},rs=c.intel.readings_summary,m=a.metrics;
 return `<section class="rw-dsec rw-legacy"><h4>${L2('بيانات الموقع','Site data')}</h4>${speciesBlock(a)}<div class="rw-kv" style="margin-top:12px">${kv2(t('irrigation'),esc(a.irrigation||'—'))}${kv2(t('plantingDate'),esc(a.planting_date||'—'))}${kv2(t('sensorStatus'),m.demo?'DEMO':'USER / SATELLITE')}${kv2(L2('الإحداثيات','Coordinates'),v.centroid?`<bdi dir="ltr">${v.centroid[1]}, ${v.centroid[0]}</bdi>`:'—')}</div></section>
 <section class="rw-dsec"><h4>${L2('الحدود بالتفصيل','Boundary details')}</h4><div class="rw-kv">${kv2(L2('الحالة','Status'),bndPill(b.status),b.reviewed_at?`${L2('آخر مراجعة','Reviewed')} ${dshort(b.reviewed_at)}`:'')}${kv2(L2('المساحة','Area'),ha(v.area_m2),`${v.vertices??'—'} ${L2('رأسًا','vertices')}`)}${kv2(L2('المصدر','Source'),esc(b.source||'—'),`v${b.version||1}`,'span2')}</div>
 ${b.notes?`<p class="rw-mini">${esc(b.notes)}</p>`:''}${(v.warnings||[]).length?`<ul class="rw-ul" style="margin-top:12px">${v.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}
 ${(b.history||[]).length?`<table class="rw-mini-table" style="margin-top:12px"><thead><tr><th>${L2('الإصدار','Version')}</th><th>${L2('الإجراء','Action')}</th><th>${L2('الحالة','Status')}</th><th>${L2('التاريخ','Date')}</th></tr></thead><tbody>${b.history.map(h=>`<tr><td>v${h.version}</td><td>${esc(ACT_L[h.action]?L2(...ACT_L[h.action]):h.action)}</td><td>${BND[h.status]?L2(BND[h.status][1],BND[h.status][2]):esc(h.status)}</td><td>${dshort(h.created_at)}</td></tr>`).join('')}</tbody></table>`:''}</section>
 <section class="rw-dsec"><h4>${L2('القراءات','Readings')}</h4><div class="rw-kv">${kv2(L2('مستخدمة في التحليل','Used in analysis'),`<bdi dir="ltr">${rs.used} / ${rs.total}</bdi>`)}${kv2(L2('غائمة أو غير صالحة','Cloudy / invalid'),rs.unreliable)}${kv2(L2('مستوردة أو يدوية','Imported / manual'),rs.unverified_imported_or_manual,L2('تُعرض ولا تُستخدم','shown, never used'))}${kv2(L2('على حدود سابقة','On an older boundary'),rs.older_boundary_version)}</div>
 <button type="button" class="btn" style="margin-top:12px" data-action="pm-readings" data-id="${a.id}">${icon('database',15)} ${L2('سجل القراءات ومصدر كل قراءة','Readings & provenance')}</button></section>
 <div class="rw-legacy">${copernicusPanel(a)}${maintenancePanel(a)}</div>`}
