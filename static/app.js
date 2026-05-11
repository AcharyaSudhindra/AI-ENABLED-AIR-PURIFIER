const byId = (id) => document.getElementById(id);

let refreshMs = 2000;
let timer = null;

const ctx = byId("trendChart").getContext("2d");
const trendChart = new Chart(ctx, {
  type: "line",
  data: {
    labels: [],
    datasets: [
      { label: "AQI", data: [], borderColor: "#4fd1ff", tension: 0.35, pointRadius: 0 },
      { label: "Voltage", data: [], borderColor: "#17c387", tension: 0.35, pointRadius: 0 }
    ]
  },
  options: {
    responsive: true,
    plugins: { legend: { labels: { color: "#ecf4ff" } } },
    scales: {
      x: { ticks: { color: "#b8c6df" } },
      y: { ticks: { color: "#b8c6df" } }
    }
  }
});

function buildAlerts(sample) {
  const alerts = [];
  if (sample.aqi > 150) alerts.push({ t: `Hazardous AQI (${sample.aqi}). Run fan high and ventilate.`, c: "bad" });
  else if (sample.aqi > 100) alerts.push({ t: `Unhealthy AQI (${sample.aqi}). Sensitive people should limit exposure.`, c: "warn" });
  else alerts.push({ t: `Air quality is stable (${sample.aqi_label}).`, c: "good" });

  if (sample.voltage >= sample.threshold_voltage) alerts.push({ t: "Sensor is above threshold, purifier should stay active.", c: "warn" });
  return alerts;
}

function renderSample(sample) {
  byId("aqiValue").textContent = sample.aqi;
  byId("aqiLabel").textContent = sample.aqi_label;
  byId("voltageValue").textContent = `${sample.voltage.toFixed(2)} V`;
  byId("fanValue").textContent = sample.fan_on ? "ON" : "OFF";
  byId("modeLabel").textContent = `Mode: ${sample.mode.toUpperCase()}`;
  byId("adcValue").textContent = sample.adc;
  byId("sourceChip").textContent = `Source: ${sample.source}`;
  byId("lastSeen").textContent = `Last update: ${sample.timestamp}`;

  const list = byId("alerts");
  list.innerHTML = "";
  buildAlerts(sample).forEach((a) => {
    const li = document.createElement("li");
    li.className = a.c;
    li.textContent = a.t;
    list.appendChild(li);
  });
}

async function fetchLive() {
  const res = await fetch("/api/live");
  const data = await res.json();
  renderSample(data);
}

async function loadHistory() {
  const res = await fetch("/api/history?points=60");
  const data = await res.json();
  trendChart.data.labels = data.map((x) => x.timestamp.slice(11));
  trendChart.data.datasets[0].data = data.map((x) => x.aqi);
  trendChart.data.datasets[1].data = data.map((x) => x.voltage);
  trendChart.update();
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  byId("modeSelect").value = s.mode;
  byId("thresholdRange").value = s.threshold_voltage;
  byId("thresholdText").textContent = `${Number(s.threshold_voltage).toFixed(2)} V`;
  byId("refreshSelect").value = String(s.refresh_ms);
  refreshMs = s.refresh_ms;
}

async function saveSettings(payload) {
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

function startLoop() {
  if (timer) clearInterval(timer);
  timer = setInterval(async () => {
    await fetchLive();
    await loadHistory();
  }, refreshMs);
}

byId("modeSelect").addEventListener("change", async (e) => {
  await saveSettings({ mode: e.target.value });
});

byId("thresholdRange").addEventListener("input", (e) => {
  byId("thresholdText").textContent = `${Number(e.target.value).toFixed(2)} V`;
});

byId("thresholdRange").addEventListener("change", async (e) => {
  await saveSettings({ threshold_voltage: Number(e.target.value) });
});

byId("refreshSelect").addEventListener("change", async (e) => {
  refreshMs = Number(e.target.value);
  await saveSettings({ refresh_ms: refreshMs });
  startLoop();
});

byId("fanOnBtn").addEventListener("click", async () => {
  await fetch("/api/fan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: true })
  });
});

byId("fanOffBtn").addEventListener("click", async () => {
  await fetch("/api/fan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: false })
  });
});

(async function boot() {
  await loadSettings();
  await fetchLive();
  await loadHistory();
  startLoop();
})();
