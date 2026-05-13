const log = document.getElementById('chatLog');
const input = document.getElementById('chatInput');
const btn = document.getElementById('sendBtn');
const chips = document.querySelectorAll('.chip');

function append(type, text) {
  const d = document.createElement('div');
  d.className = `msg ${type}`;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

function typing(on) {
  let t = document.getElementById('typing');
  if (on) {
    if (!t) {
      t = document.createElement('div');
      t.id = 'typing';
      t.className = 'msg bot typing';
      t.textContent = 'Assistant is thinking...';
      log.appendChild(t);
      log.scrollTop = log.scrollHeight;
    }
  } else if (t) {
    t.remove();
  }
}

async function ask(question) {
  const m = question.trim();
  if (!m) return;
  append('user', m);
  input.value = '';
  typing(true);
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: m })
    });
    const j = await r.json();
    typing(false);
    append('bot', j.reply || 'No response');
  } catch {
    typing(false);
    append('bot', 'Unable to reach assistant right now. Please try again.');
  }
}

btn.addEventListener('click', () => ask(input.value));
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') ask(input.value); });
chips.forEach((c) => c.addEventListener('click', () => ask(c.dataset.q || 'current status')));

append('bot', 'Welcome. I can analyze current AQI, daily trends, and suggest fan/air-quality actions in real time.');
