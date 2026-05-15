const el = (id) => document.getElementById(id);
let currentRange = "24h";

const historyChart = new Chart(el("historyChart").getContext("2d"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      { label: "AQI", data: [], borderColor: "rgba(47,215,161,.95)", tension: 0.3, pointRadius: 0, yAxisID: "y" },
      { label: "PM2.5", data: [], borderColor: "rgba(242,178,79,.9)", tension: 0.3, pointRadius: 0, yAxisID: "y" },
      { label: "Voltage", data: [], borderColor: "rgba(173,203,255,.9)", tension: 0.25, pointRadius: 0, yAxisID: "y1" },
    ],
  },
  options: {
    plugins: { legend: { labels: { color: "#eef5ff" } } },
    scales: {
      x: { ticks: { color: "#c2cde0", maxTicksLimit: 10 } },
      y: { ticks: { color: "#c2cde0" }, beginAtZero: true, suggestedMax: 220 },
      y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#adcaff" }, suggestedMin: 0, suggestedMax: 3.3 },
    },
  },
});

function setRangeButtons(activeRange) {
  document.querySelectorAll(".range-chip").forEach((btn) => {
    const on = btn.dataset.range === activeRange;
    btn.classList.toggle("active", on);
  });
}

function renderRangeStats(stats, rangeKey) {
  el("avgAqi").textContent = Number(stats.avg_aqi || 0).toFixed(1);
  el("minAqi").textContent = Number(stats.min_aqi || 0).toFixed(0);
  el("maxAqi").textContent = Number(stats.max_aqi || 0).toFixed(0);
  el("samples").textContent = Number(stats.samples || 0).toFixed(0);
  el("rangeMeta").textContent = `${rangeKey} | Avg PM2.5 ${Number(stats.avg_pm25 || 0).toFixed(1)} ug/m3 | Avg Voltage ${Number(stats.avg_voltage || 0).toFixed(2)}V`;
}

function renderHistoryChart(points) {
  historyChart.data.labels = points.map((p) => {
    const ts = String(p.ts || p.timestamp || "");
    return ts.length >= 16 ? ts.slice(11, 16) : ts;
  });
  historyChart.data.datasets[0].data = points.map((p) => Number(p.aqi || 0));
  historyChart.data.datasets[1].data = points.map((p) => Number(p.pm25 || 0));
  historyChart.data.datasets[2].data = points.map((p) => Number(p.voltage || 0));
  historyChart.update();
}

function renderTable(points) {
  let html = "<table><tr><th>Time</th><th>AQI</th><th>PM2.5</th><th>Voltage</th><th>Fan</th><th>Mode</th><th>Source</th></tr>";
  const rows = points.slice(-80).reverse();
  rows.forEach((p) => {
    const ts = String(p.ts || p.timestamp || "");
    html += `<tr><td>${ts.replace("T", " ")}</td><td>${Number(p.aqi || 0)}</td><td>${Number(p.pm25 || 0).toFixed(1)}</td><td>${Number(p.voltage || 0).toFixed(2)}</td><td>${p.fan_on ? "ON" : "OFF"}</td><td>${String(p.mode || "--").toUpperCase()}</td><td>${p.source || "--"}</td></tr>`;
  });
  html += "</table>";
  el("dailyTable").innerHTML = html;
}

async function loadRange(rangeKey) {
  currentRange = rangeKey;
  setRangeButtons(rangeKey);
  const res = await fetch(`/api/reports/history?range=${encodeURIComponent(rangeKey)}&max_points=700`);
  const payload = await res.json();
  const points = payload.points || [];
  const stats = payload.stats || {};
  renderRangeStats(stats, payload.range || rangeKey);
  renderHistoryChart(points);
  renderTable(points);
}

function renderNotifyStatus(status) {
  const readyText = status.ready ? "Ready" : "Not Ready";
  const msg = `${readyText} | Recipient: ${status.email_to || "--"} | Threshold: ${status.aqi_threshold || "--"} | Last event: ${status.last_event || "--"} | Last sent: ${status.last_sent_at || "--"}`;
  el("notifyState").textContent = status.last_error ? `${msg} | Error: ${status.last_error}` : msg;
}

async function loadNotificationStatus() {
  const status = await fetch("/api/notifications/status").then((r) => r.json());
  el("notifyEmail").value = status.email_to || "";
  el("notifyThreshold").value = String(status.aqi_threshold || 150);
  renderNotifyStatus(status);
}

async function saveNotificationConfig() {
  const payload = {
    email_to: (el("notifyEmail").value || "").trim(),
    aqi_threshold: Number(el("notifyThreshold").value || 150),
    enabled: true,
  };
  const r = await fetch("/api/notifications/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const out = await r.json();
  renderNotifyStatus(out);
}

async function sendTestEmail() {
  const payload = { email_to: (el("notifyEmail").value || "").trim() };
  const r = await fetch("/api/notifications/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const out = await r.json();
  if (!r.ok) {
    const status = out.status || {};
    renderNotifyStatus(status);
    throw new Error(status.last_error || "Test email failed");
  }
  renderNotifyStatus(out.status || {});
}

function bindEvents() {
  document.querySelectorAll(".range-chip").forEach((btn) => {
    btn.addEventListener("click", () => loadRange(btn.dataset.range || "24h"));
  });

  const admin = window.USER_ROLE === "admin";
  const saveBtn = el("saveNotifyBtn");
  const testBtn = el("testNotifyBtn");
  if (!admin) {
    if (saveBtn) saveBtn.style.display = "none";
    if (testBtn) testBtn.style.display = "none";
    return;
  }

  saveBtn?.addEventListener("click", async () => {
    await saveNotificationConfig();
  });
  testBtn?.addEventListener("click", async () => {
    try {
      await sendTestEmail();
    } catch (e) {
      el("notifyState").textContent = `Test failed: ${e.message || e}`;
    }
  });
}

async function load() {
  bindEvents();
  await loadRange(currentRange);
  await loadNotificationStatus();
}

load();
