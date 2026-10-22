"""End-to-end API test on a throwaway SQLite database.

Run from backend/:  python -m pytest -q tests
"""
import os
import tempfile

DB = os.path.join(tempfile.mkdtemp(), 'test.db')
os.environ.update(DATABASE_URL=f'sqlite:///{DB}', SECRET_KEY='test-secret', ADMIN_USERNAME='Admin',
                  ADMIN_PASSWORD='admin-pass-123', FRONTEND_ORIGINS='http://localhost:5173')
for k in ('SMTP_HOST', 'NOTIFY_EMAIL', 'NOTIFY_WEBHOOK_URL'):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app import notify  # noqa: E402
from app.main import app  # noqa: E402

sent = []
notify.channels = lambda: {'email': False, 'webhook': True}
notify._webhook = lambda text: sent.append(text)


def auth(client, username, password):
    r = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['token']}"}


def fill_all(client, h, text='lekhyo'):
    while True:
        me = client.get('/api/me', headers=h).json()
        if me['next_ord'] is None:
            return me
        unit = client.get(f"/api/units/{me['next_ord']}", headers=h).json()
        r = client.put(f"/api/units/{me['next_ord']}", headers=h, json={
            'responses': [{'segment_id': s['id'], 'romanized': text} for s in unit['segments']], 'active_ms': 1000})
        assert r.status_code == 200, r.text


def test_full_flow():
    with TestClient(app) as c:
        admin = auth(c, 'admin', 'admin-pass-123')  # username is case-insensitive
        ov = c.get('/api/admin/overview', headers=admin).json()
        assert ov['units'] == 275 and ov['segments'] == 1640

        assert c.post('/api/admin/users', headers=admin, json={'username': 'ram', 'password': 'short'}).status_code == 422
        for name in ('ram', 'sita'):
            r = c.post('/api/admin/users', headers=admin, json={'username': name, 'password': 'writer-pass-1'})
            assert r.status_code == 200, r.text
        codes = [w['writer_code'] for w in c.get('/api/admin/overview', headers=admin).json()['writers']]
        assert codes == ['W1', 'W2']

        ram = auth(c, 'ram', 'writer-pass-1')
        assert c.get('/api/admin/overview', headers=ram).status_code == 403
        me = c.get('/api/me', headers=ram).json()
        assert me['progress'] == {'done': 0, 'total': 1640, 'units': 275} and me['next_ord'] == 1

        unit = c.get('/api/units/1', headers=ram).json()
        assert 'r_std' not in unit['segments'][0] and 'answer' not in unit['segments'][0]
        seg = unit['segments'][0]['id']
        # Saving requires consent; Devanagari is rejected.
        assert c.put('/api/units/1', headers=ram, json={'responses': []}).status_code == 400
        c.put('/api/me/profile', headers=ram, json={'profile': {'home_region': 'Kaski'}, 'consent': True})
        bad = c.put('/api/units/1', headers=ram, json={'responses': [{'segment_id': seg, 'romanized': 'नेपाल'}]})
        assert bad.status_code == 422
        other = c.get('/api/units/2', headers=ram).json()['segments'][0]['id']
        assert c.put('/api/units/1', headers=ram, json={'responses': [{'segment_id': other, 'romanized': 'x'}]}).status_code == 400

        # Writers get different orders.
        sita = auth(c, 'sita', 'writer-pass-1')
        assert c.get('/api/units/1', headers=sita).json()['segments'][0]['devanagari'] != unit['segments'][0]['devanagari']

        # Admin adds a unit -> appended for every writer.
        r = c.post('/api/admin/units', headers=admin, json={
            'category': 'test', 'questions': [{'question': 'नेपालको राजधानी कुन हो?', 'answer': 'B',
                                              'options': {'A': 'पोखरा', 'B': 'काठमाडौं', 'C': 'धरान', 'D': 'बुटवल'}}]})
        assert r.status_code == 200, r.text
        new_id = r.json()['id']
        assert c.get('/api/me', headers=ram).json()['progress']['units'] == 276
        assert c.get(f"/api/admin/units?q={r.json()['unit_key']}", headers=admin).json()['total'] == 1
        assert c.get('/api/admin/units?q=राजधानी', headers=admin).json()['total'] >= 1
        assert c.delete(f'/api/admin/units/{new_id}', headers=admin).status_code == 200
        assert c.get('/api/me', headers=ram).json()['progress']['units'] == 275

        # Completing everything notifies once per writer, then once for "all done".
        fill_all(c, ram)
        assert c.get('/api/me', headers=ram).json()['user']['completed_at'] is not None
        assert len(sent) == 1 and 'finished' in sent[0]
        c.put('/api/me/profile', headers=sita, json={'profile': {}, 'consent': True})
        fill_all(c, sita, 'arko')
        assert len(sent) == 3 and 'All writers finished' in sent[2]

        csv_body = c.get('/api/admin/export/responses?format=csv', headers=admin).text
        assert csv_body.count('\n') == 1 + 2 * 1640
        jsonl = c.get('/api/admin/export/responses?format=jsonl', headers=admin).text
        assert len(jsonl.splitlines()) == 2 * 1640 and '"r_std"' in jsonl
        assert 'Kaski' in c.get('/api/admin/export/writers', headers=admin).text

        # Password reset logs the writer out.
        c.patch(f"/api/admin/users/{codes and c.get('/api/admin/overview', headers=admin).json()['writers'][0]['id']}",
                headers=admin, json={'password': 'new-pass-123'})
        assert c.get('/api/me', headers=ram).status_code == 401
        auth(c, 'ram', 'new-pass-123')
