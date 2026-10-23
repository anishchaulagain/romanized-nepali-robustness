import { Fragment, useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import { useLogout } from '../hooks.js';
import Brand from '../Brand.jsx';
import { AdminSkeleton } from '../Skeleton.jsx';

const fmt = (d) => (d ? new Date(d).toLocaleString() : '—');

function Overview({ data, reload }) {
  const [msg, setMsg] = useState('');
  async function testNotify() {
    try {
      const r = await api.post('/api/admin/notify/test');
      setMsg(`Sent via: ${r.delivered.join(', ') || 'nothing (check server logs)'}`);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }
  const finished = data.writers.filter((w) => w.active && w.completed_at).length;
  const active = data.writers.filter((w) => w.active).length;
  return (
    <>
      <div className="summary">
        <div><b>{data.units}</b><span>items in the study</span></div>
        <div><b>{active} of {data.slots}</b><span>writer slots filled</span></div>
        <div><b>{finished} of {active}</b><span>writers finished</span></div>
      </div>
      <div className="slots">
        {Array.from({ length: data.slots }, (_, i) => i + 1).map((slot) => {
          const w = data.writers.find((x) => x.active && x.slot === slot);
          if (!w) return <div key={slot} className="slot free"><div className="n">Slot {slot}</div><div>Free</div></div>;
          const pct = w.total ? Math.round((100 * w.done) / w.total) : 0;
          return (
            <div key={slot} className="slot">
              <div className="n">Slot {slot}, {w.writer_code}</div>
              <div className="who">{w.display_name || w.username}</div>
              {w.completed_at ? <div className="done-tag">Finished</div>
                : <div><span className="bar"><div style={{ width: `${pct}%` }} /></span>{pct}%</div>}
            </div>
          );
        })}
      </div>
      <div className="card">
        <h3>Writers</h3>
        {data.writers.length === 0 ? <p className="muted">No writers yet. Create them in the Writers tab.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Code</th><th>Slot</th><th>Writer</th><th>Progress</th><th>Last seen</th><th>Finished</th></tr></thead>
            <tbody>
              {data.writers.map((w) => {
                const pct = w.total ? Math.round((100 * w.done) / w.total) : 0;
                return (
                  <tr key={w.id} className={w.active ? '' : 'inactive'}>
                    <td>{w.writer_code}</td>
                    <td>{w.slot ?? '—'}</td>
                    <td>{w.display_name || w.username}{!w.active && ' (disabled)'}</td>
                    <td className="num"><span className={`bar ${pct === 100 ? 'full' : ''}`}><div style={{ width: `${pct}%` }} /></span>{w.done} / {w.total}</td>
                    <td>{fmt(w.last_seen_at)}</td>
                    <td>{fmt(w.completed_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        )}
      </div>
      <div className="card">
        <h3>Notifications</h3>
        <p className="muted">
          Email is {data.channels.email ? 'set up' : 'not set up'}, and the webhook is {data.channels.webhook ? 'set up' : 'not set up'}.
        </p>
        <button onClick={testNotify}>Send test notification</button> {msg && <span className="muted">{msg}</span>}
        <ul className="log">
          {data.notifications.map((n, i) => (
            <li key={i}><span className="muted">{fmt(n.created_at)}</span> {n.message.split('\n')[0]}
              <span className="muted"> ({n.delivered || 'not delivered'})</span></li>
          ))}
        </ul>
      </div>
    </>
  );
}

function Writers({ data, reload }) {
  const [form, setForm] = useState({ username: '', password: '', display_name: '', slot: '' });
  const [msg, setMsg] = useState('');
  const activeBySlot = Object.fromEntries(data.writers.filter((w) => w.active).map((w) => [w.slot, w]));

  async function create(e) {
    e.preventDefault();
    try {
      const w = await api.post('/api/admin/users', { ...form, slot: form.slot ? Number(form.slot) : null });
      setMsg(`Created ${w.username} (${w.writer_code}, slot ${w.slot}). Send them the username and password.`);
      setForm({ username: '', password: '', display_name: '', slot: '' });
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function patch(w, body, done) {
    try {
      await api.patch(`/api/admin/users/${w.id}`, body);
      setMsg(done);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  return (
    <>
      <form className="card form-grid" onSubmit={create}>
        <h3>Create writer</h3>
        <label>Username<input value={form.username} required autoCapitalize="off"
          onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label>Password (min. 8)<input value={form.password} required minLength={8}
          onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        <label>Display name (private)<input value={form.display_name}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
        <label>Slot
          <select value={form.slot} onChange={(e) => setForm({ ...form, slot: e.target.value })}>
            <option value="">{data.free_slot ? `Next free (slot ${data.free_slot})` : 'All slots taken'}</option>
            {Array.from({ length: data.slots }, (_, i) => i + 1).map((s) => (
              <option key={s} value={s}>
                Slot {s}{activeBySlot[s] ? ` (replaces ${activeBySlot[s].username})` : ' (free)'}
              </option>
            ))}
          </select>
        </label>
        <button className="primary">Create writer</button>
        <p className="muted span">
          The study uses {data.slots} slots; each item is written by 3 of them, so each slot gets about half the
          items. To replace a writer who dropped out, disable them and create the new writer in the same slot.
        </p>
      </form>
      {msg && <div className="card notice" role="status">{msg}</div>}
      <div className="card">
        <h3>All writers</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Code</th><th>Slot</th><th>Username</th><th>Name</th><th>Region</th><th></th></tr></thead>
          <tbody>
            {data.writers.map((w) => (
              <tr key={w.id} className={w.active ? '' : 'inactive'}>
                <td>{w.writer_code}</td>
                <td>{w.slot ?? '—'}</td>
                <td>{w.username}</td>
                <td>{w.display_name || '—'}</td>
                <td>{w.profile?.home_region || '—'}</td>
                <td className="row-actions">
                  <button onClick={() => {
                    const p = window.prompt(`New password for ${w.username} (min. 8 characters)`);
                    if (p) patch(w, { password: p }, `Password for ${w.username} changed.`);
                  }}>Reset password</button>
                  <button onClick={() => patch(w, { active: !w.active }, `${w.username} ${w.active ? 'disabled' : 'enabled'}.`)}>
                    {w.active ? 'Disable' : 'Enable'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>
    </>
  );
}

const emptyQuestion = () => ({ question: '', options: { A: '', B: '', C: '', D: '' }, answer: 'A' });

function Questions({ reload }) {
  const [form, setForm] = useState({ source: 'custom', category: '', passage: '', questions: [emptyQuestion()] });
  const [list, setList] = useState({ total: 0, units: [] });
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState('');
  const LIMIT = 20;

  const load = useCallback(() => {
    api.get(`/api/admin/units?q=${encodeURIComponent(q)}&offset=${offset}&limit=${LIMIT}`).then(setList)
      .catch((err) => setMsg(err.message));
  }, [q, offset]);
  useEffect(load, [load]);

  const setQuestion = (i, patch) => setForm({ ...form, questions: form.questions.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  async function create(e) {
    e.preventDefault();
    try {
      const r = await api.post('/api/admin/units', form);
      setMsg(`Added ${r.unit_key}. It was added to the end of every writer's list.`);
      setForm({ ...form, passage: '', questions: [emptyQuestion()] });
      load();
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function remove(u) {
    if (!window.confirm(`Delete ${u.unit_key}? This cannot be undone.`)) return;
    try {
      await api.del(`/api/admin/units/${u.id}`);
      setMsg(`Deleted ${u.unit_key}.`);
      load();
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  return (
    <>
      <form className="card" onSubmit={create}>
        <h3>Add item</h3>
        <p className="muted">Write everything in Devanagari. New items are added to the end of every writer’s list.</p>
        <div className="form-grid">
          <label>Source<input value={form.source} required onChange={(e) => setForm({ ...form, source: e.target.value })} /></label>
          <label>Category<input value={form.category} required onChange={(e) => setForm({ ...form, category: e.target.value })} /></label>
        </div>
        <label>Passage (optional)
          <textarea className="dev-input" rows={3} value={form.passage} onChange={(e) => setForm({ ...form, passage: e.target.value })} />
        </label>
        {form.questions.map((qn, i) => (
          <fieldset key={i}>
            <legend>Question {i + 1}</legend>
            <label>Question<input className="dev-input" value={qn.question} required onChange={(e) => setQuestion(i, { question: e.target.value })} /></label>
            <div className="form-grid">
              {['A', 'B', 'C', 'D'].map((k) => (
                <label key={k}>Option {k}<input className="dev-input" value={qn.options[k]} required
                  onChange={(e) => setQuestion(i, { options: { ...qn.options, [k]: e.target.value } })} /></label>
              ))}
            </div>
            <label className="inline">Correct answer
              <select value={qn.answer} onChange={(e) => setQuestion(i, { answer: e.target.value })}>
                {['A', 'B', 'C', 'D'].map((k) => <option key={k}>{k}</option>)}
              </select>
            </label>
            {form.questions.length > 1 && (
              <button type="button" className="link" onClick={() => setForm({ ...form, questions: form.questions.filter((_, j) => j !== i) })}>
                Remove question
              </button>
            )}
          </fieldset>
        ))}
        <div className="nav left">
          <button type="button" onClick={() => setForm({ ...form, questions: [...form.questions, emptyQuestion()] })}>Add another question</button>
          <button className="primary">Add item</button>
        </div>
      </form>
      {msg && <div className="card notice" role="status">{msg}</div>}
      <div className="card">
        <div className="list-head">
          <h3>Items ({list.total})</h3>
          <input placeholder="Search text, key or category" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Key</th><th>Category</th><th>First line</th><th>Responses</th><th></th></tr></thead>
          <tbody>
            {list.units.map((u) => (
              <Fragment key={u.id}>
                <tr className="clickable" onClick={() => setOpen(open === u.id ? null : u.id)}>
                  <td>{u.unit_key}{u.repeat_of && <span className="tag">repeat</span>}</td>
                  <td>{u.category}</td>
                  <td className="dev">{u.segments[0]?.devanagari.slice(0, 60)}</td>
                  <td>{u.responses}</td>
                  <td>{u.responses === 0 && <button className="danger" onClick={(e) => { e.stopPropagation(); remove(u); }}>Delete</button>}</td>
                </tr>
                {open === u.id && (
                  <tr><td colSpan={5}>
                    {u.segments.map((s, i) => (
                      <div key={i} className="seg-detail">
                        <b>{s.label}{s.answer && ` (answer ${s.answer})`}:</b> <span className="dev">{s.devanagari}</span>
                        {s.r_std && <div className="muted">existing romanization: {s.r_std}</div>}
                      </div>
                    ))}
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table></div>
        <div className="nav left">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Newer</button>
          <button disabled={offset + LIMIT >= list.total} onClick={() => setOffset(offset + LIMIT)}>Older</button>
        </div>
      </div>
    </>
  );
}

function Export({ data }) {
  const [msg, setMsg] = useState('');
  const get = (path) => api.download(path).catch((err) => setMsg(err.message));
  const allDone = data.writers.some((w) => w.active) && data.writers.filter((w) => w.active).every((w) => w.completed_at);
  return (
    <div className="card">
      <h3>Download dataset</h3>
      <p className="muted">
        {allDone ? 'All active writers have finished.' : 'Not all writers have finished yet; downloads contain what has been written so far.'}
        {' '}One row per writer per box, with the Devanagari, the writer’s romanization, the existing romanization and the answer key.
      </p>
      <div className="nav left">
        <button className="primary" onClick={() => get('/api/admin/export/responses?format=csv')}>Responses (CSV)</button>
        <button onClick={() => get('/api/admin/export/responses?format=jsonl')}>Responses (JSONL)</button>
        <button onClick={() => get('/api/admin/export/writers')}>Writer profiles (CSV)</button>
      </div>
      {msg && <div className="error">{msg}</div>}
    </div>
  );
}

const TABS = ['Overview', 'Writers', 'Questions', 'Export'];

export default function Admin() {
  const navigate = useNavigate();
  const logout = useLogout();
  const [tab, setTab] = useState('Overview');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const reload = useCallback(() => {
    api.get('/api/admin/overview').then(setData).catch((err) => {
      if (err.status === 403) navigate('/write', { replace: true });
      else setError(err.message);
    });
  }, [navigate]);
  useEffect(reload, [reload]);

  return (
    <div className="page wide">
      <header className="topbar">
        <Brand sub="Study admin" />
        <nav className="tabs">
          {TABS.map((t) => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
        <div className="actions"><button className="ghost" onClick={logout}>Log out</button></div>
      </header>
      <main>
        {!data ? (error ? <div className="error" role="alert">{error}</div> : <AdminSkeleton />) : (
          <>
            {tab === 'Overview' && <Overview data={data} reload={reload} />}
            {tab === 'Writers' && <Writers data={data} reload={reload} />}
            {tab === 'Questions' && <Questions reload={reload} />}
            {tab === 'Export' && <Export data={data} />}
          </>
        )}
      </main>
    </div>
  );
}
