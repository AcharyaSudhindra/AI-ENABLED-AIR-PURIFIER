const log = document.getElementById('chatLog');
const input = document.getElementById('chatInput');
const btn = document.getElementById('sendBtn');
const chips = document.querySelectorAll('.chip');
const apiKeyInput = document.getElementById('apiKeyInput');
const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
const apiKeyStatus = document.getElementById('apiKeyStatus');

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
  btn.disabled = true;
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
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

btn.addEventListener('click', () => ask(input.value));
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') ask(input.value); });
chips.forEach((c) => c.addEventListener('click', () => ask(c.dataset.q || 'current status')));

async function loadApiKeyStatus() {
  if (!apiKeyStatus) return;
  try {
    const r = await fetch('/api/chatbot/key');
    const j = await r.json();
    if (j.configured) {
      apiKeyStatus.textContent = `Key status: configured (${j.masked || 'hidden'})`;
    } else {
      apiKeyStatus.textContent = 'Key status: not set';
    }
  } catch {
    apiKeyStatus.textContent = 'Key status: unavailable';
  }
}

async function saveApiKey() {
  if (!apiKeyInput || !apiKeyStatus) return;
  const apiKey = (apiKeyInput.value || '').trim();
  if (!apiKey) {
    apiKeyStatus.textContent = 'Enter a key first.';
    return;
  }
  try {
    const r = await fetch('/api/chatbot/key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey })
    });
    const j = await r.json();
    if (!r.ok) {
      apiKeyStatus.textContent = j.error || 'Failed to save key';
      return;
    }
    apiKeyInput.value = '';
    apiKeyStatus.textContent = `Key status: configured (${j.masked || 'hidden'})`;
  } catch {
    apiKeyStatus.textContent = 'Failed to save key';
  }
}

saveApiKeyBtn?.addEventListener('click', saveApiKey);
apiKeyInput?.addEventListener('keydown', (e) => { if (e.key === 'Enter') saveApiKey(); });

append('bot', 'Welcome. I can analyze current AQI, daily trends, and suggest fan/air-quality actions in real time.');
loadApiKeyStatus();
