// EarthScape dashboard. All data comes from the API; the server enforces every role check.
const TOKEN_KEY = 'es_token';
const ZONES = ['64N-90N', '44N-64N', '24N-44N', 'EQU-24N', '24S-EQU', '44S-24S', '64S-44S', '90S-64S'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const YEAR_COLORS = ['#94a3b8', '#1a814a', '#040404', '#c0a78c', '#0284c7'];
const ML_HORIZONS = [2030, 2040, 2050];
const ML_CHART_START = 1950;

const NAV = [
  ['landing', 'globe', 'Agency Landing'],
  ['dashboard', 'bar-chart-2', 'Executive Dashboard'],
  ['analytics', 'activity', 'Climate Analytics'],
  ['monitoring', 'wifi', 'Sensor Monitor'],
  ['data', 'database', 'Data Explorer & Upload'],
  ['Big Data Infrastructure'],
  ['hadoop', 'server', 'Hadoop & HDFS Cluster'],
  ['ml', 'cpu', 'ML Models & Forecasts'],
  ['alerts', 'alert-triangle', 'Alert Management'],
  ['reports', 'file-text', 'Reports & Export'],
  ['Administration'],
  ['rbac', 'users', 'Users & Roles'],
  ['support', 'help-circle', 'Feedback & Support'],
  ['architecture', 'code', 'System Architecture'],
  ['settings', 'settings', 'Account Settings'],
];

const state = { page: 'landing', user: null, charts: {}, searchIndex: null, jobPoll: null, mlForecast: null, mlHorizon: 2050 };

const $ = (id) => document.getElementById(id);

function esc(value) {
  const element = document.createElement('div');
  element.textContent = value === null || value === undefined ? '' : String(value);
  return element.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function isAdmin() {
  return state.user && state.user.role === 'Admin';
}

function toast(message, isError) {
  const element = document.createElement('div');
  element.className = 'px-4 py-3 rounded-full shadow-2xl border border-[#2b2b2b] font-medium text-xs bg-[#040404] ' + (isError ? 'text-rose-300' : 'text-[#f6d987]');
  element.textContent = message;
  $('toast-container').appendChild(element);
  setTimeout(() => element.remove(), 4000);
}

function signedOut() {
  sessionStorage.removeItem(TOKEN_KEY);
  location.replace('login.html');
}

async function request(path, options) {
  const settings = options || {};
  const headers = Object.assign({ Authorization: 'Bearer ' + sessionStorage.getItem(TOKEN_KEY) }, settings.headers);
  if (settings.json !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {
    method: settings.method || 'GET',
    headers,
    body: settings.json !== undefined ? JSON.stringify(settings.json) : settings.body,
  });
  if (response.status === 401) {
    signedOut();
    throw new Error('Please sign in.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : 'Please check the form and try again.';
    throw new Error(detail);
  }
  return settings.raw ? response : response.json();
}

// Runs an action from a button or form, and shows any failure instead of losing it.
async function attempt(action) {
  try {
    return await action();
  } catch (error) {
    toast(error instanceof TypeError ? "Can't reach the server." : error.message, true);
    return undefined;
  }
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return 'Unavailable';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return value.toFixed(unit === 0 ? 0 : 1) + ' ' + units[unit];
}

function formatNumber(value) {
  return value === null || value === undefined ? 'n/a' : Number(value).toLocaleString();
}

function formatSigned(value, suffix) {
  if (value === null || value === undefined) return 'n/a';
  return (value > 0 ? '+' : '') + value + suffix;
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : '';
}

function formatCompactDate(value) {
  const text = String(value);
  return text.slice(0, 4) + '-' + text.slice(4, 6) + '-' + text.slice(6, 8);
}

function table(headers, rows, emptyMessage) {
  if (!rows.length) return '<div class="empty">' + esc(emptyMessage) + '</div>';
  const head = headers.map((header) => '<th>' + esc(header) + '</th>').join('');
  const body = rows.map((cells) => '<tr>' + cells.map((cell) => '<td>' + cell + '</td>').join('') + '</tr>').join('');
  return '<table class="data-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>';
}

function statCard(label, value, note) {
  return '<div class="card p-5 space-y-1"><span class="stat-label">' + esc(label) + '</span><p class="stat-value">' + esc(value) + '</p><p class="text-[11px] text-slate-500">' + esc(note) + '</p></div>';
}

function drawLineChart(name, canvasId, labels, datasets, yLabel) {
  if (state.charts[name]) state.charts[name].destroy();
  state.charts[name] = new Chart($(canvasId), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      spanGaps: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: datasets.length > 1, labels: { filter: (item, data) => !data.datasets[item.datasetIndex].hideFromLegend } } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: '#f0f0f0' }, title: { display: Boolean(yLabel), text: yLabel } },
      },
    },
  });
}

// --- Pages ---

async function renderLanding() {
  const data = await request('/overview');
  const temperature = data.temperature;
  const co2 = data.co2;
  const previous = data.temperature_previous;
  $('landing-stats').innerHTML = [
    statCard('Global temp anomaly', temperature ? formatSigned(temperature['J-D'], ' °C') : 'n/a',
      temperature ? 'NASA GISTEMP, ' + temperature.Year + (previous ? ' (' + previous.Year + ': ' + formatSigned(previous['J-D'], ' °C') + ')' : '') : ''),
    statCard('Atmospheric CO₂', co2 ? co2.mean + ' ppm' : 'n/a', co2 ? 'Mauna Loa, ' + co2.year : ''),
    statCard('Unusual station readings', formatNumber(data.anomaly_count), 'More than 3 standard deviations from normal'),
    statCard('Datasets in HDFS', formatNumber(data.dataset_count), 'Weather, satellite-derived and sensor data'),
  ].join('');
  updateSidebar(data.cluster);
  updateRefreshTime();
}

async function renderDashboard() {
  const [overview, series, anomalies, jobs] = await Promise.all([
    request('/overview'), request('/climate/global'), request('/anomalies?limit=8'), request('/jobs'),
  ]);
  const temperature = overview.temperature;
  const cluster = overview.cluster;
  $('dashboard-stats').innerHTML = [
    statCard('Temp anomaly', temperature ? formatSigned(temperature['J-D'], ' °C') : 'n/a', temperature ? String(temperature.Year) : ''),
    statCard('CO₂', overview.co2 ? overview.co2.mean + ' ppm' : 'n/a', overview.co2 ? String(overview.co2.year) : ''),
    statCard('Active alerts', overview.active_alerts, 'Alert checking arrives in Phase 4'),
    statCard('Datasets', overview.dataset_count, 'In HDFS'),
    statCard('Hadoop', cluster.hdfs_online && cluster.yarn_online ? 'Online' : 'Offline',
      cluster.hdfs_online ? cluster.live_datanodes + ' DataNode, ' + formatNumber(cluster.active_nodes) + ' YARN node' : 'Start HDFS and YARN'),
  ].join('');
  drawLineChart('global', 'chart-global', series.map((row) => row.year), [{
    label: 'Anomaly (°C)', data: series.map((row) => row.anomaly), borderColor: '#1a814a',
    backgroundColor: 'rgba(26,129,74,.1)', fill: true, pointRadius: 0, tension: 0.2, borderWidth: 2,
  }], '°C');
  $('dashboard-anomalies').innerHTML = anomalies.rows.map((row) => (
    '<div class="p-3 bg-[#f9f9f9] rounded-2xl border border-[#ebebeb] text-xs"><div class="flex justify-between font-bold"><span>' + esc(row.station) + ' ' + esc(row.element) + '</span><span class="text-rose-600 font-mono">' + esc(row.value_c) + ' °C</span></div><p class="text-[11px] text-slate-500">' + esc(formatCompactDate(row.date)) + ', usually ' + esc(row.mean_c) + ' °C (z = ' + esc(row.z_score) + ')</p></div>'
  )).join('') || '<div class="empty">No data yet.</div>';
  $('dashboard-jobs').innerHTML = jobsTable(jobs.jobs.slice(0, 5), jobs.yarn_online, false);
  updateSidebar(cluster);
  updateRefreshTime();
}

async function renderAnalytics() {
  const zone = $('analytics-zone').value;
  const variable = $('analytics-variable').value;
  const label = $('analytics-variable').selectedOptions[0].textContent;
  const zoneLabel = $('analytics-zone').selectedOptions[0].textContent;
  $('analytics-title').textContent = label + ' - ' + zoneLabel;
  const empty = $('analytics-empty');
  const canvas = $('chart-analytics');

  function showMessage(message) {
    if (state.charts.analytics) state.charts.analytics.destroy();
    state.charts.analytics = null;
    canvas.classList.add('hidden');
    empty.textContent = message;
    empty.classList.remove('hidden');
  }

  canvas.classList.remove('hidden');
  empty.classList.add('hidden');
  if (variable === 'anomaly') {
    const series = await request('/climate/zonal?zone=' + encodeURIComponent(zone));
    drawLineChart('analytics', 'chart-analytics', series.map((row) => row.year), [{
      label: label, data: series.map((row) => row.value), borderColor: '#040404',
      pointRadius: 0, tension: 0.2, borderWidth: 2,
    }], '°C');
  } else if (zone === 'Glob') {
    showMessage('This variable is only available by latitude zone. Choose a zone above.');
  } else {
    const years = await request('/climate/monthly?zone=' + encodeURIComponent(zone) + '&variable=' + variable);
    const yearKeys = Object.keys(years).sort();
    if (!yearKeys.length) {
      showMessage('The grid has no points in this zone. Weather station variables cover every zone.');
    } else {
      drawLineChart('analytics', 'chart-analytics', MONTHS, yearKeys.map((year, index) => ({
        label: year,
        data: MONTHS.map((_, month) => years[year][month + 1] === undefined ? null : years[year][month + 1]),
        borderColor: YEAR_COLORS[index % YEAR_COLORS.length],
        backgroundColor: YEAR_COLORS[index % YEAR_COLORS.length],
        tension: 0.2, borderWidth: 2, pointRadius: 3,
      })), '');
    }
  }

  const summary = await request('/climate/zones');
  $('zones-title').textContent = 'Latitude zones (station averages for ' + summary.year + ')';
  $('zones-table').innerHTML = table(
    ['Zone', 'Anomaly', 'Avg daily high', 'Avg daily low', 'Precipitation', 'Readings'],
    summary.zones.map((row) => [
      '<strong class="text-[#040404]">' + esc(row.zone) + '</strong>',
      row.anomaly === null ? 'n/a' : esc(formatSigned(row.anomaly, ' °C')) + ' <span class="text-slate-400">(' + esc(row.anomaly_year) + ')</span>',
      row.tmax === null ? 'n/a' : esc(row.tmax) + ' °C',
      row.tmin === null ? 'n/a' : esc(row.tmin) + ' °C',
      row.prcp === null ? 'n/a' : esc(row.prcp) + ' mm/day',
      esc(formatNumber(row.readings)),
    ]), 'No data yet.');
  updateRefreshTime();
}

async function renderMonitoring() {
  const sensors = await request('/air-quality');
  $('sensor-grid').innerHTML = sensors.map((sensor) => {
    const rows = Object.values(sensor.pollutants).map((row) => (
      '<div class="flex justify-between text-xs font-mono"><span>' + esc(row.parameter.toUpperCase()) + ' <span class="text-slate-400">(' + esc(MONTHS[row.month - 1]) + ')</span></span><strong>' + esc(Number(row.mean).toPrecision(3)) + ' ' + esc(row.units) + '</strong></div>'
    )).join('');
    return '<div class="card p-5 space-y-2"><h4 class="font-extrabold text-sm">' + esc(sensor.name) + '</h4><p class="text-[10px] text-slate-500 font-mono">Lat ' + esc(Number(sensor.lat).toFixed(2)) + ', Lon ' + esc(Number(sensor.lon).toFixed(2)) + '</p>' + rows + '</div>';
  }).join('') || '<div class="empty">No sensor data yet. Run the pipeline first.</div>';
  updateRefreshTime();
}

async function renderData() {
  const [datasets, quality] = await Promise.all([request('/datasets'), request('/quality')]);
  $('datasets-count').textContent = datasets.length + ' datasets';
  $('datasets-table').innerHTML = table(['Name', 'Format', 'Size', 'Source', 'HDFS path'], datasets.map((row) => [
    '<strong class="text-[#040404]">' + esc(row.name) + '</strong>' + (row.uploaded ? ' <span class="tag tag-gold">Uploaded</span>' : ''),
    '<span class="tag tag-grey">' + esc(row.format) + '</span>',
    esc(formatBytes(row.size_bytes)), esc(row.source), '<span class="font-mono text-[11px]">' + esc(row.path) + '</span>',
  ]), 'No datasets yet.');
  $('quality-table').innerHTML = table(['Year', 'Measurement', 'Valid', 'Failed checks', 'Missing', 'Pass rate'], quality.map((row) => [
    esc(row.year), esc(row.element), esc(formatNumber(row.valid)), esc(formatNumber(row.failed_qc)), esc(formatNumber(row.missing)),
    esc((100 * row.valid / (row.valid + row.failed_qc)).toFixed(2)) + '%',
  ]), 'No quality results yet. Run the pipeline first.');
  updateRefreshTime();
}

function jobsTable(jobs, online, withActions) {
  if (!online) return '<div class="empty">YARN isn\'t reachable. Start it from an administrator Command Prompt.</div>';
  return table(['Job', 'Application', 'State', 'Result', 'Duration'].concat(withActions ? [''] : []), jobs.map((job) => {
    const failed = job.final_status === 'FAILED' || job.final_status === 'KILLED';
    const running = job.state === 'RUNNING' || job.state === 'ACCEPTED';
    const cls = failed ? 'tag-red' : running ? 'tag-blue' : 'tag-green';
    const cells = [
      '<strong class="text-[#040404]">' + esc(job.name) + '</strong>',
      '<span class="font-mono text-[11px]">' + esc(job.id) + '</span>',
      '<span class="tag ' + cls + '">' + esc(job.state) + '</span>',
      esc(running ? Math.round(job.progress) + '%' : job.final_status),
      esc(Math.round(job.elapsed_ms / 1000)) + ' s',
    ];
    if (withActions) cells.push('<button class="pill pill-light" data-action="job-details" data-id="' + esc(job.id) + '">Details</button>');
    return cells;
  }), 'YARN has no EarthScape jobs since it last restarted.');
}

async function renderHadoop() {
  const [cluster, jobs] = await Promise.all([request('/cluster'), request('/jobs')]);
  updateSidebar(cluster);
  const percent = cluster.hdfs_online && cluster.capacity_bytes ? (100 * cluster.used_bytes / cluster.capacity_bytes).toFixed(2) : null;
  $('cluster-stats').innerHTML = [
    statCard('HDFS used', cluster.hdfs_online ? formatBytes(cluster.used_bytes) : 'Offline', cluster.hdfs_online ? percent + '% of ' + formatBytes(cluster.capacity_bytes) : 'Start HDFS'),
    statCard('DataNodes', cluster.hdfs_online ? cluster.live_datanodes + ' live' : 'Offline', cluster.hdfs_online ? cluster.dead_datanodes + ' dead, ' + formatNumber(cluster.files) + ' files' : ''),
    statCard('YARN nodes', cluster.yarn_online ? cluster.active_nodes + ' active' : 'Offline', cluster.yarn_online ? cluster.containers_allocated + ' containers in use' : 'Start YARN as administrator'),
    statCard('Jobs since YARN start', cluster.yarn_online ? cluster.apps_completed + ' done' : 'Offline', cluster.yarn_online ? cluster.apps_running + ' running, ' + cluster.apps_failed + ' failed' : ''),
  ].join('');
  $('jobs-table').innerHTML = jobsTable(jobs.jobs, jobs.yarn_online, true);
  $('runs-table').innerHTML = table(['Job', 'Run time', 'Finished'], jobs.recent_runs.map((run) => [
    esc(run.job), esc(run.seconds) + ' s', esc(formatDate(run.finished_at)),
  ]), 'No recorded runs yet.');
  $('job-run-buttons').innerHTML = jobs.runnable.map((name) => (
    '<button class="pill pill-light" data-action="run-job" data-name="' + esc(name) + '">Run ' + esc(name) + '</button>'
  )).join('');
  updateRefreshTime();
  // Keep the list moving while a job is in progress.
  clearTimeout(state.jobPoll);
  if (jobs.jobs.some((job) => job.state === 'RUNNING' || job.state === 'ACCEPTED')) {
    state.jobPoll = setTimeout(() => { if (state.page === 'hadoop') attempt(renderHadoop); }, 5000);
  }
}

async function showJobDetails(id) {
  const job = await request('/jobs/' + encodeURIComponent(id));
  $('modal-job-title').textContent = job.name + ' / ' + job.id;
  $('modal-job-body').textContent = [
    'State: ' + job.state + ' (' + job.finalStatus + ')',
    'Progress: ' + job.progress + '%',
    'Started: ' + formatDate(job.startedTime),
    'Run time: ' + Math.round(job.elapsedTime / 1000) + ' s',
    'Resources: ' + job.memorySeconds + ' MB-seconds, ' + job.vcoreSeconds + ' vcore-seconds',
    'Message from YARN: ' + (job.diagnostics || '(none)'),
    'Tracking page: ' + job.trackingUrl,
  ].join('\n');
  $('modal-job').classList.remove('hidden');
}

function seriesLabel(series) {
  return series === 'Glob' ? 'Global' : series;
}

function percent(share, decimals) {
  return (100 * share).toFixed(decimals || 0) + '%';
}

function drawForecast() {
  const forecast = state.mlForecast;
  const history = forecast.history.filter((row) => row.year >= ML_CHART_START);
  const future = forecast.forecast.filter((row) => row.year <= state.mlHorizon);
  const last = history[history.length - 1];
  const blanks = history.slice(0, -1).map(() => null);
  drawLineChart('mlForecast', 'chart-ml-forecast', history.map((row) => row.year).concat(future.map((row) => row.year)), [
    { label: 'Measured', data: history.map((row) => row.value), borderColor: '#040404', backgroundColor: '#040404', pointRadius: 0, tension: 0.2, borderWidth: 2 },
    { label: 'Forecast', data: blanks.concat([last.value], future.map((row) => row.forecast)), borderColor: '#1a814a', backgroundColor: '#1a814a', borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
    { label: '95% range, upper', data: blanks.concat([last.value], future.map((row) => row.upper)), borderWidth: 0, pointRadius: 0, backgroundColor: 'rgba(26,129,74,.15)', fill: '+1' },
    { label: '95% range, lower', data: blanks.concat([last.value], future.map((row) => row.lower)), borderWidth: 0, pointRadius: 0, hideFromLegend: true },
  ], '°C');
  $('ml-horizons').innerHTML = ML_HORIZONS.map((year) => (
    '<button class="pill ' + (year === state.mlHorizon ? 'pill-dark' : 'pill-light') + '" data-action="ml-horizon" data-year="' + year + '" aria-pressed="' + (year === state.mlHorizon) + '">' + year + '</button>'
  )).join('');
}

async function renderForecast() {
  const series = $('ml-series').value;
  const forecast = await request('/ml/forecast?series=' + encodeURIComponent(series));
  state.mlForecast = forecast;
  drawForecast();
  $('ml-forecast-table').innerHTML = table(['Year', 'Forecast', '95% range'], forecast.forecast.filter((row) => ML_HORIZONS.includes(row.year)).map((row) => [
    esc(row.year), esc(formatSigned(row.forecast.toFixed(2), ' °C')), esc(formatSigned(row.lower.toFixed(2), '')) + ' to ' + esc(formatSigned(row.upper.toFixed(2), ' °C')),
  ]), 'No forecast yet.');
  $('ml-verdict').textContent = 'Method for ' + seriesLabel(series) + ': ' + forecast.chosen_label + '. It had the lowest error on past data. On '
    + forecast.test_period + ', held back from that choice, it ' + (forecast.beats_baseline ? 'beat' : "didn't beat") + ' simply repeating the last value (error '
    + forecast.test_rmse.toFixed(3) + ' against ' + forecast.baseline_test_rmse.toFixed(3) + ' °C), and ' + percent(forecast.test_coverage) + ' of those years fell inside its 95% range. One decade is a small test.';
  $('ml-comparison').innerHTML = table(['Method', 'Error on past data', 'Error on ' + forecast.test_period, 'Average miss'], forecast.comparison.map((row) => [
    '<strong class="text-[#040404]">' + esc(row.label) + '</strong>' + (row.method === forecast.chosen_method ? ' <span class="tag tag-green">Chosen</span>' : ''),
    esc(row.backtest_rmse.toFixed(3)) + ' °C', esc(row.test_rmse.toFixed(3)) + ' °C', esc(formatSigned(row.test_bias, ' °C')),
  ]), 'No results yet.');
}

function renderMlEmpty() {
  ['ml-stats', 'ml-forecast-table', 'ml-comparison', 'ml-anomalies', 'ml-correlations', 'ml-history', 'ml-horizons'].forEach((id) => { $(id).innerHTML = ''; });
  $('ml-verdict').textContent = '';
  $('ml-run-note').textContent = 'No models have been trained yet. Run ml/train_models.py or use the Retrain button.';
}

function showRetrainState(retraining) {
  $('btn-retrain').disabled = retraining;
  $('btn-retrain').textContent = retraining ? 'Training...' : 'Retrain models';
}

async function renderMl() {
  const [summary, anomalies, correlations] = await Promise.all([request('/ml/summary'), request('/ml/anomalies?limit=25'), request('/ml/correlations')]);
  showRetrainState(summary.retraining);
  clearTimeout(state.jobPoll);
  if (summary.retraining) state.jobPoll = setTimeout(() => attempt(() => watchTraining(summary.latest && summary.latest.version)), 5000);
  const latest = summary.latest;
  if (!latest) {
    renderMlEmpty();
    return;
  }
  const scores = latest.forecast_scores;
  const anomaly = latest.anomaly;
  const recall = anomaly.recall_by_spike_size;
  const beating = scores.filter((score) => score.beats_baseline).length;
  const coverage = scores.reduce((total, score) => total + score.test_coverage, 0) / scores.length;
  $('ml-run-note').textContent = 'Version ' + latest.version + ', trained ' + formatDate(latest.trained_at) + ' by ' + latest.triggered_by + '. Every figure here comes from this run.';
  $('ml-stats').innerHTML = [
    statCard('Beat the baseline', beating + ' of ' + scores.length, 'Regions where the forecast beat repeating the last value on ' + scores[0].test_period),
    statCard('Inside the 95% range', percent(coverage), 'Held-back years inside the range, averaged across regions'),
    statCard('False alarms', percent(anomaly.false_alarm_rate, 2), 'Oct-Dec days flagged after training on Jan-Sep, target about 1%'),
    statCard('Test spikes found', percent(recall['10']), 'At 10 times a sensor\'s usual spread. At 6: ' + percent(recall['6']) + ', at 3: ' + percent(recall['3'])),
  ].join('');
  await renderForecast();
  $('ml-anomalies').innerHTML = table(['Date', 'Sensor', 'Pollutant', 'Daily mean', 'Daily peak', 'Spreads above recent normal'], anomalies.map((row) => [
    esc(row.date), esc(row.location), esc(row.parameter.toUpperCase()), esc(row.mean) + ' ' + esc(row.units), esc(row.max) + ' ' + esc(row.units), esc(row.z_mean),
  ]), 'No unusual days flagged.');
  $('ml-correlations').innerHTML = table(['Compared', 'Data', 'Pairs', 'Pearson', 'Spearman', 'p-value', 'How to read it'], correlations.map((row) => [
    '<strong class="text-[#040404]">' + esc(row.left) + '</strong><br />' + esc(row.right), esc(row.kind), esc(row.n), esc(row.pearson), esc(row.spearman),
    esc(row.pearson_p) + (row.pearson_p >= 0.05 ? ' <span class="tag tag-grey">Not significant</span>' : ''), esc(row.note),
  ]), 'No correlations yet.');
  $('ml-history').innerHTML = table(['Version', 'Trained', 'By', 'Global error', 'Baseline error', 'Regions beating baseline', 'False alarms', 'Spikes found (10 spreads)'], summary.history.map((run) => [
    '<span class="font-mono text-[11px]">' + esc(run.version) + '</span>', esc(formatDate(run.trained_at)), esc(run.triggered_by),
    esc(run.global_test_rmse) + ' °C', esc(run.global_baseline_rmse) + ' °C', esc(run.series_beating_baseline) + ' of ' + esc(run.series_count),
    esc(percent(run.false_alarm_rate, 2)), esc(percent(run.recall_by_spike_size['10'])),
  ]), 'No runs yet.');
  updateRefreshTime();
}

async function watchTraining(previousVersion) {
  if (state.page !== 'ml') return;
  const summary = await request('/ml/summary');
  if (summary.retraining) {
    state.jobPoll = setTimeout(() => attempt(() => watchTraining(previousVersion)), 5000);
    return;
  }
  const version = summary.latest && summary.latest.version;
  if (version !== previousVersion) toast('Models retrained: version ' + version);
  else toast('Training failed. See notifications for the reason.', true);
  attempt(loadNotifications);
  await renderMl();
}

function severityTag(severity) {
  const cls = severity === 'Critical' ? 'tag-red' : severity === 'High' ? 'tag-gold' : 'tag-grey';
  return '<span class="tag ' + cls + '">' + esc(severity) + '</span>';
}

async function renderAlerts() {
  const [alerts, rules, options] = await Promise.all([request('/alerts'), request('/alert-rules'), request('/alert-metrics')]);
  $('alerts-table').innerHTML = table(['Severity', 'Title', 'Measured', 'Status', ''], alerts.map((alert) => [
    severityTag(alert.severity), esc(alert.title), esc(alert.value), esc(alert.status),
    (alert.status === 'Active' ? '<button class="pill pill-gold" data-action="alert-status" data-id="' + esc(alert.id) + '" data-status="Acknowledged">Acknowledge</button> ' : '')
    + (alert.status !== 'Resolved' ? '<button class="pill pill-green" data-action="alert-status" data-id="' + esc(alert.id) + '" data-status="Resolved">Resolve</button>' : ''),
  ]), 'No alerts have fired. Automatic checking arrives in Phase 4.');
  $('rules-table').innerHTML = table(['Name', 'Metric', 'Fire above', 'Severity', 'Created by'].concat(isAdmin() ? [''] : []), rules.map((rule) => {
    const cells = [esc(rule.name), esc(options.metrics[rule.metric] || rule.metric), esc(rule.threshold), severityTag(rule.severity), esc(rule.created_by)];
    if (isAdmin()) cells.push('<button class="pill pill-light" data-action="delete-rule" data-id="' + esc(rule.id) + '">Delete</button>');
    return cells;
  }), 'No rules yet.');
  $('rule-metric').innerHTML = Object.entries(options.metrics).map(([key, value]) => '<option value="' + esc(key) + '">' + esc(value) + '</option>').join('');
  $('rule-severity').innerHTML = options.severities.map((value) => '<option>' + esc(value) + '</option>').join('');
  updateAlertBadge(alerts);
  updateRefreshTime();
}

function updateAlertBadge(alerts) {
  const badge = $('sidebar-alerts-badge');
  if (!badge) return;
  const active = alerts.filter((alert) => alert.status === 'Active').length;
  badge.textContent = active;
  badge.classList.toggle('hidden', active === 0);
}

let reports = [];

function updateReportFormats() {
  const report = reports.find((entry) => entry.id === $('report-select').value);
  const formats = [['csv', 'CSV'], ['json', 'JSON']].concat(report && report.geo ? [['geojson', 'GeoJSON']] : []);
  $('report-format').innerHTML = formats.map(([value, label]) => '<option value="' + value + '">' + label + '</option>').join('');
}

async function renderReports() {
  reports = await request('/reports');
  $('report-select').innerHTML = reports.map((report) => '<option value="' + esc(report.id) + '">' + esc(report.title) + '</option>').join('');
  updateReportFormats();
}

async function downloadReport() {
  const id = $('report-select').value;
  const format = $('report-format').value;
  const response = await request('/reports/' + id + '?format=' + format, { raw: true });
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = id + '.' + format;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  toast('Downloaded ' + link.download);
}

async function renderUsers() {
  const users = await request('/users');
  $('users-table').innerHTML = table(['User', 'Email', 'Role', 'Status'].concat(isAdmin() ? [''] : []), users.map((user) => {
    const active = user.active;
    const cells = [
      '<strong class="text-[#040404]">' + esc(user.name) + '</strong><br /><span class="text-[11px]">' + esc(user.title) + '</span>',
      esc(user.email),
      '<span class="tag ' + (user.role === 'Admin' ? 'tag-green' : 'tag-blue') + '">' + esc(user.role) + '</span>',
      '<span class="tag ' + (active ? 'tag-green' : 'tag-red') + '">' + (active ? 'Active' : 'Disabled') + '</span>',
    ];
    if (isAdmin()) {
      cells.push(user.id === state.user.id ? '<span class="text-[11px] text-slate-400">You</span>'
        : '<button class="pill pill-light" data-action="toggle-role" data-id="' + esc(user.id) + '" data-role="' + (user.role === 'Admin' ? 'Analyst' : 'Admin') + '">Make ' + (user.role === 'Admin' ? 'Analyst' : 'Admin') + '</button> '
        + '<button class="pill pill-light" data-action="toggle-active" data-id="' + esc(user.id) + '" data-active="' + (!active) + '">' + (active ? 'Disable' : 'Enable') + '</button>');
    }
    return cells;
  }), 'No users.');
  updateRefreshTime();
}

async function renderSupport() {
  const tickets = await request('/tickets');
  const statuses = ['Open', 'In progress', 'Closed'];
  $('tickets-table').innerHTML = table(['Category', 'Description', 'From', 'Raised', 'Status'], tickets.map((ticket) => [
    esc(ticket.category), esc(ticket.description), esc(ticket.created_by_name), esc(formatDate(ticket.created_at)),
    isAdmin() ? '<select class="field w-auto" aria-label="Ticket status" data-ticket="' + esc(ticket.id) + '">' + statuses.map((status) => '<option' + (status === ticket.status ? ' selected' : '') + '>' + status + '</option>').join('') + '</select>'
      : '<span class="tag tag-grey">' + esc(ticket.status) + '</span>',
  ]), 'No tickets yet.');
  updateRefreshTime();
}

function renderSettings() {
  $('settings-name').value = state.user.name;
  $('settings-title').value = state.user.title;
  $('settings-email').value = state.user.email;
}

const RENDERERS = {
  landing: renderLanding, dashboard: renderDashboard, analytics: renderAnalytics, monitoring: renderMonitoring,
  data: renderData, hadoop: renderHadoop, ml: renderMl, alerts: renderAlerts, reports: renderReports, rbac: renderUsers,
  support: renderSupport, settings: renderSettings,
};

function setPage(page) {
  state.page = page;
  clearTimeout(state.jobPoll);
  document.querySelectorAll('.page-view').forEach((view) => view.classList.add('hidden'));
  $('view-' + page).classList.remove('hidden');
  document.querySelectorAll('.sidebar-nav-item').forEach((link) => link.classList.toggle('active', link.dataset.nav === page));
  document.querySelector('main').scrollTop = 0;
  if (window.innerWidth < 768) setSidebar(false);
  return RENDERERS[page] ? attempt(RENDERERS[page]) : undefined;
}

function updateRefreshTime() {
  $('refresh-time').textContent = new Date().toLocaleTimeString();
}

function updateSidebar(cluster) {
  if (!cluster.hdfs_online) {
    $('sidebar-nodes').textContent = 'Offline';
    $('sidebar-capacity').textContent = 'HDFS unreachable';
    $('sidebar-capacity-bar').style.width = '0';
    return;
  }
  const percent = 100 * cluster.used_bytes / cluster.capacity_bytes;
  $('sidebar-nodes').textContent = cluster.live_datanodes + ' DataNode online';
  $('sidebar-capacity').textContent = formatBytes(cluster.used_bytes) + ' of ' + formatBytes(cluster.capacity_bytes);
  $('sidebar-capacity-bar').style.width = Math.max(percent, 1) + '%';
}

function setSidebar(open) {
  const sidebar = $('sidebar');
  sidebar.classList.toggle('w-64', open);
  sidebar.classList.toggle('w-16', !open);
  document.querySelectorAll('.sidebar-label, .sidebar-heading').forEach((element) => element.classList.toggle('hidden', !open));
  $('sidebar-footer').classList.toggle('hidden', !open);
  state.sidebarOpen = open;
}

function buildSidebar() {
  $('sidebar-nav').innerHTML = NAV.map((item) => {
    if (item.length === 1) return '<div class="sidebar-heading pt-3 pb-1 px-3.5 text-[9px] uppercase tracking-widest font-semibold text-[#bfa78e]">' + esc(item[0]) + '</div>';
    const badge = item[0] === 'alerts' ? '<span id="sidebar-alerts-badge" class="sidebar-label hidden bg-[#f6d987] text-[#040404] font-bold px-2 py-0.5 rounded-full text-[9px]"></span>' : '';
    return '<a href="#" title="' + esc(item[2]) + '" data-nav="' + item[0] + '" class="sidebar-nav-item"><span class="flex items-center gap-3 truncate"><i data-lucide="' + item[1] + '" class="w-4 h-4 flex-shrink-0"></i><span class="sidebar-label truncate">' + esc(item[2]) + '</span></span>' + badge + '</a>';
  }).join('');
}

function showUser() {
  const user = state.user;
  document.body.classList.toggle('hide-admin', !isAdmin());
  $('role-tag').textContent = user.role.toUpperCase();
  $('user-name').textContent = user.name;
  $('user-title').textContent = user.title;
  $('user-email').textContent = user.email;
  $('user-initials').textContent = user.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();
}

async function loadNotifications() {
  const notifications = await request('/notifications');
  const unread = notifications.filter((item) => !item.read).length;
  const badge = $('notif-badge');
  badge.textContent = unread > 9 ? '9+' : unread;
  badge.classList.toggle('hidden', unread === 0);
  badge.classList.toggle('flex', unread > 0);
  $('notif-list').innerHTML = notifications.map((item) => (
    '<div class="p-3.5 ' + (item.read ? '' : 'bg-[#141414]') + '"><p class="text-slate-200 font-medium">' + esc(item.text) + '</p><span class="text-[10px] text-slate-500">' + esc(formatDate(item.created_at)) + '</span></div>'
  )).join('') || '<div class="p-4 text-center text-slate-500">No notifications.</div>';
}

// --- Global search ---

async function buildSearchIndex() {
  const [datasets, sensors, rules] = await Promise.all([request('/datasets'), request('/air-quality'), request('/alert-rules')]);
  return datasets.map((row) => ({ group: 'Datasets', text: row.name, page: 'data' }))
    .concat(sensors.map((row) => ({ group: 'Sensors', text: row.name, page: 'monitoring' })))
    .concat(rules.map((row) => ({ group: 'Alert rules', text: row.name, page: 'alerts' })));
}

async function runSearch(query) {
  const results = $('search-results');
  if (query.length < 2) {
    results.classList.add('hidden');
    return;
  }
  if (!state.searchIndex) state.searchIndex = await buildSearchIndex();
  const matches = state.searchIndex.filter((item) => item.text.toLowerCase().includes(query.toLowerCase())).slice(0, 12);
  results.innerHTML = matches.map((item) => (
    '<button class="w-full text-left p-2 hover:bg-[#1f1f1f] rounded-xl flex justify-between gap-2" data-nav="' + item.page + '"><span class="truncate">' + esc(item.text) + '</span><span class="text-[10px] text-[#f6d987] shrink-0">' + esc(item.group) + '</span></button>'
  )).join('') || '<p class="text-slate-400 text-center py-2">No matches.</p>';
  results.classList.remove('hidden');
}

// --- Upload ---

function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  $('btn-upload').classList.add('hidden');
  $('upload-progress').classList.remove('hidden');
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/datasets');
  xhr.setRequestHeader('Authorization', 'Bearer ' + sessionStorage.getItem(TOKEN_KEY));
  xhr.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    const percent = Math.round(100 * event.loaded / event.total);
    $('upload-bar').style.width = percent + '%';
    $('upload-label').textContent = percent < 100 ? 'Uploading ' + percent + '%' : 'Storing in HDFS...';
  };
  const finish = () => {
    $('btn-upload').classList.remove('hidden');
    $('upload-progress').classList.add('hidden');
    $('upload-bar').style.width = '0';
    $('upload-input').value = '';
  };
  xhr.onload = () => {
    finish();
    if (xhr.status === 201) {
      toast(file.name + ' stored in HDFS');
      state.searchIndex = null;
      attempt(renderData);
      attempt(loadNotifications);
    } else if (xhr.status === 401) {
      signedOut();
    } else {
      let detail = 'Upload failed.';
      try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (error) { /* keep the default */ }
      toast(detail, true);
    }
  };
  xhr.onerror = () => {
    finish();
    toast("Can't reach the server.", true);
  };
  xhr.send(form);
}

// --- Events ---

const ACTIONS = {
  'job-details': (data) => showJobDetails(data.id),
  'run-job': async (data) => {
    await request('/jobs/' + encodeURIComponent(data.name) + '/run', { method: 'POST' });
    toast('Started ' + data.name + '. It will appear below shortly.');
    setTimeout(() => { if (state.page === 'hadoop') attempt(renderHadoop); }, 4000);
  },
  'ml-horizon': (data) => {
    state.mlHorizon = Number(data.year);
    drawForecast();
  },
  'alert-status': async (data) => {
    await request('/alerts/' + data.id, { method: 'PATCH', json: { status: data.status } });
    await renderAlerts();
  },
  'delete-rule': async (data) => {
    await request('/alert-rules/' + data.id, { method: 'DELETE' });
    state.searchIndex = null;
    toast('Rule deleted');
    await renderAlerts();
  },
  'toggle-role': async (data) => {
    await request('/users/' + data.id, { method: 'PATCH', json: { role: data.role } });
    await renderUsers();
  },
  'toggle-active': async (data) => {
    await request('/users/' + data.id, { method: 'PATCH', json: { active: data.active === 'true' } });
    await renderUsers();
  },
};

function closeMenus() {
  $('notif-dropdown').classList.add('hidden');
  $('user-dropdown').classList.add('hidden');
  $('search-results').classList.add('hidden');
}

function onSubmit(id, action) {
  $(id).addEventListener('submit', (event) => {
    event.preventDefault();
    attempt(() => action(event.target));
  });
}

function bindEvents() {
  document.addEventListener('click', (event) => {
    const nav = event.target.closest('[data-nav]');
    if (nav) {
      event.preventDefault();
      closeMenus();
      setPage(nav.dataset.nav);
      return;
    }
    const action = event.target.closest('[data-action]');
    if (action) {
      attempt(() => ACTIONS[action.dataset.action](action.dataset));
      return;
    }
    const close = event.target.closest('[data-close]');
    if (close) {
      $(close.dataset.close).classList.add('hidden');
      return;
    }
    if (!event.target.closest('#notif-dropdown, #user-dropdown, #btn-notif, #btn-user, #search-results, #global-search-input')) closeMenus();
  });

  $('btn-toggle-sidebar').addEventListener('click', () => setSidebar(!state.sidebarOpen));
  $('btn-notif').addEventListener('click', () => {
    $('user-dropdown').classList.add('hidden');
    $('notif-dropdown').classList.toggle('hidden');
    attempt(loadNotifications);
  });
  $('btn-user').addEventListener('click', () => {
    $('notif-dropdown').classList.add('hidden');
    $('user-dropdown').classList.toggle('hidden');
  });
  $('btn-mark-read').addEventListener('click', () => attempt(async () => {
    await request('/notifications/read', { method: 'POST' });
    await loadNotifications();
  }));
  $('btn-sign-out').addEventListener('click', async () => {
    await request('/auth/logout', { method: 'POST' }).catch(() => {});
    signedOut();
  });
  $('btn-refresh').addEventListener('click', async () => {
    const icon = document.querySelector('#btn-refresh svg');
    if (icon) icon.classList.add('animate-spin');
    state.searchIndex = null;
    await setPage(state.page);
    if (icon) icon.classList.remove('animate-spin');
  });
  $('global-search-input').addEventListener('input', (event) => attempt(() => runSearch(event.target.value.trim())));
  $('analytics-zone').addEventListener('change', () => attempt(renderAnalytics));
  $('analytics-variable').addEventListener('change', () => attempt(renderAnalytics));
  $('btn-upload').addEventListener('click', () => $('upload-input').click());
  $('upload-input').addEventListener('change', (event) => { if (event.target.files[0]) uploadFile(event.target.files[0]); });
  $('report-select').addEventListener('change', updateReportFormats);
  $('btn-download').addEventListener('click', () => attempt(downloadReport));
  $('ml-series').addEventListener('change', () => attempt(renderForecast));
  $('btn-retrain').addEventListener('click', () => attempt(async () => {
    const before = await request('/ml/summary');
    await request('/ml/retrain', { method: 'POST' });
    showRetrainState(true);
    toast('Training started. This takes about a minute.');
    state.jobPoll = setTimeout(() => attempt(() => watchTraining(before.latest && before.latest.version)), 5000);
  }));
  $('btn-new-rule').addEventListener('click', () => $('modal-rule').classList.remove('hidden'));
  $('btn-new-user').addEventListener('click', () => $('modal-user').classList.remove('hidden'));

  document.addEventListener('change', (event) => {
    const id = event.target.dataset && event.target.dataset.ticket;
    if (id) {
      attempt(async () => {
        await request('/tickets/' + id, { method: 'PATCH', json: { status: event.target.value } });
        toast('Ticket updated');
      });
    }
  });

  onSubmit('rule-form', async (form) => {
    await request('/alert-rules', { method: 'POST', json: {
      name: $('rule-name').value,
      metric: $('rule-metric').value,
      threshold: Number($('rule-threshold').value),
      severity: $('rule-severity').value,
    } });
    form.reset();
    $('modal-rule').classList.add('hidden');
    state.searchIndex = null;
    toast('Rule saved');
    await renderAlerts();
  });
  onSubmit('user-form', async (form) => {
    await request('/users', { method: 'POST', json: {
      name: $('new-user-name').value,
      title: $('new-user-title').value,
      email: $('new-user-email').value,
      role: $('new-user-role').value,
      password: $('new-user-password').value,
    } });
    form.reset();
    $('modal-user').classList.add('hidden');
    toast('User created');
    await renderUsers();
  });
  onSubmit('ticket-form', async (form) => {
    await request('/tickets', { method: 'POST', json: { category: $('ticket-category').value, description: $('ticket-description').value } });
    form.reset();
    toast('Ticket submitted');
    await renderSupport();
  });
  onSubmit('profile-form', async () => {
    state.user = await request('/auth/me', { method: 'PATCH', json: { name: $('settings-name').value, title: $('settings-title').value } });
    showUser();
    toast('Profile saved');
  });
  onSubmit('password-form', async (form) => {
    await request('/auth/password', { method: 'POST', json: { current_password: $('current-password').value, new_password: $('new-password').value } });
    form.reset();
    toast('Password changed');
  });
}

async function start() {
  buildSidebar();
  $('analytics-zone').innerHTML = '<option value="Glob">Global</option>' + ZONES.map((zone) => '<option>' + zone + '</option>').join('');
  $('ml-series').innerHTML = $('analytics-zone').innerHTML;
  bindEvents();
  state.sidebarOpen = true;
  try {
    state.user = await request('/auth/me');
  } catch (error) {
    if (error instanceof TypeError) toast("Can't reach the server. Is the backend running?", true);
    return;
  }
  showUser();
  lucide.createIcons();
  if (window.innerWidth < 768) setSidebar(false);
  await setPage('landing');
  attempt(loadNotifications);
  attempt(async () => updateAlertBadge(await request('/alerts')));
}

start();
