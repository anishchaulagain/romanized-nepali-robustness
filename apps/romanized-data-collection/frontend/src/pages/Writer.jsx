import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import { useLogout } from '../hooks.js';
import Brand, { Mark } from '../Brand.jsx';
import { PageError, UnitSkeleton, WriterSkeleton } from '../Skeleton.jsx';

const DEVANAGARI = /[ऀ-ॿ]/;
const IDLE_MS = 60_000; // time without any interaction is not counted as active

const PROFILE_FIELDS = [
  ['home_region', 'Home district / region where you grew up', null],
  ['first_language', 'First language(s)', null],
  ['age_group', 'Age group', ['under 20', '20-29', '30-39', '40+']],
  ['school_medium', 'School medium', ['Nepali', 'English', 'Both']],
  ['romanized_frequency', 'How often do you type Nepali in English letters?', ['Daily', 'Weekly', 'Rarely']],
  ['device', 'Device you usually type on', ['Phone', 'Computer', 'Both']],
  ['mixes_english', 'Do you mix English words when you chat?', ['Often', 'Sometimes', 'Rarely']],
];

function Instructions({ onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="card modal" onClick={(e) => e.stopPropagation()}>
        <h2>How to write</h2>
        <p>Each item shows Nepali text in Devanagari. In the box below each line, type the same text in
          English letters, <b>exactly the way you would type it in Messenger, Viber or WhatsApp</b>.</p>
        <ul>
          <li>There is no correct spelling. Write it your own way.</li>
          <li>Keep the same words in the same order. Do not translate to English and do not rephrase.</li>
          <li>Short forms you normally use are fine (for example छ as “xa” or “cha”).</li>
          <li>Do not use Google Translate, transliteration keyboards or tools, and do not ask anyone else. Pasting is turned off.</li>
          <li>Some items may look familiar. Just write them again normally; do not look back.</li>
          <li>Your work is saved every time you leave a box or press Save. You can stop and continue later.</li>
          <li>If a word is unclear, write your best guess and add a note.</li>
        </ul>
        <div className="example">
          <div className="chat-demo">
            <div className="in">नेपालको राजधानी कुन हो?</div>
            <div className="who">One person</div>
            <div className="out">nepal ko rajdhani kun ho?</div>
            <div className="who">Another person</div>
            <div className="out alt">Nepalko rajdhaani kun ho</div>
          </div>
          <p className="muted" style={{ margin: '.6rem 0 0' }}>Both are right.</p>
        </div>
        <button className="primary" onClick={onClose}>Start writing</button>
      </div>
    </div>
  );
}

function ProfileForm({ user, onSaved, onLogout }) {
  const [profile, setProfile] = useState(user.profile || {});
  const [consent, setConsent] = useState(Boolean(user.consent));
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    if (!consent) return setError('Please tick the consent box to continue.');
    try {
      const res = await api.put('/api/me/profile', { profile, consent });
      onSaved(res.user);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="center">
      <form className="card narrow" onSubmit={submit}>
        <div className="form-head">
          <Brand sub="Romanized Nepali writing study" />
          <button type="button" className="ghost" onClick={onLogout}>Log out</button>
        </div>
        <h2 style={{ marginTop: '1.2rem' }}>About you</h2>
        <p className="muted">This helps us understand different writing styles. Your name is never published.</p>
        {PROFILE_FIELDS.map(([key, label, options]) => (
          <label key={key}>
            {label}
            {options ? (
              <select value={profile[key] || ''} required onChange={(e) => setProfile({ ...profile, [key]: e.target.value })}>
                <option value="" disabled>Choose…</option>
                {options.map((o) => <option key={o}>{o}</option>)}
              </select>
            ) : (
              <input value={profile[key] || ''} required onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />
            )}
          </label>
        ))}
        <label className="check">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          I agree that my anonymous writing may be published in a research dataset.
        </label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary">Save and continue</button>
      </form>
    </div>
  );
}

function SegLabel({ s }) {
  // Seed labels look like "Question", "Option B", "Passage", "Q2 Question", "Q2 Option B".
  const m = /^(?:Q(\d+) )?(Question|Option ([A-D]))$/.exec(s.label);
  if (!m) return s.label;
  const q = m[1] ? `Question ${m[1]}` : 'Question';
  return m[3] ? <><span className="opt">{m[3]}</span>{m[1] ? `${q}, option` : 'Option'}</> : q;
}

function AutoTextarea({ value, onChange, invalid, rows = 1, ...rest }) {
  const filled = Boolean((value || '').trim());
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [value]);
  return (
    <textarea ref={ref} rows={rows} value={value} onChange={onChange} className={`${invalid ? 'invalid' : ''} ${filled ? 'filled' : ''}`}
      autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} data-gramm="false" {...rest} />
  );
}

export default function Writer() {
  const navigate = useNavigate();
  const logout = useLogout();
  const [me, setMe] = useState(null);
  const [ord, setOrd] = useState(null);
  const [unit, setUnit] = useState(null);
  const [values, setValues] = useState({});
  const [notes, setNotes] = useState({});
  const [openNotes, setOpenNotes] = useState({});
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [jump, setJump] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const activeMs = useRef(0);
  const pasteBlocked = useRef(0);
  const lastActivity = useRef(Date.now());
  const edits = useRef(0); // bumped on every edit, so a slow save never hides newer unsaved text

  // Active-time counter: counts only while the tab is visible and the writer interacted recently.
  useEffect(() => {
    const touch = () => { lastActivity.current = Date.now(); };
    const tick = setInterval(() => {
      if (document.visibilityState === 'visible' && Date.now() - lastActivity.current < IDLE_MS) activeMs.current += 1000;
    }, 1000);
    window.addEventListener('keydown', touch);
    window.addEventListener('pointerdown', touch);
    return () => {
      clearInterval(tick);
      window.removeEventListener('keydown', touch);
      window.removeEventListener('pointerdown', touch);
    };
  }, []);

  useEffect(() => {
    const warn = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  useEffect(() => {
    api.get('/api/me').then((data) => {
      if (data.user.role === 'admin') return navigate('/admin', { replace: true });
      setMe(data);
      setOrd(data.next_ord ?? null);
      if (data.user.consent && !localStorage.getItem(`rn-help-${data.user.username}`)) setShowHelp(true);
    }).catch((err) => setError(err.message));
  }, [navigate]);

  useEffect(() => {
    if (!ord) return;
    setUnit(null);
    api.get(`/api/units/${ord}`).then((u) => {
      setUnit(u);
      setValues(Object.fromEntries(u.segments.map((s) => [s.id, s.romanized])));
      setNotes(Object.fromEntries(u.segments.map((s) => [s.id, s.note || ''])));
      setOpenNotes(Object.fromEntries(u.segments.map((s) => [s.id, Boolean(s.note)])));
      setDirty(false);
      setError('');
      window.scrollTo(0, 0);
    }).catch((err) => setError(err.message));
  }, [ord]);

  const saveNow = useCallback(async ({ force = false } = {}) => {
    if (!unit) return true;
    if (unit.segments.some((s) => DEVANAGARI.test(values[s.id] || ''))) {
      setError('Please use English letters only. Remove the Devanagari text marked in red.');
      return false;
    }
    if (!force && !dirty && activeMs.current === 0) return true;
    const version = edits.current;
    const sentMs = Math.min(activeMs.current, 3_600_000);
    const sentPastes = pasteBlocked.current;
    setStatus('Saving…');
    try {
      const res = await api.put(`/api/units/${unit.ord}`, {
        responses: unit.segments.map((s) => ({ segment_id: s.id, romanized: values[s.id] || '', note: notes[s.id] || '' })),
        active_ms: sentMs,
        paste_blocked: sentPastes,
      });
      // Subtract only what this request reported: time and pastes counted meanwhile go with the next save.
      activeMs.current = Math.max(0, activeMs.current - sentMs);
      pasteBlocked.current = Math.max(0, pasteBlocked.current - sentPastes);
      setMe((m) => ({ ...m, progress: res.progress, next_ord: res.next_ord }));
      if (edits.current === version) setDirty(false);
      setError('');
      setStatus('Saved');
      setTimeout(() => setStatus(''), 1500);
      return res;
    } catch (err) {
      setStatus('');
      setError(err.message);
      return false;
    }
  }, [unit, values, notes, dirty]);

  // Saves run one at a time, in the order they were asked for, so a later save always carries the newer text.
  const saveQueue = useRef(Promise.resolve());
  const save = useCallback((opts) => {
    const run = saveQueue.current.then(() => saveNow(opts));
    saveQueue.current = run.catch(() => {});
    return run;
  }, [saveNow]);

  async function goTo(target) {
    const res = await save();
    if (res === false) return;
    const total = unit?.total_units ?? me.progress.units;
    if (target >= 1 && target <= total) setOrd(target);
  }

  async function saveAndNext() {
    const empty = unit.segments.filter((s) => !(values[s.id] || '').trim());
    if (empty.length) {
      setError(`Please fill in all ${empty.length} empty box${empty.length > 1 ? 'es' : ''} before going on.`);
      return;
    }
    // Always save here, so where to go next comes from the server and not from an older save's answer.
    const res = await save({ force: true });
    if (res === false) return;
    const nextOrd = res.next_ord;
    const hasNext = unit.ord < unit.total_units;
    if (nextOrd == null && !(reviewing && hasNext)) setOrd(null); // everything written: show the done screen
    else setOrd(hasNext ? unit.ord + 1 : nextOrd);
  }

  function blockPaste(e) {
    e.preventDefault();
    pasteBlocked.current += 1;
    setError('Pasting is turned off. Please type the text yourself.');
  }

  if (!me) return error ? <PageError message={error} /> : <WriterSkeleton />;
  if (!me.user.consent) {
    return <ProfileForm user={me.user} onLogout={logout}
      onSaved={(user) => { setMe({ ...me, user }); setShowHelp(true); }} />;
  }

  const { done, total } = me.progress;
  const pct = total ? Math.round((100 * done) / total) : 0;

  return (
    <div className="page">
      {showHelp && <Instructions onClose={() => { localStorage.setItem(`rn-help-${me.user.username}`, '1'); setShowHelp(false); }} />}
      <header className="topbar">
        <Brand sub="Romanized Nepali writing study" />
        <span className="count"><b>{done}</b> of {total} boxes written ({pct}%)</span>
        <div className="actions">
          <button className="ghost" onClick={() => setShowHelp(true)}>Instructions</button>
          <button className="ghost" onClick={async () => { await save(); logout(); }}>Log out</button>
        </div>
        <div className="meter" style={{ width: `${pct}%` }} role="progressbar" aria-valuenow={pct}
          aria-valuemin={0} aria-valuemax={100} aria-label="Progress" />
      </header>

      {ord == null ? (
        <div className="card done">
          <Mark />
          <h2>All done. Thank you!</h2>
          <p>You have written all {total} boxes. Your work has been saved and the research team has been notified.</p>
          <p className="muted">You can still go back and correct anything.</p>
          <button onClick={() => { setReviewing(true); setOrd(1); }}>Review from the start</button>
        </div>
      ) : !unit ? (
        error ? <div className="error" role="alert">{error}</div> : <UnitSkeleton />
      ) : (
        <main className="work">
          <div className="unit-head">
            <h2>Item {unit.ord} <span>of {unit.total_units}</span></h2>
            <span className={`status ${status === 'Saving…' ? 'saving' : ''}`} aria-live="polite">{status}</span>
          </div>
          {unit.segments.map((s) => {
            const invalid = DEVANAGARI.test(values[s.id] || '');
            return (
              <section key={s.id} className={`segment ${s.field === 'passage' ? 'passage' : ''}`}>
                <div className="seg-label"><SegLabel s={s} /></div>
                <div className="dev" lang="ne">{s.devanagari}</div>
                <div className="bubble-row">
                <AutoTextarea
                  aria-label={`${s.label} in English letters`}
                  value={values[s.id] || ''}
                  rows={s.field === 'passage' ? 5 : 1}
                  invalid={invalid}
                  placeholder="Type it in English letters…"
                  onChange={(e) => { setValues({ ...values, [s.id]: e.target.value }); edits.current += 1; setDirty(true); }}
                  onBlur={() => save()}
                  onPaste={blockPaste}
                  onDrop={blockPaste}
                />
                </div>
                {invalid && <div className="error small">Use English letters only.</div>}
                {openNotes[s.id] ? (
                  <input className="note" placeholder="Note (optional), e.g. a word you were unsure about"
                    value={notes[s.id] || ''} onBlur={() => save()}
                    onChange={(e) => { setNotes({ ...notes, [s.id]: e.target.value }); edits.current += 1; setDirty(true); }} />
                ) : (
                  <div className="seg-foot">
                    <button className="link" onClick={() => setOpenNotes({ ...openNotes, [s.id]: true })}>Add a note</button>
                  </div>
                )}
              </section>
            );
          })}
          {error && <div className="error" role="alert">{error}</div>}
          <div className="dock">
            <div className="dock-inner">
              <button onClick={() => goTo(unit.ord - 1)} disabled={unit.ord <= 1}>Previous</button>
              <span className="spacer" />
              <button className="save-only" onClick={() => save({ force: true })}>Save</button>
              <button className="primary" onClick={saveAndNext}>Save and next</button>
            </div>
          </div>
          <div className="jump">
            {me.next_ord && me.next_ord !== unit.ord && (
              <button className="link" onClick={() => goTo(me.next_ord)}>Go to first unfinished item ({me.next_ord})</button>
            )}
            <form onSubmit={(e) => { e.preventDefault(); goTo(Number(jump)); setJump(''); }}>
              <input value={jump} onChange={(e) => setJump(e.target.value.replace(/\D/g, ''))} placeholder="Item #" inputMode="numeric" />
              <button>Go</button>
            </form>
          </div>
        </main>
      )}
    </div>
  );
}
