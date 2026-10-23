import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, setToken } from '../api.js';
import Brand from '../Brand.jsx';

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { token, user } = await api.post('/api/auth/login', { username, password });
      setToken(token);
      navigate(user.role === 'admin' ? '/admin' : '/write', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <div className="login-wrap">
        <section className="login-intro">
          <Brand sub="Romanized Nepali writing study" />
          <h1>Write Nepali the way you type it in chat.</h1>
          <p>You will see Nepali sentences in Devanagari and type each one in English letters, in your own spelling.</p>
          <div className="chat-demo" aria-hidden="true">
            <div className="in">तिमी कहाँ छौ?</div>
            <div className="out">timi kaha xau?<span className="caret" /></div>
          </div>
        </section>
        <form className="card login-card" onSubmit={submit}>
          <h2>Log in</h2>
          <p className="muted">Use the username and password the research team sent you.</p>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
              autoCapitalize="off" autoCorrect="off" spellCheck={false} required autoFocus />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password" required />
          </label>
          {error && <div className="error" role="alert">{error}</div>}
          <button className="primary" disabled={busy}>{busy ? 'Logging in…' : 'Log in'}</button>
        </form>
      </div>
    </div>
  );
}
