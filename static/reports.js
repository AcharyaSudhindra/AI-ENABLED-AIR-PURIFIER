const el=(id)=>document.getElementById(id);
const c=new Chart(el('dailyChart').getContext('2d'),{type:'bar',data:{labels:[],datasets:[{label:'Avg AQI',data:[],backgroundColor:'rgba(47,215,161,.64)'},{label:'Peak AQI',data:[],backgroundColor:'rgba(242,178,79,.68)'}]},options:{plugins:{legend:{labels:{color:'#eef5ff'}}},scales:{x:{ticks:{color:'#c2cde0'}},y:{ticks:{color:'#c2cde0'}}}}});

async function load(){
 const s=await fetch('/api/reports/summary').then(r=>r.json());
 el('avgAqi').textContent=Math.round(s.avg_aqi||0);
 el('peakAqi').textContent=Math.round(s.peak_aqi||0);
 el('avgVolt').textContent=((s.avg_voltage||0).toFixed(2));
 el('samples').textContent=s.total_samples||0;

 const d=await fetch('/api/reports/daily?days=7').then(r=>r.json());
 c.data.labels=d.map(x=>x.day).reverse();
 c.data.datasets[0].data=d.map(x=>Number(x.avg_aqi||0)).reverse();
 c.data.datasets[1].data=d.map(x=>Number(x.peak_aqi||0)).reverse();
 c.update();

 let html='<table><tr><th>Day</th><th>Avg AQI</th><th>Peak</th><th>Min</th><th>Avg Volt</th><th>Fan ON %</th><th>Samples</th></tr>';
 d.forEach(x=>{const pct=x.samples?((x.fan_on_samples/x.samples)*100):0; html+=`<tr><td>${x.day}</td><td>${Number(x.avg_aqi||0).toFixed(1)}</td><td>${x.peak_aqi}</td><td>${x.min_aqi}</td><td>${Number(x.avg_voltage||0).toFixed(2)}</td><td>${pct.toFixed(1)}%</td><td>${x.samples}</td></tr>`;});
 html+='</table>';
 el('dailyTable').innerHTML=html;
}
load();
