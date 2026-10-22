import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import { useLogout } from '../hooks.js';

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
          <div className="dev">नेपालको राजधानी कुन हो?</div>
          <div>Person 1: <code>nepal ko rajdhani kun ho?</code></div>
          <div>Person 2: <code>Nepalko rajdhaani kun ho</code></div>
          <div className="muted">Both are correct.</div>
        </div>
        <button className="primary" onClick={onClose}>Start writing</button>
      </div>
    </div>
  );
}

function ProfileForm({ user, onSaved }) {
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
        <h2>About you</h2>
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
        {error && <div className="error">{error}</div>}
        <button className="primary">Continue</button>
      </form>
    </div>
  );
}

function AutoTextarea({ value, onChange, invalid, rows = 1, ...rest }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [value]);
  return (
    <textarea ref={ref} rows={rows} value={value} onChange={onChange} className={invalid ? 'invalid' : ''}
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

  const save = useCallback(async () => {
    if (!unit) return true;
    if (unit.segments.some((s) => DEVANAGARI.test(values[s.id] || ''))) {
      setError('Please use English letters only. Remove the Devanagari text marked in red.');
      return false;
    }
    if (!dirty && activeMs.current === 0) return true;
    setStatus('Saving…');
    try {
      const res = await api.put(`/api/units/${unit.ord}`, {
        responses: unit.segments.map((s) => ({ segment_id: s.id, romanized: values[s.id] || '', note: notes[s.id] || '' })),
        active_ms: Math.min(activeMs.current, 3_600_000),
        paste_blocked: pasteBlocked.current,
      });
      activeMs.current = 0;
      pasteBlocked.current = 0;
      setMe((m) => ({ ...m, progress: res.progress, next_ord: res.next_ord }));
      setDirty(false);
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
    const res = await save();
    if (res === false) return;
    const nextOrd = res === true ? me.next_ord : res.next_ord;
    const hasNext = unit.ord < unit.total_units;
    if (nextOrd == null && !(reviewing && hasNext)) setOrd(null); // everything written: show the done screen
    else setOrd(hasNext ? unit.ord + 1 : nextOrd);
  }

  function blockPaste(e) {
    e.preventDefault();
    pasteBlocked.current += 1;
    setError('Pasting is turned off. Please type the text yourself.');
  }

  if (!me) return <div className="center muted">{error || 'Loading…'}</div>;
  if (!me.user.consent) return <ProfileForm user={me.user} onSaved={(user) => { setMe({ ...me, user }); setShowHelp(true); }} />;

  const { done, total } = me.progress;
  const pct = total ? Math.round((100 * done) / total) : 0;

  return (
    <div className="page">
      {showHelp && <Instructions onClose={() => { localStorage.setItem(`rn-help-${me.user.username}`, '1'); setShowHelp(false); }} />}
      <header className="topbar">
        <div className="brand">Romanized Nepali Writing</div>
        <div className="progress" title={`${done} of ${total} boxes`}>
          <div className="bar"><div style={{ width: `${pct}%` }} /></div>
          <span>{done} / {total}</span>
        </div>
        <div className="actions">
          <button onClick={() => setShowHelp(true)}>Instructions</button>
          <button onClick={async () => { await save(); logout(); }}>Log out</button>
        </div>
      </header>

      {ord == null ? (
        <div className="card done">
          <h2>All done. Thank you!</h2>
          <p>You have written all {total} boxes. Your work has been saved and the research team has been notified.</p>
          <p className="muted">You can still go back and correct anything.</p>
          <button onClick={() => { setReviewing(true); setOrd(1); }}>Review from the start</button>
        </div>
      ) : !unit ? (
        <div className="center muted">{error || 'Loading…'}</div>
      ) : (
        <main className="work">
          <div className="unit-head">
            <h2>Item {unit.ord} <span className="muted">of {unit.total_units}</span></h2>
            <span className="status">{status}</span>
          </div>
          {unit.segments.map((s) => {
            const invalid = DEVANAGARI.test(values[s.id] || '');
            return (
              <section key={s.id} className={`segment ${s.field === 'passage' ? 'passage' : ''}`}>
                <div className="label">{s.label}</div>
                <div className="dev">{s.devanagari}</div>
                <AutoTextarea
                  value={values[s.id] || ''}
                  rows={s.field === 'passage' ? 5 : 1}
                  invalid={invalid}
                  placeholder="Type it here in English letters…"
                  onChange={(e) => { setValues({ ...values, [s.id]: e.target.value }); setDirty(true); }}
                  onBlur={() => save()}
                  onPaste={blockPaste}
                  onDrop={blockPaste}
                />
                {invalid && <div className="error small">English letters only, please.</div>}
                {openNotes[s.id] ? (
                  <input className="note" placeholder="Note (optional), e.g. a word you were unsure about"
                    value={notes[s.id] || ''} onBlur={() => save()}
                    onChange={(e) => { setNotes({ ...notes, [s.id]: e.target.value }); setDirty(true); }} />
                ) : (
                  <button className="link" onClick={() => setOpenNotes({ ...openNotes, [s.id]: true })}>+ add note</button>
                )}
              </section>
            );
          })}
          {error && <div className="error">{error}</div>}
          <div className="nav">
            <button onClick={() => goTo(unit.ord - 1)} disabled={unit.ord <= 1}>← Previous</button>
            <button onClick={() => save()}>Save</button>
            <button className="primary" onClick={saveAndNext}>Save &amp; next →</button>
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
