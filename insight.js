/* RAWAA intelligence UI: diagnosis → forecast → maintenance plan (Maintenance Engine), each explaining its own numbers. */
const DX_TONE={healthy:'good',improving:'good',maintenance:'info',insufficient:'muted',water_stress:'bad',waterlogging:'bad',patchy_damage:'bad',unexplained:'bad',salinity:'warn',nutrition:'warn'};
const CONF_AR={high:'مرتفعة',medium:'متوسطة',low:'منخفضة'};
const PRI_AR={high:'عالية',medium:'متوسطة',low:'منخفضة'};
const GLOSSARY=[
 ['NDVI','كثافة الغطاء النباتي وصحته','Vegetation density & vigour','(B8 − B4)/(B8 + B4)','أقل من 0.1 تربة/ممرات · 0.2–0.4 غطاء متوسط · أعلى من 0.5 غطاء كثيف وسليم','<0.1 soil/paths · 0.2–0.4 moderate · >0.5 dense, healthy'],
 ['NDMI','رطوبة أوراق النبات','Leaf water content','(B8 − B11)/(B8 + B11)','انخفاضه عن معتاد الحديقة يعني عطشًا (إجهاد مائي)','A drop below the park’s usual means thirst'],
 ['NDWI','الماء المكشوف والتربة المشبعة','Open water / saturated soil','(B3 − B8)/(B3 + B8)','ارتفاعه فوق المعتاد يعني تجمع مياه أو تسربًا','A rise above usual suggests ponding or leaks'],
 ['NDRE','الكلوروفيل والتغذية','Chlorophyll / nutrition','(B8A − B5)/(B8A + B5)','انخفاضه مع رطوبة طبيعية يشير لنقص تغذية','A drop with normal moisture suggests nutrient deficiency'],
 ['SI','مؤشر ملوحة تقريبي','Approximate salinity index','√(B2 × B4)','يرتفع مع القشور الملحية والتربة المكشوفة؛ يحتاج تأكيدًا بقياس EC','Rises with salt crusts/bare soil; confirm with EC'],
 ['σ','الانحراف المعياري','Standard deviation','—','مقدار التذبذب المعتاد لقراءات الحديقة؛ الابتعاد 1σ أو أكثر عن المعتاد يُعد ملحوظًا','Usual fluctuation; ≥1σ away is notable'],
];
function glossaryBlock(){return `<details class="ins-details"><summary>${icon('info',15)} ${ar()?'كيف أقرأ هذه الأرقام؟':'How do I read these numbers?'}</summary><div class="glossary">${GLOSSARY.map(g=>`<div class="gl-row"><b>${g[0]}</b><div><span>${ar()?g[1]:g[2]}</span><code>${g[3]}</code><small>${ar()?g[4]:g[5]}</small></div></div>`).join('')}</div></details>`}

function diagnosisCard(a){const i=a?.insight;if(!i)return '';const tone=DX_TONE[i.diagnosis]||'muted';
 if(i.diagnosis==='insufficient')return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">1</span><div><small>${ar()?'التشخيص':'Diagnosis'}</small><h3>${ar()?i.title_ar:i.title_en}</h3></div></div><p class="ins-sum">${ar()?i.summary_ar:i.summary_en}</p>${glossaryBlock()}</div>`;
 const rows=i.evidence.map(e=>`<tr class="v-${e.verdict}"><td><b>${esc(ar()?e.label_ar:e.label_en)}</b></td><td class="num">${e.value===null?'—':e.value}</td><td class="ref">${esc(e.reference||'')}</td><td><span class="verdict ${e.verdict}">${e.verdict==='bad'?(ar()?'غير طبيعي':'abnormal'):e.verdict==='good'?(ar()?'جيد':'good'):(ar()?'طبيعي':'normal')}</span></td></tr><tr class="why"><td colspan="4">${esc(ar()?e.why_ar:e.why_en)}</td></tr>`).join('');
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">1</span><div><small>${ar()?'التشخيص · ماذا يحدث؟':'Diagnosis · what is happening?'}</small><h3 class="tone-${tone}">${ar()?i.title_ar:i.title_en}</h3></div><span class="conf conf-${i.confidence}">${ar()?'الثقة: '+CONF_AR[i.confidence]:'Confidence: '+i.confidence}</span></div>
 <p class="ins-sum">${esc(ar()?i.summary_ar:i.summary_en)}</p>
 <div class="table-wrap"><table class="ev-table"><thead><tr><th>${ar()?'المؤشر':'Index'}</th><th>${ar()?'القيمة':'Value'}</th><th>${ar()?'مقارنة بمعتاد الحديقة':'vs park’s usual'}</th><th>${ar()?'الحكم':'Verdict'}</th></tr></thead><tbody>${rows}</tbody></table></div>
 ${i.alternatives?.length?`<p class="ins-alt"><b>${ar()?'احتمالات أخرى:':'Other possibilities:'}</b> ${i.alternatives.map(x=>esc(ar()?x.title_ar:x.title_en)).join(' · ')}</p>`:''}
 ${(ar()?i.notes_ar:i.notes_en)?.length?`<ul class="ins-notes">${(ar()?i.notes_ar:i.notes_en).map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:''}
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'كيف وصلنا لهذا التشخيص؟':'How was this diagnosis made?'}</summary><p>${esc(ar()?i.method_ar:i.method_en)}</p><p class="muted">${ar()?'نافذة المقارنة':'Comparison window'}: ${esc(i.data_quality?.history_window||'—')} · ${ar()?'عدد القراءات الصالحة':'valid readings'}: ${i.data_quality?.n} · ${ar()?'صفاء آخر قراءة':'last clear-sky share'}: ${i.data_quality?.latest_valid_pct}%</p></details>
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
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">2</span><div><small>${ar()?'التنبؤ · ماذا سيحدث خلال 3 أشهر؟':'Forecast · next 3 months'}</small><h3>${ar()?'الاتجاه: ':'Trend: '}${dir}</h3></div><span class="risk risk-${lvl}">${ar()?'خطر التراجع':'Decline risk'} <b>${f.risk_pct??'—'}%</b></span></div>
 ${forecastSvg(a,f)}
 <div class="fc-points">${f.points.map(p=>`<div><span>${ar()?p.month_ar:p.date.slice(0,7)}</span><b>${p.ndvi.toFixed(2)}</b><small>${p.low.toFixed(2)} – ${p.high.toFixed(2)}</small></div>`).join('')}</div>
 <p class="ins-sum">${esc(ar()?f.explain_ar:f.explain_en)}</p>
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'كيف حُسب التنبؤ؟':'How is it calculated?'}</summary><p>${ar()?`نموذج ${f.method}: يتابع مستوى المؤشر واتجاهه الشهري مع إخماد الاتجاه تدريجيًا حتى لا يبالغ في الامتداد. نطاق الثقة من أخطاء النموذج السابقة (الانحراف ${f.residual_sd}). احتمال الخطر = احتمال أن تقع قيمة الشهر الثالث تحت حد الإنذار. اختبار الدقة: خطأ النموذج ${f.mae_model} مقابل ${f.mae_naive} للطريقة البسيطة.`:`${f.method}: tracks level and monthly trend, damping the trend. Range from past errors (sd ${f.residual_sd}). Risk = probability month-3 value falls below the alert line. Back-test error ${f.mae_model} vs naive ${f.mae_naive}.`}</p></details></div>`}

function planCard(a){const i=a?.insight,p=i?.maintenance_plan;if(!p)return '';const reg=S.user?.role==='regulator';
 const canAlert=reg&&!['healthy','improving','insufficient','maintenance'].includes(i.diagnosis);
 const monthName=ar()?(typeof MONTHS_AR!=='undefined'?MONTHS_AR[p.month-1]:p.month):p.month;
 return `<div class="surface ins-card"><div class="ins-head"><span class="ins-step">3</span><div><small>${ar()?'خطة التدخل والصيانة · ماذا نفعل؟':'Intervention & maintenance plan · what to do?'}</small><h3>${ar()?'محرك الصيانة':'Maintenance Engine'}</h3></div></div>
 <div class="plan-meta"><div><span>${ar()?'الأولوية':'Priority'}</span><b class="pri-${(p.priority||'').toLowerCase()}">${ar()?p.priority_ar:p.priority}</b></div><div><span>${ar()?'المهلة':'Deadline'}</span><b>${esc(ar()?p.deadline_ar:p.deadline)}</b></div><div><span>${ar()?'المسؤول':'Owner'}</span><b>${esc(ar()?p.owner_ar:p.owner)}</b></div><div><span>${ar()?'الثقة':'Confidence'}</span><b>${ar()?CONF_AR[i.confidence]||'—':p.confidence}</b></div></div>
 <h4>${icon('wrench',15)} ${ar()?'الإجراءات الموصى بها':'Recommended actions'}</h4>
 <ol class="plan-list">${(i.recommendations||[]).map(r=>`<li>${esc(ar()?r.action_ar:r.action_en)} <span class="chip pri-${r.priority}">${ar()?PRI_AR[r.priority]:r.priority}</span> <span class="chip">${esc(ar()?r.timeframe_ar:r.timeframe_en)}</span></li>`).join('')}</ol>
 <div class="success-ind">${icon('circle-check',15)} <b>${ar()?'مؤشر النجاح:':'Success indicator:'}</b> ${esc(ar()?p.success_indicator_ar:p.success_indicator)}</div>
 <h4>${icon('calendar',15)} ${ar()?`الصيانة المجدولة لشهر ${monthName} (البرنامج المعتمد – الملحق 6)`:`Scheduled maintenance this month (Appendix 6)`}</h4>
 ${(ar()?p.scheduled_maintenance_ar:p.scheduled_maintenance).length?`<ul class="sched">${(ar()?p.scheduled_maintenance_ar:p.scheduled_maintenance).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:`<p class="muted">${ar()?'لا توجد أعمال مجدولة':'Nothing scheduled'}</p>`}
 ${!a.plants?`<p class="muted" style="font-size:11px">${ar()?'نوع النباتات غير محدد لهذه الحديقة، فعُرضت أعمال كل الفئات. حدّدوه لتصبح الخطة أدق.':'Plant type not set, so all groups are shown.'}</p>`:''}
 ${canAlert?`<div style="margin-top:14px">${btn(ar()?'إنشاء تنبيه بهذه الخطة':'Create alert with this plan','scan',{primary:true,icon:'bell-plus'})}<p class="muted" style="font-size:11px;margin:6px 0 0">${ar()?'عند تحويل التنبيه لمهمة تُنسخ الإجراءات ومؤشر النجاح إلى ملاحظات المهمة تلقائيًا.':'When the alert becomes a task, actions and the success indicator are copied into it.'}</p></div>`:''}
 <details class="ins-details"><summary>${icon('book-open',15)} ${ar()?'من أين تأتي الخطة؟':'Where does the plan come from?'}</summary><p>${ar()?'يأخذ محرك الصيانة التشخيص ودرجة ثقته ونوع النباتات والشهر الحالي، ويُخرج الأولوية والمهلة والمسؤول والإجراءات ومؤشر النجاح من قواعد مكتوبة مسبقًا، ويضيف أعمال الشهر من برنامج الصيانة المعتمد. هي قواعد واضحة قابلة للمراجعة وليست نموذجًا مدرَّبًا.':'The engine maps diagnosis, confidence, plant type and month to priority, deadline, owner, actions and a success indicator via explicit rules, plus this month’s approved programme. Rules, not a trained model.'}</p></details></div>`}

function insightSection(a){if(!a?.insight)return '';return `<div class="section-row"><div><h3>${ar()?'التحليل الذكي لهذه الحديقة':'Intelligence for this park'}</h3><small>${ar()?'تشخيص ← تنبؤ ← خطة تدخل، وكل رقم مشروح':'Diagnosis → forecast → plan, every number explained'}</small></div></div><div class="ins-grid">${diagnosisCard(a)}${forecastCard(a)}${planCard(a)}</div>`}

function prioritiesTable(){const rows=(S.data.areas||[]).filter(a=>a.insight).slice().sort((x,y)=>(y.insight.risk_score||0)-(x.insight.risk_score||0));if(!rows.length)return '';
 return `<div class="section-row"><div><h3>${ar()?'أولويات التدخل':'Intervention priorities'}</h3><small>${ar()?'مرتبة حسب درجة الخطر (0–100) التي تجمع شدة التشخيص ونسبة التراجع واحتمال التراجع المتوقع':'Ranked by risk score (0–100): diagnosis severity + decline + forecast risk'}</small></div></div>
 <div class="surface table-wrap"><table class="data-table prio"><thead><tr><th>${ar()?'الحديقة':'Park'}</th><th>${ar()?'الخطر':'Risk'}</th><th>${ar()?'التشخيص':'Diagnosis'}</th><th>${ar()?'الثقة':'Confidence'}</th><th>${ar()?'توقع 3 أشهر':'3-month risk'}</th><th>${ar()?'أول إجراء':'First action'}</th><th></th></tr></thead><tbody>
 ${rows.map(a=>{const i=a.insight,f=i.forecast||{},r=(i.recommendations||[])[0];return `<tr><td class="strong-name">${esc(areaLabel(a))}</td><td><div class="risk-bar"><i style="width:${i.risk_score||0}%" class="${(i.risk_score||0)>=60?'hi':(i.risk_score||0)>=30?'md':'lo'}"></i></div><small>${i.risk_score||0}</small></td><td class="tone-${DX_TONE[i.diagnosis]||'muted'}">${esc(ar()?i.title_ar:i.title_en)}</td><td>${ar()?CONF_AR[i.confidence]||'—':i.confidence}</td><td>${f.available?f.risk_pct+'%':'—'}</td><td style="white-space:normal;max-width:280px">${r?esc(ar()?r.action_ar:r.action_en):'—'}</td><td>${btn(t('areaDetails'),'open-area',{id:a.id})}</td></tr>`}).join('')}
 </tbody></table></div><p class="muted" style="font-size:11px;margin:8px 2px">${ar()?'درجة الخطر = شدة التشخيص × 18 + نسبة التراجع × 0.8 + احتمال التراجع المتوقع × 0.25 (بحد أقصى 100). التشخيص تمهيدي ويحتاج تحققًا ميدانيًا.':'Risk = severity×18 + decline%×0.8 + forecast risk×0.25 (max 100). Provisional; verify in the field.'}</p>`}

/* Approved plant list: which species grow in this park (drives the maintenance programme and the diagnosis notes). */
const IRR_CLASS={1:'lo',1.5:'lo',2:'md',2.5:'hi',3:'hi'};
function speciesBlock(a){const sp=a?.insight?.species||[],sum=a?.insight?.species_summary,reg=S.user?.role==='regulator';
 return `<div class="species-block"><div class="kpi-line"><span>${t('plantType')}</span>${reg?btn(ar()?'تحديد النباتات':'Set plants','edit-plants',{icon:'sprout'}):''}</div>
 ${sp.length?`<div class="sp-chips">${sp.map(p=>`<span class="sp-chip" title="${esc(p.scientific)} · ${esc(p.category_ar)}">${esc(ar()?p.name_ar:p.scientific)} <i class="irr ${IRR_CLASS[{'Low':1,'Low–medium':1.5,'Medium':2,'Medium–high':2.5,'High':3}[p.irrigation_en]]}">${ar()?'ري '+esc(p.irrigation_ar):esc(p.irrigation_en)}</i>${p.coastal?`<i class="irr coast">${ar()?'ساحلي/ملحي':'coastal'}</i>`:''}</span>`).join('')}</div>
 ${sum?`<p class="muted" style="font-size:11px;margin:6px 0 0">${ar()?`${sum.count} نوعًا · أعلى احتياج للري: ${({'Low':'منخفض','Low–medium':'منخفض–متوسط','Medium':'متوسط','Medium–high':'متوسط–مرتفع','High':'مرتفع'})[sum.max_irrigation]}. تُستخدم الأنواع لاختيار برنامج الصيانة وتفسير التشخيص.`:`${sum.count} species · highest water need: ${sum.max_irrigation}.`}</p>`:''}`
 :`<p class="muted" style="font-size:12px;margin:6px 0 0">${ar()?'لم تُحدَّد نباتات هذه الحديقة بعد. تحديدها من القائمة المعتمدة يجعل خطة الصيانة والتشخيص أدق.':'No species set yet; setting them makes the plan and diagnosis more precise.'}</p>`}</div>`}
let PLANT_CACHE=null;
async function plantsModal(){const a=selectedArea();if(!a)return;if(!PLANT_CACHE)PLANT_CACHE=await api('/plants');
 const chosen=new Set((a.insight?.species||[]).map(p=>p.scientific));const groups={};PLANT_CACHE.forEach(p=>(groups[p.category_ar]=groups[p.category_ar]||[]).push(p));
 openModal(`${modalHeader(ar()?'نباتات الحديقة':'Park plants',ar()?'اختاروا الأنواع المزروعة فعلًا من القائمة المعتمدة. بجانب كل نوع احتياجه الاسترشادي للري.':'Pick the species actually planted, from the approved list.')}
 <form id="plants-form" class="plants-form">${Object.entries(groups).map(([g,list])=>`<fieldset><legend>${esc(g)}</legend>${list.map(p=>`<label class="sp-opt"><input type="checkbox" name="sp" value="${esc(p.scientific)}" ${chosen.has(p.scientific)?'checked':''}/> <span><b>${esc(p.name_ar)}</b> <small>${esc(p.scientific)}</small><small>${esc(p.use_ar)} · ري ${esc(p.irrigation_ar)}</small></span></label>`).join('')}</fieldset>`).join('')}
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}
