/* RAWAA — presentation layer for "Predictions & Monitoring Schedule" and the park details page.
   Shared components (pills, chips, menus, side panel, NDVI chart), data loading, actions and modals.
   Presentation only: every value shown comes unchanged from the existing API responses. */
const PM={intel:null,area:{},acc:null,loading:{},stale:{intel:null,area:{},acc:null},filter:null,drawer:null};
const L2=(a,e)=>ar()?a:e;

/* ---------------------------------------------------------------- vocabulary */
const PRI={
 urgent:{cls:'u',ar:'تدخل عاجل',en:'Urgent',rank:0,hint:['زيارة ميدانية خلال 3 أيام','Field visit within 3 days']},
 follow_up:{cls:'f',ar:'تحتاج متابعة',en:'Follow-up',rank:1,hint:['فحص خلال أسبوعين','Inspection within two weeks']},
 stable:{cls:'s',ar:'مستقرة',en:'Stable',rank:2,hint:['فحص دوري شهري','Routine monthly check']},
 insufficient:{cls:'n',ar:'بيانات غير كافية',en:'Insufficient data',rank:3,hint:['تحتاج قراءات أو اعتماد حدود','Needs readings or boundary approval']}};
const PRI_ORDER=['urgent','follow_up','stable','insufficient'];
const BND={approved:['s','معتمدة','Approved'],pending_approval:['f','بانتظار الاعتماد','Pending approval'],needs_review:['u','تحتاج مراجعة جغرافية','Needs geographic review'],rejected:['u','مرفوضة','Rejected']};
const SCH={scheduled:['','مجدول','Scheduled'],in_progress:['prog','قيد التنفيذ','In progress'],done:['done','تم الفحص','Inspected'],cancelled:['','ملغى','Cancelled'],superseded:['','استُبدل','Superseded']};
const REL={high:['مرتفعة','high'],medium:['متوسطة','medium'],low:['منخفضة','low']};

/* ---------------------------------------------------------------- icons (lucide paths) */
const RWI={
 more:'<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
 x:'<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
 down:'<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
 up:'<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
 flat:'<path d="M2 12h20"/><path d="m18 8 4 4-4 4"/>',
 minus:'<path d="M5 12h14"/>',
 arrowDown:'<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
 arrowUp:'<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
 chevDown:'<path d="m6 9 6 6 6-6"/>',chevR:'<path d="m9 18 6-6-6-6"/>',chevL:'<path d="m15 18-6-6 6-6"/>',
 panel:'<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/><path d="m10 15-3-3 3-3"/>',
 pin:'<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
 cal:'<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
 check:'<path d="M20 6 9 17l-5-5"/>',
 ext:'<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
 sat:'<path d="M13 7 9 3 5 7l4 4"/><path d="m17 11 4 4-4 4-4-4"/><path d="m8 12 4 4 6-6-4-4Z"/><path d="m16 8 3-3"/><path d="M9 21a6 6 0 0 0-6-6"/>',
 pencil:'<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
 shield:'<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
 layers:'<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
 filter:'<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
};
function rwIcon(n,s=16){const p=RWI[n];return p?`<svg class="icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width:${s}px;height:${s}px;flex:none">${p}</svg>`:icon(n,s)}

/* ---------------------------------------------------------------- formatting */
const LOC=()=>ar()?'ar-SA-u-nu-latn':'en-GB';
const nfx=(v,d=3)=>(typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):null);
const num=(v,d=3)=>{const s=nfx(v,d);return s==null?'—':`<bdi dir="ltr">${s}</bdi>`};
const sgn=(v,d=1)=>`${v<0?'−':v>0?'+':''}${Math.abs(v).toFixed(d)}`;
const rng=(a,b)=>`<bdi dir="ltr">${nfx(a)??'—'} – ${nfx(b)??'—'}</bdi>`;
const pdate=s=>{if(!s)return null;const [y,m,d]=String(s).slice(0,10).split('-').map(Number);return new Date(y,m-1,d)};
const dshort=s=>{const d=pdate(s);return d?`<bdi>${d.toLocaleDateString(LOC(),{day:'numeric',month:'short'})}</bdi>`:'—'};
const dlong=s=>{const d=pdate(s);return d?`<bdi>${d.toLocaleDateString(LOC(),{day:'numeric',month:'long',year:'numeric'})}</bdi>`:'—'};
const pct=v=>`<bdi dir="ltr">${v}%</bdi>`;
const dtime=s=>{if(!s)return '—';const d=new Date(s);return `<bdi>${d.toLocaleString(LOC(),{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}</bdi>`};
const ha=m2=>Number.isFinite(m2)?`<bdi dir="ltr">${(m2/10000).toFixed(2)}</bdi> ${L2('هكتار','ha')}`:'—';
function daysFromToday(s){const d=pdate(s);if(!d)return null;const t=new Date();t.setHours(0,0,0,0);return Math.round((d-t)/864e5)}
const arDays=n=>n===1?'يوم':n===2?'يومين':n<=10?`${n} أيام`:`${n} يومًا`;
function relDay(s){const n=daysFromToday(s);if(n==null)return '';if(n===0)return L2('اليوم','today');if(n===1)return L2('غدًا','tomorrow');
 if(n>0)return ar()?`بعد ${arDays(n)}`:`in ${n} days`;return ar()?`متأخر ${arDays(-n)}`:`${-n} day${n<-1?'s':''} overdue`}

/* ---------------------------------------------------------------- small components */
const pill=(p,size='')=>{const m=PRI[p]||PRI.insufficient;return `<span class="rw-pill ${m.cls} ${size}"><i></i>${L2(m.ar,m.en)}</span>`};
const bndPill=s=>{const m=BND[s]||['n','—','—'];return `<span class="rw-pill ${m[0]} sm"><i></i>${L2(m[1],m[2])}</span>`};
const bndTag=s=>{const m=BND[s]||['n','—','—'];return `<span class="rw-bnd ${m[0]}"><i></i>${L2('الحدود: '+m[1],'Boundary: '+m[2].toLowerCase())}</span>`};
const schTag=s=>{if(!s)return '';const m=SCH[s.status]||['',s.status,s.status];return s.overdue&&s.status==='scheduled'?`<span class="rw-sched late">${L2('متأخر','Overdue')}</span>`:`<span class="rw-sched ${m[0]}">${L2(m[1],m[2])}</span>`};
const trendBox=dir=>{const k=dir==='declining'?'down':dir==='improving'?'up':'flat';return `<span class="rw-arrow ${k}" title="${L2({down:'تراجع متوقع',up:'تحسّن متوقع',flat:'استقرار متوقع'}[k],{down:'Expected decline',up:'Expected improvement',flat:'Expected stable'}[k])}">${rwIcon(k,16)}</span>`};
const rwTip=text=>`<button type="button" class="tip" data-action="tip" aria-label="${esc(text)}" data-tip="${esc(text)}">!</button>`;
const chipsHtml=c=>c.length?`<ul class="rw-facts">${c.map(([cls,txt,ic])=>`<li class="${cls}">${ic?rwIcon(ic,14):''}<span>${txt}</span></li>`).join('')}</ul>`:'';
const skel=(w,h,extra='')=>`<div class="rw-skel" style="width:${w};height:${h}px;${extra}"></div>`;

function rwMenu(items,opt={}){items=items.filter(Boolean);if(!items.length)return '';
 const lbl=L2('إجراءات أخرى','More actions');
 const trig=opt.label?`<button type="button" class="btn rw-menu-btn" data-action="pm-menu" aria-haspopup="menu" aria-expanded="false">${opt.icon?rwIcon(opt.icon,15):''}<span>${opt.label}</span>${rwIcon('chevDown',14)}</button>`
  :`<button type="button" class="rw-icon-btn" data-action="pm-menu" aria-haspopup="menu" aria-expanded="false" aria-label="${lbl}" title="${lbl}">${rwIcon('more',18)}</button>`;
 return `<div class="rw-menu">${trig}<div class="rw-menu-list" role="menu">${items.map(it=>it==='-'?'<div class="rw-menu-sep"></div>':it.href
  ?`<a class="rw-menu-item" role="menuitem" href="${esc(it.href)}" target="_blank" rel="noopener">${rwIcon(it.icon||'ext',15)}<span>${it.label}</span></a>`
  :`<button type="button" class="rw-menu-item${it.danger?' danger':''}" role="menuitem" data-action="${it.action}"${it.id!=null?` data-id="${it.id}"`:''}${it.view?` data-view="${it.view}"`:''}>${rwIcon(it.icon||'chevR',15)}<span>${it.label}</span></button>`).join('')}</div></div>`}
function closeMenus(except){document.querySelectorAll('.rw-menu.open').forEach(m=>{if(m!==except){m.classList.remove('open');m.querySelector('[data-action=pm-menu]')?.setAttribute('aria-expanded','false')}})}

/* ---------------------------------------------------------------- decision wording (from the decision object) */
/* Returns safe HTML: server text is escaped, numbers are bidi-isolated. */
function rwSummary(d){
 if(d.priority==='insufficient'||!d.current)return esc((ar()?d.reasons_ar:d.reasons_en)?.[0]||L2('لا توجد قراءات كافية بعد.','Not enough readings yet.'));
 const v=num(d.current.ndvi),an=d.anomaly_pct,seas=d.baseline_kind==='seasonal';
 const exp=seas?L2('المتوقع لهذا الموسم','the seasonal norm'):L2('مستواها المعتاد','its usual level');let s;
 if(an==null)s=L2(`NDVI الحالي ${v}`,`Current NDVI is ${v}`);
 else if(an<=-10)s=L2(`NDVI الحالي ${v}، أقل بـ ${pct(Math.abs(an).toFixed(0))} من ${exp}`,`NDVI ${v} is ${pct(Math.abs(an).toFixed(0))} below ${exp}`);
 else if(an>=10)s=L2(`NDVI الحالي ${v}، أعلى بـ ${pct(an.toFixed(0))} من ${exp}`,`NDVI ${v} is ${pct(an.toFixed(0))} above ${exp}`);
 else s=L2(`NDVI الحالي ${v} قريب من ${exp}`,`NDVI ${v} is close to ${exp}`);
 const p=d.persistence||0,dir=d.trend?.direction;
 if(p>=2)s+=L2(`، والتراجع مستمر في ${p} قراءات متتالية`,`, declining for ${p} consecutive readings`);
 else if(p===1)s+=L2('؛ ظهر التراجع في آخر قراءة فقط ويحتاج تأكيدًا',`; the drop shows in the latest reading only`);
 else s+=L2(`، والاتجاه ${({declining:'تراجع',improving:'تحسّن'})[dir]||'مستقر'}`,`, trend ${dir||'stable'}`);
 return s+'.'}
function rwWhy(d){const c=[],an=d.anomaly_pct;
 const stale=d.stale_days!=null&&d.stale_days>45?['warn',L2(`آخر قراءة قبل ${d.stale_days} يومًا`,`Last reading ${d.stale_days} days ago`),'clock']:null;
 const unv=d.excluded_unverified_readings?['',L2(`${d.excluded_unverified_readings} قراءات مستوردة لم تُستخدم`,`${d.excluded_unverified_readings} imported readings not used`),'file-up']:null;
 if(d.priority==='insufficient'||!d.current){c.push(['',L2(`${d.n_trusted||0} قراءات فضائية موثوقة`,`${d.n_trusted||0} trusted readings`),'database']);if(stale)c.push(stale);if(unv)c.push(unv);
  if(['needs_review','rejected'].includes(d.boundary_status))c.push(['warn',L2('الحدود تحتاج مراجعة','Boundary needs review'),'pin']);return c}
 if(an!=null)c.push([an<=-10?'bad':an<0?'warn':an>=10?'good':'',`<bdi dir="ltr">${sgn(an)}%</bdi> ${L2('عن المتوقع','vs expected')}`,an<0?'arrowDown':'arrowUp']);
 if(d.persistence>=1)c.push([d.persistence>=2?'bad':'warn',d.persistence===1?L2('قراءة واحدة منخفضة','One low reading'):L2(`${d.persistence} قراءات متتالية`,`${d.persistence} consecutive readings`),'history']);
 const dir=d.trend?.direction,sl=d.trend?.slope_per_30d;
 if(dir&&dir!=='unknown')c.push([dir==='declining'?'bad':dir==='improving'?'good':'',`${L2('الاتجاه','Trend')} <bdi dir="ltr">${sl!=null?sgn(sl,3):''}</bdi> ${L2('شهريًا','/mo')}`,dir==='declining'?'down':dir==='improving'?'up':'flat']);
 if(d.baseline_kind!=='seasonal')c.push(['',L2('لا يوجد عام سابق للمقارنة الموسمية','No prior-year season yet'),'info']);
 if(stale)c.push(stale);if(unv)c.push(unv);return c}
const rwShortAction=d=>((ar()?d.action_ar:d.action_en)||'').split(/[:؛;]|\.\s/)[0].replace(/\.$/,'').trim();
/* chart widths that match the space they are drawn in, so text stays at its natural size on every screen */
const fitPage=()=>(document.querySelector('.content')?.clientWidth||window.innerWidth)-(window.innerWidth<=560?56:84);
const fitDrawer=()=>Math.min(620,window.innerWidth)-(window.innerWidth<=560?32:48);
const expLabel=d=>d.baseline_kind==='seasonal'?L2('المتوقع موسميًا','Seasonal norm'):L2('المستوى المعتاد','Usual level');
const firstClause=s=>(s||'').split(/[؛;]/)[0].replace(/\.$/,'').trim();

/* ---------------------------------------------------------------- NDVI chart: actual (solid) · forecast (dashed + 80% band) · seasonal norm */
let RW_SEQ=0,RW_TT=false;
function rwChart(series,fc,expected,opt={}){
 const P=(series||[]).filter(s=>Number.isFinite(s.ndvi)).map(s=>({t:+pdate(s.date),v:s.ndvi,d:s.date,q:s.valid_pixels_pct}));
 if(!P.length)return `<div class="rw-empty">${rwIcon('info',16)}<span>${L2('لا توجد قراءات فضائية موثوقة لرسم الاتجاه بعد.','No trusted satellite readings to chart yet.')}</span></div>`;
 const F=fc?.available?fc.horizons.map(h=>({t:+pdate(h.target_date),v:h.ndvi,lo:h.low80,hi:h.high80,d:h.target_date,days:h.days})):[];
 const last=P.at(-1),today=+new Date(new Date().setHours(0,0,0,0)),hasE=Number.isFinite(expected);
 const vals=[...P.map(p=>p.v),...F.flatMap(f=>[f.lo,f.hi,f.v]),...(hasE?[expected]:[])];
 let lo=Math.min(...vals),hi=Math.max(...vals);const pad=Math.max(.02,(hi-lo)*.14);lo-=pad;hi+=pad;
 const t0=P[0].t-4*864e5,t1=Math.max(last.t,...F.map(f=>f.t),today)+6*864e5;
 const fitW=Math.round(typeof opt.fit==='function'?opt.fit():0),W=fitW>200?Math.min(opt.w||720,fitW):(opt.w||720),H=Math.round((opt.h||250)*(W<560?.82:1)),Lp=42,Rp=16,Tp=18,Bp=40,X=t=>Lp+(t-t0)/((t1-t0)||1)*(W-Lp-Rp),Y=v=>Tp+(hi-v)/((hi-lo)||1)*(H-Tp-Bp),r1=n=>n.toFixed(1);
 const st=[.01,.02,.025,.05,.1,.2,.25,.5].find(s=>(hi-lo)/s<=4.5)||.5,ys=[];for(let v=Math.ceil(lo/st)*st;v<=hi+1e-9;v+=st)ys.push(+v.toFixed(3));
 const months=[],dd=new Date(t0);dd.setDate(1);dd.setMonth(dd.getMonth()+1);while(+dd<=t1){months.push(+dd);dd.setMonth(dd.getMonth()+1)}
 const every=Math.max(1,Math.ceil(months.length/(W<560?4:6))),xs=months.filter((m,i)=>i%every===0);
 const mlab=(t,i)=>{const d=new Date(t);return {m:(ar()?MONTHS_AR:MONTHS_EN)[d.getMonth()],y:i===0||d.getMonth()===0?String(d.getFullYear()):''}};
 const gid='rwg'+(++RW_SEQ),line=P.map(p=>`${r1(X(p.t))},${r1(Y(p.v))}`).join(' ');
 const area=`M${r1(X(P[0].t))},${r1(Y(P[0].v))} `+P.slice(1).map(p=>`L${r1(X(p.t))},${r1(Y(p.v))}`).join(' ')+` L${r1(X(last.t))},${H-Bp} L${r1(X(P[0].t))},${H-Bp} Z`;
 let fcs='';if(F.length){const band=`M${r1(X(last.t))},${r1(Y(last.v))} `+F.map(f=>`L${r1(X(f.t))},${r1(Y(f.hi))}`).join(' ')+' '+F.slice().reverse().map(f=>`L${r1(X(f.t))},${r1(Y(f.lo))}`).join(' ')+' Z';
  fcs=`<path d="${band}" class="band"/><polyline class="fc" points="${r1(X(last.t))},${r1(Y(last.v))} ${F.map(f=>`${r1(X(f.t))},${r1(Y(f.v))}`).join(' ')}"/>${F.map(f=>`<circle class="fpt" cx="${r1(X(f.t))}" cy="${r1(Y(f.v))}" r="4"/>`).join('')}`}
 let ex='';if(hasE){const endV=F.length?F.at(-1).v:last.v,right=Math.abs(expected-endV)>=Math.abs(expected-P[0].v),above=(right?endV:P[0].v)<=expected,ly=Y(expected)+(above?-7:14);
  ex=`<line class="exp" x1="${Lp}" x2="${W-Rp}" y1="${r1(Y(expected))}" y2="${r1(Y(expected))}"/><text class="tk exp-t" x="${right?W-Rp-2:Lp+6}" y="${r1(ly)}" text-anchor="${right?'end':'start'}">${esc(opt.expLabel||'')} ${expected.toFixed(2)}</text>`}
 const td=today>=t0&&today<=t1?`<line class="today" x1="${r1(X(today))}" x2="${r1(X(today))}" y1="${Tp}" y2="${H-Bp}"/><text class="tk" x="${r1(X(today))}" y="${Tp-6}" text-anchor="middle">${L2('اليوم','Today')}</text>`:'';
 const pts=[...P.map(p=>({x:+r1(X(p.t)),y:+r1(Y(p.v)),k:'a',d:p.d,v:p.v,q:p.q})),...F.map(f=>({x:+r1(X(f.t)),y:+r1(Y(f.v)),k:'f',d:f.d,v:f.v,lo:f.lo,hi:f.hi,n:f.days}))];
 return `<div class="rw-chart" dir="ltr" data-w="${W}" data-h="${H}" data-pts="${esc(JSON.stringify(pts))}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${L2('اتجاه NDVI: قراءات فعلية وتوقع','NDVI trend: actual readings and forecast')}">
 <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".18"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
 ${ys.map(v=>`<line class="g" x1="${Lp}" x2="${W-Rp}" y1="${r1(Y(v))}" y2="${r1(Y(v))}"/><text class="tk" x="${Lp-9}" y="${r1(Y(v)+3.5)}" text-anchor="end">${v.toFixed(2)}</text>`).join('')}
 ${xs.map((t,i)=>{const l=mlab(t,i);return `<text class="tk" x="${r1(X(t))}" y="${H-21}" text-anchor="middle">${l.m}</text>${l.y?`<text class="tk yr" x="${r1(X(t))}" y="${H-6}" text-anchor="middle">${l.y}</text>`:''}`}).join('')}${td}${ex}
 <path d="${area}" fill="url(#${gid})"/><polyline class="act" points="${line}"/>${fcs}
 ${P.map((p,i)=>i===P.length-1?`<circle class="halo" cx="${r1(X(p.t))}" cy="${r1(Y(p.v))}" r="10"/><circle class="pt last" cx="${r1(X(p.t))}" cy="${r1(Y(p.v))}" r="4.5"/>`:`<circle class="pt" cx="${r1(X(p.t))}" cy="${r1(Y(p.v))}" r="3"/>`).join('')}
 <line class="guide" x1="-9" x2="-9" y1="${Tp}" y2="${H-Bp}"/><circle class="hl" cx="-20" cy="-20" r="5.5"/></svg><div class="rw-tt" dir="${ar()?'rtl':'ltr'}"></div></div>`}
const chartLegend=(hasE,kind)=>`<div class="rw-legend"><span><i class="lg a"></i>${L2('قراءة فعلية','Actual')}</span><span><i class="lg f"></i>${L2('توقع','Forecast')}</span><span><i class="lg b"></i>${L2('النطاق المرجّح 80%','80% range')}</span>${hasE?`<span><i class="lg e"></i>${kind==='seasonal'?L2('المتوقع موسميًا','Seasonal norm'):L2('المستوى المعتاد','Usual level')}</span>`:''}</div>`;
function rwSpark(vals){vals=vals.filter(Number.isFinite).slice(-10);if(vals.length<2)return '';const W=104,H=36,mn=Math.min(...vals),mx=Math.max(...vals),r=(mx-mn)||1,X=i=>3+i*(W-6)/(vals.length-1),Y=v=>4+(mx-v)/r*(H-8);
 return `<svg class="rw-spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><polyline points="${vals.map((v,i)=>`${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')}"/><circle cx="${X(vals.length-1).toFixed(1)}" cy="${Y(vals.at(-1)).toFixed(1)}" r="3"/></svg>`}
function rwHideTT(){document.querySelectorAll('.rw-chart').forEach(c=>{c.querySelector('.rw-tt')?.classList.remove('on');const g=c.querySelector('.guide');if(g)g.style.opacity=0;const h=c.querySelector('.hl');if(h)h.style.opacity=0});RW_TT=false}
document.addEventListener('mousemove',e=>{const c=e.target.closest?.('.rw-chart');if(!c){if(RW_TT)rwHideTT();return}
 const svg=c.querySelector('svg'),r=svg.getBoundingClientRect(),W=+c.dataset.w,H=+c.dataset.h;let pts=c._pts;if(!pts)try{pts=c._pts=JSON.parse(c.dataset.pts)}catch{return}
 const vx=(e.clientX-r.left)/r.width*W;let b=null;for(const p of pts){const dx=Math.abs(p.x-vx);if(!b||dx<b.dx)b={...p,dx}}if(!b)return;
 const g=svg.querySelector('.guide'),hl=svg.querySelector('.hl'),tt=c.querySelector('.rw-tt');g.setAttribute('x1',b.x);g.setAttribute('x2',b.x);g.style.opacity=1;hl.setAttribute('cx',b.x);hl.setAttribute('cy',b.y);hl.setAttribute('class','hl '+b.k);hl.style.opacity=1;
 tt.innerHTML=b.k==='a'?`<small>${L2('قراءة فعلية','Actual reading')} · ${dlong(b.d)}</small><b dir="ltr">NDVI ${b.v.toFixed(3)}</b>${b.q!=null?`<small>${L2('بكسلات صافية','Clear pixels')} ${pct(Math.round(b.q))}</small>`:''}`
  :`<small>${L2('توقع','Forecast')} · ${L2(`بعد ${b.n} ${b.n===7?'أيام':'يومًا'}`,`in ${b.n} days`)} · ${dlong(b.d)}</small><b dir="ltr">NDVI ${b.v.toFixed(3)}</b><small>${L2('النطاق المرجّح','Likely range')} ${rng(b.lo,b.hi)}</small>`;
 const cr=c.getBoundingClientRect();let left=r.left-cr.left+b.x/W*r.width;left=Math.max(90,Math.min(cr.width-90,left));tt.style.left=left+'px';tt.style.top=(r.top-cr.top+b.y/H*r.height)+'px';tt.classList.add('on');RW_TT=true});

/* ---------------------------------------------------------------- side panel */
function drawerSlot(){const d=PM.drawer;if(d&&d.view!==S.view)PM.drawer=null;return `<div id="rw-drawer-slot">${PM.drawer?drawerHtml():''}</div>`}
function drawerHtml(){const d=PM.drawer;if(!d)return '';const inner=d.kind==='park'?parkDrawer(d):predDrawer(d);if(!inner)return '';const st=d.shown?' rw-static':'';
 return `<div class="rw-shade${st}" data-action="pm-drawer-close"></div><aside id="rw-drawer" class="rw-drawer${st}" role="dialog" aria-modal="true" aria-label="${esc(inner.title)}">${inner.html}</aside>`}
function drawerFrame({eyebrow,title,badge,tabs,tab,body,foot}){return `<header class="rw-dr-head"><div class="rw-grow"><small>${eyebrow}</small><h3>${title}</h3></div>${badge||''}<button type="button" class="rw-icon-btn" data-action="pm-drawer-close" aria-label="${L2('إغلاق','Close')}">${rwIcon('x',18)}</button></header>
 ${tabs?`<nav class="rw-tabs" role="tablist">${tabs.map(([k,l])=>`<button type="button" role="tab" aria-selected="${k===tab}" class="rw-tab${k===tab?' on':''}" data-action="pm-dtab" data-tab="${k}">${l}</button>`).join('')}</nav>`:''}
 <div class="rw-dr-body">${body}</div>${foot?`<footer class="rw-dr-foot">${foot}</footer>`:''}`}
function pmPaintDrawer(){const slot=document.getElementById('rw-drawer-slot');if(!slot)return;slot.innerHTML=PM.drawer?drawerHtml():'';
 if(PM.drawer&&!PM.drawer.shown){PM.drawer.shown=true;setTimeout(()=>document.querySelector('#rw-drawer .rw-dr-head [data-action=pm-drawer-close]')?.focus({preventScroll:true}),60)}}
function pmOpenDrawer(kind,id,tab){PM.drawer={kind,id,tab:tab||(kind==='park'?'summary':null),view:S.view,shown:false};closeMenus();pmPaintDrawer()}
function pmCloseDrawer(){PM.drawer=null;const slot=document.getElementById('rw-drawer-slot');if(slot)slot.innerHTML=''}

/* ---------------------------------------------------------------- data */
function pmReset(){PM.stale={intel:PM.intel||PM.stale.intel,area:{...PM.stale.area,...PM.area},acc:PM.acc||PM.stale.acc};PM.intel=null;PM.area={};PM.acc=null}
async function pmLoadIntel(){if(PM.loading.intel)return;PM.loading.intel=true;try{const [i,a]=await Promise.all([api('/intel/areas'),api('/forecast-accuracy')]);PM.intel=i;PM.acc=a;if(S.view==='predictions')render()}catch(e){toast(e.message,true)}finally{PM.loading.intel=false}}
async function pmLoadArea(id){if(PM.loading['a'+id])return;PM.loading['a'+id]=true;try{const [intel,bnd]=await Promise.all([api(`/areas/${id}/intel`),api(`/areas/${id}/boundary`)]);
 const before=JSON.stringify(PM.stale.area[id]||null);PM.area[id]={intel,bnd};const changed=before!==JSON.stringify(PM.area[id]);
 if(S.view==='area'&&S.areaId===id){if(changed||!document.querySelector('.rw-park .rw-hero'))softRenderPark()}else if(PM.drawer?.id===id)pmPaintDrawer()}catch(e){toast(e.message,true)}finally{PM.loading['a'+id]=false}}

/* ================================================================ Predictions & Monitoring Schedule page */
function predictionsPage(){const d=PM.intel||PM.stale.intel;if(!PM.intel)setTimeout(pmLoadIntel,0);const reg=S.user.role==='regulator';
 const actions=(reg?`<button type="button" class="btn primary" data-action="pm-run">${icon('refresh-cw',15)} ${L2('تشغيل التحليل الآن','Run analysis now')}</button>`:'')+rwMenu([
  {label:L2('جدول المتابعة (CSV)','Monitoring schedule (CSV)'),action:'pm-export-schedule',icon:'download'},
  {label:L2('ملخص القرار (CSV)','Decision summary (CSV)'),action:'pm-export-decisions',icon:'download'},
  reg&&{label:L2('سجل التنبؤات (CSV)','Predictions log (CSV)'),action:'pm-export-predictions',icon:'download'}],{label:L2('تصدير','Export'),icon:'download'});
 if(!d)return `<div class="rw rw-pred">${heading(t('predictions'),L2('جارٍ تحليل القراءات…','Analysing readings…'),actions)}<div class="rw-stats">${`<div class="rw-card rw-stat">${skel('60%',12)}${skel('40%',30)}${skel('100%',4)}</div>`.repeat(4)}</div><section class="rw-card rw-list">${`<div class="rw-row rw-row-skel">${skel('70%',14)}${skel('60%',14)}${skel('60%',14)}${skel('50%',14)}${skel('80%',28)}</div>`.repeat(4)}</section></div>`;
 const total=d.areas.length;
 const rows=d.areas.slice().sort((x,y)=>(PRI[x.decision.priority]?.rank??9)-(PRI[y.decision.priority]?.rank??9)||String(x.schedule?.next_check||'9').localeCompare(String(y.schedule?.next_check||'9'))).filter(x=>!PM.filter||x.decision.priority===PM.filter);
 const last=d.last_run;
 const sub=`<span class="rw-sub">${total} ${L2('حدائق تحت المراقبة','parks monitored')} · ${last?`${L2('آخر تحليل','Last analysis')} ${dtime(last.started_at)}`:L2('لم يُشغَّل التحليل بعد','Not analysed yet')}${last?.error?` · <b class="rw-bad">${L2('فشل آخر تشغيل','last run failed')}</b>`:''}</span>`;
 const toolbar=PM.filter?`<div class="rw-count">${rwIcon('filter',14)} ${L2('عرض','Showing')} ${pill(PM.filter,'sm')} <span>${rows.length} ${L2('من','of')} ${total}</span><button type="button" class="rw-link" data-action="pm-filter" data-p="">${rwIcon('x',14)} ${L2('إلغاء التصفية','Clear filter')}</button></div>`
  :`<div class="rw-count">${L2('مرتبة حسب الأولوية ثم موعد المتابعة · اضغط أي صف لعرض التفاصيل','Sorted by priority, then follow-up date · click a row for details')}</div>`;
 return `<div class="rw rw-pred">${heading(t('predictions'),sub,actions)}
 <div class="rw-stats">${PRI_ORDER.map(p=>predStat(p,d.counts[p]||0,total)).join('')}</div>
 <div class="rw-toolbar">${toolbar}<div class="rw-legend"><span><i class="lg a"></i>${L2('قراءة فعلية = قياس فضائي','Actual = satellite measurement')}</span><span><i class="lg f"></i>${L2('توقع = تقدير نموذج مختبَر','Forecast = backtested estimate')}</span></div></div>
 <section class="rw-card rw-list" role="table" aria-label="${t('predictions')}"><div class="rw-lhead" role="row"><span role="columnheader">${L2('الحديقة','Park')}</span><span role="columnheader">${L2('الحالة','Status')}</span><span role="columnheader">${L2('التوقع','Forecast')}</span><span role="columnheader">${L2('موعد المتابعة','Follow-up')}</span><span role="columnheader" class="end">${L2('الإجراء','Action')}</span></div>
 ${rows.map(predRow).join('')||`<div class="rw-empty">${rwIcon('info',16)}<span>${t('empty')}</span></div>`}</section>
 <div class="rw-bottom">${accCard()}${howCard(d)}</div>${drawerSlot()}</div>`}

function predStat(p,n,total){const m=PRI[p],on=PM.filter===p,pct=total?Math.round(100*n/total):0;
 return `<button type="button" class="rw-card rw-stat ${m.cls}${on?' on':''}" data-action="pm-filter" data-p="${p}" aria-pressed="${on}" title="${L2('اضغط لتصفية الجدول','Click to filter the list')}">
 <span class="rw-stat-top"><i></i>${L2(m.ar,m.en)}</span><span class="rw-stat-num">${n}<small>${L2('من','of')} ${total}</small></span>
 <span class="rw-stat-bar"><i style="width:${pct}%"></i></span><span class="rw-stat-hint">${L2(m.hint[0],m.hint[1])}</span></button>`}

function predRow(x){const d=x.decision,f=x.forecast,s=x.schedule,cur=d.current,h30=f.available?f.horizons.find(h=>h.days===30):null,reg=S.user.role==='regulator';
 const status=`${pill(d.priority)}<small>${cur?`<bdi dir="ltr">NDVI ${nfx(cur.ndvi)}</bdi> · ${dshort(cur.date)}`:L2('لا توجد قراءة موثوقة','No trusted reading')}</small>`;
 const fc=h30?`<div class="rw-fc">${trendBox(f.direction)}<div class="rw-fc-v"><span><b class="rw-num">${num(h30.ndvi)}</b> <small>${L2('بعد 30 يومًا','in 30 days')}</small></span>${f.decline_probability_pct!=null?`<span class="rw-prob">${L2('احتمال التراجع','Decline risk')} ${pct(f.decline_probability_pct)}</span>`:`<small>${L2('النطاق','Range')} ${rng(h30.low80,h30.high80)}</small>`}</div></div>`
  :`<div class="rw-fc" title="${esc(ar()?f.reason_ar:f.reason_en)}"><span class="rw-arrow none">${rwIcon('minus',16)}</span><small>${L2('لا يوجد توقع بعد','No forecast yet')}</small></div>`;
 const next=!s?`<small>—</small>`:s.status==='done'?`<b>${dshort(s.reassess_at)}</b><small>${L2('إعادة التقييم','Reassessment')}</small>${schTag(s)}`
  :`<b>${dshort(s.next_check)}</b><small class="${s.overdue?'rw-bad':''}">${relDay(s.next_check)}</small>${s.status!=='scheduled'||s.overdue?schTag(s):''}`;
 const menu=rwMenu([{label:L2('فتح صفحة الحديقة','Open park page'),action:'open-area',id:x.area_id,icon:'pin'},
  s&&['scheduled','in_progress'].includes(s.status)&&{label:L2('تسجيل الفحص كمنجز','Mark as inspected'),action:'pm-sched-done',id:s.id,icon:'check'},
  reg&&s&&s.status==='scheduled'&&{label:L2('تعديل موعد المتابعة','Edit follow-up date'),action:'pm-sched-edit',id:s.id,icon:'cal'}]);
 return `<div class="rw-row" role="row" data-action="pm-pred-details" data-id="${x.area_id}">
 <div class="rw-cell rw-c-park" role="cell"><b>${esc(ar()?x.name_ar:x.name_en)}</b>${bndTag(x.boundary_status)}</div>
 <div class="rw-cell rw-c-status" role="cell">${status}</div><div class="rw-cell" role="cell">${fc}</div>
 <div class="rw-cell rw-c-next" role="cell">${next}</div>
 <div class="rw-cell rw-c-act" role="cell"><button type="button" class="btn tiny rw-details" data-action="pm-pred-details" data-id="${x.area_id}">${L2('التفاصيل','Details')}</button>${menu}</div></div>`}

function accCard(){const a=PM.acc||PM.stale.acc;if(!a)return '<div></div>';
 const tile=(lab,val,sub)=>`<div class="rw-acc-tile"><small>${lab}</small><b>${val}</b><span>${sub}</span></div>`;
 return `<section class="rw-card rw-acc"><div class="rw-sec-head"><h3>${L2('دقة التوقعات الفعلية','Live forecast accuracy')}</h3><p>${L2('كل توقع يُقارن تلقائيًا بالقراءة الفعلية عند وصولها','Every forecast is scored against the actual reading when it arrives')}</p></div>
 <div class="rw-acc-grid">${a.horizons.map(h=>tile(L2(`توقعات ${h.days} ${h.days===7?'أيام':'يومًا'}`,`${h.days}-day forecasts`),h.evaluated?num(h.mae):'—',h.evaluated?`${L2('متوسط الخطأ','Mean error')} · ${L2('المرجع','naive')} ${num(h.mae_naive)} · n=${h.evaluated}`:L2('لم يُتحقق منها بعد','Not verified yet'))).join('')}
 ${tile(L2('بانتظار قراءة فعلية','Awaiting an actual'),`<bdi dir="ltr">${a.pending}</bdi>`,L2('توقعات محفوظة','stored forecasts'))}</div></section>`}
function howCard(d){return `<details class="rw-card rw-how"><summary><span>${rwIcon('info',16)} ${L2('طريقة قراءة هذه الصفحة','How to read this page')}</span>${rwIcon('chevDown',16)}</summary><ul class="rw-ul">
 <li>${L2('«قراءة فعلية» قياس من صورة Sentinel-2 حقيقية، و«توقع» تقدير لنموذج اختُبر على السجل التاريخي وليس قياسًا.','"Actual" is measured on a real Sentinel-2 image; "forecast" is an estimate from a backtested model, not a measurement.')}</li>
 <li>${L2('لا تُستخدم القراءات المستوردة يدويًا أو الغائمة في التصنيف أو التنبؤ أو التنبيهات التلقائية.','Imported/manual or cloudy readings never drive classification, forecasts or automatic alerts.')}</li>
 <li>${L2('لا يُعرض توقع عند نقص البيانات، ولا يظهر احتمال التراجع إلا إذا تفوّق النموذج على النموذج المرجعي البسيط.','No forecast is shown without enough data, and the decline probability only appears when the model beats the naive reference.')}</li>
 <li>${L2('صور الأقمار تكشف التراجع ولا تشخّص سببه؛ مرض النبات أو عطل الري يُؤكَّد بالفحص الميداني فقط.','Satellite images reveal a decline, not its cause; plant disease or irrigation faults are confirmed only in the field.')}</li>
 <li>${d.auto_pipeline?L2('التحليل يعمل تلقائيًا على الخادم.','Analysis runs automatically on the server.'):L2('التشغيل التلقائي غير مفعّل على الخادم؛ يُشغَّل التحليل يدويًا أو بعد كل مزامنة فضائية.','Automatic runs are off on the server; analysis runs manually or after each satellite sync.')}</li></ul></details>`}

function predDrawer(dr){const src=PM.intel||PM.stale.intel,x=src?.areas.find(a=>a.area_id===dr.id);if(!x)return null;
 const d=x.decision,f=x.forecast,s=x.schedule,cur=d.current,c=PM.area[dr.id]||PM.stale.area[dr.id],reg=S.user.role==='regulator',name=ar()?x.name_ar:x.name_en;
 const h=f.available?Object.fromEntries(f.horizons.map(z=>[z.days,z])):{};
 const tile=(lab,v,sub,cls='')=>`<div class="rw-tile ${cls}"><small>${lab}</small><b>${v}</b><span>${sub}</span></div>`;
 const tiles=`<div class="rw-tiles">${tile(`<i class="lg a"></i>${L2('الآن · قراءة فعلية','Now · actual')}`,cur?num(cur.ndvi):'—',cur?`${dlong(cur.date)} · ${pct(Math.round(cur.valid_pixels_pct))} ${L2('صافٍ','clear')}`:L2('لا توجد قراءة موثوقة','No trusted reading'))}
 ${[7,30].map(k=>tile(`<i class="lg f"></i>${L2(`بعد ${k} ${k===7?'أيام':'يومًا'} · توقع`,`In ${k} days · forecast`)}`,h[k]?num(h[k].ndvi):'—',h[k]?`${rng(h[k].low80,h[k].high80)} · ${L2('نطاق','range')} ${pct(80)}`:L2('غير متاح','Not available'))).join('')}</div>`;
 const conf=f.available?`<div class="rw-kv">
  <div><small>${L2('ثقة التوقع','Forecast confidence')}</small><b class="t">${L2(REL[f.confidence][0],REL[f.confidence][1])}</b><span>${esc(ar()?f.model_ar:f.model_en)}</span></div>
  <div><small>${L2('مقارنة بالنموذج المرجعي','Versus naive reference')}</small><b>${f.backtest.beats_naive?`<bdi dir="ltr">+${f.backtest.skill_pct}%</bdi>`:'—'}</b><span>${f.backtest.beats_naive?L2(`أدق في ${f.backtest.origins} اختبارات تاريخية`,`more accurate over ${f.backtest.origins} backtests`):L2('لا يتفوّق على المرجع','does not beat naive')}</span></div>
  <div class="span2"><small>${L2('احتمال استمرار التراجع','Chance the decline continues')}</small><b class="${f.decline_probability_pct>=50?'rw-bad':''}">${f.decline_probability_pct!=null?pct(f.decline_probability_pct):'—'}</b><span>${f.decline_probability_pct!=null?L2('خلال 30 يومًا مقارنة بالقراءة الحالية','within 30 days, vs the current reading'):esc(ar()?f.decline_probability_reason_ar||'':f.decline_probability_reason_en||'')}</span></div></div>`
  :`<p>${esc(ar()?f.reason_ar:f.reason_en)}</p>`;
 const rel=REL[d.reliability]||REL.low,meta=[['',`${L2('موثوقية القراءة','Reading reliability')} ${L2(rel[0],rel[1])}`,'shield'],...(d.provisional&&d.priority!=='insufficient'?[['warn',L2('نتيجة مبدئية · الحدود غير معتمدة','Provisional · boundary not approved'),'pin']]:[])];
 const body=`<p class="rw-dr-summary">${rwSummary(d)}</p>${chipsHtml([...meta,...rwWhy(d)])}${tiles}
 <section class="rw-dsec"><div class="rw-sec-row"><h4>${L2('الاتجاه والتوقع','Trend & outlook')}</h4>${chartLegend(d.expected_ndvi!=null,d.baseline_kind)}</div>${c?rwChart(c.intel.series,f,d.expected_ndvi,{h:230,w:720,fit:fitDrawer,expLabel:expLabel(d)}):`<div class="rw-skel" style="height:200px"></div>`}</section>
 <section class="rw-dsec"><h4>${L2('موثوقية التوقع','Forecast reliability')}</h4>${conf}</section>
 <section class="rw-dsec"><h4>${L2('سبب التصنيف','Reasons for this status')}</h4><ul class="rw-ul">${(ar()?d.reasons_ar:d.reasons_en).map(r=>`<li>${esc(r)}</li>`).join('')}</ul></section>
 <section class="rw-dsec"><h4>${L2('المتابعة','Follow-up')}</h4>${s?`<div class="rw-kv">
  <div><small>${L2('موعد الفحص','Inspection date')}</small><b class="t">${dlong(s.next_check)}</b><span class="${s.overdue?'rw-bad':''}">${relDay(s.next_check)}</span></div>
  <div><small>${L2('الحالة','Status')}</small><b class="t">${schTag(s)}</b><span>${s.assignee_id?`${t('operator')} #${s.assignee_id}`:'—'}</span></div>
  <div class="span2"><small>${L2('إعادة التقييم','Reassessment')}</small><b class="t">${dlong(s.reassess_at)}</b><span>${esc(ar()?s.reason_ar:s.reason_en)}</span></div></div>`:`<p>—</p>`}</section>
 <section class="rw-dsec"><h4>${L2('الحدود','Boundary')}</h4><div class="rw-inline">${bndPill(x.boundary_status)}<span>${ha(x.area_m2)}</span></div></section>`;
 const foot=`${s&&['scheduled','in_progress'].includes(s.status)?`<button type="button" class="btn" data-action="pm-sched-done" data-id="${s.id}">${rwIcon('check',15)} ${L2('تم الفحص','Mark inspected')}</button>`:''}${reg&&s&&s.status==='scheduled'?`<button type="button" class="btn" data-action="pm-sched-edit" data-id="${s.id}">${rwIcon('cal',15)} ${L2('تعديل الموعد','Edit date')}</button>`:''}<button type="button" class="btn primary" data-action="open-area" data-id="${x.area_id}">${L2('فتح صفحة الحديقة','Open park page')} ${rwIcon(ar()?'chevL':'chevR',15)}</button>`;
 return {title:name,html:drawerFrame({eyebrow:L2('تفاصيل الحالة والتوقع والمتابعة','Status, forecast & follow-up'),title:esc(name),badge:pill(d.priority),body,foot})}}

/* ================================================================ modals */
async function pmReadingsModal(id){const rows=await api(`/areas/${id}/observations`);
 openModal(`${modalHeader(L2('سجل القراءات','Readings log'),L2('كل قراءة مع مصدرها وجودتها وسبب استبعادها إن وُجد. اضغط «المصدر» لعرض طريقة الحساب.','Every reading with origin, quality and exclusion reason.'))}
 <div class="table-wrap" style="max-height:420px;overflow:auto"><table class="data-table"><thead><tr><th>${L2('التاريخ','Date')}</th><th>NDVI</th><th>${L2('صالح %','Valid %')}</th><th>${L2('المصدر','Origin')}</th><th>${L2('الموثوقية','Reliability')}</th><th>${L2('في التحليل','Used')}</th><th></th></tr></thead><tbody>
 ${rows.slice().reverse().map(r=>`<tr><td>${esc((r.acquired_at||r.measured_at).slice(0,10))}</td><td>${num(r.ndvi)}</td><td>${r.valid_pixels_pct??'—'}</td><td>${esc(r.origin)}<br><small class="muted">${esc(r.source)}</small></td><td>${esc(r.reliability)}</td><td>${r.used_in_analysis?`<span class="rw-yes" title="${L2('مستخدمة','Used')}">${rwIcon('check',15)}<span class="rw-sr">${L2('مستخدمة','Used')}</span></span>`:`<small class="muted">${esc(r.excluded_reason||'')}</small>`}</td><td>${btn(L2('المصدر','Provenance'),'pm-prov',{id:r.id,class:'tiny'})}</td></tr>`).join('')||`<tr><td colspan="7">${t('empty')}</td></tr>`}</tbody></table></div>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button></div>`)}
async function pmProvModal(id){const p=await api(`/observations/${id}/provenance`);
 openModal(`${modalHeader(L2('كيف حُسبت هذه القراءة','How this reading was computed'),`${esc(p.source)} · ${esc((p.acquired_at||p.measured_at||'').slice(0,10))}`)}
 <pre style="white-space:pre-wrap;direction:ltr;text-align:left;max-height:420px;overflow:auto;font-size:11px;background:rgba(0,0,0,.05);padding:12px;border-radius:10px">${esc(JSON.stringify(p,null,2))}</pre>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button></div>`)}
function pmTaskExtra(task){if(S.user.role!=='regulator'||!['pending_review','closed'].includes(task.status))return '';return btn(L2('أثر التدخل','Impact'),'pm-impact',{id:task.id,class:'tiny'})}
async function pmImpactModal(id){const r=await api(`/tasks/${id}/impact`);const task=S.data.tasks.find(x=>x.id===id)||{};
 const list=xs=>xs.length?xs.map(z=>`<div class="kpi-line"><span>${dt(z.date)}</span><b>${num(z.ndvi)} <small class="muted">${z.valid_pixels_pct}%</small></b></div>`).join(''):`<p class="muted">—</p>`;
 const verdict={improved:L2('تحسّن','Improved'),declined:L2('تراجع','Declined'),no_clear_change:L2('لا تغير واضح','No clear change'),awaiting_readings:L2('بانتظار قراءات','Awaiting readings')}[r.verdict];
 openModal(`${modalHeader(L2('مقارنة المؤشرات قبل الصيانة وبعدها','Before / after indices'),esc(ar()?r.note_ar:r.note_en))}
 <div class="dashboard-grid" style="direction:inherit"><div><h4>${L2('قبل المهمة','Before')}</h4>${list(r.before)}</div><div><h4>${L2('بعد الإنجاز','After')}</h4>${list(r.after)}</div></div>
 <div class="kpi-line"><span>${L2('النتيجة','Result')}</span><b>${esc(verdict)}${r.change!=null?` (${r.change>0?'+':''}${r.change})`:''}</b></div>
 ${task.notes_before?`<div class="kpi-line"><span>${L2('ملاحظات قبل','Notes before')}</span><b>${esc(task.notes_before)}</b></div>`:''}${task.notes_after?`<div class="kpi-line"><span>${L2('ملاحظات بعد','Notes after')}</span><b>${esc(task.notes_after)}</b></div>`:''}
 ${task.review_outcome?`<div class="help-note">${L2('تقييم سابق','Previous review')}: ${esc(task.review_outcome)}${task.review_notes?' · '+esc(task.review_notes):''}</div>`:''}
 <form class="pm-form" id="pm-review-form" data-id="${id}"><label>${L2('تقييم نتيجة التدخل','Intervention outcome')}</label><select name="outcome" required><option value="effective">${L2('فعّال','Effective')}</option><option value="not_effective">${L2('غير فعّال','Not effective')}</option><option value="inconclusive">${L2('غير محسوم بعد','Inconclusive')}</option></select><label>${t('notes')}</label><input name="notes" maxlength="1000"/>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}
function pmBoundaryModal(id){const g=(PM.area[id]||PM.stale.area[id])?.bnd?.geometry||{};
 openModal(`${modalHeader(L2('تعديل حدود الحديقة','Edit park boundary'),L2('ألصق مضلع GeoJSON بإحداثيات [خط الطول، خط العرض]. يُنشئ إصدارًا جديدًا، وتُستبعد القراءات المحسوبة على الحدود السابقة حتى تُعاد المزامنة.','Paste a GeoJSON Polygon ([lon, lat]). Creates a new version; readings on the old boundary are excluded until re-synced.'))}
 <form class="pm-form" id="pm-bnd-form" data-id="${id}"><label>GeoJSON</label><textarea name="geojson" required style="min-height:160px;direction:ltr">${esc(JSON.stringify(g))}</textarea><label>${L2('مصدر الحدود','Boundary source')}</label><input name="source" required placeholder="${L2('مثال: مخطط الأمانة 2026','e.g. Municipality plan 2026')}"/><label>${t('notes')}</label><input name="notes" maxlength="1000"/>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}
function pmBoundaryReviewModal(id,decision){const b=(PM.area[id]||PM.stale.area[id])?.bnd,need=decision==='reject'||b?.validation?.placeholder;
 openModal(`${modalHeader(decision==='approve'?L2('اعتماد حدود الحديقة','Approve park boundary'):L2('رفض حدود الحديقة','Reject park boundary'),decision==='approve'?L2('الاعتماد يجعل نتائج التحليل نهائية لهذه الحديقة. اذكر المرجع الذي طابقت عليه الحدود.','Approval makes this park’s results final. State the reference you checked against.'):L2('لن تُنشأ تنبيهات تلقائية لهذه الحديقة حتى تُصحَّح حدودها.','No automatic alerts will be created until the boundary is fixed.'))}
 <form class="pm-form" id="pm-bnd-review-form" data-id="${id}" data-decision="${decision}"><label>${decision==='approve'?L2('مرجع الاعتماد','Approval reference'):L2('سبب الرفض','Reason')}${need?' *':''}</label><input name="notes" maxlength="1000" ${need?'required':''} placeholder="${decision==='approve'?L2('مثال: مطابقة لمخطط الأمانة 2026','e.g. Matches municipality plan 2026'):''}"/>
 ${decision==='approve'&&b?.validation?.placeholder?`<div class="help-note warning" style="margin-top:12px">${L2('هذه الحدود مستطيل تقريبي حول موقع الخريطة؛ يُفضّل رسم الحدود الفعلية قبل الاعتماد.','This outline is an approximate rectangle around the map pin; drawing the real outline first is recommended.')}</div>`:''}
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${decision==='approve'?L2('اعتماد','Approve'):L2('رفض الحدود','Reject boundary')}</button></div></form>`)}
function pmScheduleModal(id){const all=[...((PM.intel||PM.stale.intel)?.areas||[]).map(x=>x.schedule),...Object.values({...PM.stale.area,...PM.area}).map(c=>c?.intel?.schedule)];const s=all.find(x=>x&&x.id===id)||{};
 openModal(`${modalHeader(L2('تعديل موعد المتابعة','Edit follow-up'),L2('يبقى سبب الموعد الأصلي محفوظًا في السجل.','The original reason stays in the log.'))}<form class="pm-form" id="pm-sched-form" data-id="${id}"><label>${L2('موعد الفحص','Inspection date')}</label><input type="date" name="next_check" value="${esc(s.next_check||'')}" required/><label>${t('notes')}</label><input name="notes" value="${esc(s.notes||'')}" maxlength="1000"/>
 <div class="form-actions"><button type="button" class="btn" data-action="close-modal">${t('cancel')}</button><button type="submit" class="btn primary">${t('save')}</button></div></form>`)}

/* ================================================================ actions & forms */
async function rawaaIntelAction(act,id,el){switch(act){
 case 'pm-menu':{const m=el.closest('.rw-menu'),open=!m.classList.contains('open');closeMenus(m);m.classList.toggle('open',open);el.setAttribute('aria-expanded',String(open));return true}
 case 'pm-filter':{const p=el.dataset.p||null;PM.filter=PM.filter===p?null:p;render();return true}
 case 'pm-drawer-open':pmOpenDrawer('park',id,el.dataset.tab);return true;
 case 'pm-pred-details':pmOpenDrawer('pred',id);if(!PM.area[id])pmLoadArea(id);return true;
 case 'pm-drawer-close':pmCloseDrawer();return true;
 case 'pm-dtab':if(PM.drawer){PM.drawer.tab=el.dataset.tab;pmPaintDrawer();document.querySelector('#rw-drawer .rw-dr-body')?.scrollTo(0,0)}return true;
 case 'pm-run':await perform(async()=>{const r=await api('/pipeline/run',{method:'POST',body:{}});toast(L2(`تم التحليل: ${r.areas} حدائق، ${r.alerts_created} تنبيهات جديدة، ${r.schedules_created} مواعيد جديدة`,`${r.areas} parks analysed, ${r.alerts_created} new alerts, ${r.schedules_created} new schedule entries`))});return true;
 case 'pm-export-schedule':window.location.href='/api/reports/schedule.csv';return true;
 case 'pm-export-decisions':window.location.href='/api/reports/decisions.csv';return true;
 case 'pm-export-predictions':window.location.href='/api/reports/predictions.csv';return true;
 case 'pm-export-audit':window.location.href='/api/reports/audit.csv';return true;
 case 'pm-sched-done':await perform(async()=>{await api(`/schedule/${id}`,{method:'PATCH',body:{status:'done'}});toast(L2('سُجّل الفحص','Inspection recorded'))});return true;
 case 'pm-sched-edit':pmScheduleModal(id);return true;
 case 'pm-bnd-approve':pmBoundaryReviewModal(id,'approve');return true;
 case 'pm-bnd-reject':pmBoundaryReviewModal(id,'reject');return true;
 case 'pm-bnd-edit':pmBoundaryModal(id);return true;
 case 'pm-readings':try{await pmReadingsModal(id||S.areaId)}catch(e){toast(e.message,true)}return true;
 case 'pm-prov':try{await pmProvModal(id)}catch(e){toast(e.message,true)}return true;
 case 'pm-impact':try{await pmImpactModal(id)}catch(e){toast(e.message,true)}return true;
 }return false}
async function rawaaIntelSubmit(form){const f=new FormData(form),id=Number(form.dataset.id);
 if(form.id==='pm-review-form')return perform(async()=>{await api(`/tasks/${id}/review`,{method:'POST',body:{outcome:f.get('outcome'),notes:f.get('notes')||''}});toast(L2('حُفظ التقييم','Review saved'))});
 if(form.id==='pm-sched-form')return perform(async()=>{await api(`/schedule/${id}`,{method:'PATCH',body:{next_check:f.get('next_check'),notes:f.get('notes')||''}});toast(t('save'))});
 if(form.id==='pm-bnd-review-form')return perform(async()=>{const r=await api(`/areas/${id}/boundary/review`,{method:'POST',body:{decision:form.dataset.decision,notes:f.get('notes')||''}});toast(r.status==='approved'?L2('اعتُمدت الحدود','Boundary approved'):L2('سُجّل قرار الحدود','Boundary decision saved'))});
 if(form.id==='pm-bnd-form'){let geometry;try{geometry=JSON.parse(f.get('geojson'))}catch{toast('GeoJSON',true);return}
  return perform(async()=>{const r=await api(`/areas/${id}/boundary`,{method:'PUT',body:{geometry,source:f.get('source'),notes:f.get('notes')||''}});toast(L2(`حُفظ الإصدار ${r.version} من الحدود`,`Boundary v${r.version} saved`))})}}

/* Menus close on outside click / after choosing; the side panel closes when the user navigates away or presses Esc. */
document.addEventListener('click',e=>{const tg=e.target;if(!tg.closest?.('.rw-menu'))closeMenus();else if(tg.closest('.rw-menu-item'))setTimeout(()=>closeMenus(),0);
 if(tg.closest?.('[data-view],[data-action=back-areas],[data-action=open-area],[data-action=logout]'))PM.drawer=null},true);
let RW_RW=window.innerWidth,RW_RT;window.addEventListener('resize',()=>{clearTimeout(RW_RT);RW_RT=setTimeout(()=>{if(Math.abs(window.innerWidth-RW_RW)<60)return;RW_RW=window.innerWidth;
 if(S.user&&(S.view==='area'||PM.drawer))render()},300)});
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;if(document.querySelector('.rw-menu.open')){closeMenus();return}if(!S.modal&&PM.drawer)pmCloseDrawer()});
