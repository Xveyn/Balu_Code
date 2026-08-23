/**
 * Balu Code Plugin UI — single-file React bundle. No build step.
 *
 * Runs inside BaluHost's plugin sandbox: the iframe is created with
 * sandbox="allow-scripts" and deliberately WITHOUT allow-same-origin, so the
 * document has an opaque origin. There is no `window.React` there, reading
 * `localStorage` throws, and a direct fetch would leave as a cross-origin
 * request with no credentials — which is why the pre-sandbox version of this
 * file died on load with "React is undefined".
 *
 * The contract is `window.BaluHost`: React, hooks, ui, icons, utils plus a
 * *proxied* api/toast/storage/navigate. The host performs the HTTP call and
 * gates it — a plugin's own /api/plugins/balu_code/… routes are always
 * allowed, anything else needs a granted scope. Only the response body comes
 * back through that bridge; headers do not.
 */

const { React, hooks, api: host } = window.BaluHost;
const { useState, useEffect, useCallback } = hooks;
const ce = React.createElement;

const API = '/api/plugins/balu_code';

/**
 * Keeps the call signature the rest of this file already used, so every tab
 * stays unchanged; only the transport moved to the host bridge. Bridge
 * rejections are plain objects ({code, message}), so they are normalised to
 * Error here — call sites read `.message`.
 */
async function api(path, opts = {}) {
  const url = `${API}${path}`;
  const method = (opts.method || 'GET').toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : undefined;
  try {
    if (method === 'GET') return await host.get(url);
    if (method === 'POST') return await host.post(url, body);
    if (method === 'PUT') return await host.put(url, body);
    if (method === 'PATCH') return await host.patch(url, body);
    if (method === 'DELETE') return await host.delete(url);
    throw new Error(`unsupported method ${method}`);
  } catch (err) {
    if (err instanceof Error) throw err;
    throw new Error((err && (err.message || err.code)) || String(err));
  }
}

// ── Shared UI atoms ──────────────────────────────────────────────────────────

function Card({ children, className = '' }) {
  return ce('div', { className: `rounded-xl border border-slate-800 bg-slate-900/50 p-6 ${className}` }, children);
}

function Btn({ children, onClick, disabled, variant = 'primary' }) {
  const base = 'px-4 py-2 text-sm font-medium rounded-lg disabled:opacity-50 transition-colors';
  const styles = {
    primary: 'bg-sky-500/20 text-sky-400 hover:bg-sky-500/30',
    danger:  'bg-red-500/20 text-red-400 hover:bg-red-500/30',
    ghost:   'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
  };
  return ce('button', { onClick, disabled, className: `${base} ${styles[variant]}` }, children);
}

function Badge({ text, ok }) {
  const cls = ok
    ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400'
    : 'text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400';
  return ce('span', { className: cls }, text);
}

function ErrorBox({ msg }) {
  if (!msg) return null;
  return ce('div', { className: 'p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm' }, msg);
}

function Spinner() {
  return ce('div', { className: 'flex items-center justify-center h-32' },
    ce('div', { className: 'animate-spin rounded-full h-8 w-8 border-b-2 border-sky-500' })
  );
}

// ── Models tab ───────────────────────────────────────────────────────────────

function ModelsTab() {
  const [models, setModels] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api('/models'), api('/config')])
      .then(([m, c]) => { setModels(m.models); setConfig(c); })
      .catch(e => setError(e.message));
  }, []);

  if (error) return ce(ErrorBox, { msg: error });
  if (!models) return ce(Spinner);

  return ce('div', { className: 'space-y-4' },
    ce('h2', { className: 'text-lg font-semibold text-white' }, 'Available Models'),
    ce('p', { className: 'text-sm text-slate-400' }, 'Models available on the Ollama server. Chat and embed models are set in Config.'),
    ce('div', { className: 'space-y-2' },
      models.length === 0
        ? ce('p', { className: 'text-slate-500 text-sm' }, 'No models found — is Ollama running?')
        : models.map(m =>
            ce(Card, { key: m.name, className: 'flex items-center justify-between py-3' },
              ce('div', null,
                ce('div', { className: 'text-white font-medium' }, m.name),
                m.size ? ce('div', { className: 'text-xs text-slate-500 mt-0.5' }, `${(m.size / 1e9).toFixed(1)} GB`) : null
              ),
              ce('div', { className: 'flex gap-2' },
                config?.chat_model === m.name  ? ce(Badge, { text: 'chat',  ok: true }) : null,
                config?.embed_model === m.name ? ce(Badge, { text: 'embed', ok: true }) : null
              )
            )
          )
    )
  );
}

// ── Projects tab ─────────────────────────────────────────────────────────────

function ProjectsTab() {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState('');
  const [rootPath, setRootPath] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api('/projects')
      .then(r => setProjects(r.projects))
      .catch(e => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function create() {
    if (!name.trim() || !rootPath.trim()) return;
    setCreating(true);
    try {
      await api('/projects', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), root_path: rootPath.trim(), config_yaml: null }),
      });
      setName(''); setRootPath('');
      load();
    } catch (e) { setError(e.message); }
    finally { setCreating(false); }
  }

  async function del(id) {
    try { await api(`/projects/${id}`, { method: 'DELETE' }); load(); }
    catch (e) { setError(e.message); }
  }

  if (!projects) return ce(Spinner);

  const inputCls = 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 w-full';

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),
    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Add Project'),
      ce('div', { className: 'grid grid-cols-1 md:grid-cols-2 gap-3 mb-3' },
        ce('input', { placeholder: 'Name', value: name, onChange: e => setName(e.target.value), className: inputCls }),
        ce('input', { placeholder: '/absolute/path/to/project', value: rootPath, onChange: e => setRootPath(e.target.value), className: inputCls })
      ),
      ce(Btn, { onClick: create, disabled: creating || !name.trim() || !rootPath.trim() },
        creating ? 'Creating…' : 'Create Project'
      )
    ),
    projects.length === 0
      ? ce('p', { className: 'text-slate-500 text-sm' }, 'No projects yet.')
      : ce('div', { className: 'space-y-3' },
          projects.map(p =>
            ce(Card, { key: p.id, className: 'flex items-center justify-between gap-4 py-4' },
              ce('div', { className: 'min-w-0' },
                ce('div', { className: 'text-white font-medium truncate' }, p.name),
                ce('div', { className: 'text-xs text-slate-500 truncate' }, p.root_path)
              ),
              ce('div', { className: 'flex gap-2 shrink-0' },
                ce(Btn, { onClick: () => del(p.id), variant: 'danger' }, 'Delete')
              )
            )
          )
        )
  );
}

// ── Config tab ────────────────────────────────────────────────────────────────

// Only fields ConfigUpdateRequest accepts may be sent: it is extra="forbid",
// and GET /config returns more than that (opencode_port), so echoing the whole
// object back — which this tab used to do — is answered with 422.
const CONFIG_FIELDS = [
  { key: 'ollama_base_url',           label: 'Ollama Base URL',                 type: 'text' },
  { key: 'chat_model',                label: 'Chat Model',                      type: 'text' },
  { key: 'embed_model',               label: 'Embed Model',                     type: 'text' },
  { key: 'context_window',            label: 'Context Window (tokens)',         type: 'number' },
  { key: 'repo_map_enabled',          label: 'Repo Map',                        type: 'bool' },
  { key: 'repo_map_budget',           label: 'Repo Map Budget (tokens)',        type: 'number' },
  { key: 'rag_budget',                label: 'RAG Budget (tokens)',             type: 'number' },
  { key: 'rag_top_k',                 label: 'RAG Top K',                       type: 'number' },
  { key: 'max_iterations',            label: 'Max Iterations',                  type: 'number' },
  { key: 'max_total_tokens_per_turn', label: 'Max Total Tokens / Turn',         type: 'number' },
  { key: 'temperature',               label: 'Temperature (0–2)',               type: 'number', step: 0.1 },
  { key: 'poll_interval_seconds',     label: 'System poll interval (s, min 3)', type: 'number' },
  { key: 'think',                     label: 'Reasoning trace (think)',         type: 'think' },
];

const THINK_UNSET = 'unset';

function thinkToForm(value) {
  if (value === true) return 'on';
  if (value === false) return 'off';
  return THINK_UNSET;
}

function ConfigTab() {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api('/config').then(setForm).catch(e => setError(e.message));
  }, []);

  function set(key, value) {
    setForm(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true); setError(null);
    const payload = {};
    for (const f of CONFIG_FIELDS) {
      // `think` unset cannot be restored: PUT /config drops null fields, so
      // sending it would be a silent no-op. Skip it instead of pretending.
      if (f.key === 'think') {
        if (form.think === true || form.think === false) payload.think = form.think;
        continue;
      }
      payload[f.key] = form[f.key];
    }
    try {
      const updated = await api('/config', { method: 'PUT', body: JSON.stringify(payload) });
      setForm(updated);
      setSaved(true);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }

  if (!form) return error ? ce(ErrorBox, { msg: error }) : ce(Spinner);

  const inputCls = 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 w-full';

  function field(f) {
    if (f.type === 'bool') {
      return ce('select', {
        value: form[f.key] ? 'on' : 'off',
        onChange: e => set(f.key, e.target.value === 'on'),
        className: inputCls,
      },
        ce('option', { value: 'on' }, 'Enabled'),
        ce('option', { value: 'off' }, 'Disabled')
      );
    }
    if (f.type === 'think') {
      return ce('div', null,
        ce('select', {
          value: thinkToForm(form.think),
          onChange: e => set('think', e.target.value === 'on' ? true : e.target.value === 'off' ? false : null),
          className: inputCls,
        },
          ce('option', { value: THINK_UNSET, disabled: true }, 'Not set — Ollama decides'),
          ce('option', { value: 'off' }, 'Off — no reasoning trace'),
          ce('option', { value: 'on' }, 'On — model emits its reasoning trace')
        ),
        ce('p', { className: 'text-xs text-slate-500 mt-1' },
          thinkToForm(form.think) === THINK_UNSET
            ? 'Unset means Ollama enables thinking for every capable model — for qwen3.8 that is its longest trace. Once changed, unset cannot be restored from here.'
            : 'Ollama enables thinking by default for capable models; qwen3.8 measured 2493 output tokens / 65.8s with the trace against 1096 / 27.7s without.'
        )
      );
    }
    return ce('input', {
      type: f.type,
      step: f.step,
      value: form[f.key] ?? '',
      onChange: e => set(f.key, f.type === 'number' ? Number(e.target.value) : e.target.value),
      className: inputCls,
    });
  }

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),
    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Plugin Configuration'),
      ce('div', { className: 'space-y-4' },
        CONFIG_FIELDS.map(f =>
          ce('div', { key: f.key },
            ce('label', { className: 'block text-sm text-slate-400 mb-1' }, f.label),
            field(f)
          )
        )
      ),
      ce('div', { className: 'flex items-center gap-3 mt-6' },
        ce(Btn, { onClick: save, disabled: saving }, saving ? 'Saving…' : 'Save'),
        saved ? ce('span', { className: 'text-sm text-emerald-400' }, 'Saved!') : null
      ),
      ce('p', { className: 'text-xs text-slate-500 mt-3' },
        'Saving rewrites opencode.json and restarts the embedded runtime. ' +
        'Check the Runtime tab: a changed pid means the new config is live.'
      )
    )
  );
}

// ── Logs tab ──────────────────────────────────────────────────────────────────

function LogsTab() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);
  const [limit, setLimit] = useState(100);

  const load = useCallback(() => {
    api(`/logs?limit=${limit}`)
      .then(r => setEntries(r.entries))
      .catch(e => setError(e.message));
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  if (error) return ce(ErrorBox, { msg: error });
  if (!entries) return ce(Spinner);

  function fmt(ts) {
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
  }

  return ce('div', { className: 'space-y-4' },
    ce('div', { className: 'flex items-center justify-between' },
      ce('h2', { className: 'text-lg font-semibold text-white' }, 'Audit Log'),
      ce('div', { className: 'flex items-center gap-2' },
        ce('label', { className: 'text-sm text-slate-400' }, 'Limit'),
        ce('select', {
          value: limit,
          onChange: e => setLimit(Number(e.target.value)),
          className: 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-2 py-1',
        },
          [25, 50, 100, 200, 500].map(n => ce('option', { key: n, value: n }, n))
        ),
        ce(Btn, { onClick: load, variant: 'ghost' }, 'Refresh')
      )
    ),
    entries.length === 0
      ? ce('p', { className: 'text-slate-500 text-sm' }, 'No tool calls recorded yet.')
      : ce('div', { className: 'overflow-x-auto' },
          ce('table', { className: 'w-full text-sm' },
            ce('thead', null,
              ce('tr', { className: 'text-left text-slate-500 border-b border-slate-800' },
                ['Time', 'User', 'Action', 'Resource', 'Status'].map(h =>
                  ce('th', { key: h, className: 'py-2 pr-4 font-medium' }, h)
                )
              )
            ),
            ce('tbody', null,
              entries.map(e =>
                ce('tr', { key: e.id, className: 'border-b border-slate-800/50 hover:bg-slate-800/30' },
                  ce('td', { className: 'py-2 pr-4 text-slate-400 whitespace-nowrap' }, fmt(e.timestamp)),
                  ce('td', { className: 'py-2 pr-4 text-slate-300' }, e.user ?? '—'),
                  ce('td', { className: 'py-2 pr-4 text-white font-mono text-xs' }, e.action),
                  ce('td', { className: 'py-2 pr-4 text-slate-400 max-w-xs truncate' }, e.resource ?? '—'),
                  ce('td', { className: 'py-2' },
                    ce('span', {
                      className: e.success
                        ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400'
                        : 'text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400',
                    }, e.success ? 'ok' : 'error')
                  )
                )
              )
            )
          )
        )
  );
}

// ── System tab ────────────────────────────────────────────────────────────────

function useInterval(callback, delayMs) {
  const savedCallback = React.useRef(callback);
  React.useEffect(() => { savedCallback.current = callback; }, [callback]);
  React.useEffect(() => {
    if (delayMs == null) return;
    const id = setInterval(() => savedCallback.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}

function VramBar({ usedBytes, totalBytes }) {
  if (!totalBytes) {
    const gb = usedBytes ? (usedBytes / 1e9).toFixed(1) : '—';
    return ce('span', { className: 'text-sm text-slate-400' }, `${gb} GB loaded (total unknown)`);
  }
  const pct = Math.min(100, Math.round((usedBytes / totalBytes) * 100));
  const usedGb = (usedBytes / 1e9).toFixed(1);
  const totalGb = (totalBytes / 1e9).toFixed(1);
  const color = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : 'bg-sky-500';
  return ce('div', { className: 'space-y-1' },
    ce('div', { className: 'flex justify-between text-xs text-slate-400' },
      ce('span', null, `${usedGb} GB / ${totalGb} GB`),
      ce('span', null, `${pct}%`)
    ),
    ce('div', { className: 'w-full bg-slate-700 rounded-full h-2' },
      ce('div', { className: `${color} h-2 rounded-full transition-all`, style: { width: `${pct}%` } })
    )
  );
}

function SystemTab() {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [pollMs, setPollMs] = useState(10_000);

  useEffect(() => {
    api('/config').then(c => {
      setConfig(c);
      const interval = Math.max(3, c.poll_interval_seconds || 10) * 1000;
      setPollMs(interval);
    }).catch(() => {});
  }, []);

  const load = useCallback(() => {
    api('/system')
      .then(d => { setData(d); setLastUpdated(new Date()); setError(null); })
      .catch(e => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);
  useInterval(load, pollMs);

  async function changePollInterval(seconds) {
    const clamped = Math.max(3, seconds);
    setPollMs(clamped * 1000);
    try { await api('/config', { method: 'PUT', body: JSON.stringify({ poll_interval_seconds: clamped }) }); }
    catch (e) { /* non-critical */ }
  }

  const secsAgo = lastUpdated ? Math.round((Date.now() - lastUpdated) / 1000) : null;

  if (error && !data) return ce(ErrorBox, { msg: error });
  if (!data) return ce(Spinner);

  const loaded = data.ollama.loaded_models || [];
  const gpu = data.gpu;

  return ce('div', { className: 'space-y-4' },
    ce(ErrorBox, { msg: error }),

    ce(Card, null,
      ce('div', { className: 'flex items-center justify-between mb-4' },
        ce('h3', { className: 'text-white font-medium' }, 'VRAM'),
        gpu.available
          ? ce(Badge, { text: `GPU ${gpu.utilization_pct}%`, ok: gpu.utilization_pct < 90 })
          : ce('span', { className: 'text-xs text-slate-500' }, 'no GPU tool')
      ),
      ce(VramBar, {
        usedBytes: loaded.reduce((s, m) => s + (m.size_vram || 0), 0),
        totalBytes: gpu.available ? gpu.vram_total_bytes : null,
      }),
      gpu.available
        ? null
        : ce('p', { className: 'text-xs text-slate-500 mt-2' },
            'Install amd-smi, rocm-smi or nvidia-smi on the server to see total VRAM.')
    ),

    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Loaded Models'),
      loaded.length === 0
        ? ce('p', { className: 'text-slate-500 text-sm' }, 'No models loaded.')
        : ce('div', { className: 'space-y-2' },
            loaded.map(m =>
              ce('div', { key: m.name, className: 'flex items-center justify-between' },
                ce('div', null,
                  ce('div', { className: 'text-white text-sm' }, m.name),
                  ce('div', { className: 'text-xs text-slate-500' },
                    (m.size_vram != null ? `${(m.size_vram / 1e9).toFixed(1)} GB VRAM` : 'CPU') +
                    (m.context_length ? ` · ${m.context_length.toLocaleString()} ctx` : '')
                  )
                ),
                ce('div', { className: 'flex gap-1' },
                  config?.chat_model === m.name  ? ce(Badge, { text: 'chat',  ok: true }) : null,
                  config?.embed_model === m.name ? ce(Badge, { text: 'embed', ok: true }) : null
                )
              )
            )
          )
    ),

    ce('div', { className: 'flex items-center gap-3 text-xs text-slate-500' },
      secsAgo !== null ? ce('span', null, `Updated ${secsAgo}s ago`) : null,
      ce('span', null, '·'),
      ce('label', null, 'every'),
      ce('select', {
        value: pollMs / 1000,
        onChange: e => changePollInterval(Number(e.target.value)),
        className: 'bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded px-1 py-0.5',
      },
        [3, 5, 10, 30].map(s => ce('option', { key: s, value: s }, `${s}s`))
      )
    )
  );
}

// ── Runtime tab (opencode subprocess status) ──────────────────────────────────

function RuntimeTab() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(() => {
    api('/runtime/status')
      .then(d => { setStatus(d); setLastUpdated(new Date()); setError(null); })
      .catch(e => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);
  useInterval(load, 5000);

  if (error && !status) return ce(ErrorBox, { msg: error });
  if (!status) return ce(Spinner);

  const secsAgo = lastUpdated ? Math.round((Date.now() - lastUpdated) / 1000) : null;

  function Row({ label, value, badge }) {
    return ce('div', { className: 'flex items-center justify-between py-2 border-b border-slate-800 last:border-b-0' },
      ce('span', { className: 'text-slate-400 text-sm' }, label),
      ce('div', { className: 'flex items-center gap-2' },
        ce('span', { className: 'text-white font-mono text-sm' }, value),
        badge
      )
    );
  }

  return ce('div', { className: 'space-y-4' },
    ce(ErrorBox, { msg: error }),

    ce(Card, null,
      ce('div', { className: 'flex items-center justify-between mb-4' },
        ce('h3', { className: 'text-white font-medium' }, 'opencode runtime'),
        ce(Badge, { text: status.healthy ? 'healthy' : 'down', ok: status.healthy })
      ),
      ce('div', null,
        ce(Row, { label: 'binary version', value: status.binary_version }),
        ce(Row, { label: 'listening port', value: status.port }),
        ce(Row, {
          label: 'owner worker pid',
          value: status.pid > 0 ? status.pid : '— (attached worker)',
          badge: status.pid === 0
            ? ce('span', { className: 'text-xs text-slate-500' }, 'this worker did not spawn')
            : null,
        })
      )
    ),

    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-2' }, 'Notes'),
      ce('ul', { className: 'text-sm text-slate-400 space-y-1 list-disc list-inside' },
        ce('li', null, 'Plugin embeds an opencode binary as a long-lived subprocess (one server, shared across BaluHost workers).'),
        ce('li', null, 'Chat goes through ', ce('code', { className: 'text-slate-300' }, 'POST /chat/v2/{project_id}'), ' (synchronous JSON). SSE streaming is a v0.3.0 candidate.'),
        ce('li', null, 'Saving in Config rewrites opencode.json and restarts this runtime — the pid above changes when it did.'),
      )
    ),

    ce('div', { className: 'flex items-center gap-3 text-xs text-slate-500' },
      secsAgo !== null ? ce('span', null, `Updated ${secsAgo}s ago`) : null,
      ce('span', null, '· auto-refresh every 5s')
    )
  );
}

// ── Stats tab ─────────────────────────────────────────────────────────────────

const _thCls = 'text-left text-slate-500 text-xs font-medium py-2 pr-4';
const _tdCls = 'py-2 pr-4 text-sm';

function StatsTable({ headers, rows }) {
  return ce('div', { className: 'overflow-x-auto' },
    ce('table', { className: 'w-full' },
      ce('thead', null,
        ce('tr', { className: 'border-b border-slate-800' },
          headers.map(h => ce('th', { key: h, className: _thCls }, h))
        )
      ),
      ce('tbody', null,
        rows.map((row, i) =>
          ce('tr', { key: i, className: 'border-b border-slate-800/50' },
            row.map((cell, j) => ce('td', { key: j, className: `${_tdCls} text-slate-300` }, cell))
          )
        )
      )
    )
  );
}

function StatsTab() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);

  const load = useCallback(() => {
    api(`/stats?days=${days}`)
      .then(setStats)
      .catch(e => setError(e.message));
  }, [days]);

  useEffect(() => { load(); }, [load]);

  if (error && !stats) return ce(ErrorBox, { msg: error });

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),

    ce('div', { className: 'flex items-center justify-between' },
      ce('h2', { className: 'text-lg font-semibold text-white' }, 'Usage Stats'),
      ce('div', { className: 'flex items-center gap-2' },
        ce('label', { className: 'text-sm text-slate-400' }, 'Days'),
        ce('select', {
          value: days,
          onChange: e => setDays(Number(e.target.value)),
          className: 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-2 py-1',
        },
          [7, 14, 30, 90].map(n => ce('option', { key: n, value: n }, n))
        ),
        ce(Btn, { onClick: load, variant: 'ghost' }, 'Refresh')
      )
    ),

    !stats ? ce(Spinner) : ce('div', { className: 'space-y-6' },

      ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, `Last ${days} days`),
        ce(StatsTable, {
          headers: ['Date', 'Requests', 'Tokens In', 'Tokens Out'],
          rows: stats.last_n_days.map(d => [
            d.date,
            d.requests,
            d.tokens_in.toLocaleString(),
            d.tokens_out.toLocaleString(),
          ]),
        })
      ),

      stats.by_model.length > 0 && ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'By Model'),
        ce(StatsTable, {
          headers: ['Model', 'Requests', 'Avg Tokens/s'],
          rows: stats.by_model.map(m => [m.model, m.requests, m.avg_tokens_per_s]),
        })
      ),

      stats.top_tools.length > 0 && ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'Top Tools'),
        ce(StatsTable, {
          headers: ['Tool', 'Calls', 'Success Rate'],
          rows: stats.top_tools.map(t => [
            t.tool,
            t.calls,
            `${(t.success_rate * 100).toFixed(0)}%`,
          ]),
        })
      ),

      ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'Tool Approvals'),
        ce('div', { className: 'flex gap-3' },
          ce(Badge, { text: `auto: ${stats.approval_summary.auto_approved}`, ok: true }),
          ce(Badge, { text: `user: ${stats.approval_summary.user_approved}`, ok: true }),
          ce(Badge, { text: `rejected: ${stats.approval_summary.rejected}`, ok: false }),
        )
      )
    )
  );
}

// ── Main shell ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'models',   label: 'Models' },
  { id: 'projects', label: 'Projects' },
  { id: 'config',   label: 'Config' },
  { id: 'runtime',  label: 'Runtime' },
  { id: 'logs',     label: 'Logs' },
  { id: 'system',   label: 'System' },
  { id: 'stats',    label: 'Stats' },
];

function BaluCode({ user }) {
  const [tab, setTab] = useState('models');

  const content = {
    models:   ce(ModelsTab),
    projects: ce(ProjectsTab),
    config:   ce(ConfigTab),
    runtime:  ce(RuntimeTab),
    logs:     ce(LogsTab),
    system:   ce(SystemTab),
    stats:    ce(StatsTab),
  };

  return ce('div', { className: 'space-y-6' },
    ce('div', { className: 'flex gap-1 border-b border-slate-800 pb-0' },
      TABS.map(t =>
        ce('button', {
          key: t.id,
          onClick: () => setTab(t.id),
          className: `px-4 py-2 text-sm font-medium transition-colors ${
            tab === t.id
              ? 'text-sky-400 border-b-2 border-sky-400 -mb-px'
              : 'text-slate-400 hover:text-slate-200'
          }`,
        }, t.label)
      )
    ),
    ce('div', null, content[tab])
  );
}

export default BaluCode;
