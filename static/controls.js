const id=(x)=>document.getElementById(x);
async function loadSettings(){
  const s=await fetch('/api/settings').then(r=>r.json());
  id('modeSelect').value=s.mode;
  id('thresholdRange').value=s.threshold_voltage;
  id('thresholdText').textContent=`${Number(s.threshold_voltage).toFixed(2)} V`;
  id('refreshSelect').value=String(s.refresh_ms);
}
async function save(p){
  const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const j=await r.json();
  id('saveMsg').textContent=j.error?j.error:'Saved';
}
id('modeSelect').addEventListener('change',e=>save({mode:e.target.value}));
id('thresholdRange').addEventListener('input',e=>id('thresholdText').textContent=`${Number(e.target.value).toFixed(2)} V`);
id('thresholdRange').addEventListener('change',e=>save({threshold_voltage:Number(e.target.value)}));
id('refreshSelect').addEventListener('change',e=>save({refresh_ms:Number(e.target.value)}));

if(window.USER_ROLE==='admin'){
  id('fanOn')?.addEventListener('click',()=>fetch('/api/fan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:true})}));
  id('fanOff')?.addEventListener('click',()=>fetch('/api/fan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:false})}));
}
loadSettings();
