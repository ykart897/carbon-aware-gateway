const $ = id => document.getElementById(id);
const colors = {DE: '#d97706', IE: '#059669', FR: '#10b981', PL: '#dc2626'};
const schedulerColors = {carbon_aware: '#059669', round_robin: '#d97706', latency_only: '#2563eb'};
const display = (value, suffix = '') => value == null ? '—' : `${value}${suffix}`;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = String(text);
  return element;
}

function row(values) {
  const tr = node('tr');
  for (const value of values) tr.append(node('td', '', value));
  return tr;
}

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

let selectedType = 'standard';
let selectedScheduler = 'carbon_aware';
function bindChoices(id, selected, onChange) {
  const buttons = document.querySelectorAll(`#${id} button`);
  for (const button of buttons) {
    button.setAttribute('aria-pressed', String(button.dataset.v === selected));
    button.addEventListener('click', () => {
      for (const other of buttons) {
        other.className = 'pill';
        other.setAttribute('aria-pressed', 'false');
      }
      button.className = 'pill active-ft';
      button.setAttribute('aria-pressed', 'true');
      onChange(button.dataset.v);
    });
  }
}
bindChoices('ft-btns', selectedType, value => { selectedType = value; });
bindChoices('sc-btns', selectedScheduler, value => {
  selectedScheduler = value;
  $('opt-method').disabled = value !== 'carbon_aware';
});

$('route-btn').addEventListener('click', async () => {
  const button = $('route-btn');
  const box = $('result-box');
  button.disabled = true;
  box.textContent = 'Routing request...';
  try {
    const result = await request('/route', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'demo_request', function_type: selectedType,
        scheduler: selectedScheduler, opt_method: $('opt-method').value, data: {}}),
    });
    const dec = result.decision;
    const inv = result.invocation;
    box.replaceChildren(
      node('strong', '', `${dec.region_label} (${inv.region}) — ${inv.success ? 'Succeeded' : 'Failed'}`),
      node('div', '', `Carbon: ${dec.carbon_intensity} gCO₂/kWh · Latency: ${inv.latency_ms} ms`),
      node('div', '', `Estimated savings: ${display(result.carbon_saved_g, ' g')} · Energy assumption: ${result.energy_kwh_per_request} kWh/request`),
      node('div', '', `Backend: ${result.backend} · Source: ${result.data_source}`),
      node('div', '', `Execution: immediate · ${inv.cold_start ? 'cold' : 'warm'} start`),
    );
    if (inv.error) box.append(node('div', 'error', inv.error));
    if (result.sla_satisfied != null) {
      box.append(node('div', '', `Estimated base latency target ≤ ${dec.sla_ms} ms: ${result.sla_satisfied ? 'met' : 'not met'}`));
    }
    const rec = result.deferral_recommendation;
    if (rec) box.append(node('div', '', `Suggestion only: ${rec.region} at ${rec.scheduled_at} (${rec.predicted_carbon} gCO₂/kWh). Forecast: ${rec.model_used}, ${rec.data_source}. No later execution scheduled.`));
  } catch (error) {
    box.textContent = `Request failed (${error.name === 'AbortError' ? 'timeout; execution outcome unknown' : error.message}).`;
  } finally {
    button.disabled = false;
  }
  await refresh();
});

function renderCarbon(carbon) {
  const entries = Object.entries(carbon.regions);
  const max = Math.max(...entries.map(([, data]) => data.carbon_intensity), 1);
  const min = Math.min(...entries.map(([, data]) => data.carbon_intensity));
  $('rg').replaceChildren(...entries.map(([region, data]) => {
    const card = node('div', `rc ${data.carbon_intensity === min ? 'best' : ''}`);
    if (data.carbon_intensity === min) card.append(node('div', 'bp', 'lowest carbon'));
    card.append(node('div', 'rn', region), node('div', 'rv', data.carbon_intensity),
      node('div', 'ru', `gCO₂/kWh · hour ${carbon.hour}`),
      node('div', 'rs', `${data.energy_source} · ${data.renewable_pct}% renewable`));
    const bar = node('div', 'rbar');
    const fill = node('div', 'rbar-f');
    fill.style.width = `${Math.max(0, Math.min(100, data.carbon_intensity / max * 100))}%`;
    fill.style.backgroundColor = colors[region] || '#888';
    bar.append(fill);
    card.append(bar, node('div', 'api-lbl', data.source));
    return card;
  }));
}

function renderStats(stats) {
  const totals = stats.totals;
  $('k-total').textContent = totals.total_requests;
  $('k-saved').textContent = display(totals.total_saved_g, ' g');
  $('k-carbon').textContent = display(totals.avg_carbon == null ? null : Number(totals.avg_carbon.toFixed(2)));
  $('k-lat').textContent = display(totals.avg_latency == null ? null : Number(totals.avg_latency.toFixed(2)), ' ms');
  $('k-defer').textContent = totals.recommendation_count;
  $('metrics-info').textContent = `${totals.successful_requests} successful · ${totals.failed_requests} failed · ${totals.legacy_requests} legacy records excluded from current metrics. Savings are estimated against the same snapshot's four-region average.`;
  const max = Math.max(...stats.by_scheduler.map(s => s.avg_carbon || 0), 1);
  const bars = stats.by_scheduler.map(s => {
    const element = node('div', 'sbar-row');
    const wrap = node('div', 'sbar-wrap');
    const fill = node('div', 'sbar-fill', display(s.avg_carbon == null ? null : s.avg_carbon.toFixed(1)));
    fill.style.width = `${(s.avg_carbon || 0) / max * 100}%`;
    fill.style.backgroundColor = schedulerColors[s.scheduler] || '#888';
    wrap.append(fill);
    element.append(node('div', 'sbar-lbl', s.scheduler), wrap, node('div', 'sbar-val', `${s.requests} req`));
    return element;
  });
  $('sched-bars').replaceChildren(...(bars.length ? bars : [node('div', '', 'Send requests to see comparison.')]));
}

function renderForecast(forecast) {
  const max = Math.max(...forecast.arima_forecast, 1);
  $('fc-cols').replaceChildren(...forecast.arima_forecast.map((value, index) => {
    const column = node('div', 'fc-col');
    const wrap = node('div', 'fc-bw');
    const bar = node('div', 'fc-b');
    bar.style.height = `${Math.max(0, value / max * 48)}px`;
    wrap.append(bar);
    column.append(wrap, node('div', 'fc-v', value),
      node('div', 'fc-l', `${String(forecast.forecast_hours[index]).padStart(2, '0')}:00`));
    return column;
  }));
  $('forecast-info').textContent = `${forecast.steps}-hour forecast · MAE ${display(forecast.metrics.mae)} gCO₂/kWh · ${forecast.data_source || 'CSV sample profile'} · UTC`;
}

function renderClusters(clusters) {
  document.querySelector('#cl-tbl tbody').replaceChildren(...Object.entries(clusters).map(([region, data]) =>
    row([region, `${data.label} (${data.backend})`, data.active, data.capacity, data.total])));
}

function renderLogs(logs) {
  $('lb').replaceChildren(...logs.map(log => row([
    log.timestamp, log.action || '—', log.function_type, log.scheduler, log.region,
    log.carbon, display(log.latency_ms, ' ms'),
    log.metric_version === 2 ? display(log.carbon_saved_g, ' g') : 'legacy',
    log.exec_mode, `${log.success ? 'success' : 'failed'} / ${log.backend || 'legacy'}`,
  ])));
}

const panels = [
  ['Carbon', '/carbon', renderCarbon], ['Metrics', '/stats', renderStats],
  ['Logs', '/logs?limit=25', renderLogs], ['Forecast', '/forecast/IE?steps=6', renderForecast],
  ['Clusters', '/clusters', renderClusters],
];
let refreshing = null;
let timer;
function refresh() {
  if (refreshing) return refreshing;
  clearTimeout(timer);
  refreshing = (async () => {
    const results = await Promise.allSettled(panels.map(async ([, url, render]) => render(await request(url))));
    const errors = results.flatMap((result, index) => result.status === 'rejected' ? [`${panels[index][0]} unavailable; displayed data may be stale.`] : []);
    $('panel-errors').replaceChildren(...errors.map(text => node('div', 'error', text)));
    $('live-txt').textContent = `${errors.length ? 'Partial update' : 'Updated'} · ${new Date().toLocaleTimeString()}`;
  })().finally(() => {
    refreshing = null;
    timer = setTimeout(refresh, 7000);
  });
  return refreshing;
}
refresh();
