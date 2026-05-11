const q = (id) => document.getElementById(id);
const chart = new Chart(q("trend").getContext("2d"), {type:"line",data:{labels:[],datasets:[{label:"AQI",data:[],borderColor:"#42d7ff",tension:.3,pointRadius:0},{label:"Voltage",data:[],borderColor:"#3ee0a2",tension:.3,pointRadius:0}]},options:{plugins:{legend:{labels:{color:"#eef5ff"}}},scales:{x:{ticks:{color:"#c2cde0"}},y:{ticks:{color:"#c2cde0"}}}}});

function alerts(s){
  const out=[];
  if(s.aqi>150) out.push(["bad",`Hazardous AQI ${s.aqi}. Keep purifier ON and ventilate.`]);
  else if(s.aqi>100) out.push(["warn",`Unhealthy AQI ${s.aqi}. Limit prolonged exposure.`]);
  else out.push(["good",`Air quality is ${s.aqi_label}.`]);
  if(s.voltage>=s.threshold_voltage) out.push(["warn","Sensor above threshold, fan should remain active."]);
  return out;
}

async function refresh(){
  const live=await fetch('/api/live').then(r=>r.json());
  q('aqi').textContent=live.aqi;
  q('aqiLabel').textContent=live.aqi_label;
  q('voltage').textContent=`${live.voltage.toFixed(2)} V`;
  q('fan').textContent=live.fan_on?"ON":"OFF";
  q('mode').textContent=`Mode ${live.mode.toUpperCase()}`;
  q('source').textContent=live.source;
  q('time').textContent=live.timestamp;

  const hist=await fetch('/api/history?points=60').then(r=>r.json());
  chart.data.labels=hist.map(x=>x.timestamp.slice(11));
  chart.data.datasets[0].data=hist.map(x=>x.aqi);
  chart.data.datasets[1].data=hist.map(x=>x.voltage);
  chart.update();

  const box=q('alerts'); box.innerHTML='';
  alerts(live).forEach(([cls,msg])=>{ const li=document.createElement('li'); li.className=cls; li.textContent=msg; box.appendChild(li);});
}
setInterval(refresh,2500); refresh();
