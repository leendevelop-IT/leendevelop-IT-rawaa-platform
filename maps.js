/* Real map sources only. A failed provider never becomes a fabricated basemap. */
function buildMap(){
 const id=S.view==='dashboard'?'dashboard-map':S.view==='map'?'full-map':S.view==='area'?'area-map':null,el=id&&document.getElementById(id);if(!el)return;el.replaceChildren();
 const fail=message=>{let box=el.querySelector('.map-error');if(!box){box=document.createElement('div');box.className='map-error';box.setAttribute('role','status');el.appendChild(box)}box.innerHTML=`<p>${esc(message)}</p>${btn(ar()?'إعادة المحاولة':'Retry','retry-map')}`};
 buildRasterMap(el,fail);
}

async function loadCopernicusOverlay(map,say,layer){
 const a=selectedArea();if(!a)return;const month=S.mapMonth,mode=layer==='ndvi'?'ndvi':'true_color',key=`${a.id}:${month}:${mode}`;say(t('copernicusLoading'));
 try{const obj=S.imageryCache[key]||(S.imageryCache[key]=await api(`/areas/${a.id}/imagery`,{method:'POST',body:{month,layer:mode}}));if(S.map!==map)return;
 const [w,s,e,n]=obj.bounds;map.addSource('sentinel-image',{type:'image',url:obj.image_data_url,coordinates:[[w,n],[e,n],[e,s],[w,s]]});map.addLayer({id:'sentinel-image',type:'raster',source:'sentinel-image',paint:{'raster-opacity':layer==='ndvi'?.8:1}},'rawaa-fill');
 say(`Copernicus Sentinel-2 · ${month} · `+(ar()?'تركيب للفترة المحددة؛ ليس تاريخ التقاط منفردًا':'Composite for selected period; not a single acquisition')+(layer==='ndvi'?' · NDVI: <0.08 red | 0.08–0.20 orange | 0.20–0.35 yellow | 0.35–0.55 green | ≥0.55 dark green':''));
 }catch(e){if(S.map===map)say(t('copernicusFailed')+' · '+e.message)}
}
/* Leaflet map. With Copernicus connected, the map itself is Sentinel-2 L2A (Copernicus Browser-style tiles served by
   /api/tiles, any of the 8 layers, filtered by month and max cloud cover). Esri imagery sits underneath outside the Jeddah tile region. */
function buildRasterMap(el,fail){
 el.replaceChildren();if(!window.L){fail(ar()?'محرك الخرائط غير متاح.':'Map engine unavailable.');return}
 const map=window.L.map(el,{scrollWheelZoom:S.view!=='dashboard',minZoom:5}).setView([21.553,39.187],11);S.map=map;
 const mode=S.mapLayer;const s2=typeof s2Layer==='function'&&s2Layer(mode);const live=!!(s2&&S.data.integration);
 let satellite=mode==='satellite'||!!s2,errors=0,loaded=0,timer,base,s2tiles,s2errors=0;
 const status=document.createElement('div');status.className='map-status';status.setAttribute('role','status');el.appendChild(status);
 const say=message=>{status.textContent=message;const node=document.getElementById('map-layer-source');if(node)node.textContent=message};
 function addBase(isSatellite){satellite=isSatellite;errors=0;loaded=0;if(base)map.removeLayer(base);base=window.L.tileLayer(isSatellite?'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}':'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:18,attribution:isSatellite?'Tiles © Esri · Vantor · Earthstar Geographics · GIS User Community':'Tiles © Esri · HERE · Garmin · USGS · Intermap · increment P · OpenStreetMap contributors · GIS User Community'});
 if(!live)say(isSatellite?(ar()?'Esri World Imagery · تاريخ الالتقاط غير متاح · ليست NDVI':'Esri World Imagery · capture date unavailable · not NDVI'):(ar()?'Esri World Street Map · خريطة الشوارع':'Esri World Street Map · Street map'));
 if(s2&&!S.data.integration)say(status.textContent+' · '+(ar()?'طبقات Sentinel-2 داخل رواء تحتاج مفاتيح Copernicus في الخادم':'Sentinel-2 layers need Copernicus keys on the server'));
 base.on('tileload',()=>{loaded++;el.dataset.tilesLoaded='true';clearTimeout(timer);el.querySelector('.map-error')?.remove()});
 base.on('tileerror',()=>{if(++errors>=3&&!live){if(satellite){addBase(false);say(status.textContent+' · '+(ar()?'تعذر مصدر الصور؛ تم الرجوع للشوارع':'Imagery failed; using streets'))}else fail(ar()?'تعذر تحميل خريطة الشوارع. بيانات المناطق متاحة أدناه.':'Street tiles unavailable. Area data remains available below.')}});base.addTo(map);
 clearTimeout(timer);timer=setTimeout(()=>{if(S.map===map&&!loaded)fail(ar()?'انتهت مهلة تحميل الخريطة؛ أعد المحاولة.':'Map loading timed out; retry.')},20000)}addBase(satellite);map.on('unload',()=>clearTimeout(timer));
 if(live){
  const name=ar()?s2[1]:s2[2];
  s2tiles=window.L.tileLayer(`/api/tiles/${mode}/{z}/{x}/{y}.png?month=${encodeURIComponent(S.mapMonth)}&cc=${S.mapCC}`,{minZoom:9,maxNativeZoom:17,maxZoom:18,zIndex:5,attribution:`Contains modified Copernicus Sentinel data ${S.mapMonth.slice(0,4)} · Copernicus Data Space Ecosystem`}).addTo(map);
  say(`Copernicus Sentinel-2 L2A · ${name} · ${S.mapMonth} · ${ar()?'غيوم':'clouds'} ≤ ${S.mapCC}%`+(map.getZoom()<9?' · '+(ar()?'قرّب الخريطة لعرض الطبقة':'zoom in to see the layer'):''));
  s2tiles.on('tileload',()=>{loaded++;clearTimeout(timer)});
  s2tiles.on('tileerror',()=>{if(++s2errors===3)say(`${t('copernicusFailed')} · ${ar()?'تعذر تحميل بعض بلاطات Sentinel-2 (قد تكون الحصة أو الشهر بلا صور)':'Some Sentinel-2 tiles failed (quota, or no scenes for this month)'}`)});
  map.on('zoomend',()=>{if(map.getZoom()<9)say(ar()?'قرّب الخريطة (مستوى ٩ فأكثر) لعرض طبقة Sentinel-2 لمنطقة جدة':'Zoom in (level 9+) to see the Sentinel-2 layer over Jeddah')});
 }
 for(const a of (S.view==='area'?[selectedArea()].filter(Boolean):S.data.areas)){const color=({stable:'#36ba80',monitor:'#e4ad4c',high:'#d96a62'})[a.metrics.status]||'#9eafb0';const polygon=window.L.geoJSON(a.geometry,{style:{color,weight:live?2.5:3,fillOpacity:live?0.03:.2}}).addTo(map);polygon.bindPopup(`<b>${esc(areaLabel(a))}</b><p>${origin(a)} · NDVI ${fmt(a.metrics.current_ndvi)}</p>${btn(t('areaDetails'),'open-area',{id:a.id})} <a class="btn tiny" href="${esc(copernicusBrowserUrl(a,s2?mode:'ndvi'))}" target="_blank" rel="noopener">Copernicus Browser ↗</a>`);window.L.marker(polygon.getBounds().getCenter(),{icon:window.L.divIcon({className:'map-marker',html:esc(areaLabel(a).split(' ').at(-1)),iconSize:[30,30]})}).bindPopup(polygon.getPopup()).addTo(map);if((S.mapFocus||S.view==='area')&&a.id===S.areaId)map.fitBounds(polygon.getBounds(),{padding:[65,65],maxZoom:15})}
 const label=document.createElement('div');label.className='map-demo';label.textContent=t('demoBoundaries');el.appendChild(label);
}
