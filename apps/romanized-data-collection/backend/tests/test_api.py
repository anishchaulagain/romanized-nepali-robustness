"""End-to-end API test on a throwaway SQLite database.

Run from backend/:  python -m pytest -q tests
"""
import json
import os
import tempfile
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / 'seed' / 'items.json'

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
        assert ov['units'] == 552 and ov['segments'] == 3182 and ov['free_slot'] == 1

        assert c.post('/api/admin/users', headers=admin, json={'username': 'ram', 'password': 'short'}).status_code == 422
        for name in ('ram', 'sita'):
            r = c.post('/api/admin/users', headers=admin, json={'username': name, 'password': 'writer-pass-1'})
            assert r.status_code == 200, r.text
        codes = [w['writer_code'] for w in c.get('/api/admin/overview', headers=admin).json()['writers']]
        assert codes == ['W1', 'W2']

        ram = auth(c, 'ram', 'writer-pass-1')
        assert c.get('/api/admin/overview', headers=ram).status_code == 403
        me = c.get('/api/me', headers=ram).json()
        assert me['user']['slot'] == 1 and me['next_ord'] == 1
        # Slot 1 gets its half of the design: every unit whose writer triple contains 1.
        seed = json.loads(SEED.read_text(encoding='utf-8'))['units']
        mine = [u for u in seed if 1 in u['writers']]
        assert me['progress'] == {'done': 0, 'units': len(mine), 'total': sum(len(u['segments']) for u in mine)}
        ram_total = me['progress']['total']

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
        assert c.get('/api/me', headers=ram).json()['progress']['units'] == len(mine) + 1
        assert c.get(f"/api/admin/units?q={r.json()['unit_key']}", headers=admin).json()['total'] == 1
        assert c.get('/api/admin/units?q=राजधानी', headers=admin).json()['total'] >= 1
        assert c.delete(f'/api/admin/units/{new_id}', headers=admin).status_code == 200
        assert c.get('/api/me', headers=ram).json()['progress']['units'] == len(mine)

        # Completing everything notifies once per writer, then once for "all done".
        fill_all(c, ram)
        assert c.get('/api/me', headers=ram).json()['user']['completed_at'] is not None
        assert len(sent) == 1 and 'finished' in sent[0]
        c.put('/api/me/profile', headers=sita, json={'profile': {}, 'consent': True})
        sita_total = fill_all(c, sita, 'arko')['progress']['total']
        assert len(sent) == 3 and 'All writers finished' in sent[2]

        csv_body = c.get('/api/admin/export/responses?format=csv', headers=admin).text
        assert csv_body.count('\n') == 1 + ram_total + sita_total
        jsonl = c.get('/api/admin/export/responses?format=jsonl', headers=admin).text
        assert len(jsonl.splitlines()) == ram_total + sita_total and '"writer_slot": 2' in jsonl
        assert 'Kaski' in c.get('/api/admin/export/writers', headers=admin).text

        # Slots: 6 in total; a 7th writer needs an explicit slot (a replacement).
        for i in range(3, 7):
            assert c.post('/api/admin/users', headers=admin,
                          json={'username': f'writer{i}', 'password': 'writer-pass-1'}).json()['slot'] == i
        full = c.post('/api/admin/users', headers=admin, json={'username': 'writer7', 'password': 'writer-pass-1'})
        assert full.status_code == 409
        rep = c.post('/api/admin/users', headers=admin, json={'username': 'writer7', 'password': 'writer-pass-1', 'slot': 2})
        assert rep.json()['slot'] == 2
        w7 = auth(c, 'writer7', 'writer-pass-1')
        assert c.get('/api/me', headers=w7).json()['progress']['total'] == sita_total

        # Password reset logs the writer out.
        c.patch(f"/api/admin/users/{codes and c.get('/api/admin/overview', headers=admin).json()['writers'][0]['id']}",
                headers=admin, json={'password': 'new-pass-123'})
        assert c.get('/api/me', headers=ram).status_code == 401
        auth(c, 'ram', 'new-pass-123')


def test_concurrent_first_saves_do_not_fail():
    """Leaving a box and clicking Save and next sends two saves of a new item at once; both must succeed."""
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        admin = auth(c, 'admin', 'admin-pass-123')
        c.post('/api/admin/users', headers=admin, json={'username': 'racer', 'password': 'writer-pass-1', 'slot': 5})
        w = auth(c, 'racer', 'writer-pass-1')
        c.put('/api/me/profile', headers=w, json={'profile': {}, 'consent': True})
        for ord_ in (1, 2, 3):
            unit = c.get(f'/api/units/{ord_}', headers=w).json()
            body = {'responses': [{'segment_id': s['id'], 'romanized': 'ek', 'note': ''} for s in unit['segments']],
                    'active_ms': 10, 'paste_blocked': 0}
            with ThreadPoolExecutor(4) as pool:
                codes = list(pool.map(lambda _: c.put(f'/api/units/{ord_}', headers=w, json=body).status_code, range(4)))
            assert codes == [200] * 4
