/* RAWAA intelligence UI: diagnosis → forecast → maintenance plan (Maintenance Engine), each explaining its own numbers. */
const DX_TONE={healthy:'good',improving:'good',maintenance:'info',insufficient:'muted',water_stress:'bad',waterlogging:'bad',patchy_damage:'bad',unexplained:'bad',salinity:'warn',nutrition:'warn',heat_stress:'bad'};
const CONF_AR={high:'مرتفعة',medium:'متوسطة',low:'منخفضة'};
const PRI_AR={high:'عالية',medium:'متوسطة',low:'منخفضة'};
const GLOSSARY=[
 ['NDVI','كثافة الغطاء النباتي وصحته','Vegetation density & vigour','(B8 − B4)/(B8 + B4)','أقل من 0.1 تربة/ممرات · 0.2–0.4 غطاء متوسط · أعلى من 0.5 غطاء كثيف وسليم','<0.1 soil/paths · 0.2–0.4 moderate · >0.5 dense, healthy'],
 ['NDMI','رطوبة أوراق النبات','Leaf water content','(B8 − B11)/(B8 + B11)','انخفاضه عن معتاد الحديقة يعني عطشًا (إجهاد مائي)','A drop below the park’s usual means thirst'],
 ['NDWI','الماء المكشوف والتربة المشبعة','Open water / saturated soil','(B3 − B8)/(B3 + B8)','ارتفاعه فوق المعتاد يعني تجمع مياه أو تسربًا','A rise above usual suggests ponding or leaks'],
 ['NDRE','الكلوروفيل والتغذية','Chlorophyll / nutrition','(B8A − B5)/(B8A + B5)','انخفاضه مع رطوبة طبيعية يشير لنقص تغذية','A drop with normal moisture suggests nutrient deficiency'],
 ['SI','مؤشر ملوحة تقريبي','Approximate salinity index','√(B2 × B4)','يرتفع مع القشور الملحية والتربة المكشوفة؛ يحتاج تأكيدًا بقياس EC','Rises with salt crusts/bare soil; confirm with EC'],
 ['LST','حرارة سطح الأرض (°م)','Land-surface temperature','Landsat 8/9 B10 + emissivity','ارتفاعها عن المعتاد لنفس الوقت من السنة يعني أن النبات يفقد قدرته على التبريد','Above the usual for this time of year = losing evaporative cooling'],
 ['Δ°','تأثير التبريد','Cooling effect','LST المحيط − LST الحديقة','كم درجة الحديقة أبرد من حزام عمراني ~300 م حولها؛ تراجعه علامة إجهاد حراري','How much cooler the park is than a ~300 m urban belt around it'],
 ['σ','الانحراف المعياري','Standard deviation','—','مقدار التذبذب المعتاد لقراءات الحديقة؛ الابتعاد 1σ أو أكثر عن المعتاد يُعد ملحوظًا','Usual fluctuation; ≥1σ away is notable'],
];
function glossaryBlock(){return `<details class="ins-details"><summary>${icon('info',15)} ${ar()?'دليل قراءة الأرقام':'Reading these numbers'}</summary><div class="glossary">${GLOSSARY.map(g=>`<div class="gl-row"><b>${g[0]}</b><div><span>${ar()?g[1]:g[2]}</span><code>${g[3]}</code><small>${ar()?g[4]:g[5]}</small></div></div>`).join('')}</div></details>`}

function diagnosisCard(a){const i=a?.insight;if(!i)return '';const tone=DX_TONE[i.diagnosis]||'muted';
 if(i.diagnosis==='insufficient')return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">1</span><div><small>${ar()?'التشخيص':'Diagnosis'}</small><h3>${ar()?i.title_ar:i.title_en}</h3></div></div><p class="ins-sum">${ar()?i.summary_ar:i.summary_en}</p>${glossaryBlock()}</div>`;
 const rows=i.evidence.map(e=>`<tr class="v-${e.verdict}"><td><b>${esc(ar()?e.label_ar:e.label_en)}</b></td><td class="num">${e.value===null?'—':e.value}</td><td class="ref">${esc(e.reference||'')}</td><td><span class="verdict ${e.verdict}">${e.verdict==='bad'?(ar()?'غير طبيعي':'abnormal'):e.verdict==='good'?(ar()?'جيد':'good'):(ar()?'طبيعي':'normal')}</span></td></tr><tr class="why"><td colspan="4">${esc(ar()?e.why_ar:e.why_en)}</td></tr>`).join('');
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">1</span><div><small>${ar()?'التشخيص · الوضع الحالي':'Diagnosis · current state'}</small><h3 class="tone-${tone}">${ar()?i.title_ar:i.title_en}</h3></div><span class="conf conf-${i.confidence}">${ar()?'الثقة: '+CONF_AR[i.confidence]:'Confidence: '+i.confidence}</span></div>
 <p class="ins-sum">${esc(ar()?i.summary_ar:i.summary_en)}</p>
 <div class="table-wrap"><table class="ev-table"><thead><tr><th>${ar()?'المؤشر':'Index'}</th><th>${ar()?'القيمة':'Value'}</th><th>${ar()?'مقارنة بمعتاد الحديقة':'vs park’s usual'}</th><th>${ar()?'الحكم':'Verdict'}</th></tr></thead><tbody>${rows}</tbody></table></div>
 ${i.alternatives?.length?`<p class="ins-alt"><b>${ar()?'احتمالات أخرى:':'Other possibilities:'}</b> ${i.alternatives.map(x=>esc(ar()?x.title_ar:x.title_en)).join(' · ')}</p>`:''}
 ${(ar()?i.notes_ar:i.notes_en)?.length?`<ul class="ins-notes">${(ar()?i.notes_ar:i.notes_en).map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:''}
${mlBlock(i)}
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'طريقة التشخيص':'Diagnosis method'}</summary><p>${esc(ar()?i.method_ar:i.method_en)}</p><p class="muted">${ar()?'نافذة المقارنة':'Comparison window'}: ${esc(i.data_quality?.history_window||'—')} · ${ar()?'عدد القراءات الصالحة':'valid readings'}: ${i.data_quality?.n} · ${ar()?'صفاء آخر قراءة':'last clear-sky share'}: ${i.data_quality?.latest_valid_pct}%</p></details>
 ${glossaryBlock()}</div>`}

function forecastSvg(a,f){const hist=(a.metrics.observations||[]).filter(o=>Number.isFinite(o.ndvi)&&o.valid_pixels_pct>=60).slice(-9);if(!hist.length)return '';
 const pts=[...hist.map(o=>({d:o.measured_at,v:o.ndvi})),...f.points.map(p=>({d:p.date,v:p.ndvi,lo:p.low,hi:p.high,f:1}))];
 const vals=pts.flatMap(p=>[p.v,p.lo,p.hi]).filter(Number.isFinite).concat(f.threshold??[]);const mn=Math.min(...vals)-0.02,mx=Math.max(...vals)+0.02;
 const W=560,H=190,L=34,R=10,T=12,B=28,x=i=>L+i*(W-L-R)/(pts.length-1),y=v=>T+(mx-v)/(mx-mn)*(H-T-B);
 const h=hist.length-1,fi=pts.map((p,i)=>i).filter(i=>i>=h);
 const band=`M${x(h)},${y(pts[h].v)} `+fi.slice(1).map(i=>`L${x(i)},${y(pts[i].hi)}`).join(' ')+' '+fi.slice(1).reverse().map(i=>`L${x(i)},${y(pts[i].lo)}`).join(' ')+` L${x(h)},${y(pts[h].v)}Z`;
 const ticks=[mn+0.02,(mn+mx)/2,mx-0.02];
 return `<svg class="fc-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="NDVI forecast">${ticks.map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="2" y="${y(v)+4}" class="tick">${v.toFixed(2)}</text>`).join('')}
 <path d="${band}" class="band"/>${f.threshold!=null?`<line x1="${L}" x2="${W-R}" y1="${y(f.threshold)}" y2="${y(f.threshold)}" class="thr"/><text x="${W-R}" y="${y(f.threshold)-5}" text-anchor="end" class="thr-t">${ar()?'حد الإنذار':'alert line'} ${f.threshold}</text>`:''}
 <polyline points="${pts.slice(0,h+1).map((p,i)=>`${x(i)},${y(p.v)}`).join(' ')}" class="hist"/><polyline points="${fi.map(i=>`${x(i)},${y(pts[i].v)}`).join(' ')}" class="fc"/>
 ${pts.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" class="${p.f?'fcp':'hp'}"><title>${p.d.slice(0,7)} · NDVI ${p.v.toFixed(3)}${p.f?` (${p.lo}–${p.hi})`:''}</title></circle>`).join('')}
 ${pts.map((p,i)=>i%2===0||p.f?`<text x="${x(i)}" y="${H-8}" text-anchor="middle" class="tick">${p.d.slice(2,7)}</text>`:'').join('')}</svg>
 <div class="fc-legend"><span><i class="lg-h"></i>${ar()?'قراءات فعلية':'observed'}</span><span><i class="lg-f"></i>${ar()?'متوقع':'forecast'}</span><span><i class="lg-b"></i>${ar()?'نطاق ثقة 95%':'95% range'}</span><span><i class="lg-t"></i>${ar()?'حد الإنذار (85% من خط الأساس)':'alert line (85% of baseline)'}</span></div>`}

function forecastCard(a){const i=a?.insight,f=i?.forecast;if(!i)return '';
 if(!f?.available)return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">2</span><div><small>${ar()?'التنبؤ':'Forecast'}</small><h3>${ar()?'لا يتوفر تنبؤ بعد':'No forecast yet'}</h3></div></div><p class="ins-sum">${esc(ar()?f?.reason_ar:f?.reason_en)}</p></div>`;
 const lvl=f.risk_level,dir={declining:ar()?'تراجع':'declining',improving:ar()?'تحسّن':'improving',stable:ar()?'استقرار':'stable'}[f.direction];
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">2</span><div><small>${ar()?'التنبؤ · الأشهر الثلاثة القادمة':'Forecast · next 3 months'}</small><h3>${ar()?'الاتجاه: ':'Trend: '}${dir}</h3></div><span class="risk risk-${lvl}">${ar()?'خطر التراجع':'Decline risk'} <b>${f.risk_pct??'—'}%</b></span></div>
 ${forecastSvg(a,f)}
 <div class="fc-points">${f.points.map(p=>`<div><span>${ar()?p.month_ar:p.date.slice(0,7)}</span><b>${p.ndvi.toFixed(2)}</b><small>${p.low.toFixed(2)} – ${p.high.toFixed(2)}</small></div>`).join('')}</div>
 <p class="ins-sum">${esc(ar()?f.explain_ar:f.explain_en)}</p>
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'طريقة حساب التنبؤ (مقارنة النماذج)':'Calculation method (model comparison)'}</summary><p>${ar()?`جُرّبت عدة نماذج على آخر ${f.test_months} أشهر (كأنها مستقبل لم يُرَ) واختير صاحب أقل خطأ. البيانات: ${f.months_used} شهرًا من Sentinel-2. نطاق الثقة من أخطاء النموذج السابقة (الانحراف ${f.residual_sd}). احتمال الخطر = احتمال أن تقع قيمة الشهر الثالث تحت حد الإنذار.`:`Several models were tested on the last ${f.test_months} months; the most accurate was chosen. ${f.months_used} months of Sentinel-2 data.`}</p>
 <table class="ev-table lb"><thead><tr><th>${ar()?'النموذج':'Model'}</th><th>${ar()?'متوسط الخطأ (MAE)':'MAE'}</th><th></th></tr></thead><tbody>${(f.leaderboard||[]).map(m=>`<tr class="${m.chosen?'chosen':''}"><td>${esc(ar()?m.label_ar:m.label_en)}</td><td class="num">${m.mae.toFixed(4)}</td><td>${m.chosen?`<span class="verdict good">${ar()?'المُختار':'chosen'}</span>`:''}</td></tr>`).join('')}</tbody></table></details></div>`}

function planCard(a){const i=a?.insight,p=i?.maintenance_plan;if(!p)return '';const reg=S.user?.role==='regulator';
 const canAlert=reg&&!['healthy','improving','insufficient','maintenance'].includes(i.diagnosis);
 const monthName=ar()?(typeof MONTHS_AR!=='undefined'?MONTHS_AR[p.month-1]:p.month):p.month;
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">3</span><div><small>${ar()?'خطة التدخل والصيانة':'Intervention & maintenance plan'}</small><h3>${ar()?'محرك الصيانة':'Maintenance Engine'}</h3></div></div>
 <div class="plan-meta"><div><span>${ar()?'الأولوية':'Priority'}</span><b class="pri-${(p.priority||'').toLowerCase()}">${ar()?p.priority_ar:p.priority}</b></div><div><span>${ar()?'المهلة':'Deadline'}</span><b>${esc(ar()?p.deadline_ar:p.deadline)}</b></div><div><span>${ar()?'المسؤول':'Owner'}</span><b>${esc(ar()?p.owner_ar:p.owner)}</b></div><div><span>${ar()?'الثقة':'Confidence'}</span><b>${ar()?CONF_AR[i.confidence]||'—':p.confidence}</b></div></div>
 <h4>${icon('wrench',15)} ${ar()?'الإجراءات الموصى بها':'Recommended actions'}</h4>
 <ol class="plan-list">${(i.recommendations||[]).map(r=>`<li>${esc(ar()?r.action_ar:r.action_en)} <span class="chip pri-${r.priority}">${ar()?PRI_AR[r.priority]:r.priority}</span> <span class="plan-time">${esc(ar()?r.timeframe_ar:r.timeframe_en)}</span></li>`).join('')}</ol>
 <div class="success-ind">${icon('check-circle',15)} <b>${ar()?'مؤشر النجاح:':'Success indicator:'}</b> ${esc(ar()?p.success_indicator_ar:p.success_indicator)}</div>
 <h4>${icon('calendar',15)} ${ar()?`الصيانة المجدولة لشهر ${monthName} (البرنامج المعتمد – الملحق 6)`:`Scheduled maintenance this month (Appendix 6)`}</h4>
 ${(ar()?p.scheduled_maintenance_ar:p.scheduled_maintenance).length?`<ul class="sched">${(ar()?p.scheduled_maintenance_ar:p.scheduled_maintenance).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:`<p class="muted">${ar()?'لا توجد أعمال مجدولة':'Nothing scheduled'}</p>`}
 ${!a.plants?`<p class="muted" style="font-size:12px">${ar()?'نوع النباتات غير محدد لهذه الحديقة، فعُرضت أعمال كل الفئات. حدّدوه لتصبح الخطة أدق.':'Plant type not set, so all groups are shown.'}</p>`:''}
 ${canAlert?`<div style="margin-top:14px">${btn(ar()?'إنشاء تنبيه بهذه الخطة':'Create alert with this plan','scan',{primary:true,icon:'bell-plus'})}<p class="muted" style="font-size:12px;margin:6px 0 0">${ar()?'عند تحويل التنبيه لمهمة تُنسخ الإجراءات ومؤشر النجاح إلى ملاحظات المهمة تلقائيًا.':'When the alert becomes a task, actions and the success indicator are copied into it.'}</p></div>`:''}
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'مصدر الخطة':'Source of the plan'}</summary><p>${ar()?'يأخذ محرك الصيانة التشخيص ودرجة ثقته ونوع النباتات والشهر الحالي، ويُخرج الأولوية والمهلة والمسؤول والإجراءات ومؤشر النجاح من قواعد مكتوبة مسبقًا، ويضيف أعمال الشهر من برنامج الصيانة المعتمد. هي قواعد واضحة قابلة للمراجعة وليست نموذجًا مدرَّبًا.':'The engine maps diagnosis, confidence, plant type and month to priority, deadline, owner, actions and a success indicator via explicit rules, plus this month’s approved programme. Rules, not a trained model.'}</p></details></div>`}

function insightSection(a){if(!a?.insight)return '';return `<div class="section-row"><div><h3>${ar()?'التحليل الذكي لهذه الحديقة':'Intelligence for this park'}</h3><small>${ar()?'تشخيص ← تنبؤ ← خطة تدخل، وكل رقم مشروح':'Diagnosis → forecast → plan, every number explained'}</small></div></div><div class="ins-grid">${diagnosisCard(a)}${forecastCard(a)}${planCard(a)}</div>`}

function prioritiesTable(){const rows=(S.data.areas||[]).filter(a=>a.insight).slice().sort((x,y)=>(y.insight.risk_score||0)-(x.insight.risk_score||0));if(!rows.length)return '';
 return `<div class="section-row"><div><h3>${ar()?'أولويات التدخل':'Intervention priorities'}</h3><small>${ar()?'مرتبة حسب درجة الخطر (0–100) التي تجمع شدة التشخيص ونسبة التراجع واحتمال التراجع المتوقع':'Ranked by risk score (0–100): diagnosis severity + decline + forecast risk'}</small></div></div>
 <div class="surface table-wrap"><table class="data-table prio"><thead><tr><th>${ar()?'الحديقة':'Park'}</th><th>${ar()?'الخطر':'Risk'}</th><th>${ar()?'التشخيص':'Diagnosis'}</th><th>${ar()?'الثقة':'Confidence'}</th><th>${ar()?'توقع 3 أشهر':'3-month risk'}</th><th>${ar()?'أول إجراء':'First action'}</th><th></th></tr></thead><tbody>
 ${rows.map(a=>{const i=a.insight,f=i.forecast||{},r=(i.recommendations||[])[0];return `<tr><td class="strong-name">${esc(areaLabel(a))}</td><td><div class="risk-bar"><i style="width:${i.risk_score||0}%" class="${(i.risk_score||0)>=60?'hi':(i.risk_score||0)>=30?'md':'lo'}"></i></div><small>${i.risk_score||0}</small></td><td class="tone-${DX_TONE[i.diagnosis]||'muted'}">${esc(ar()?i.title_ar:i.title_en)}</td><td>${ar()?CONF_AR[i.confidence]||'—':i.confidence}</td><td>${f.available?f.risk_pct+'%':'—'}</td><td style="white-space:normal;max-width:280px">${r?esc(ar()?r.action_ar:r.action_en):'—'}</td><td>${btn(t('areaDetails'),'open-area',{id:a.id})}</td></tr>`}).join('')}
 </tbody></table></div><p class="muted" style="font-size:12px;margin:8px 2px">${ar()?'درجة الخطر = شدة التشخيص × 18 + نسبة التراجع × 0.8 + احتمال التراجع المتوقع × 0.25 (بحد أقصى 100). التشخيص تمهيدي ويحتاج تحققًا ميدانيًا.':'Risk = severity×18 + decline%×0.8 + forecast risk×0.25 (max 100). Provisional; verify in the field.'}</p>`}

/* Approved plant list: which species grow in this park (drives the maintenance programme and the diagnosis notes). */
const IRR_CLASS={1:'lo',1.5:'lo',2:'md',2.5:'hi',3:'hi'};
function speciesBlock(a){const sp=a?.insight?.species||[],sum=a?.insight?.species_summary,reg=S.user?.role==='regulator';
 return `<div class="species-block"><div class="kpi-line"><span>${t('plantType')}</span>${reg?btn(ar()?'تحديد النباتات':'Set plants','edit-plants',{icon:'sprout'}):''}</div>
 ${sp.length?`<div class="sp-chips">${sp.map(p=>`<span class="sp-chip" title="${esc(p.scientific)} · ${esc(p.category_ar)}">${esc(ar()?p.name_ar:p.scientific)} <i class="irr ${IRR_CLASS[{'Low':1,'Low–medium':1.5,'Medium':2,'Medium–high':2.5,'High':3}[p.irrigation_en]]}">${ar()?'ري '+esc(p.irrigation_ar):esc(p.irrigation_en)}</i>${p.coastal?`<i class="irr coast">${ar()?'ساحلي/ملحي':'coastal'}</i>`:''}</span>`).join('')}</div>
 ${sum?`<p class="muted" style="font-size:12px;margin:6px 0 0">${ar()?`${sum.count} نوعًا · أعلى احتياج للري: ${({'Low':'منخفض','Low–medium':'منخفض–متوسط','Medium':'متوسط','Medium–high':'متوسط–مرتفع','High':'مرتفع'})[sum.max_irrigation]}. تُستخدم الأنواع لاختيار برنامج الصيانة وتفسير التشخيص.`:`${sum.count} species · highest water need: ${sum.max_irrigation}.`}</p>`:''}`
 :`<p class="muted" style="font-size:12px;margin:6px 0 0">${ar()?'لم تُحدَّد نباتات هذه الحديقة بعد. تحديدها من القائمة المعتمدة يجعل خطة الصيانة والتشخيص أدق.':'No species set yet; setting them makes the plan and diagnosis more precise.'}</p>`}</div>`}
let PLANT_CACHE=null;
async function plantsModal(){const a=selectedArea();if(!a)return;if(!PLANT_CACHE)PLANT_CACHE=await api('/plants');
 const chosen=new Set((a.insight?.species||[]).map(p=>p.scientific));const groups={};PLANT_CACHE.forEach(p=>(groups[p.category_ar]=groups[p.category_ar]||[]).push(p));
 openModal(`${modalHeader(ar()?'نباتات الحديقة':'Park plants',ar()?'اختاروا الأنواع المزروعة فعلًا من القائمة المعتمدة. بجانب كل نوع احتياجه الاسترشادي للري.':'Pick the species actually planted, from the approved list.')}
 <form id="plants-form" class="plants-form">${Object.entries(groups).map(([g,list])=>`<fieldset><legend>${esc(g)}</legend>${list.map(p=>`<label class="sp-opt"><input type="checkbox" name="sp" value="${esc(p.scientific)}" ${chosen.has(p.scientific)?'checked':''}/> <span><b>${esc(p.name_ar)}</b> <small>${esc(p.scientific)}</small><small>${esc(p.use_ar)} · ري ${esc(p.irrigation_ar)}</small></span></label>`).join('')}</fieldset>`).join('')}
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}

/* "!" info tips: every number explains itself (hover, keyboard focus, or tap). */
const _f=v=>Number.isFinite(v)?Number(v).toFixed(2):'—';
const TIPS={
 lastRead:a=>ar()?'تاريخ التقاط أوضح مشهد Sentinel-2 في ذلك الشهر. القراءات القديمة المجمّعة على 30 يومًا تبدأ من هذا التاريخ.':'Acquisition date of the clearest Sentinel-2 scene that month. Older 30-day composite readings start on this date.',
 status:a=>ar()?'الحالة تُحسب بمقارنة آخر قراءة بخط الأساس: «مستقر» إذا كان التغير أقل من −10%، «متابعة» من −10% إلى −20%، و«خطر مرتفع» إذا بقي التراجع −20% أو أكثر في آخر قراءتين. «بيانات غير كافية» تعني أقل من 3 قراءات صالحة.':'Stable if change > −10%; Monitor −10% to −20%; High if ≤ −20% in the last two readings; Insufficient if < 3 valid readings.',
 latest:a=>ar()?`قيمة NDVI لآخر قراءة (${_f(a?.metrics?.current_ndvi)}). NDVI يقيس كثافة النبات الأخضر وصحته من −1 إلى 1: أقل من 0.1 تربة أو ممرات، 0.2–0.4 غطاء متوسط، أعلى من 0.5 كثيف وسليم. الرقم متوسط لكل مساحة الحديقة بما فيها الممرات والمباني.`:'Latest NDVI (vegetation density/vigour, −1 to 1): <0.1 soil/paths, 0.2–0.4 moderate, >0.5 dense. Averaged over the whole park.',
 baseline:a=>ar()?`القيمة الطبيعية لهذه الحديقة (${_f(a?.metrics?.baseline)}): الوسيط لقراءاتها السابقة دون آخر قراءتين. نقارن كل حديقة بنفسها لأن الحدائق تختلف في نباتاتها وكثافتها.`:'This park’s normal value: median of its earlier readings (excluding the last two).',
 change:a=>ar()?`الفرق بين آخر قراءة وخط الأساس كنسبة مئوية (${a?.metrics?.change_pct??'—'}%). السالب يعني تراجعًا. التراجع أقل من 10% يُعد تذبذبًا طبيعيًا، و10% أو أكثر إشارة تحتاج تفسيرًا.`:'Percent difference between latest reading and baseline. Under −10% is normal fluctuation.',
 quality:a=>ar()?'نسبة مساحة الحديقة التي كانت صافية (بلا غيوم أو ظلال غيوم أو ماء) في آخر قراءة. 80% فأكثر موثوقة، و60–80% محدودة، وأقل من 60% تُستبعد.':'Share of the park that was clear (no cloud/shadow/water) in the latest reading: ≥80% reliable, 60–80% limited, under 60% excluded.',
 source:a=>ar()?'مصدر البيانات: القمر الصناعي الأوروبي Sentinel-2 بالمستوى L2A (مصحّح من تأثير الغلاف الجوي) عبر Copernicus Data Space، بدقة 10 أمتار. «غير تجريبية» تعني قراءات فضائية حقيقية.':'Sentinel-2 L2A (atmosphere-corrected) via Copernicus Data Space, 10 m. Real satellite data.',
 NDMI:a=>ar()?'مؤشر رطوبة أوراق النبات (B8−B11)/(B8+B11). انخفاضه عن معتاد الحديقة قد يدل على عطش أو ضعف ري، ويُؤكَّد ذلك ميدانيًا.':'Leaf moisture; a drop can indicate water stress, to be confirmed in the field.',
 NDRE:a=>ar()?'مؤشر الكلوروفيل والتغذية (B8A−B5)/(B8A+B5). انخفاضه مع رطوبة طبيعية يشير لنقص تسميد.':'Chlorophyll/nutrition; a drop with normal moisture suggests nutrient deficiency.',
 SAVI:a=>ar()?'مثل NDVI لكنه يقلل تأثير التربة المكشوفة، فيفيد في الحدائق قليلة الكثافة.':'Like NDVI but reduces bare-soil influence.',
 NDWI:a=>ar()?'مؤشر الماء (B3−B8)/(B3+B8). ارتفاعه فوق المعتاد قد يدل على تجمّع مياه أو تسرب أو تشبع التربة.':'Water index; a rise suggests ponding or leaks.',
 SI:a=>ar()?'مؤشر ملوحة تقريبي √(B2×B4) يرتفع مع القشور الملحية والتربة المكشوفة. يحتاج تأكيدًا بقياس ملوحة التربة (EC).':'Approximate salinity index; confirm with soil EC.',
 LST:a=>ar()?'حرارة سطح الحديقة من Landsat 8/9 (°م) مصححة بالانبعاثية؛ تُقارن بالمعتاد لنفس الوقت من السنة.':'Landsat surface temperature.',
 STD:a=>ar()?'مدى اختلاف NDVI بين أجزاء الحديقة. ارتفاعه قد يعني أن بعض الأجزاء تتدهور بينما غيرها سليم (مثل عطل خط ري فرعي).':'NDVI variability inside the park; a rise can mean patchy damage.',
 allAreas:a=>ar()?'عدد الحدائق والمواقع المسجلة في المنصة.':'Number of monitored sites.',
 stableC:a=>ar()?'حدائق تراجعها عن خط الأساس أقل من 10%.':'Sites with decline under 10%.',
 monitorC:a=>ar()?'حدائق تراجعت 10%–20% عن خط الأساس وتستحق المتابعة.':'Sites with a 10–20% decline.',
 highC:a=>ar()?'حدائق تراجعت 20% أو أكثر في آخر قراءتين، وأولوية للتحقق الميداني.':'Sites down 20%+ in the last two readings.',
};
function tip(key,a){const f=TIPS[key];if(!f)return '';const text=f(a);return `<button type="button" class="tip" data-action="tip" aria-label="${esc(text)}" data-tip="${esc(text)}">!</button>`}

/* Learning model: shown inside the diagnosis card. */
function mlBlock(i){const m=i.ml;if(!m)return '';
 if(!m.trained){const pct=Math.min(100,Math.round(100*(m.labels||0)/(m.min_labels||10)));return `<div class="ml-box"><b>${icon('cpu',15)} ${ar()?'النموذج المدرَّب':'Trained model'}</b><p>${esc(m.reason_ar||'')}</p><div class="progress" style="margin-top:6px"><div style="width:${pct}%"></div></div><small class="muted">${ar()?`${m.labels} من ${m.min_labels} سجلات مؤكدة. التشخيص الحالي من القواعد الشفافة.`:`${m.labels}/${m.min_labels} confirmed records.`}</small></div>`}
 const p=m.predictions||[];return `<div class="ml-box"><b>${icon('cpu',15)} ${ar()?'رأي النموذج المدرَّب على سجلات الأمانة':'Model trained on confirmed records'}</b>
 <div class="ml-preds">${p.map((x,k)=>`<div class="${k===0?'top':''}"><span>${esc(ar()?x.label_ar:x.label_en)}</span><i style="width:${x.probability}%"></i><b>${x.probability}%</b></div>`).join('')}</div>
 <p class="${m.agrees?'tone-good':'tone-warn'}" style="font-size:12px;margin:8px 0 4px">${m.agrees?`${icon('check-circle',14)} ${ar()?'النموذج يتفق مع تشخيص القواعد.':'Agrees with the rules.'}`:`${icon('triangle-alert',14)} ${ar()?'النموذج يرجّح سببًا مختلفًا عن القواعد؛ يُنصح بالتحقق الميداني من الاحتمالين.':'Model disagrees with the rules; verify both in the field.'}`}</p>
 <small class="muted">${ar()?`تدرّب على ${m.labels} سجلًا مؤكدًا · دقة التحقق المتقاطع ${m.cv_accuracy??'—'}% مقابل ${m.rules_accuracy??'—'}% للقواعد على نفس السجلات · أهم العوامل: ${(m.importances||[]).map(x=>esc(x.label_ar)).join('، ')}`:`Trained on ${m.labels} records · CV accuracy ${m.cv_accuracy??'—'}% vs rules ${m.rules_accuracy??'—'}%`}</small></div>`}

/* Heat stress list for the intelligence page. */
function heatRows(){const rows=(S.data.areas||[]).map(a=>({a,th:(a.thermal||[]).filter(x=>Number.isFinite(x.lst_park)).at(-1),i:a.insight})).filter(x=>x.th);
 if(!rows.length)return `<div class="empty"><b>${ar()?'لا توجد قراءات حرارية بعد':'No thermal readings yet'}</b>${ar()?'اضغطوا «جلب قراءات فضائية» في صفحة الحديقة؛ ويجلب الزر حرارة السطح من Landsat 8/9 أيضًا (دقة 30–100 م).':'Sync a park; the sync also fetches Landsat 8/9 surface temperature.'}</div>`;
 rows.sort((x,y)=>((x.th.lst_ring??x.th.lst_park)-x.th.lst_park)-((y.th.lst_ring??y.th.lst_park)-y.th.lst_park));
 return `<p>${ar()?'حرارة سطح كل حديقة من Landsat 8/9 ومقدار تبريدها لمحيطها العمراني (~300 م). الأقل تبريدًا في الأعلى.':'Park surface temperature and cooling vs ~300 m surroundings; least cooling first.'}</p>`+rows.map(({a,th,i})=>{const c=Number.isFinite(th.lst_ring)?th.lst_ring-th.lst_park:null;return `<div class="analysis-row"><div><b>${esc(areaLabel(a))}</b><p>LST ${th.lst_park.toFixed(1)}°م${c!==null?` · ${ar()?'أبرد من محيطها بـ':'cooler by'} <b class="${c<1?'tone-bad':'tone-good'}">${c.toFixed(1)}°م</b>`:''} · ${esc(th.measured_at.slice(0,7))}${i?.diagnosis==='heat_stress'?` · <span class="tone-bad">${ar()?'إجهاد حراري محتمل':'probable heat stress'}</span>`:''}</p></div>${btn(t('areaDetails'),'open-area',{id:a.id})}</div>`}).join('')}

/* Municipality records & training (reports page, regulator). */
let MODEL_CACHE=null;
async function loadModel(){try{MODEL_CACHE=await api('/model');const el=document.getElementById('model-panel');if(el)el.outerHTML=modelPanel()}catch(e){}}
function modelPanel(){const m=MODEL_CACHE;if(!m)return `<div id="model-panel" class="surface ins-card"><p class="muted">${ar()?'جارٍ تحميل حالة النموذج…':'Loading model…'}</p></div>`;
 return `<div id="model-panel" class="surface ins-card"><div class="ins-head"><span class="ins-step">${icon('cpu',16)}</span><div><small>${ar()?'التعلّم من سجلات الأمانة':'Learning from municipality records'}</small><h3>${m.trained?(ar()?'النموذج مدرَّب':'Model trained'):(ar()?'النموذج لم يتدرّب بعد':'Not trained yet')}</h3></div></div>
 <div class="plan-meta"><div><span>${ar()?'سجلات مؤكدة':'Confirmed records'}</span><b>${m.labels}</b></div><div><span>${ar()?'دقة النموذج (تحقق متقاطع)':'Model CV accuracy'}</span><b>${m.cv_accuracy!=null?m.cv_accuracy+'%':'—'}</b></div><div><span>${ar()?'دقة القواعد على نفس السجلات':'Rules accuracy'}</span><b>${m.rules_accuracy!=null?m.rules_accuracy+'%':'—'}</b></div><div><span>${ar()?'الأسباب المسجلة':'Causes'}</span><b>${Object.keys(m.classes||{}).length}</b></div></div>
 ${m.trained?'':`<p class="ins-sum">${esc(m.reason_ar||'')}</p>`}
 ${Object.keys(m.classes||{}).length?`<p class="muted" style="font-size:12px">${Object.entries(m.classes).map(([k,v])=>`${esc((m.class_names_ar||{})[k]||k)}: ${v}`).join(' · ')}</p>`:''}
 <p style="font-size:12px;line-height:1.9">${ar()?'مصادر التدريب: (1) عند إغلاق مهمة يختار المشغّل «السبب المؤكد» فيُحفظ تلقائيًا، (2) استيراد سجلات الأمانة كملف CSV. كل سجل يُربط بقراءات القمر الصناعي للحديقة في ذلك التاريخ، ثم يُقارن النموذج بالقواعد على السجلات نفسها، وبهذه المقارنة يُتحقق من نتائج المنصة مقابل نتائج الأمانة.':'Sources: tasks closed with a confirmed cause, and imported municipality CSV records.'}</p>
 ${btn(ar()?'استيراد سجلات الأمانة (CSV)':'Import municipality records (CSV)','import-labels',{primary:true,icon:'file-up'})}</div>`}
function labelsModal(){const causes=MODEL_CACHE?.causes||{};openModal(`${modalHeader(ar()?'استيراد سجلات الأمانة':'Import municipality records',ar()?`الأعمدة: site (اسم الحديقة بالعربي أو الإنجليزي أو رقمها)، date (YYYY-MM-DD)، cause، notes. قيم cause المقبولة: ${Object.keys(causes).join(', ')}`:'Columns: site, date, cause, notes')}
 <form id="labels-form"><textarea name="csv_text" required style="min-height:170px">site,date,cause,notes\nحديقة الهدى,2026-06-15,water_stress,عطل في مضخة الري\nPrince Majid Park,2026-03-10,maintenance,تهوية النجيل</textarea>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}
const CAUSE_OPTS=[['water_stress','إجهاد مائي / نقص ري'],['waterlogging','تشبع مائي / تسرب'],['salinity','ملوحة'],['nutrition','نقص تغذية'],['patchy_damage','تلف موضعي (عطل خط ري/آفة)'],['heat_stress','إجهاد حراري'],['maintenance','أثر صيانة مجدولة'],['healthy','لا توجد مشكلة'],['other','سبب آخر']];

/* Plain-language information: city briefing (dashboard) and park story (area page). */
function briefingCard(){const b=S.data?.briefing;if(!b)return '';
 return `<div class="surface brief tone-box-${b.tone}"><div class="brief-head">${icon(({good:'check-circle',warn:'circle-alert',bad:'triangle-alert'})[b.tone]||'info',20)}<div><small>${ar()?'ملخص حالة حدائق جدة':'Jeddah parks briefing'}</small><h3>${esc(b.headline_ar)}</h3></div></div>
 <ul class="brief-lines">${b.lines_ar.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>
 ${b.priorities?.length?`<div class="brief-pri"><b>${ar()?'ما يجب فعله هذا الأسبوع:':'This week:'}</b>${b.priorities.map((p,k)=>`<div class="brief-row"><span class="brief-n">${k+1}</span><div><b>${esc(p.name_ar)}</b> · ${esc(p.title_ar)}<small>${esc(p.action_ar)}${p.deadline_ar?` · ${ar()?'خلال':'within'} ${esc(p.deadline_ar)}`:''}</small></div>${btn(t('areaDetails'),'open-area',{id:p.id})}</div>`).join('')}</div>`:''}</div>`}
function storyCard(a){const st=a?.insight?.story;if(!st)return '';
 return `<div class="surface brief tone-box-${st.tone}"><div class="brief-head">${icon('message-square-text',20)}<div><small>${ar()?'الخلاصة بلغة بسيطة':'In plain words'}</small><h3>${esc(st.headline_ar)}</h3></div></div>
 <div class="story">${st.story_ar.map(p=>`<p>${esc(p)}</p>`).join('')}</div>
 <small class="muted">${ar()?'الأرقام والأدلة التفصيلية في بطاقات التحليل أسفل الصفحة.':'Details and evidence are in the cards below.'}</small></div>`}
