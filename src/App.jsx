import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity, AlertTriangle, ArrowDownLeft, ArrowUpRight, Bell, ChevronDown, CircleHelp, Database, FileUp, Filter, LayoutDashboard, Network, Search, ShieldCheck, SlidersHorizontal, Sparkles, WalletCards, X } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
const money = (n, currency = 'USD', missing = false) => { if (missing || !currency) return `${Number(n || 0).toLocaleString('en-US')} (currency unknown)`; try { return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n || 0) } catch { return `${Number(n || 0).toLocaleString('en-US')} ${currency} (unrecognized code)` } }
const initials = name => name?.slice(-3) || '—'
const timeLabel = tx => tx?.simulation_step != null ? `Simulation step ${tx.simulation_step}` : (tx?.timestamp ? new Date(tx.timestamp).toLocaleString() : 'Time unavailable')

async function request(path, options) {
  const res = await fetch(`${API}${path}`, options)
  if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || `Request failed (${res.status})`)) }
  return res.json()
}

function App() {
  const [page, setPage] = useState('Overview')
  const [dashboard, setDashboard] = useState(null)
  const [transactions, setTransactions] = useState([])
  const [alerts, setAlerts] = useState([])
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [search, setSearch] = useState('')
  const [severity, setSeverity] = useState('all')
  const [selected, setSelected] = useState(null)
  const [toast, setToast] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [importData, setImportData] = useState(null)
  const [importReport, setImportReport] = useState(null)
  const [evaluation, setEvaluation] = useState(null)
  const [evaluationBusy, setEvaluationBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [d, t, a, g] = await Promise.all([
        request('/dashboard'), request(`/transactions?q=${encodeURIComponent(search)}&severity=${severity}&limit=250`),
        request('/alerts'), request('/graph')
      ])
      setDashboard(d); setTransactions(t.items); setAlerts(a); setGraph(g); setError('')
    } catch (e) { setError(`${e.message}. Start the backend at http://localhost:8000 and refresh.`) }
  }, [search, severity])
  useEffect(() => { refresh() }, [refresh])
  const notify = message => { setToast(message); setTimeout(() => setToast(''), 4000) }

  async function loadDemo() {
    setBusy(true)
    try { const r = await request('/demo/load', { method: 'POST' }); notify(r.message); await refresh() }
    catch (e) { notify(e.message) } finally { setBusy(false) }
  }
  async function inspectUpload(event) {
    const file = event.target.files?.[0]; if (!file) return
    const form = new FormData(); form.append('file', file); setBusy(true)
    try { const data = await request('/transactions/inspect', { method: 'POST', body: form }); setImportData({ file, ...data }); setImportReport(null) }
    catch (e) { notify(e.message) } finally { setBusy(false); event.target.value = '' }
  }
  async function uploadDataset(mapping, datasetName, detectionConfig, analysisScope, timestampKind) {
    if (!importData?.file) return
    const form = new FormData(); form.append('file', importData.file); form.append('mapping', JSON.stringify(mapping))
    form.append('dataset_name', datasetName); form.append('detection_config', JSON.stringify(detectionConfig)); form.append('analysis_scope', analysisScope); form.append('timestamp_kind', timestampKind); setBusy(true)
    try {
      const report = await request('/transactions/upload', { method: 'POST', body: form })
      setImportReport(report); setImportData(null); setEvaluation(null); await refresh()
    } catch (e) { notify(typeof e.message === 'string' ? e.message : JSON.stringify(e.message)) }
    finally { setBusy(false) }
  }
  async function calculateEvaluation(positiveLabel, negativeLabel) {
    setEvaluationBusy(true)
    try { setEvaluation(await request(`/evaluation?labels_verified=true&positive_label=${encodeURIComponent(positiveLabel)}&negative_label=${encodeURIComponent(negativeLabel)}`)) }
    catch (e) { notify(e.message) } finally { setEvaluationBusy(false) }
  }
  async function setStatus(tx, status) {
    try { await request(`/alerts/${encodeURIComponent(tx.transaction_id)}/status?status=${status}`, { method: 'PATCH' }); await refresh(); setSelected(null) }
    catch (e) { notify(e.message) }
  }

  const nav = [
    { name: 'Overview', icon: LayoutDashboard }, { name: 'Transactions', icon: ArrowLeftRight },
    { name: 'Alerts', icon: Bell, count: dashboard?.alert_count }, { name: 'Network analysis', icon: Network },
    { name: 'Dataset & evaluation', icon: SlidersHorizontal },
  ]
  const chartData = dashboard?.activity?.map(x => ({ ...x, day: x.simulation_step != null ? `Step ${x.simulation_step}` : new Date(x.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) })) || []
  const pageTitle = page === 'Overview' ? 'Investigation overview' : page

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><ShieldCheck size={19} /></div><div><b>cleartrace</b><small>FINANCIAL INTELLIGENCE</small></div></div>
      <div className="workspace"><div className="workspace-icon">N</div><div><b>Northstar Bank</b><small>Investigation workspace</small></div><ChevronDown size={15} /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav>{nav.map(({ name, icon: Icon, count }) => <button key={name} onClick={() => setPage(name)} className={`nav-item ${page === name ? 'active' : ''}`}><Icon size={18} /><span>{name}</span>{count > 0 && <i>{count}</i>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="storage-card"><div className="storage-head"><Database size={16} /><span>Local workspace</span><span className="live-dot" /></div><p>Your investigation data stays on this machine.</p><div className="storage-meter"><span /></div><small>SQLite · ready</small></div><button className="nav-item"><CircleHelp size={18} /><span>Help & documentation</span></button><div className="profile"><div className="avatar">JD</div><div><b>Jordan Davis</b><small>Financial investigator</small></div><ChevronDown size={15} /></div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs">Investigation <span>/</span> <b>{pageTitle}</b></div><div className="top-actions"><div className="connection"><span className={`live-dot ${error ? 'offline' : ''}`} /> {error ? 'API disconnected' : 'All systems operational'}</div><button className="icon-button" aria-label="Notifications"><Bell size={18} /><em /></button><div className="avatar small">JD</div></div></header>
      <div className="content">
        <div className="page-head"><div><div className="eyebrow">MONITOR · INVESTIGATE · REVIEW</div><h1>{pageTitle}</h1><p>{page === 'Overview' ? 'A clear view of transaction activity and emerging risk indicators.' : page === 'Transactions' ? 'Search and review transaction activity across monitored accounts.' : page === 'Alerts' ? 'Review prioritized risk indicators with supporting evidence.' : page === 'Network analysis' ? 'Explore account relationships and connected transfer paths.' : 'Import public transaction datasets and evaluate against verified reference labels.'}</p></div><div className="head-actions"><label className="button secondary"><FileUp size={16} /> Import CSV<input type="file" accept=".csv,text/csv" hidden onChange={inspectUpload} /></label><button className="button primary" onClick={loadDemo} disabled={busy}><Sparkles size={16} /> {busy ? 'Loading…' : 'Load demo data'}</button></div></div>
        {error && <div className="error-banner"><AlertTriangle size={17}/>{error}</div>}
        {page === 'Overview' && <Overview dashboard={dashboard} chartData={chartData} alerts={alerts} onSelect={setSelected} onNavigate={setPage} />}
        {page === 'Transactions' && <Transactions items={transactions} search={search} setSearch={setSearch} severity={severity} setSeverity={setSeverity} onSelect={setSelected} />}
        {page === 'Alerts' && <Alerts items={alerts} onSelect={setSelected} onStatus={setStatus} />}
        {page === 'Network analysis' && <NetworkPage graph={graph} onSelect={setSelected} />}
        {page === 'Dataset & evaluation' && <DatasetEvaluation dashboard={dashboard} result={evaluation} busy={evaluationBusy} onEvaluate={calculateEvaluation} />}
        <footer>ClearTrace supports investigation and prioritization. A risk indicator is not a finding of wrongdoing.</footer>
      </div>
    </main>
    {selected && <Detail tx={selected} onClose={() => setSelected(null)} onStatus={setStatus} />}
    {importData && <DatasetImportDialog data={importData} busy={busy} onCancel={() => setImportData(null)} onImport={uploadDataset} />}
    {importReport && <ImportReport report={importReport} onClose={() => setImportReport(null)} />}
    {toast && <div className="toast"><ShieldCheck size={16}/>{toast}<button onClick={() => setToast('')}><X size={14}/></button></div>}
  </div>
}

function ArrowLeftRight({ size = 18 }) { return <Activity size={size} /> }

const importFields = [
  ['transaction_id', 'Source transaction ID', false], ['timestamp', 'Timestamp / simulation step', true], ['sender', 'Origin account', true],
  ['receiver', 'Destination account', true], ['amount', 'Amount', true], ['currency', 'Currency', false],
  ['channel', 'Payment channel / type', false], ['label', 'Dataset reference label', false], ['source_alert_id', 'Source alert ID', false], ['from_bank', 'Origin bank (optional)', false],
  ['to_bank', 'Destination bank (optional)', false],
]

function DatasetImportDialog({ data, busy, onCancel, onImport }) {
  const [mapping, setMapping] = useState(data.mapping || {})
  const [datasetName, setDatasetName] = useState(data.file.name.replace(/\.csv$/i, ''))
  const [analysisScope, setAnalysisScope] = useState('import')
  const [timestampKind, setTimestampKind] = useState('datetime')
  const [config, setConfig] = useState({ rapid_window_minutes: 60, structuring_window_hours: 24, rapid_window_steps: 1, structuring_window_steps: 24, burst_window_steps: 1, small_transfer_threshold: 1000, alert_threshold: 40, rule_weight: .25, graph_weight: .30, temporal_weight: .25, anomaly_weight: .20 })
  const setField = (key, value) => setMapping(old => ({ ...old, [key]: value }))
  const setSetting = (key, value) => setConfig(old => ({ ...old, [key]: Number(value) }))
  return <div className="drawer-backdrop"><section className="import-dialog">
    <div className="drawer-head"><div><div className="eyebrow">CSV COLUMN REVIEW</div><h2>Map dataset columns</h2></div><button className="icon-button" onClick={onCancel}><X size={18}/></button></div>
    <p className="dialog-copy">Detected {data.headers.length} columns and {data.sample.length} preview rows. IBM AMLSim headers are inferred when possible; confirm mappings before importing.</p>
    <label className="field-label">Dataset name<input value={datasetName} onChange={e => setDatasetName(e.target.value)} /></label>
    <label className="field-label">Analysis scope<select value={analysisScope} onChange={e => setAnalysisScope(e.target.value)}><option value="import">This import only</option><option value="all_imported">All imported datasets together</option></select></label>
    <label className="field-label">Timestamp meaning<select value={timestampKind} onChange={e => setTimestampKind(e.target.value)}><option value="datetime">Calendar date/time</option><option value="simulation_step">Integer simulation step (no duration assumed)</option></select></label>
    {timestampKind === 'simulation_step' && <p className="dialog-copy">Transactions sharing a simulation step are tied. ClearTrace preserves the original step and does not convert it to a calendar date.</p>}
    <div className="mapping-grid">{importFields.map(([key, title, required]) => <label className="field-label" key={key}>{title}{required && <i> required</i>}<select value={mapping[key] || ''} onChange={e => setField(key, e.target.value)}><option value="">{key === 'label' ? 'Unlabeled' : 'Not mapped'}</option>{data.headers.map(h => <option key={h} value={h}>{h}</option>)}</select></label>)}</div>
    <div className="dialog-section"><b>Detection windows & signal weights</b><div className="config-grid">{timestampKind === 'simulation_step' ? <label className="field-label">Rapid transfer window (steps)<input type="number" min="1" value={config.rapid_window_steps} onChange={e => setSetting('rapid_window_steps', e.target.value)} /></label> : <label className="field-label">Rapid transfer window (minutes)<input type="number" min="1" value={config.rapid_window_minutes} onChange={e => setSetting('rapid_window_minutes', e.target.value)} /></label>} {timestampKind === 'simulation_step' ? <label className="field-label">Structuring window (steps)<input type="number" min="1" value={config.structuring_window_steps} onChange={e => setSetting('structuring_window_steps', e.target.value)} /></label> : <label className="field-label">Structuring window (hours)<input type="number" min="1" value={config.structuring_window_hours} onChange={e => setSetting('structuring_window_hours', e.target.value)} /></label>} {timestampKind === 'simulation_step' && <label className="field-label">Burst window (steps)<input type="number" min="1" value={config.burst_window_steps} onChange={e => setSetting('burst_window_steps', e.target.value)} /></label>}<label className="field-label">Small transfer threshold (USD)<input type="number" min="1" value={config.small_transfer_threshold} onChange={e => setSetting('small_transfer_threshold', e.target.value)} /></label><label className="field-label">Alert threshold (0–100)<input type="number" min="0" max="100" value={config.alert_threshold} onChange={e => setSetting('alert_threshold', e.target.value)} /></label>{[['rule_weight','Rule'],['graph_weight','Graph'],['temporal_weight','Temporal'],['anomaly_weight','Anomaly']].map(([key,title]) => <label className="field-label" key={key}>{title} score weight<input type="number" min="0" max="1" step="0.05" value={config[key]} onChange={e => setSetting(key, e.target.value)} /></label>)}</div></div>
    {data.sample.length > 0 && <div className="sample-preview"><b>Source preview</b><div className="table-scroll"><table><thead><tr>{data.headers.slice(0, 7).map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{data.sample.slice(0, 3).map((r, i) => <tr key={i}>{data.headers.slice(0, 7).map(h => <td key={h}>{r[h]}</td>)}</tr>)}</tbody></table></div></div>}
    <div className="drawer-actions"><button className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" disabled={busy || importFields.filter(x => x[2]).some(x => !mapping[x[0]])} onClick={() => onImport(mapping, datasetName, config, analysisScope, timestampKind)}>{busy ? 'Importing…' : 'Validate & import'}</button></div>
  </section></div>
}

function ImportReport({ report, onClose }) { return <div className="drawer-backdrop"><section className="import-dialog report-dialog"><div className="drawer-head"><div><div className="eyebrow">IMPORT SUMMARY</div><h2>Dataset import complete</h2></div><button className="icon-button" onClick={onClose}><X size={18}/></button></div><div className="import-stats"><b>{report.inserted}<small>imported</small></b><b>{report.skipped_duplicates}<small>duplicates skipped</small></b><b>{report.invalid_count}<small>invalid rows</small></b><b>{report.labelled_rows}<small>dataset labels preserved</small></b></div><p className="dialog-copy">{report.message} Generated risk indicators remain separate from source labels.</p>{report.currency_warning && <div className="evaluation-message">{report.currency_warning}</div>}{report.invalid_rows?.length > 0 && <div className="invalid-list"><h3>Rows requiring correction</h3>{report.invalid_rows.map((row, i) => <p key={i}><b>Row {row.row}:</b> {row.error}</p>)}</div>}<div className="drawer-actions"><button className="button primary" onClick={onClose}>Done</button></div></section></div> }

function DatasetEvaluation({ dashboard, result, busy, onEvaluate }) {
  const [positive, setPositive] = useState('True'), [negative, setNegative] = useState('False')
  return <section className="panel evaluation-panel"><div className="panel-heading"><div><h2>Dataset provenance & evaluation</h2><p>Reference labels are kept separate from model-generated risk alerts.</p></div><span className="graph-count">{dashboard?.dataset_count || 0} imported datasets</span></div><div className="eval-cards"><div><small>Imported rows with source labels</small><b>{dashboard?.labelled_count || 0}</b></div><div><small>Evaluation method</small><b>Train / validation / holdout</b></div><div><small>Alert label semantics</small><b>Risk signals only · never confirmed findings</b></div></div><div className="disclaimer"><ShieldCheck size={16}/><p>Only exact source labels you explicitly map are used. The validation partition selects a threshold; metrics are reported on the later chronological holdout. Unknown labels are ignored.</p></div><div className="mapping-grid"><label className="field-label">Exact positive label<input value={positive} onChange={e => setPositive(e.target.value)} /></label><label className="field-label">Exact negative label<input value={negative} onChange={e => setNegative(e.target.value)} /></label></div><button className="button primary" onClick={() => onEvaluate(positive, negative)} disabled={busy || !positive || !negative || positive === negative}>{busy ? 'Calculating…' : 'I verified these labels · calculate metrics'}</button>{result && (result.available ? <div className="metric-grid"><Metric name="Precision" value={result.precision}/><Metric name="Recall" value={result.recall}/><Metric name="F1 score" value={result.f1}/><Metric name="False-positive rate" value={result.false_positive_rate}/><p>{result.evaluation_type} · {result.evaluated_sample_count} holdout rows · {result.positive_class_count} positive ({(result.positive_class_proportion * 100).toFixed(2)}%) · {result.negative_class_count} negative ({(result.negative_class_proportion * 100).toFixed(2)}%) · validation-selected threshold {result.threshold} (validation F1 {(result.validation_selected_f1 * 100).toFixed(1)}%; FPR cap {(result.max_validation_fpr * 100).toFixed(1)}%). This evaluation cutoff does not change the configured live alert threshold.</p><p>Validation sample: {result.validation_sample_count} rows, {result.validation_positive_count} positive. Baselines — all-negative F1 {(result.baselines.all_negative.f1 * 100).toFixed(1)}%; existing threshold {result.fixed_detector_threshold} F1 {(result.baselines.existing_detector.f1 * 100).toFixed(1)}%.</p></div> : <div className="evaluation-message">{result.reason}</div>)}</section>
}
function Metric({ name, value }) { return <div className="metric-card"><small>{name}</small><b>{(value * 100).toFixed(1)}%</b></div> }

function Overview({ dashboard: d, chartData, alerts, onSelect, onNavigate }) {
  return <>
    <div className="stat-grid">
      <Stat label="Transaction volume" value={d?.volume_comparable ? money(d.total_volume, d.total_volume_currency) : "Mixed / unknown currencies"} sub={d?.currency_warning ? `${d.currency_warning} ${Object.entries(d.currency_totals || {}).map(([c, v]) => `${c} ${Number(v).toLocaleString('en-US')}`).join(' ? ')}` : `${d?.transaction_count || 0} transactions analyzed`} icon={WalletCards} tone="blue" trend="↑ 12.8%" />
      <Stat label="Accounts monitored" value={d?.accounts_monitored ?? '—'} sub={`${d?.flagged_accounts || 0} accounts with indicators`} icon={Activity} tone="violet" trend="Active" />
      <Stat label="Open alerts" value={d?.alert_count ?? '—'} sub={`${d?.high_alerts || 0} high priority`} icon={Bell} tone="amber" trend={d?.alert_count ? 'Review' : 'Clear'} />
      <Stat label="High priority" value={d?.high_alerts ?? '—'} sub={`${d?.medium_alerts || 0} medium priority`} icon={AlertTriangle} tone="red" trend="Triage" />
    </div>
    <div className="dashboard-grid"><section className="panel chart-panel"><div className="panel-heading"><div><h2>Transaction activity</h2><p>Daily volume and flagged transfers · last 14 active days</p></div><button className="select-pill"><span className="live-dot"/> Last 14 days <ChevronDown size={14}/></button></div><div className="chart-legend"><span><i className="legend-blue"/>{d?.volume_comparable ? `Transaction volume (${d.total_volume_currency})` : 'Volume unavailable across mixed / unknown currencies'}</span><span><i className="legend-red"/>Flagged transactions</span></div><div className="chart-wrap">{chartData.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}><defs><linearGradient id="blueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4277f5" stopOpacity={0.19}/><stop offset="95%" stopColor="#4277f5" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#edf0f4" vertical={false}/><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#8b95a5', fontSize: 11 }} dy={10}/><YAxis axisLine={false} tickLine={false} tick={{ fill: '#8b95a5', fontSize: 11 }} tickFormatter={v => `$${Math.round(v / 1000)}k`}/><Tooltip formatter={(v, name) => [name === 'volume' ? money(v, d?.total_volume_currency) : v, name === 'volume' ? 'Volume' : 'Flagged']} contentStyle={{ border: '1px solid #e9edf3', borderRadius: 10, boxShadow: '0 8px 30px #182b4916' }}/><Area type="monotone" dataKey="volume" stroke="#477af5" strokeWidth={2.5} fill="url(#blueFill)"/><Area type="monotone" dataKey="flagged" stroke="#f17c70" strokeWidth={2} fill="transparent"/></AreaChart></ResponsiveContainer> : <Empty text="Load the synthetic demonstration transactions to populate activity."/>}</div></section>
      <section className="panel signal-panel"><div className="panel-heading"><div><h2>Risk signals</h2><p>Composite risk score distribution</p></div><button className="more-button">•••</button></div><div className="signal-summary"><div className="signal-total">{d?.alert_count ?? '—'}<span>elevated indicators</span></div><div className="signal-bars"><Signal label="High" value={d?.high_alerts || 0} total={d?.alert_count || 0} tone="red"/><Signal label="Medium" value={d?.medium_alerts || 0} total={d?.alert_count || 0} tone="amber"/><Signal label="Low" value={Math.max(0, (d?.transaction_count || 0) - (d?.alert_count || 0))} total={d?.transaction_count || 0} tone="green"/></div></div><div className="signal-note"><div className="note-icon"><Sparkles size={16}/></div><p><b>Multi-signal scoring</b><br/>Graph, temporal, anomaly, and rule signals combine into one review priority.</p></div><button className="text-link" onClick={() => onNavigate('Alerts')}>View all alerts <span>→</span></button></section></div>
    <section className="panel table-panel"><div className="panel-heading"><div><h2>Priority alerts</h2><p>Transactions with the strongest combined risk indicators</p></div><button className="text-link" onClick={() => onNavigate('Alerts')}>View all alerts <span>→</span></button></div><div className="table-scroll"><table><thead><tr><th>TRANSACTION</th><th>ACCOUNTS</th><th>AMOUNT</th><th>RISK SCORE</th><th>DETECTED SIGNALS</th><th>STATUS</th></tr></thead><tbody>{alerts.slice(0, 5).map(tx => <tr key={tx.transaction_id} onClick={() => onSelect(tx)}><td><b className="mono">{tx.transaction_id}</b><small>{timeLabel(tx)}</small></td><td><div className="account-pair"><span className="account-chip">{initials(tx.sender)}</span><ArrowUpRight size={13}/><span className="account-chip">{initials(tx.receiver)}</span></div></td><td className="amount-cell">{money(tx.amount, tx.currency, tx.currency_missing)}</td><td><RiskBadge score={tx.risk_score}/></td><td><div className="signal-tags">{signalNames(tx).slice(0, 2).map(x => <span key={x}>{x}</span>)}</div></td><td><Status status={tx.review_status}/></td></tr>)}</tbody></table>{!alerts.length && <Empty text="No alerts yet. Load demo data or import transactions."/>}</div></section>
  </>
}

function Stat({ label, value, sub, icon: Icon, tone, trend }) { return <div className="stat-card"><div className="stat-top"><span>{label}</span><div className={`stat-icon ${tone}`}><Icon size={18}/></div></div><div className="stat-value">{value}</div><div className="stat-bottom"><span>{sub}</span><i className={tone}>{trend}</i></div></div> }
function Signal({ label, value, total, tone }) { const pct = total ? Math.max(value ? 4 : 0, value / total * 100) : 0; return <div className="signal-line"><div><span>{label}</span><b>{value}</b></div><div className="bar-track"><span className={tone} style={{ width: `${pct}%` }}/></div></div> }
function Empty({ text }) { return <div className="empty-state"><div className="empty-icon"><Database size={20}/></div><p>{text}</p></div> }
function signalNames(tx) { return (tx.reasons || []).filter(x => x !== 'No elevated signal identified').map(x => x.includes('circular') || x.includes('path') ? 'Circular path' : x.includes('Rapid') || x.includes('burst') ? 'Temporal burst' : x.includes('small') ? 'Repeated small' : x.includes('Large') ? 'Large transfer' : x.includes('activity') ? 'Network activity' : x) }
function RiskBadge({ score }) { const level = score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low'; return <span className={`risk-badge ${level}`}><i/>{score} <small>/ 100</small></span> }
function Status({ status }) { return <span className={`status-badge ${status}`}><i/>{status}</span> }

function Transactions({ items, search, setSearch, severity, setSeverity, onSelect }) {
  return <section className="panel full-panel"><div className="toolbar"><label className="search-box"><Search size={16}/><input placeholder="Search transaction or account…" value={search} onChange={e => setSearch(e.target.value)}/>{search && <button onClick={() => setSearch('')}><X size={13}/></button>}</label><label className="filter-select"><Filter size={15}/><select value={severity} onChange={e => setSeverity(e.target.value)}><option value="all">All risk levels</option><option value="high">High priority</option><option value="medium">Medium priority</option><option value="low">Low risk</option></select></label><span className="results-count">{items.length} transactions</span></div><TransactionTable items={items} onSelect={onSelect}/></section>
}
function TransactionTable({ items, onSelect }) { return <div className="table-scroll"><table><thead><tr><th>TRANSACTION</th><th>ACCOUNTS</th><th>AMOUNT</th><th>CHANNEL</th><th>RISK SCORE</th><th>SOURCE LABEL</th><th>STATUS</th></tr></thead><tbody>{items.map(tx => <tr key={tx.transaction_id} onClick={() => onSelect(tx)}><td><b className="mono">{tx.source_transaction_id || tx.transaction_id}</b><small>{timeLabel(tx)}{tx.source_transaction_id ? ` · internal ${tx.transaction_id}` : ''}</small></td><td><div className="account-pair"><span className="account-chip">{initials(tx.sender)}</span>{tx.sender}<ArrowUpRight size={13}/><span className="account-chip">{initials(tx.receiver)}</span>{tx.receiver}</div></td><td className="amount-cell">{money(tx.amount, tx.currency, tx.currency_missing)}</td><td><span className="channel">{tx.channel}</span></td><td><RiskBadge score={tx.risk_score}/></td><td>{tx.label_source === 'dataset' ? <span className="reference-label">Reference: {tx.source_label}</span> : <span className="no-label">Unlabeled</span>}</td><td><Status status={tx.review_status}/></td></tr>)}</tbody></table>{!items.length && <Empty text="No transactions match this view."/>}</div> }

function Alerts({ items, onSelect, onStatus }) { const [filter, setFilter] = useState('all'); const filtered = filter === 'all' ? items : items.filter(x => x.review_status === filter); return <section className="panel full-panel"><div className="toolbar"><div className="tabs">{['all','open','reviewing','closed'].map(x => <button className={filter === x ? 'selected' : ''} key={x} onClick={() => setFilter(x)}>{x[0].toUpperCase()+x.slice(1)}{x === 'all' && <b>{items.length}</b>}</button>)}</div><span className="results-count">{filtered.length} indicators</span></div><div className="alert-list">{filtered.map(tx => <article className="alert-card" key={tx.transaction_id}><div className={`alert-symbol ${tx.risk_score >= 70 ? 'red' : 'amber'}`}><AlertTriangle size={18}/></div><div className="alert-main"><div className="alert-title-row"><h3>{signalNames(tx).join(' · ') || 'Elevated transaction score'}</h3><RiskBadge score={tx.risk_score}/></div><p>{tx.reasons?.join(' · ')}</p><div className="alert-meta"><span className="mono">{tx.transaction_id}</span><span>{timeLabel(tx)}</span><span>{tx.sender} <ArrowUpRight size={12}/> {tx.receiver}</span><span>{money(tx.amount, tx.currency, tx.currency_missing)}</span></div></div><div className="alert-actions"><Status status={tx.review_status}/><button className="button secondary compact" onClick={() => onSelect(tx)}>Investigate</button>{tx.review_status === 'open' && <button className="button primary compact" onClick={() => onStatus(tx, 'reviewing')}>Start review</button>}</div></article>)}{!filtered.length && <Empty text="No alerts in this status. Load demo data to explore investigation workflows."/>}</div></section> }

function NetworkPage({ graph, onSelect }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current || !graph.nodes.length) return
    const elements = [...graph.nodes.map(n => ({ data: { id: n.id, label: n.id } })), ...graph.edges.map(e => ({ data: { id: e.id, source: e.source, target: e.target, amount: e.amount, risk: e.risk } }))]
    const cy = cytoscape({ container: ref.current, elements, style: [
      { selector: 'node', style: { 'background-color': '#edf2ff', 'border-color': '#6f91ef', 'border-width': 1.5, label: 'data(label)', color: '#33415f', 'font-size': 10, 'text-valign': 'bottom', 'text-margin-y': 7, width: 32, height: 32 } },
      { selector: 'edge', style: { width: 'mapData(risk, 0, 100, 1, 4)', 'line-color': 'mapData(risk, 0, 100, #c4d2ed, #e7796d)', 'target-arrow-color': '#96a7c4', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: 0.7 } },
      { selector: ':selected', style: { 'background-color': '#6386ed', 'line-color': '#6386ed', 'target-arrow-color': '#6386ed' } },
    ], layout: { name: 'cose', animate: false, padding: 35, nodeRepulsion: 7000, idealEdgeLength: 85 }, minZoom: 0.35, maxZoom: 2 })
    cy.on('tap', 'edge', event => { const id = event.target.id(); const tx = graph.edges.find(e => e.id === id); if (tx) onSelect({ ...tx, transaction_id: tx.id, sender: tx.source, receiver: tx.target, timestamp: tx.timestamp, simulation_step: tx.simulation_step, reasons: tx.reasons || [`Network relationship · ${money(tx.amount, tx.currency, tx.currency_missing)}`], review_status: 'open' }) })
    return () => cy.destroy()
  }, [graph, onSelect])
  return <section className="panel graph-panel"><div className="panel-heading"><div><h2>Account relationship map</h2><p>Directed edges show transfers; warmer edges indicate higher composite risk.</p></div><span className="graph-count">{graph.nodes.length} accounts · {graph.edges.length} transfers</span></div>{graph.nodes.length ? <><div className="graph-legend"><span><i className="node-dot"/>Account</span><span><i className="edge-line"/>Transfer</span><span><i className="edge-line risk"/>Elevated risk</span><span className="graph-tip">Select an edge to inspect transaction details</span></div><div ref={ref} className="cytoscape-canvas"/></> : <Empty text="No account relationships yet. Load demo transactions to explore the network."/>}</section>
}

function Detail({ tx, onClose, onStatus }) { return <div className="drawer-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}><aside className="detail-drawer"><div className="drawer-head"><div><div className="eyebrow">TRANSACTION INVESTIGATION</div><h2>Risk assessment</h2></div><button className="icon-button" onClick={onClose}><X size={18}/></button></div><div className="detail-id"><span className="mono">{tx.source_transaction_id || tx.transaction_id}{tx.source_transaction_id && <small> · {tx.transaction_id}</small>}</span><RiskBadge score={tx.risk_score}/></div><div className="detail-transfer"><div><small>FROM ACCOUNT</small><b>{tx.sender}</b></div><ArrowUpRight size={17}/><div><small>TO ACCOUNT</small><b>{tx.receiver}</b></div></div><div className="detail-amount">{money(tx.amount, tx.currency, tx.currency_missing)} <span>{tx.currency || 'USD'} · {tx.channel || 'transfer'}</span></div><div className="detail-time">{timeLabel(tx)} · {tx.source_dataset || 'local'}</div>{tx.label_source === 'dataset' && <div className="source-label-detail">Dataset reference label: <b>{tx.source_label}</b> <span>(not generated by detector)</span></div>}<h3 className="section-title">Signal breakdown</h3><div className="score-list"><Score label="Graph relationships" score={tx.graph_score}/><Score label="Temporal behavior" score={tx.temporal_score}/><Score label="Anomaly model" score={tx.anomaly_score}/><Score label="Rule-based indicators" score={tx.rule_score}/></div><h3 className="section-title">Evidence & observations</h3><ul className="evidence-list">{tx.reasons?.map((x, i) => <li key={i}><span><Activity size={14}/></span>{x}</li>)}</ul>{tx.related_accounts?.length > 0 && <div className="evidence-extra"><b>Related accounts</b><p>{tx.related_accounts.join(' · ')}</p></div>}{tx.supporting_transaction_ids?.length > 0 && <div className="evidence-extra"><b>Supporting transactions</b><p>{tx.supporting_transaction_ids.join(' · ')}</p></div>}<div className="disclaimer"><ShieldCheck size={16}/><p>These explainable indicators support investigator triage. They do not establish criminal activity.</p></div><div className="drawer-actions"><button className="button secondary" onClick={onClose}>Close</button>{tx.review_status !== 'closed' && <button className="button primary" onClick={() => onStatus(tx, tx.review_status === 'reviewing' ? 'closed' : 'reviewing')}>{tx.review_status === 'reviewing' ? 'Mark reviewed' : 'Start review'}</button>}</div></aside></div> }
function Score({ label, score = 0 }) { return <div className="score-row"><div><span>{label}</span><b>{Math.round(score * 100)}<small>/100</small></b></div><div className="bar-track"><span className={score > .65 ? 'red' : score > .35 ? 'amber' : 'blue'} style={{ width: `${Math.max(score * 100, score ? 4 : 0)}%` }}/></div></div> }

export default App
