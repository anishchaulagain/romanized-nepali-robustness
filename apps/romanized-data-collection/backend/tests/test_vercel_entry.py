"""The Vercel entry restores the original path that vercel.json passes as ?__path=."""
import os
import tempfile

os.environ.setdefault('DATABASE_URL', f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'entry.db')}")
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('ADMIN_USERNAME', 'admin')
os.environ.setdefault('ADMIN_PASSWORD', 'admin-pass-123')

from fastapi.testclient import TestClient  # noqa: E402

from api.index import app  # noqa: E402


def test_rewritten_requests_reach_their_routes():
    with TestClient(app) as c:
        assert c.get('/api/index?__path=/api/health').json() == {'ok': True}
        assert c.get('/api/index?__path=api/health').json() == {'ok': True}   # without leading slash
        assert c.get('/api/health').json() == {'ok': True}                    # no rewrite: unchanged
        assert c.get('/api/index?__path=/docs').status_code == 200
        r = c.get('/api/index?__path=/api/admin/units&q=x&limit=5')           # other query params survive
        assert r.status_code == 401
        assert c.get('/api/index?__path=/nope').json() == {'detail': 'Not Found', 'path': '/nope'}
