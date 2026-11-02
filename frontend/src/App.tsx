import { useState, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import './index.css';
import { api } from './services/api';
import {
  LayoutDashboard, Database, Upload, Zap, Activity,
  Settings, Shield, FlaskConical, AlertTriangle,
  CheckCircle, TrendingUp, RefreshCw, Play, XCircle,
  Eye, Brain, Server
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid
} from 'recharts';


// ── Types ────────────────────────────────────────────────────
type Page = 'dashboard' | 'datasets' | 'schema' | 'query' | 'performance'
  | 'monitoring' | 'incidents' | 'optimizations' | 'approvals'
  | 'experiments' | 'settings';

// ── Sidebar Navigation ────────────────────────────────────────
const NAV = [
  { id: 'dashboard',      label: 'Dashboard',       icon: LayoutDashboard },
  { id: 'datasets',       label: 'Datasets',         icon: Upload },
  { id: 'schema',         label: 'Schema Explorer',  icon: Database },
  { id: 'query',          label: 'AI Query Assistant',icon: Brain },
  { id: 'performance',    label: 'Performance',       icon: TrendingUp },
  { id: 'monitoring',     label: 'Monitoring',        icon: Activity },
  { id: 'incidents',      label: 'Incidents',         icon: AlertTriangle },
  { id: 'optimizations',  label: 'Optimizations',     icon: Zap },
  { id: 'approvals',      label: 'Approvals',         icon: Shield },
  { id: 'experiments',    label: 'Experiments',       icon: FlaskConical },
  { id: 'settings',       label: 'Settings',          icon: Settings },
] as const;

// ── Reusable helpers ─────────────────────────────────────────
function Spinner() { return <div className="spinner-center"><div className="spinner"/></div>; }
function Badge({ v, type }: { v: string; type?: string }) {
  const map: Record<string,string> = {
    open:'danger', investigating:'warning', resolved:'success', dismissed:'neutral',
    pending:'warning', approved:'success', rejected:'danger', applied:'success', failed:'danger',
    low:'info', medium:'warning', high:'danger', critical:'danger',
    active:'success', 'not_running':'neutral', completed:'success',
  };
  const cls = type || map[v?.toLowerCase()] || 'neutral';
  return <span className={`badge badge-${cls}`}>{v || '—'}</span>;
}

// ── Dashboard ─────────────────────────────────────────────────
function Dashboard() {
  const [data, setData] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.dashboard(), api.health()])
      .then(([d, h]) => { setData(d); setHealth(h); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  const metrics = [
    { label: 'Tables', value: data?.tables ?? 0, icon: '🗃️', color: '#6366f1' },
    { label: 'Queries Run', value: data?.total_queries ?? 0, icon: '⚡', color: '#22c55e' },
    { label: 'Slow Queries', value: data?.slow_queries ?? 0, icon: '🐢', color: '#f59e0b' },
    { label: 'Open Incidents', value: data?.open_incidents ?? 0, icon: '🔴', color: '#ef4444' },
    { label: 'Resolved', value: data?.resolved_incidents ?? 0, icon: '✅', color: '#22c55e' },
    { label: 'Pending Approvals', value: data?.pending_approvals ?? 0, icon: '⏳', color: '#a855f7' },
    { label: 'Optimizations', value: data?.optimizations ?? 0, icon: '🚀', color: '#38bdf8' },
  ];

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">AgenticDB Dashboard</h1>
        <p className="page-subtitle">Autonomous AI Database Administrator — Real-time insights & performance management</p>
      </div>

      {/* LLM Status */}
      {!health?.llm_configured && (
        <div className="alert alert-warning mb-6">
          <AlertTriangle size={16}/>
          <div>
            <strong>LLM not configured.</strong> SQL generation and AI diagnosis require{' '}
            <code>LLM_API_KEY</code> in your <code>.env</code> file.
            Dataset upload, schema exploration, monitoring, and deterministic analysis are fully available.
          </div>
        </div>
      )}

      <div className="metric-grid">
        {metrics.map(m => (
          <div key={m.label} className="metric-card" style={{ '--accent-gradient': `linear-gradient(90deg, ${m.color}, ${m.color}88)` } as any}>
            <div className="metric-icon">{m.icon}</div>
            <div className="metric-value">{m.value}</div>
            <div className="metric-label">{m.label}</div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title mb-4">System Status</div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              ['Backend API', '🟢 Connected'],
              ['LLM Provider', health?.llm_configured ? `🟢 ${health.llm_model}` : '🔴 Not configured'],
              ['Monitoring', data?.monitoring_active ? '🟢 Active' : '🔴 Inactive'],
              ['Database', '🟢 SQLite (dev mode)'],
            ].map(([k,v]) => (
              <div key={k} className="flex justify-between items-center">
                <span className="text-secondary">{k}</span>
                <span style={{fontWeight:500}}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-title mb-4">Quick Actions</div>
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {[
              { label:'Load Sample Retail Data', action: () => api.loadSample(500).then(() => window.location.reload()), icon:'📦' },
              { label:'Run Monitoring Cycle', action: () => api.runCycle(), icon:'🔄' },
              { label:'View API Docs', action: () => window.open('http://localhost:8000/docs'), icon:'📖' },
            ].map(a => (
              <button key={a.label} className="btn btn-secondary" style={{justifyContent:'flex-start'}} onClick={a.action}>
                <span>{a.icon}</span>{a.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Dataset Upload ─────────────────────────────────────────────
function Datasets() {
  const [tables, setTables] = useState<any[]>([]);
  const [file, setFile] = useState<File|null>(null);
  const [tableName, setTableName] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{type:string;text:string}|null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = () => api.getTables().then(d => setTables(d.tables || []));
  useEffect(() => { load(); }, []);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setMsg(null);
    try {
      const r = await api.uploadCSV(file, tableName || file.name.replace('.csv',''), overwrite);
      setMsg({ type:'success', text:`Imported ${r.row_count} rows into "${r.table_name}". ${r.warnings?.join(' ')||''}` });
      setFile(null); setTableName('');
      load();
    } catch(e:any) {
      setMsg({ type:'danger', text: e.message });
    } finally { setLoading(false); }
  };

  const handleSample = async () => {
    setLoading(true); setMsg(null);
    try {
      await api.loadSample(500);
      setMsg({ type:'success', text:'Sample retail data loaded: customers, products, orders, order_items' });
      load();
    } catch(e:any) { setMsg({ type:'danger', text: e.message }); }
    finally { setLoading(false); }
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Dataset Management</h1>
        <p className="page-subtitle">Upload CSV files or load sample data to begin querying</p>
      </div>

      {msg && <div className={`alert alert-${msg.type} mb-4`}>{msg.text}</div>}

      <div className="grid-2 mb-6">
        {/* Upload */}
        <div className="card">
          <div className="section-title">Upload CSV</div>
          <div
            className={`upload-zone ${dragging?'drag-over':''}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if(f) { setFile(f); setTableName(f.name.replace('.csv','')); } }}
          >
            <div className="upload-icon">📁</div>
            <div className="upload-title">{file ? file.name : 'Drop CSV file here'}</div>
            <div className="upload-sub">{file ? `${(file.size/1024).toFixed(1)} KB` : 'or click to browse'}</div>
            <input ref={inputRef} type="file" accept=".csv" hidden onChange={e => { const f=e.target.files?.[0]; if(f){setFile(f);setTableName(f.name.replace('.csv',''));} }} />
          </div>
          {file && (
            <div style={{marginTop:16}}>
              <div className="form-group">
                <label className="form-label">Table Name</label>
                <input className="input" value={tableName} onChange={e=>setTableName(e.target.value)} placeholder="table_name"/>
              </div>
              <label style={{display:'flex',alignItems:'center',gap:8,marginBottom:16,cursor:'pointer'}}>
                <input type="checkbox" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>
                <span className="text-secondary text-sm">Overwrite if table exists</span>
              </label>
              <button className="btn btn-primary w-full" onClick={handleUpload} disabled={loading}>
                {loading ? 'Importing…' : '⬆️ Import Table'}
              </button>
            </div>
          )}
        </div>

        {/* Sample Data */}
        <div className="card">
          <div className="section-title">Sample Retail Dataset</div>
          <p className="text-secondary mb-4" style={{fontSize:13,lineHeight:1.7}}>
            Load a synthetic retail database with 4 tables:<br/>
            <strong>customers</strong>, <strong>products</strong>, <strong>orders</strong>, <strong>order_items</strong><br/><br/>
            Great for testing AI queries and optimization features immediately.
          </p>
          <div style={{background:'var(--bg-elevated)',borderRadius:'var(--radius-sm)',padding:12,marginBottom:16}}>
            <div style={{fontSize:12,color:'var(--text-muted)',fontFamily:'monospace'}}>
              ~ 500 customers · 200 products · 2000 orders · 5000+ items
            </div>
          </div>
          <button className="btn btn-primary w-full" onClick={handleSample} disabled={loading}>
            {loading ? 'Generating…' : '📦 Load Sample Data'}
          </button>
        </div>
      </div>

      {/* Registered Tables */}
      <div className="section-title">Registered Tables ({tables.length})</div>
      {tables.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">🗃️</div>
          <div className="empty-title">No tables yet</div>
          <div className="empty-desc">Upload a CSV or load the sample data to get started.</div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Table Name</th><th>Rows</th><th>Source</th></tr></thead>
            <tbody>
              {tables.map(t => (
                <tr key={t.name}>
                  <td className="mono">{t.name}</td>
                  <td>{t.row_count?.toLocaleString() ?? '—'}</td>
                  <td><Badge v={t.source}/></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Schema Explorer ───────────────────────────────────────────
function SchemaExplorer() {
  const [tables, setTables] = useState<any[]>([]);
  const [selected, setSelected] = useState<string|null>(null);
  const [schema, setSchema] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [tab, setTab] = useState<'schema'|'preview'>('schema');

  useEffect(() => { api.getTables().then(d => setTables(d.tables || [])); }, []);

  const selectTable = async (name: string) => {
    setSelected(name); setLoadingSchema(true); setPreview(null);
    try {
      const s = await api.getSchema(name);
      setSchema(s);
      const p = await api.previewTable(name, 20);
      setPreview(p);
    } finally { setLoadingSchema(false); }
  };

  return (
    <div className="fade-in" style={{display:'grid',gridTemplateColumns:'220px 1fr',gap:16,height:'calc(100vh - 100px)'}}>
      <div style={{background:'var(--bg-surface)',border:'1px solid var(--border)',borderRadius:'var(--radius)',padding:16,overflowY:'auto'}}>
        <div className="section-title">Tables</div>
        {tables.map(t => (
          <div key={t.name} className={`nav-item ${selected===t.name?'active':''}`} onClick={() => selectTable(t.name)}>
            <Database size={14} className="nav-icon"/>
            <span className="truncate">{t.name}</span>
          </div>
        ))}
        {tables.length === 0 && <div className="text-muted text-sm">No tables yet</div>}
      </div>

      <div style={{overflowY:'auto'}}>
        {!selected ? (
          <div className="empty-state"><div className="empty-icon">🔍</div><div className="empty-title">Select a table</div><div className="empty-desc">Click a table name on the left to explore its schema and data.</div></div>
        ) : loadingSchema ? <Spinner /> : (
          <div className="fade-in">
            <div className="flex justify-between items-center mb-4">
              <h2 style={{fontWeight:700,fontSize:18}}>{selected}</h2>
              <div style={{fontSize:12,color:'var(--text-muted)'}}>{schema?.columns?.length} columns</div>
            </div>
            <div className="tabs">
              <div className={`tab ${tab==='schema'?'active':''}`} onClick={()=>setTab('schema')}>Schema</div>
              <div className={`tab ${tab==='preview'?'active':''}`} onClick={()=>setTab('preview')}>Data Preview</div>
            </div>
            {tab==='schema' && schema && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Column</th><th>Type</th><th>Nullable</th></tr></thead>
                  <tbody>
                    {schema.columns.map((c:any) => (
                      <tr key={c.name}>
                        <td className="mono" style={{color:'var(--accent-light)'}}>{c.name}{schema.primary_keys?.includes(c.name) ? ' 🔑' : ''}</td>
                        <td className="mono text-secondary">{c.type}</td>
                        <td>{c.nullable ? '✓' : '✗'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab==='preview' && preview && (
              <div className="table-wrap" style={{maxHeight:500}}>
                <table className="data-table">
                  <thead><tr>{preview.columns?.map((c:string) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {preview.rows?.slice(0,20).map((row:any,i:number) => (
                      <tr key={i}>{preview.columns.map((c:string) => <td key={c} className="truncate" style={{maxWidth:180}}>{String(row[c]??'')}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── AI Query Assistant ────────────────────────────────────────
type Msg = { role:'user'|'assistant'; content: string; sql?:string; result?:any; time?:number; };

function QueryAssistant() {
  const [messages, setMessages] = useState<Msg[]>([
    { role:'assistant', content:"👋 I'm your AI Query Assistant. Ask me anything about your data in plain English, and I'll generate and execute SQL for you." }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sqlMode, setSqlMode] = useState('');
  const [sqlResult, setSqlResult] = useState<any>(null);
  const [tab, setTab] = useState<'chat'|'sql'>('chat');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({behavior:'smooth'}); }, [messages]);

  const suggestedQuestions = [
    'Show top 10 customers by spending',
    'Which products have the highest revenue?',
    'Find orders placed in the last 30 days',
    'Count orders by status',
  ];

  const askQuestion = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    const userMsg: Msg = { role:'user', content: q };
    setMessages(prev => [...prev, userMsg]);
    setInput('');

    try {
      const history = messages.filter(m=>m.sql).map(m=>({ question: m.content, sql: m.sql }));
      const genRes = await api.generateSQL(q, undefined, history);

      if (!genRes.sql) {
        setMessages(prev => [...prev, { role:'assistant', content: genRes.explanation || 'Could not generate SQL. Please configure LLM_API_KEY.' }]);
        return;
      }

      const execRes = await api.executeSQL(genRes.sql, q);
      const msg: Msg = {
        role: 'assistant',
        content: genRes.explanation || 'Query executed successfully.',
        sql: genRes.sql,
        result: execRes,
        time: execRes.execution_time_ms,
      };
      setMessages(prev => [...prev, msg]);
    } catch(e:any) {
      setMessages(prev => [...prev, { role:'assistant', content:`❌ Error: ${e.message}` }]);
    } finally { setLoading(false); }
  };

  const runDirectSQL = async () => {
    if (!sqlMode.trim()) return;
    setLoading(true);
    try {
      const r = await api.executeSQL(sqlMode);
      setSqlResult(r);
    } catch(e:any) { setSqlResult({ error: e.message }); }
    finally { setLoading(false); }
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">AI Query Assistant</h1>
        <p className="page-subtitle">Ask questions in plain English — get SQL, results, and explanations</p>
      </div>
      <div className="tabs">
        <div className={`tab ${tab==='chat'?'active':''}`} onClick={()=>setTab('chat')}>💬 Natural Language</div>
        <div className={`tab ${tab==='sql'?'active':''}`} onClick={()=>setTab('sql')}>📝 Direct SQL</div>
      </div>

      {tab==='chat' && (
        <div className="card" style={{padding:0}}>
          <div className="chat-container">
            <div className="chat-messages">
              {messages.map((m,i) => (
                <div key={i} className={`message ${m.role}`}>
                  <div className="message-bubble">
                    <p>{m.content}</p>
                    {m.sql && (
                      <div style={{marginTop:10}}>
                        <div className="sql-block">{m.sql}</div>
                      </div>
                    )}
                    {m.result?.rows && m.result.rows.length > 0 && (
                      <div style={{marginTop:10,maxHeight:250,overflowY:'auto'}}>
                        <table className="data-table" style={{fontSize:12}}>
                          <thead><tr>{m.result.columns.map((c:string)=><th key={c}>{c}</th>)}</tr></thead>
                          <tbody>{m.result.rows.slice(0,20).map((r:any,ri:number)=>(
                            <tr key={ri}>{m.result.columns.map((c:string)=><td key={c}>{String(r[c]??'')}</td>)}</tr>
                          ))}</tbody>
                        </table>
                        <div className="text-sm text-muted mt-4">{m.result.row_count} rows · {m.time?.toFixed(1)}ms</div>
                      </div>
                    )}
                  </div>
                  <div className="message-time">{m.role==='user'?'You':'AgenticDB'}</div>
                </div>
              ))}
              {loading && <div className="message assistant"><div className="message-bubble"><div className="spinner"/></div></div>}
              <div ref={endRef}/>
            </div>

            {messages.length === 1 && (
              <div style={{padding:'0 16px 12px',display:'flex',flexWrap:'wrap',gap:8}}>
                {suggestedQuestions.map(q => (
                  <button key={q} className="btn btn-secondary btn-sm" onClick={()=>askQuestion(q)}>{q}</button>
                ))}
              </div>
            )}

            <div className="chat-input-row">
              <input
                className="input flex-1"
                placeholder="Ask about your data… e.g. Show top 10 customers by spending"
                value={input}
                onChange={e=>setInput(e.target.value)}
                onKeyDown={e=>e.key==='Enter'&&!loading&&askQuestion(input)}
                disabled={loading}
              />
              <button className="btn btn-primary" onClick={()=>askQuestion(input)} disabled={loading||!input.trim()}>
                <Play size={14}/> Ask
              </button>
            </div>
          </div>
        </div>
      )}

      {tab==='sql' && (
        <div className="card">
          <div className="section-title">Direct SQL Query</div>
          <div className="alert alert-info mb-4"><Eye size={14}/> Only SELECT queries are permitted. Queries are row-limited and time-limited.</div>
          <div className="form-group">
            <label className="form-label">SQL Query</label>
            <textarea className="textarea" style={{minHeight:140}} value={sqlMode} onChange={e=>setSqlMode(e.target.value)} placeholder="SELECT * FROM customers LIMIT 10"/>
          </div>
          <button className="btn btn-primary" onClick={runDirectSQL} disabled={loading||!sqlMode.trim()}>
            <Play size={14}/> {loading ? 'Running…' : 'Execute'}
          </button>
          {sqlResult && (
            <div style={{marginTop:20}}>
              {sqlResult.error ? (
                <div className="alert alert-danger">{sqlResult.error}</div>
              ) : (
                <>
                  <div className="flex gap-3 mb-4 text-sm text-muted">
                    <span>✅ {sqlResult.row_count} rows</span>
                    <span>⏱ {sqlResult.execution_time_ms?.toFixed(1)}ms</span>
                  </div>
                  <div className="table-wrap" style={{maxHeight:400}}>
                    <table className="data-table">
                      <thead><tr>{sqlResult.columns?.map((c:string)=><th key={c}>{c}</th>)}</tr></thead>
                      <tbody>{sqlResult.rows?.slice(0,100).map((r:any,i:number)=>(
                        <tr key={i}>{sqlResult.columns.map((c:string)=><td key={c}>{String(r[c]??'')}</td>)}</tr>
                      ))}</tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Performance ───────────────────────────────────────────────
function Performance() {
  const [perf, setPerf] = useState<any>(null);
  const [slow, setSlow] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.perfSummary(), api.slowQueries(), api.queryHistory()])
      .then(([p,s,h]) => { setPerf(p); setSlow(s.slow_queries||[]); setHistory(h.history||[]); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  // Chart data
  const chartData = history.slice(-20).map((h:any,i:number) => ({
    name: `Q${i+1}`, ms: h.execution_time_ms||0
  }));

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Query Performance</h1>
        <p className="page-subtitle">Execution statistics, slow queries, and execution plan analysis</p>
      </div>

      <div className="metric-grid">
        {[
          { label:'Total Queries', v: perf?.total_queries ?? 0, icon:'⚡' },
          { label:'Slow Queries', v: perf?.slow_queries ?? 0, icon:'🐢' },
          { label:'Avg Latency', v: perf?.avg_execution_time_ms ? `${perf.avg_execution_time_ms}ms` : 'N/A', icon:'⏱' },
          { label:'p95 Latency', v: perf?.p95_execution_time_ms ? `${perf.p95_execution_time_ms}ms` : 'N/A (< 20 samples)', icon:'📈' },
          { label:'Slow Threshold', v: `${perf?.slow_query_threshold_ms}ms`, icon:'⚠️' },
        ].map(m => (
          <div key={m.label} className="metric-card">
            <div className="metric-icon">{m.icon}</div>
            <div className="metric-value" style={{fontSize:20}}>{m.v}</div>
            <div className="metric-label">{m.label}</div>
          </div>
        ))}
      </div>

      {chartData.length > 0 && (
        <div className="card mb-6">
          <div className="section-title">Recent Query Latency</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)"/>
              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11}/>
              <YAxis stroke="var(--text-muted)" fontSize={11} unit="ms"/>
              <Tooltip contentStyle={{background:'var(--bg-elevated)',border:'1px solid var(--border)',borderRadius:8}}/>
              <Line type="monotone" dataKey="ms" stroke="var(--accent-light)" strokeWidth={2} dot={false}/>
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="section-title">Slow Queries ({slow.length})</div>
      {slow.length === 0 ? (
        <div className="empty-state"><div className="empty-icon">✅</div><div className="empty-title">No slow queries detected</div><div className="empty-desc">Queries exceeding {perf?.slow_query_threshold_ms}ms will appear here.</div></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>#</th><th>SQL</th><th>Time (ms)</th><th>When</th></tr></thead>
            <tbody>
              {slow.map((q:any) => (
                <tr key={q.id}>
                  <td>{q.id}</td>
                  <td className="mono truncate" style={{maxWidth:400}}>{q.sql?.slice(0,80)}</td>
                  <td style={{color:'var(--danger)',fontWeight:600}}>{q.execution_time_ms?.toFixed(1)}</td>
                  <td className="text-muted text-sm">{q.created_at?.slice(0,19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Monitoring ────────────────────────────────────────────────
function Monitoring() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [cycleResult, setCycleResult] = useState<any>(null);

  const reload = () => api.monitorStatus().then(setStatus);
  useEffect(() => { reload(); }, []);

  const toggle = async () => {
    setLoading(true);
    if (status?.active) await api.stopMonitor(); else await api.startMonitor();
    await reload(); setLoading(false);
  };

  const runCycle = async () => {
    setLoading(true);
    const r = await api.runCycle();
    setCycleResult(r); await reload(); setLoading(false);
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Autonomous Monitoring</h1>
        <p className="page-subtitle">Background agent that continuously checks database health</p>
      </div>

      <div className="grid-2 mb-6">
        <div className="card">
          <div className="section-title">Monitor Status</div>
          <div className="flex items-center gap-3 mb-4">
            <div style={{width:12,height:12,borderRadius:'50%',background:status?.active?'var(--success)':'var(--text-muted)'}}/>
            <span style={{fontWeight:600,fontSize:16}}>{status?.active ? 'Active' : 'Inactive'}</span>
          </div>
          <div style={{fontSize:13,color:'var(--text-secondary)',marginBottom:16}}>
            <div>Interval: <strong>{status?.interval_seconds}s</strong></div>
            <div>Slow threshold: <strong>{status?.slow_query_threshold_ms}ms</strong></div>
          </div>
          <div className="flex gap-2">
            <button className={`btn ${status?.active?'btn-danger':'btn-success'}`} onClick={toggle} disabled={loading}>
              {status?.active ? '⏹ Stop' : '▶️ Start'} Monitor
            </button>
            <button className="btn btn-secondary" onClick={runCycle} disabled={loading}>
              <RefreshCw size={14}/> Run Cycle
            </button>
          </div>
        </div>

        <div className="card">
          <div className="section-title">What It Monitors</div>
          <ul style={{fontSize:13,color:'var(--text-secondary)',lineHeight:2,paddingLeft:20}}>
            <li>Query execution statistics</li>
            <li>Slow queries (above threshold)</li>
            <li>Table row counts</li>
            <li>pg_stat_statements (when PostgreSQL)</li>
            <li>Automatic incident creation</li>
          </ul>
        </div>
      </div>

      {cycleResult && (
        <div className={`alert alert-${cycleResult.incidents_created>0?'warning':'success'} mb-4`}>
          Cycle completed at {cycleResult.timestamp?.slice(0,19)} — {cycleResult.incidents_created} incident(s) created. Errors: {cycleResult.errors?.join(', ')||'none'}
        </div>
      )}

      <div className="alert alert-info">
        <Server size={14}/>
        <div>
          <strong>Note:</strong> In SQLite dev mode, the monitoring agent collects table row counts.
          Connect to PostgreSQL to enable full query statistics via <code>pg_stat_statements</code>.
        </div>
      </div>
    </div>
  );
}

// ── Incidents ─────────────────────────────────────────────────
function Incidents() {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnosis, setDiagnosis] = useState<any>(null);

  useEffect(() => { api.getIncidents().then(d => setIncidents(d.incidents||[])); }, []);

  const diagnose = async (id: number) => {
    setDiagnosing(true); setDiagnosis(null);
    const r = await api.diagnoseIncident(id, selected?.evidence?.query, selected?.evidence);
    setDiagnosis(r); setDiagnosing(false);
  };

  return (
    <div className="fade-in" style={{display:'grid',gridTemplateColumns: selected?'1fr 1.5fr':'1fr',gap:16}}>
      <div>
        <div className="page-header">
          <h1 className="page-title">Incidents</h1>
          <p className="page-subtitle">Performance issues detected by the monitoring agent</p>
        </div>
        {incidents.length === 0 ? (
          <div className="empty-state"><div className="empty-icon">✅</div><div className="empty-title">No incidents</div><div className="empty-desc">Run the monitoring agent to detect performance issues.</div></div>
        ) : (
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            {incidents.map((i:any) => (
              <div key={i.id} className={`card ${selected?.id===i.id?'':'hover:border-accent'}`} style={{cursor:'pointer',borderColor:selected?.id===i.id?'var(--accent)':'var(--border)'}} onClick={()=>{setSelected(i);setDiagnosis(null);}}>
                <div className="flex justify-between items-center">
                  <div style={{fontWeight:600,fontSize:13}}>{i.title}</div>
                  <Badge v={i.severity}/>
                </div>
                <div className="flex gap-2 mt-2">
                  <Badge v={i.status}/>
                  <span className="text-sm text-muted">{i.detected_at?.slice(0,19)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <div className="fade-in">
          <div className="card mb-4">
            <div className="flex justify-between mb-4">
              <div style={{fontWeight:700,fontSize:16}}>{selected.title}</div>
              <button className="btn btn-secondary btn-sm" onClick={()=>setSelected(null)}>✕</button>
            </div>
            <div className="flex gap-2 mb-4"><Badge v={selected.severity}/><Badge v={selected.status}/></div>
            <button className="btn btn-primary" onClick={()=>diagnose(selected.id)} disabled={diagnosing}>
              <Brain size={14}/> {diagnosing ? 'Diagnosing…' : 'Run AI Diagnosis'}
            </button>
          </div>

          {diagnosis && (
            <div className="card fade-in">
              <div className="section-title">🧠 Diagnosis Report</div>
              {diagnosis.workflow && (
                <div style={{marginBottom:16}}>
                  <div className="text-sm text-muted mb-2">Root Cause</div>
                  <div style={{fontWeight:500}}>{diagnosis.workflow.root_cause || '—'}</div>
                  <div className="text-sm text-muted mt-2">Confidence: <strong>{diagnosis.workflow.confidence}</strong></div>
                </div>
              )}
              {diagnosis.llm_diagnosis && (
                <div style={{background:'var(--bg-elevated)',borderRadius:'var(--radius-sm)',padding:14,fontSize:13,lineHeight:1.8}}>
                  {diagnosis.llm_diagnosis}
                </div>
              )}
              {diagnosis.workflow?.optimization_candidates?.length > 0 && (
                <div style={{marginTop:16}}>
                  <div className="text-sm text-muted mb-2">Optimization Candidates</div>
                  {diagnosis.workflow.optimization_candidates.map((c:any,i:number) => (
                    <div key={i} style={{background:'var(--bg-elevated)',borderRadius:'var(--radius-sm)',padding:12,marginBottom:8,fontSize:13}}>
                      <div style={{fontWeight:600}}>{c.title}</div>
                      <div className="text-secondary mt-1">{c.expected_benefit}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Optimizations ─────────────────────────────────────────────
function ExecStatusBadge({ s }: { s: string }) {
  const map: Record<string, string> = {
    not_executed: 'neutral', executing: 'warning', success: 'success',
    already_exists: 'info', failed: 'danger', skipped: 'neutral',
  };
  const labels: Record<string, string> = {
    not_executed: 'Not Executed', executing: 'Executing…', success: 'Executed ✓',
    already_exists: 'Already Satisfied', failed: 'Failed', skipped: 'Skipped',
  };
  const cls = map[s] || 'neutral';
  return <span className={`badge badge-${cls}`}>{labels[s] || s}</span>;
}

function getWorkflowState(opt: any): { label: string; cls: string; desc: string } {
  if (opt.status === 'rejected') {
    return { label: 'Rejected', cls: 'danger', desc: 'This recommendation was reviewed and rejected.' };
  }
  if (opt.execution_status === 'failed') {
    return { label: 'Failed', cls: 'danger', desc: opt.execution_error || 'Execution encountered an error.' };
  }
  if (opt.execution_status === 'executing') {
    return { label: 'Executing', cls: 'warning', desc: 'Database operation is currently executing.' };
  }
  if (opt.execution_status === 'already_exists') {
    return { label: 'Already satisfied because the index exists', cls: 'info', desc: 'The equivalent index already exists in the database. No redundant index was created.' };
  }
  if (opt.execution_status === 'skipped') {
    return { label: 'Skipped', cls: 'neutral', desc: 'Operation was skipped.' };
  }
  if (opt.execution_status === 'success') {
    return { label: 'Executed successfully', cls: 'success', desc: 'Index operation completed and verified in the database.' };
  }
  if (opt.status === 'approved' && (opt.execution_status === 'not_executed' || !opt.execution_status)) {
    return { label: 'Approved but not executed', cls: 'warning', desc: 'Authorization granted. Operation has not yet been executed on the database.' };
  }
  if (opt.status === 'pending') {
    return { label: 'Pending approval', cls: 'warning', desc: 'Requires explicit Class C approval before execution can proceed.' };
  }
  return { label: 'Proposed', cls: 'neutral', desc: 'Candidate recommendation generated.' };
}

function Optimizations() {
  const [opts, setOpts] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [msg, setMsg] = useState<{type:string;text:string}|null>(null);

  const load = () => api.getOptimizations().then(d => setOpts(d.optimizations || []));
  useEffect(() => { load(); }, []);

  const openDetail = async (o: any) => {
    setMsg(null);
    setDetailLoading(true);
    try {
      const full = await api.getOptimization(o.id);
      setSelected(full);
    } catch { setSelected(o); }
    finally { setDetailLoading(false); }
  };

  const requestApproval = async (id: number) => {
    try {
      const r = await api.requestApproval(id);
      setMsg({ type: 'success', text: r.status === 'already_pending'
        ? `ℹ️ ${r.message}`
        : `✅ Approval #${r.approval_id} created — go to Approvals to authorize.`
      });
      load();
    } catch (e: any) { setMsg({ type: 'danger', text: e.message }); }
  };

  const verifyIndex = async (id: number) => {
    setVerifying(true); setMsg(null);
    try {
      const r = await api.verifyIndex(id);
      setMsg({ type: r.index_exists ? 'success' : 'warning',
        text: `Index check: ${r.detail}` });
      // Refresh detail
      const full = await api.getOptimization(id);
      setSelected(full);
    } catch (e: any) { setMsg({ type: 'danger', text: e.message }); }
    finally { setVerifying(false); }
  };

  const executeOpt = async (optId: number, approvalId: number) => {
    setExecuting(true); setMsg(null);
    try {
      const r = await api.executeOptimization(optId, approvalId);
      setMsg({ type: r.status === 'success' || r.status === 'already_exists' ? 'success' : 'info',
        text: r.detail || r.error || 'Execution complete.' });
    } catch (e: any) { 
      setMsg({ type: 'danger', text: e.message }); 
    } finally {
      load();
      try {
        const full = await api.getOptimization(optId);
        setSelected(full);
      } catch {}
      setExecuting(false);
    }
  };


  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Optimizations</h1>
        <p className="page-subtitle">AI-generated query optimization candidates with safety controls</p>
      </div>
      {msg && <div className={`alert alert-${msg.type} mb-4`}>{msg.text}</div>}
      {opts.length === 0 ? (
        <div className="empty-state"><div className="empty-icon">🚀</div><div className="empty-title">No optimizations yet</div><div className="empty-desc">Run a diagnosis on an incident to generate optimization candidates.</div></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>#</th><th>Title</th><th>Type</th><th>Status</th><th>Exec Status</th><th>Improvement</th><th>Actions</th></tr></thead>
            <tbody>
              {opts.map((o: any) => (
                <tr key={o.id}>
                  <td>{o.id}</td>
                  <td style={{fontWeight:500}}>{o.title}</td>
                  <td><Badge v={o.type} type="info"/></td>
                  <td><Badge v={o.status}/></td>
                  <td><ExecStatusBadge s={o.execution_status || 'not_executed'}/></td>
                  <td>{o.improvement_pct != null && o.benchmark_verified
                    ? `${o.improvement_pct>0?'+':''}${o.improvement_pct}%`
                    : <span className="text-muted">Not measured</span>}
                  </td>
                  <td>
                    <div className="flex gap-2">
                      <button className="btn btn-secondary btn-sm" onClick={() => openDetail(o)}>View</button>
                      {o.status === 'pending' && <button className="btn btn-primary btn-sm" onClick={() => requestApproval(o.id)}>Request Approval</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail Panel */}
      {detailLoading && <div className="card mt-6 fade-in"><Spinner /></div>}
      {!detailLoading && selected && (
        <div className="card mt-6 fade-in">
          <div className="flex justify-between mb-4">
            <div style={{fontWeight:700,fontSize:16}}>Optimization #{selected.id}: {selected.title}</div>
            <button className="btn btn-secondary btn-sm" onClick={() => setSelected(null)}>✕</button>
          </div>

          {/* Status row */}
          <div className="flex gap-2 mb-3 flex-wrap">
            <Badge v={selected.status}/>
            <ExecStatusBadge s={selected.execution_status || 'not_executed'}/>
            {selected.optimization_type && <Badge v={selected.optimization_type} type="info"/>}
          </div>

          {/* Explicit Workflow State Banner */}
          {(() => {
            const ws = getWorkflowState(selected);
            return (
              <div className={`alert alert-${ws.cls === 'neutral' ? 'info' : ws.cls} mb-4`} style={{display:'flex',flexDirection:'column',gap:3}}>
                <div style={{fontWeight:700,fontSize:13}}>Workflow State: {ws.label}</div>
                <div style={{fontSize:12,opacity:0.95}}>{ws.desc}</div>
              </div>
            );
          })()}

          {/* Index metadata */}
          {selected.optimization_type === 'index' && (
            <div className="alert alert-info mb-4" style={{fontSize:13}}>
              <strong>Index Operation</strong>
              {selected.target_table && <span> · Table: <code>{selected.target_table}</code></span>}
              {selected.target_columns && <span> · Columns: <code>{selected.target_columns}</code></span>}
              {selected.index_name && <span> · Index Name: <code>{selected.index_name}</code></span>}
              {selected.index_verified_exists === true && <span> · <span style={{color:'var(--success)',fontWeight:600}}>✓ Index exists in DB</span></span>}
              {selected.index_verified_exists === false && <span> · <span style={{color:'var(--warning)',fontWeight:600}}>⚠ Index not found in DB</span></span>}
            </div>
          )}

          {/* SQL fields */}
          <div className="grid-2 mb-4">
            <div>
              <div className="form-label">Original SQL</div>
              {selected.original_sql
                ? <div className="sql-block">{selected.original_sql}</div>
                : <div className="sql-block" style={{color:'var(--text-muted)',fontStyle:'italic'}}>
                    {selected.original_sql_label || 'Not applicable — this recommendation is an index operation'}
                  </div>
              }
            </div>
            <div>
              <div className="form-label">Proposed SQL / Action</div>
              <div className="sql-block">
                {selected.proposed_sql || selected.proposed_action_display || '—'}
              </div>
            </div>
          </div>

          {/* Reasoning */}
          {selected.reasoning && <div className="mt-2 text-sm text-secondary mb-4">{selected.reasoning}</div>}
          {selected.risks && <div className="alert alert-warning mt-2 mb-4"><AlertTriangle size={14}/> {selected.risks}</div>}

          {/* Execution result */}
          {selected.execution_result && (
            <div className={`alert ${selected.execution_status === 'success' || selected.execution_status === 'already_exists' ? 'alert-success' : 'alert-danger'} mb-4`}>
              <strong>Execution Result:</strong> {selected.execution_result}
              {selected.executed_at && <div className="text-sm mt-1">Executed at: {selected.executed_at?.slice(0,19)}</div>}
            </div>
          )}
          {selected.execution_error && (
            <div className="alert alert-danger mb-4">
              <strong>Execution Error:</strong> {selected.execution_error}
            </div>
          )}

          {/* Benchmark */}
          {selected.latest_experiment && (
            <div className="card mb-4" style={{background:'var(--bg-elevated)'}}>
              <div className="section-title" style={{fontSize:13}}>Latest Benchmark</div>
              <div className="flex gap-4 text-sm" style={{flexWrap:'wrap'}}>
                <span>Baseline avg: <strong>{selected.latest_experiment.baseline_avg_ms?.toFixed(2)}ms</strong></span>
                <span>Candidate avg: <strong>{selected.latest_experiment.candidate_avg_ms?.toFixed(2)}ms</strong></span>
                {selected.latest_experiment.improvement_pct != null && selected.latest_experiment.verified && (
                  <span style={{color:selected.latest_experiment.improvement_pct>0?'var(--success)':'var(--danger)',fontWeight:700}}>
                    {selected.latest_experiment.improvement_pct > 0 ? '+' : ''}{selected.latest_experiment.improvement_pct}%
                  </span>
                )}
                {!selected.latest_experiment.verified && (
                  <span className="text-muted">Not verified — {selected.latest_experiment.unverified_reason}</span>
                )}
              </div>
              {selected.latest_experiment.correctness_detail && (
                <div className="text-sm text-muted mt-2">{selected.latest_experiment.correctness_detail}</div>
              )}
            </div>
          )}
          {!selected.latest_experiment && (
            <div className="text-sm text-muted mb-4">Improvement: <strong>Not measured</strong> — run a benchmark experiment to compare performance.</div>
          )}

          {/* Actions */}
          <div className="flex gap-2 flex-wrap">
            {selected.optimization_type === 'index' && (
              <button className="btn btn-secondary btn-sm" onClick={() => verifyIndex(selected.id)} disabled={verifying}>
                {verifying ? 'Checking…' : '🔍 Verify Index in DB'}
              </button>
            )}
            {selected.status === 'pending' && (
              <button className="btn btn-primary btn-sm" onClick={() => requestApproval(selected.id)}>Request Approval</button>
            )}
            {selected.status === 'approved' && selected.execution_status === 'not_executed' && (
              selected.approved_approval_id ? (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => executeOpt(selected.id, selected.approved_approval_id)}
                  disabled={executing}
                >
                  {executing ? 'Executing…' : '⚡ Execute Index Operation'}
                </button>
              ) : (
                <div className="alert alert-info" style={{fontSize:12,padding:'8px 12px'}}>
                  ✅ Approved. Go to <strong>Approvals</strong> page to review and execute.
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Approvals ─────────────────────────────────────────────────
function Approvals() {
  const [approvals, setApprovals] = useState<any[]>([]);
  const [executing, setExecuting] = useState<number | null>(null);
  const [msg, setMsg] = useState<{type:string;text:string}|null>(null);

  const reload = () => api.getApprovals().then(d => setApprovals(d.approvals || []));
  useEffect(() => { reload(); }, []);

  const decide = async (id: number, approve: boolean) => {
    setMsg(null);
    try {
      if (approve) await api.approve(id, 'Manually approved via dashboard');
      else await api.reject(id, 'Rejected via dashboard');
      reload();
    } catch (e: any) { setMsg({ type: 'danger', text: e.message }); }
  };

  const executeOpt = async (approval: any) => {
    setExecuting(approval.id); setMsg(null);
    try {
      const r = await api.executeOptimization(approval.optimization_id, approval.id);
      setMsg({ type: r.status === 'success' || r.status === 'already_exists' ? 'success' : 'info',
        text: r.detail || r.error || `Execution status: ${r.status}` });
    } catch (e: any) { setMsg({ type: 'danger', text: e.message }); }
    finally { 
      reload();
      setExecuting(null); 
    }
  };

  const pending = approvals.filter((a: any) => a.status === 'pending');
  const history = approvals.filter((a: any) => a.status !== 'pending');

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Pending Approvals</h1>
        <p className="page-subtitle">Class C actions requiring explicit authorization before execution</p>
      </div>
      <div className="alert alert-warning mb-6"><Shield size={14}/> Class C actions (creating indexes, changing configuration, etc.) require your explicit approval. The agent cannot bypass this gate. Approving does NOT automatically execute — you must also click Execute.</div>

      {msg && <div className={`alert alert-${msg.type} mb-4`}>{msg.text}</div>}

      {pending.length === 0 ? (
        <div className="empty-state"><div className="empty-icon">✅</div><div className="empty-title">No pending approvals</div><div className="empty-desc">When the agent proposes a Class C action, it will appear here for your review.</div></div>
      ) : (
        <div style={{display:'flex',flexDirection:'column',gap:12}}>
          {pending.map((a: any) => (
            <div key={a.id} className="card">
              <div className="flex justify-between mb-2">
                <div style={{fontWeight:600}}>Approval #{a.id} — Class {a.action_class}</div>
                <Badge v={a.status}/>
              </div>
              {a.optimization_title && (
                <div className="text-sm text-muted mb-2">Optimization: <strong>{a.optimization_title}</strong></div>
              )}
              <div className="sql-block mb-4">{a.proposed_action}</div>
              {a.explanation && <div className="text-sm text-secondary mb-3">{a.explanation}</div>}
              {a.expected_benefit && <div className="text-sm text-muted mb-3">Expected benefit: {a.expected_benefit}</div>}
              {a.risk_assessment && <div className="alert alert-warning mb-3" style={{fontSize:12}}><AlertTriangle size={12}/> {a.risk_assessment}</div>}
              <div className="flex gap-2">
                <button className="btn btn-success" onClick={() => decide(a.id, true)}><CheckCircle size={14}/>Approve</button>
                <button className="btn btn-danger" onClick={() => decide(a.id, false)}><XCircle size={14}/>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="mt-6">
          <div className="section-title">Decision History</div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>#</th><th>Action</th><th>Class</th><th>Opt Type</th><th>Status</th><th>Exec Status</th><th>Execute</th></tr></thead>
              <tbody>{history.map((a: any) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td className="truncate" style={{maxWidth:300}}>{a.proposed_action}</td>
                  <td>{a.action_class}</td>
                  <td>{a.optimization_type || '—'}</td>
                  <td><Badge v={a.status}/></td>
                  <td><ExecStatusBadge s={a.execution_status || 'not_executed'}/></td>
                  <td>
                    {a.status === 'approved' && (a.execution_status === 'not_executed' || !a.execution_status) && (
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => executeOpt(a)}
                        disabled={executing === a.id}
                      >
                        {executing === a.id ? 'Executing…' : '▶ Execute'}
                      </button>
                    )}
                    {a.status === 'approved' && a.execution_status === 'success' && <span className="text-success text-sm">✓ Done</span>}
                    {a.status === 'approved' && a.execution_status === 'already_exists' && <span className="text-muted text-sm">Already satisfied</span>}
                    {a.status === 'rejected' && <span className="text-muted text-sm">—</span>}
                  </td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Experiments ───────────────────────────────────────────────
function Experiments() {
  const [exps, setExps] = useState<any[]>([]);
  const [form, setForm] = useState({ name:'', baseline_sql:'SELECT 1', candidate_sql:'SELECT 1', runs:3 });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);

  const reload = () => api.getExperiments().then(d => setExps(d.experiments||[]));
  useEffect(() => { reload(); }, []);

  const run = async () => {
    setRunning(true); setResult(null);
    try {
      const r = await api.runExperiment(form);
      setResult(r); reload();
    } catch(e:any) { setResult({ error: e.message }); }
    finally { setRunning(false); }
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Benchmark Experiments</h1>
        <p className="page-subtitle">Compare baseline vs optimized query performance with controlled measurements</p>
      </div>

      <div className="grid-2 mb-6">
        <div className="card">
          <div className="section-title">Run New Experiment</div>
          <div className="form-group">
            <label className="form-label">Name</label>
            <input className="input" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="e.g. Index test on orders"/>
          </div>
          <div className="form-group">
            <label className="form-label">Baseline SQL</label>
            <textarea className="textarea" value={form.baseline_sql} onChange={e=>setForm({...form,baseline_sql:e.target.value})}/>
          </div>
          <div className="form-group">
            <label className="form-label">Candidate SQL</label>
            <textarea className="textarea" value={form.candidate_sql} onChange={e=>setForm({...form,candidate_sql:e.target.value})}/>
          </div>
          <div className="form-group">
            <label className="form-label">Runs (repetitions)</label>
            <input className="input" type="number" min={1} max={10} value={form.runs} onChange={e=>setForm({...form,runs:+e.target.value})}/>
          </div>
          <button className="btn btn-primary w-full" onClick={run} disabled={running||!form.name}>
            <FlaskConical size={14}/> {running?'Running…':'Run Experiment'}
          </button>

          {result && (
            <div className={`alert ${result.error?'alert-danger':'alert-success'} mt-4`}>
              {result.error ? result.error : (
                <div>
                  Baseline: {result.baseline_avg_ms?.toFixed(1)}ms → Candidate: {result.candidate_avg_ms?.toFixed(1)}ms
                  {result.improvement_pct != null && <strong> ({result.improvement_pct > 0 ? '+':''}{result.improvement_pct}%)</strong>}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="card">
          <div className="section-title">How It Works</div>
          <ol style={{fontSize:13,color:'var(--text-secondary)',lineHeight:2.2,paddingLeft:20}}>
            <li>Enter baseline and candidate SQL queries</li>
            <li>Both queries run N times each</li>
            <li>Average latency is compared</li>
            <li>Improvement % = (baseline - candidate) / baseline × 100</li>
            <li>Positive = candidate is faster</li>
          </ol>
          <div className="alert alert-warning mt-4"><AlertTriangle size={14}/>Single-run results can be noisy. Use ≥3 runs and similar conditions for reliable comparisons.</div>
        </div>
      </div>

      <div className="section-title">Past Experiments</div>
      {exps.length === 0 ? <div className="empty-state"><div className="empty-icon">🔬</div><div className="empty-title">No experiments yet</div></div> : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>#</th><th>Name</th><th>Baseline</th><th>Candidate</th><th>Improvement</th><th>Status</th><th>When</th></tr></thead>
            <tbody>{exps.map((e:any)=>(
              <tr key={e.id}>
                <td>{e.id}</td><td style={{fontWeight:500}}>{e.name}</td>
                <td>{e.baseline_avg_ms?.toFixed(1)}ms</td>
                <td>{e.candidate_avg_ms?.toFixed(1)}ms</td>
                <td style={{color:e.verified && e.improvement_pct>0?'var(--success)':e.verified && e.improvement_pct<0?'var(--danger)':'inherit',fontWeight:600}}>
                  {e.verified && e.improvement_pct != null
                    ? `${e.improvement_pct>0?'+':''}${e.improvement_pct}%`
                    : <span className="text-muted" title={e.unverified_reason || 'Unverified measurement'}>Unverified</span>
                  }
                </td>
                <td><Badge v={e.status}/></td>
                <td className="text-muted text-sm">{e.run_at?.slice(0,19)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Settings ──────────────────────────────────────────────────
function SettingsPage() {
  const [health, setHealth] = useState<any>(null);
  useEffect(() => { api.health().then(setHealth); }, []);

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Settings & Configuration</h1>
        <p className="page-subtitle">Environment configuration and system information</p>
      </div>

      <div className="card mb-4">
        <div className="section-title">LLM Configuration</div>
        <div className={`alert ${health?.llm_configured?'alert-success':'alert-warning'} mb-4`}>
          {health?.llm_configured ? `✅ LLM configured: ${health.llm_model}` : '⚠️ LLM not configured — AI features disabled'}
        </div>
        <div style={{fontSize:13,color:'var(--text-secondary)',lineHeight:2}}>
          <p>To enable AI features, add these to <code>backend/.env</code>:</p>
          <pre className="sql-block mt-2">{`LLM_PROVIDER=google
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=your_api_key_here`}</pre>
        </div>
      </div>

      <div className="card mb-4">
        <div className="section-title">Database Configuration</div>
        <div style={{fontSize:13,color:'var(--text-secondary)',lineHeight:2}}>
          <p>Current: <strong>SQLite (dev mode)</strong> — no PostgreSQL required.</p>
          <p>For production monitoring with <code>pg_stat_statements</code>, set:</p>
          <pre className="sql-block mt-2">{`DATABASE_URL=postgresql://user:pass@localhost:5432/agenticdb
MONITORED_DATABASE_URL=postgresql://user:pass@localhost:5432/your_db`}</pre>
        </div>
      </div>

      <div className="card">
        <div className="section-title">API Documentation</div>
        <p className="text-secondary text-sm mb-4">The FastAPI backend provides interactive Swagger docs:</p>
        <button className="btn btn-primary" onClick={()=>window.open('http://localhost:8000/docs')}>
          📖 Open API Docs (Swagger UI)
        </button>
      </div>
    </div>
  );
}

// ── App Shell ─────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>('dashboard');

  const pages: Record<Page, ReactNode> = {
    dashboard:     <Dashboard/>,
    datasets:      <Datasets/>,
    schema:        <SchemaExplorer/>,
    query:         <QueryAssistant/>,
    performance:   <Performance/>,
    monitoring:    <Monitoring/>,
    incidents:     <Incidents/>,
    optimizations: <Optimizations/>,
    approvals:     <Approvals/>,
    experiments:   <Experiments/>,
    settings:      <SettingsPage/>,
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">A</div>
          <div>
            <div className="sidebar-logo-text">AgenticDB</div>
            <div className="sidebar-logo-sub">AI Database Administrator</div>
          </div>
        </div>

        <div className="nav-section">
          <div className="nav-label">Navigation</div>
          {NAV.map(n => {
            const Icon = n.icon;
            return (
              <div
                key={n.id}
                className={`nav-item ${page===n.id?'active':''}`}
                onClick={() => setPage(n.id as Page)}
              >
                <Icon size={15} className="nav-icon"/>
                {n.label}
              </div>
            );
          })}
        </div>

        <div className="sidebar-footer">
          <div style={{fontSize:11,color:'var(--text-muted)',textAlign:'center'}}>
            AgenticDB v1.0 · Academic Demo<br/>
            KG Reddy College of Engineering
          </div>
        </div>
      </aside>

      <main className="main-content">
        {pages[page]}
      </main>
    </div>
  );
}
