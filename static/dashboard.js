const q = (id) => document.getElementById(id);
const lastVals = {};

const chart = new Chart(q("trend").getContext("2d"), {type:"line",data:{labels:[],datasets:[{label:"AQI",data:[],borderColor:"#2fd7a1",tension:.3,pointRadius:0},{label:"Voltage",data:[],borderColor:"#f2b24f",tension:.3,pointRadius:0}]},options:{animation:{duration:520,easing:'easeOutCubic'},plugins:{legend:{labels:{color:"#eef5ff"}}},scales:{x:{ticks:{color:"#c2cde0"}},y:{ticks:{color:"#c2cde0"}}}}});
const predictChart = new Chart(q("predictChart").getContext("2d"), {type:"line",data:{labels:[],datasets:[{label:"Predicted AQI",data:[],borderColor:"#f2b24f",backgroundColor:"rgba(242,178,79,.22)",fill:true,tension:.35,pointRadius:1}]},options:{animation:{duration:650,easing:'easeOutQuart'},plugins:{legend:{labels:{color:"#eef5ff"}}},scales:{x:{ticks:{color:"#c2cde0"}},y:{ticks:{color:"#c2cde0"}}}}});
let pollTimer = null;

function toast(msg){
  const t = q('appToast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}

function removeSkeleton(id){
  const el = q(id);
  if (el) el.classList.remove('skeleton');
}

function removeAllSkeletons(){
  document.querySelectorAll('.skeleton').forEach(el => el.classList.remove('skeleton'));
}

function updateConnDot(source){
  const dot = q('connDot');
  const label = q('connLabel');
  if (!dot || !label) return;
  dot.classList.remove('online','offline','stale');
  if (source === 'esp32') {
    dot.classList.add('online');
    label.textContent = 'ESP32 Live';
  } else if (source === 'esp32-stale') {
    dot.classList.add('stale');
    label.textContent = 'ESP32 Stale';
  } else if (source === 'esp32-offline') {
    dot.classList.add('offline');
    label.textContent = 'ESP32 Offline';
  } else if (source === 'mock') {
    dot.classList.add('online');
    label.textContent = 'Mock Data';
  } else {
    dot.classList.add('offline');
    label.textContent = source || 'Unknown';
  }
}

function pulseValue(id, value){
  const el = q(id);
  if (!el) return;
  if (lastVals[id] !== value){
    lastVals[id] = value;
    const card = el.closest('.card') || el.closest('.panel') || el;
    card.classList.remove('live-pulse');
    void card.offsetWidth;
    card.classList.add('live-pulse');
  }
}

function animateNumber(el, to, suffix=''){
  if (!el || !Number.isFinite(to)) return;
  const from = Number(el.dataset.prevVal || 0);
  const start = performance.now();
  const dur = 420;
  function frame(t){
    const p = Math.min(1, (t-start)/dur);
    const eased = 1 - Math.pow(1-p, 3);
    const val = from + (to - from) * eased;
    el.textContent = (Math.abs(to) >= 100 ? val.toFixed(0) : val.toFixed(1)) + suffix;
    if (p < 1) requestAnimationFrame(frame);
    else el.dataset.prevVal = String(to);
  }
  requestAnimationFrame(frame);
}

function setRing(id, pct){
  const el = q(id);
  if (!el) return;
  const p = Math.max(0, Math.min(100, pct));
  el.style.setProperty('--pct', p);
}

function alerts(s){
  const out=[];
  if(s.aqi>150) out.push(["bad",`Hazardous AQI ${s.aqi}. Keep purifier ON and ventilate.`]);
  else if(s.aqi>100) out.push(["warn",`Unhealthy AQI ${s.aqi}. Limit prolonged exposure.`]);
  else out.push(["good",`Air quality is ${s.aqi_label}.`]);
  if(s.voltage>=s.threshold_voltage) out.push(["warn","MQ135 above threshold, fan should remain active."]);
  return out;
}

let particleInterval = null;
let currentFanState = null;
function updateParticles(isFanOn) {
  if (currentFanState === isFanOn && particleInterval) return;
  currentFanState = isFanOn;
  if (particleInterval) clearInterval(particleInterval);
  const container = q('particles-container');
  if (!container) return;
  
  const intervalMs = isFanOn ? 120 : 800;
  particleInterval = setInterval(() => {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.left = Math.random() * 100 + 'vw';
    const duration = isFanOn ? (2 + Math.random() * 3) : (6 + Math.random() * 4);
    p.style.setProperty('--duration', duration + 's');
    const size = isFanOn ? (3 + Math.random() * 5) : (2 + Math.random() * 3);
    p.style.width = p.style.height = size + 'px';
    if (!isFanOn) p.style.background = 'rgba(114,240,201,.2)';
    container.appendChild(p);
    setTimeout(() => p.remove(), duration * 1000);
  }, intervalMs);
}

function renderLive(live){
  removeAllSkeletons();
  const noData = live.source === "esp32-offline" && Number(live.aqi || 0) === 0 && Number(live.pm25 || 0) === 0 && Number(live.voltage || 0) === 0;
  const offline = live.source === "esp32-offline";
  const aqiEl = q('aqi');
  const pmEl = q('pm25');
  const tempEl = q('temp');
  const humEl = q('hum');

  document.body.classList.remove('drama-warn', 'drama-bad');
  if (!noData) {
    if (Number(live.aqi) > 150) document.body.classList.add('drama-bad');
    else if (Number(live.aqi) > 100) document.body.classList.add('drama-warn');
  }

  updateConnDot(live.source);

  if (noData){
    if (aqiEl) aqiEl.textContent = '--';
    if (pmEl) pmEl.textContent = '--';
    if (tempEl) tempEl.textContent = '--';
    if (humEl) humEl.textContent = '--';
  } else {
    animateNumber(aqiEl, Number(live.aqi || 0));
    animateNumber(pmEl, Number(live.pm25 || 0));
    animateNumber(tempEl, Number(live.temperature_c || 0));
    animateNumber(humEl, Number(live.humidity || 0));
    setRing('aqiRing', (Number(live.aqi||0)/500)*100);
  }

  q('aqiLabel').textContent = noData ? "Waiting for ESP32" : live.aqi_label;
  const fanBadge = q('fanStatus');
  if (fanBadge) {
    if (noData) {
      fanBadge.textContent = "--";
      fanBadge.className = "fan-badge skeleton";
    } else {
      fanBadge.textContent = live.fan_on ? "ON" : "OFF";
      fanBadge.className = `fan-badge ${live.fan_on ? 'fan-on' : 'fan-off'}`;
    }
  }
  q('mode').textContent = noData ? "Mode --" : `Mode ${live.mode.toUpperCase()}`;
  q('source').textContent = live.source === "esp32-stale" ? "esp32 (stale)" : live.source;
  q('time').textContent=live.timestamp;

  const fanIcon = q('fanIcon');
  if (fanIcon) {
    fanIcon.classList.toggle('spin', !!live.fan_on && !noData);
  }
  
  updateParticles(!!live.fan_on && !noData);

  pulseValue('aqi', live.aqi);
  pulseValue('pm25', live.pm25);
  pulseValue('temp', live.temperature_c);
  pulseValue('hum', live.humidity);
  pulseValue('fanStatus', live.fan_on);
  pulseValue('source', live.source);
}

async function refreshHistory(){
  try {
    const hist=await fetch('/api/history?points=60').then(r=>r.json());
    if (hist.length > 0) {
      chart.data.labels=hist.map(x=>x.timestamp.slice(11));
      chart.data.datasets[0].data=hist.map(x=>x.aqi);
      chart.data.datasets[1].data=hist.map(x=>x.voltage);
      chart.update();
    }
  } catch(e) {
    console.warn('History fetch failed:', e);
  }
}

async function refreshPredict(){
  try {
    const p = await fetch('/api/predict?horizon=12').then(r=>r.json());
    const points = p.points || [];
    predictChart.data.labels = points.map(x => x.time);
    predictChart.data.datasets[0].data = points.map(x => x.aqi);
    predictChart.update();
  } catch(e) {
    console.warn('Predict fetch failed:', e);
  }
}

async function refreshFilterHealth(){
  try {
    const f = await fetch('/api/filter-health').then(r=>r.json());
    const health = Number(f.health_pct||0);
    q('filterHealth').textContent = `${health.toFixed(1)}%`;
    q('filterStatus').textContent = f.status || '--';
    q('filterRuntime').textContent = `${Number(f.runtime_hours||0).toFixed(2)} h`;
    q('filterLoad').textContent = Number(f.load_score||0).toFixed(1);
    q('filterRingVal').textContent = `${health.toFixed(0)}%`;
    setRing('filterRing', health);
    pulseValue('filterHealth', health);
  } catch(e) {
    console.warn('Filter health fetch failed:', e);
  }
}

function renderAlerts(live){
  const box=q('alerts'); box.innerHTML='';
  const noData = Number(live.aqi || 0) === 0 && Number(live.pm25 || 0) === 0 && Number(live.voltage || 0) === 0;
  const offline = live.source === "esp32-offline" && noData;
  const stale = live.source === "esp32-stale";
  if (offline) {
    const li=document.createElement('li');
    li.className='bad';
    li.textContent='ESP32 is offline or IP is not configured. Set ESP32_BASE_URL (or ESP32_IP) and reconnect Wi-Fi.';
    box.appendChild(li);
    if (live.esp32_error) {
      const err=document.createElement('li');
      err.className='warn';
      err.textContent=`Last error: ${live.esp32_error}`;
      box.appendChild(err);
    }
  } else if (stale || live.source === "esp32-offline") {
    const li=document.createElement('li');
    li.className='warn';
    li.textContent='Showing last saved sensor values (ESP32 temporarily unreachable).';
    box.appendChild(li);
    if (live.esp32_error) {
      const err=document.createElement('li');
      err.className='warn';
      err.textContent=`Last error: ${live.esp32_error}`;
      box.appendChild(err);
    }
  } else {
    alerts(live).forEach(([cls,msg])=>{ const li=document.createElement('li'); li.className=cls; li.textContent=msg; box.appendChild(li);});
  }
}

async function refresh(){
  try {
    const live=await fetch('/api/live').then(r=>r.json());
    renderLive(live);
    renderAlerts(live);
    await refreshHistory();
    await refreshPredict();
    await refreshFilterHealth();
  } catch(e) {
    console.warn('Refresh failed:', e);
    updateConnDot('esp32-offline');
  }
}

function startRealtime(){
  if (window.EventSource) {
    const source = new EventSource('/api/stream');
    source.onmessage = async (evt) => {
      try {
        const live = JSON.parse(evt.data);
        renderLive(live);
        renderAlerts(live);
        await refreshHistory();
        await refreshPredict();
        await refreshFilterHealth();
      } catch(e) {
        console.warn('SSE message error:', e);
      }
    };
    source.onerror = () => {
      source.close();
      if (!pollTimer) {
        pollTimer = setInterval(refresh, 2500);
      }
    };
  } else {
    pollTimer = setInterval(refresh, 2500);
  }
  refresh();
}

startRealtime();

if (window.USER_ROLE !== 'admin') {
  const b = q('resetFilterBtn');
  if (b) b.style.display = 'none';
}
q('resetFilterBtn')?.addEventListener('click', async () => {
  try {
    await fetch('/api/filter/reset', { method: 'POST' });
    await refreshFilterHealth();
    toast('Filter counter reset');
  } catch(e) {
    toast('Failed to reset filter');
  }
});
