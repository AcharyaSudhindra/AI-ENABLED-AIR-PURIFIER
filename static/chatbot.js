const log=document.getElementById('chatLog');
const input=document.getElementById('chatInput');
const btn=document.getElementById('sendBtn');

function append(type,text){
  const d=document.createElement('div');
  d.className=`msg ${type}`;
  d.textContent=text;
  log.appendChild(d);
  log.scrollTop=log.scrollHeight;
}

async function send(){
  const m=input.value.trim();
  if(!m) return;
  append('user',m);
  input.value='';
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});
  const j=await r.json();
  append('bot',j.reply||'No response');
}

btn.addEventListener('click',send);
input.addEventListener('keydown',e=>{if(e.key==='Enter') send();});
append('bot','Welcome. Ask me: "current status", "daily report", or "tips".');
