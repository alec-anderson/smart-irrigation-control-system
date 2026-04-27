const DEFAULT_CONFIG = {
  API_BASE: "http://127.0.0.1:8000",
  DEVICE_ID: "pi-prototype-001",
  DASHBOARD_TOKEN: "",
  POLL_SECONDS: 6
};

const config = { ...DEFAULT_CONFIG, ...(window.DASHBOARD_CONFIG || {}) };
const storedToken = localStorage.getItem("irrigation_dashboard_token");
if (!config.DASHBOARD_TOKEN && storedToken) {
  config.DASHBOARD_TOKEN = storedToken;
}
if (!config.DASHBOARD_TOKEN) {
  config.DASHBOARD_TOKEN = window.prompt("Dashboard token") || "";
  if (config.DASHBOARD_TOKEN) {
    localStorage.setItem("irrigation_dashboard_token", config.DASHBOARD_TOKEN);
  }
}

const $ = (id) => document.getElementById(id);

let soilFlowChart;
let motionChart;

function fmtNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function fmtBool(value) {
  if (value === true) return "On";
  if (value === false) return "Off";
  return "--";
}

function fmtTime(value) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function apiGet(path) {
  const response = await fetch(`${config.API_BASE}${path}`, {
    headers: {
      Authorization: `Bearer ${config.DASHBOARD_TOKEN}`
    }
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setConnection(status, errorMessage = "") {
  const pill = $("connectionPill");
  const state = status?.connection_state || (errorMessage ? "error" : "unknown");
  pill.className = `status-pill ${state}`;
  if (errorMessage) {
    pill.textContent = "API error";
    return;
  }
  pill.textContent = state === "offline" ? "Offline" : "Online";
}

function updateCurrent(data) {
  const telemetry = data.telemetry || {};
  const status = data.status || {};

  $("deviceLine").textContent = data.device_id || config.DEVICE_ID;
  $("soilValue").textContent = `${fmtNumber(telemetry.soil_moisture_pct)}%`;
  $("flowValue").textContent = `${fmtNumber(telemetry.flow_rate_l_min)} L/min`;
  $("totalFlowValue").textContent = `${fmtNumber(telemetry.cumulative_flow_l)} L total`;
  $("angleValue").textContent = `${fmtNumber(telemetry.angle_deg)} deg`;
  $("alignmentValue").textContent = `${fmtNumber(telemetry.alignment_error_deg)} deg error`;
  $("pumpValue").textContent = fmtBool(telemetry.pump_on);
  $("valveValue").textContent = `${fmtNumber(telemetry.valve_position_pct, 0)}%`;
  $("modeValue").textContent = telemetry.drive_mode || status.current_mode || "--";
  $("limitValue").textContent = `Min ${fmtBool(telemetry.limit_min_active)} / Max ${fmtBool(telemetry.limit_max_active)}`;
  $("lastSeenValue").textContent = fmtTime(status.last_seen_at);
  $("backlogValue").textContent = `${status.sync_backlog_count ?? "--"} queued`;
  setConnection(status);

  const events = data.recent_events || [];
  const list = $("eventList");
  list.innerHTML = "";
  if (!events.length) {
    const item = document.createElement("li");
    item.innerHTML = `<span class="event-title">No recent alerts</span><span class="event-meta">Waiting for events</span>`;
    list.appendChild(item);
    return;
  }

  for (const event of events) {
    const item = document.createElement("li");
    item.className = event.severity || "info";
    item.innerHTML = `
      <span class="event-title">${event.message || event.event_type}</span>
      <span class="event-meta">${event.severity || "info"} · ${event.event_type || "event"} · ${fmtTime(event.recorded_at)}</span>
    `;
    list.appendChild(item);
  }
}

function makeChart(canvasId, labels, datasets) {
  const canvas = $(canvasId);
  return new Chart(canvas, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { intersect: false, mode: "index" },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { ticks: { maxTicksLimit: 5 } },
        y: { beginAtZero: true }
      }
    }
  });
}

function updateCharts(history) {
  if (!window.Chart) return;

  const rows = history.telemetry || [];
  const labels = rows.map((row) => fmtTime(row.recorded_at));
  const soil = rows.map((row) => row.soil_moisture_pct);
  const flow = rows.map((row) => row.flow_rate_l_min);
  const angle = rows.map((row) => row.angle_deg);
  const vibration = rows.map((row) => row.vibration_rms_g);

  if (!soilFlowChart) {
    soilFlowChart = makeChart("soilFlowChart", labels, [
      { label: "Soil %", data: soil, borderColor: "#2d6a4f", backgroundColor: "rgba(45,106,79,0.12)", tension: 0.25 },
      { label: "Flow L/min", data: flow, borderColor: "#1f6f8b", backgroundColor: "rgba(31,111,139,0.12)", tension: 0.25 }
    ]);
  } else {
    soilFlowChart.data.labels = labels;
    soilFlowChart.data.datasets[0].data = soil;
    soilFlowChart.data.datasets[1].data = flow;
    soilFlowChart.update();
  }

  if (!motionChart) {
    motionChart = makeChart("motionChart", labels, [
      { label: "Angle deg", data: angle, borderColor: "#6b5b2a", backgroundColor: "rgba(107,91,42,0.12)", tension: 0.25 },
      { label: "Vibration g", data: vibration, borderColor: "#a13d3d", backgroundColor: "rgba(161,61,61,0.12)", tension: 0.25 }
    ]);
  } else {
    motionChart.data.labels = labels;
    motionChart.data.datasets[0].data = angle;
    motionChart.data.datasets[1].data = vibration;
    motionChart.update();
  }
}

async function refresh() {
  try {
    const hours = $("historyWindow").value;
    const [current, history] = await Promise.all([
      apiGet(`/v1/dashboard/devices/${encodeURIComponent(config.DEVICE_ID)}/current`),
      apiGet(`/v1/dashboard/devices/${encodeURIComponent(config.DEVICE_ID)}/telemetry?hours=${hours}&limit=400`)
    ]);
    updateCurrent(current);
    updateCharts(history);
  } catch (error) {
    setConnection(null, error.message);
    console.error(error);
  }
}

$("historyWindow").addEventListener("change", refresh);
refresh();
window.setInterval(refresh, Math.max(3, config.POLL_SECONDS) * 1000);
