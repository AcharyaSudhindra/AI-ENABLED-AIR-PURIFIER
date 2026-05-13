const q = (id) => document.getElementById(id);
const chart = new Chart(q("trend").getContext("2d"), {type:"line",data:{labels:[],datasets:[{label:"AQI",data:[],borderColor:"#45b7ff",tension:.3,pointRadius:0},{label:"Voltage",data:[],borderColor:"#ff9f43",tension:.3,pointRadius:0}]},options:{plugins:{legend:{labels:{color:"#eef5ff"}}},scales:{x:{ticks:{color:"#c2cde0"}},y:{ticks:{color:"#c2cde0"}}}}});
const predictChart = new Chart(q("predictChart").getContext("2d"), {type:"line",data:{labels:[],datasets:[{label:"Predicted AQI",data:[],borderColor:"#ff9f43",backgroundColor:"rgba(255,159,67,.2)",fill:true,tension:.35,pointRadius:1}]},options:{plugins:{legend:{labels:{color:"#eef5ff"}}},scales:{x:{ticks:{color:"#c2cde0"}},y:{ticks:{color:"#c2cde0"}}}}});
let pollTimer = null;

function alerts(s){
  const out=[];
  if(s.aqi>150) out.push(["bad",`Hazardous AQI ${s.aqi}. Keep purifier ON and ventilate.`]);
  else if(s.aqi>100) out.push(["warn",`Unhealthy AQI ${s.aqi}. Limit prolonged exposure.`]);
  else out.push(["good",`Air quality is ${s.aqi_label}.`]);
  if(s.voltage>=s.threshold_voltage) out.push(["warn","MQ135 above threshold, fan should remain active."]);
  return out;
}

function renderLive(live){
  const offline = live.source === "esp32-offline";
  q('aqi').textContent = offline ? "--" : live.aqi;
  q('aqiLabel').textContent = offline ? "Waiting for ESP32" : live.aqi_label;
  q('pm25').textContent = offline ? "--" : `${Number(live.pm25 || 0).toFixed(1)}`;
  q('fan').textContent = offline ? "--" : (live.fan_on ? "ON" : "OFF");
  q('mode').textContent = offline ? "Mode --" : `Mode ${live.mode.toUpperCase()}`;
  q('source').textContent = live.source === "esp32-stale" ? "esp32 (stale)" : live.source;
  q('time').textContent=live.timestamp;

}

async function refreshHistory(){
  const hist=await fetch('/api/history?points=60').then(r=>r.json());
  if (hist.length > 0) {
    chart.data.labels=hist.map(x=>x.timestamp.slice(11));
    chart.data.datasets[0].data=hist.map(x=>x.aqi);
    chart.data.datasets[1].data=hist.map(x=>x.voltage);
    chart.update();
  }
}

async function refreshPredict(){
  const p = await fetch('/api/predict?horizon=12').then(r=>r.json());
  const points = p.points || [];
  predictChart.data.labels = points.map(x => x.time);
  predictChart.data.datasets[0].data = points.map(x => x.aqi);
  predictChart.update();
}

async function refreshFilterHealth(){
  const f = await fetch('/api/filter-health').then(r=>r.json());
  q('filterHealth').textContent = `${Number(f.health_pct||0).toFixed(1)}%`;
  q('filterStatus').textContent = f.status || '--';
  q('filterRuntime').textContent = `${Number(f.runtime_hours||0).toFixed(2)} h`;
  q('filterLoad').textContent = Number(f.load_score||0).toFixed(1);
}

function renderAlerts(live){
  const box=q('alerts'); box.innerHTML='';
  const offline = live.source === "esp32-offline";
  if (offline) {
    const li=document.createElement('li');
    li.className='bad';
    li.textContent='ESP32 is offline or IP is not configured. Set ESP32_BASE_URL and reconnect Wi-Fi.';
    box.appendChild(li);
  } else {
    alerts(live).forEach(([cls,msg])=>{ const li=document.createElement('li'); li.className=cls; li.textContent=msg; box.appendChild(li);});
  }
}

async function refresh(){
  const live=await fetch('/api/live').then(r=>r.json());
  renderLive(live);
  renderAlerts(live);
  await refreshHistory();
  await refreshPredict();
  await refreshFilterHealth();
}

function startRealtime(){
  if (window.EventSource) {
    const source = new EventSource('/api/stream');
    source.onmessage = async (evt) => {
      const live = JSON.parse(evt.data);
      renderLive(live);
      renderAlerts(live);
      await refreshHistory();
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
  await fetch('/api/filter/reset', { method: 'POST' });
  await refreshFilterHealth();
});
