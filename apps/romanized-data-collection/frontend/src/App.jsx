import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { api, getToken } from './api.js';
import Login from './pages/Login.jsx';
import Writer from './pages/Writer.jsx';
import Admin from './pages/Admin.jsx';

function Home() {
  const navigate = useNavigate();
  useEffect(() => {
    if (!getToken()) return navigate('/login', { replace: true });
    api.get('/api/me')
      .then((me) => navigate(me.user.role === 'admin' ? '/admin' : '/write', { replace: true }))
      .catch(() => navigate('/login', { replace: true }));
  }, [navigate]);
  return <div className="center muted">Loading…</div>;
}

function RequireLogin({ children }) {
  const [ok] = useState(() => Boolean(getToken()));
  return ok ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/write" element={<RequireLogin><Writer /></RequireLogin>} />
      <Route path="/admin" element={<RequireLogin><Admin /></RequireLogin>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
