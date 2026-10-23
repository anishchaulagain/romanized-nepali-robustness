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


def create_writer(client, admin, username, password='writer-pass-1'):
    """Admin creates a writer with a generated temporary password; the writer logs in and sets their own."""
    r = client.post('/api/admin/users', headers=admin, json={'username': username})
    assert r.status_code == 200, r.text
    temp = r.json()['temp_password']
    h = auth(client, username, temp)
    assert client.get('/api/me', headers=h).json()['user']['must_change_password'] is True
    assert client.get('/api/units/1', headers=h).status_code == 403  # nothing else until the password is changed
    r = client.post('/api/me/password', headers=h, json={'new_password': password})
    assert r.status_code == 200 and r.json()['user']['must_change_password'] is False, r.text
    return r.json()['user']


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
        assert ov['units'] == 552 and ov['segments'] == 3182 and ov['writers_per_unit'] == 3

        assert c.post('/api/admin/users', headers=admin, json={'username': 'ram', 'password': 'short'}).status_code == 400
        # With fewer writers than 3 per item, every writer gets every item.
        for name in ('ram', 'sita'):
            create_writer(c, admin, name)
            assert c.get('/api/admin/overview', headers=admin).json()['short_units'] == 0
        # Once a writer has set their own password, the admin no longer sees one.
        assert all(w['temp_password'] is None for w in c.get('/api/admin/overview', headers=admin).json()['writers'])
        codes = [w['writer_code'] for w in c.get('/api/admin/overview', headers=admin).json()['writers']]
        assert codes == ['W1', 'W2']

        ram = auth(c, 'ram', 'writer-pass-1')
        assert c.get('/api/admin/overview', headers=ram).status_code == 403
        me = c.get('/api/me', headers=ram).json()
        assert me['progress'] == {'done': 0, 'units': 552, 'total': 3182} and me['next_ord'] == 1

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
        # Ram starts item 1 (one box written).
        assert c.put('/api/units/1', headers=ram, json={'responses': [{'segment_id': seg, 'romanized': 'suru'}]}).status_code == 200
        started_text = unit['segments'][0]['devanagari']

        # Writers get different orders.
        sita = auth(c, 'sita', 'writer-pass-1')
        assert c.get('/api/units/1', headers=sita).json()['segments'][0]['devanagari'] != started_text

        # Four writers: every item goes to exactly 3 of them, and the work is shared evenly.
        for name in ('hari', 'gita'):
            create_writer(c, admin, name)
        ov = c.get('/api/admin/overview', headers=admin).json()
        assert ov['short_units'] == 0
        totals = [w['total'] for w in ov['writers']]
        assert sum(totals) == 3 * 3182
        assert max(totals) - min(totals) <= 3182 * 0.06, totals
        # Ram keeps the item he started, still first in his list.
        assert c.get('/api/units/1', headers=ram).json()['segments'][0]['devanagari'] == started_text

        # Disabling a writer shares their unstarted work out again; enabling brings the share back.
        gita_id = next(w['id'] for w in ov['writers'] if w['username'] == 'gita')
        c.patch(f'/api/admin/users/{gita_id}', headers=admin, json={'active': False})
        ov3 = c.get('/api/admin/overview', headers=admin).json()
        assert ov3['short_units'] == 0 and all(w['total'] == 3182 for w in ov3['writers'] if w['active'])
        c.patch(f'/api/admin/users/{gita_id}', headers=admin, json={'active': True})
        ov4 = c.get('/api/admin/overview', headers=admin).json()
        assert ov4['short_units'] == 0 and sum(w['total'] for w in ov4['writers']) == 3 * 3182

        # Admin adds a unit -> it goes to 3 writers; deleting it removes it again.
        before = {w['username']: w['units'] for w in ov4['writers']}
        r = c.post('/api/admin/units', headers=admin, json={
            'category': 'test', 'questions': [{'question': 'नेपालको राजधानी कुन हो?', 'answer': 'B',
                                              'options': {'A': 'पोखरा', 'B': 'काठमाडौं', 'C': 'धरान', 'D': 'बुटवल'}}]})
        assert r.status_code == 200, r.text
        new_id = r.json()['id']
        after = {w['username']: w['units'] for w in c.get('/api/admin/overview', headers=admin).json()['writers']}
        assert sum(after.values()) - sum(before.values()) == 3
        assert c.get(f"/api/admin/units?q={r.json()['unit_key']}", headers=admin).json()['total'] == 1
        assert c.get('/api/admin/units?q=राजधानी', headers=admin).json()['total'] >= 1
        assert c.delete(f'/api/admin/units/{new_id}', headers=admin).status_code == 200
        assert {w['username']: w['units'] for w in c.get('/api/admin/overview', headers=admin).json()['writers']} == before

        # Completing everything notifies once per writer, then once for "all done".
        written = 0
        for i, name in enumerate(('ram', 'sita', 'hari', 'gita')):
            h = ram if name == 'ram' else auth(c, name, 'writer-pass-1')
            if name != 'ram':
                c.put('/api/me/profile', headers=h, json={'profile': {}, 'consent': True})
            written += fill_all(c, h, f'lekhyo{i}')['progress']['total']
            assert c.get('/api/me', headers=h).json()['user']['completed_at'] is not None
        assert len(sent) == 5 and 'All writers finished' in sent[4]

        csv_body = c.get('/api/admin/export/responses?format=csv', headers=admin).text
        assert csv_body.count('\n') == 1 + written
        jsonl = c.get('/api/admin/export/responses?format=jsonl', headers=admin).text
        assert len(jsonl.splitlines()) == written and '"writer_code": "W4"' in jsonl
        assert 'Kaski' in c.get('/api/admin/export/writers', headers=admin).text

        # A finished writer who is disabled still counts: nobody gets extra work.
        c.patch(f'/api/admin/users/{gita_id}', headers=admin, json={'active': False})
        ov = c.get('/api/admin/overview', headers=admin).json()
        assert ov['short_units'] > 0  # fewer than 3 *active* writers on gita's items, but they are written
        assert all(w['done'] == w['total'] and w['completed_at'] for w in ov['writers'] if w['active'])

        # A reset gives a new temporary password: the writer is logged out and must set their own again.
        ram_id = ov['writers'][0]['id']
        r = c.patch(f'/api/admin/users/{ram_id}', headers=admin, json={'new_temp_password': True})
        temp = r.json()['temp_password']
        assert temp and c.get('/api/me', headers=ram).status_code == 401
        assert next(w for w in c.get('/api/admin/overview', headers=admin).json()['writers'] if w['id'] == ram_id)['temp_password'] == temp
        ram = auth(c, 'ram', temp)
        assert c.get('/api/units/1', headers=ram).status_code == 403
        same = c.post('/api/me/password', headers=ram, json={'new_password': temp})
        assert same.status_code == 400  # must differ from the temporary one
        assert c.post('/api/me/password', headers=ram, json={'new_password': 'mero-naya-pass'}).status_code == 200
        ram = auth(c, 'ram', 'mero-naya-pass')
        assert c.get('/api/units/1', headers=ram).status_code == 200
        # Changing it later needs the current password.
        assert c.post('/api/me/password', headers=ram, json={'new_password': 'arko-pass-123'}).status_code == 400
        assert c.post('/api/me/password', headers=ram, json={'current_password': 'mero-naya-pass',
                                                             'new_password': 'arko-pass-123'}).status_code == 200


def test_concurrent_first_saves_do_not_fail():
    """Leaving a box and clicking Save and next sends two saves of a new item at once; both must succeed."""
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        admin = auth(c, 'admin', 'admin-pass-123')
        create_writer(c, admin, 'racer')
        w = auth(c, 'racer', 'writer-pass-1')
        c.put('/api/me/profile', headers=w, json={'profile': {}, 'consent': True})
        # Everything else is already written, so new items go to the least-loaded writer: racer.
        for i in range(3):
            c.post('/api/admin/units', headers=admin, json={'category': 'race', 'questions': [{
                'question': f'प्रश्न {i}', 'answer': 'A', 'options': {k: f'उत्तर {k}' for k in 'ABCD'}}]})
        assert c.get('/api/me', headers=w).json()['progress']['units'] == 3
        for ord_ in (1, 2, 3):
            unit = c.get(f'/api/units/{ord_}', headers=w).json()
            body = {'responses': [{'segment_id': s['id'], 'romanized': 'ek', 'note': ''} for s in unit['segments']],
                    'active_ms': 10, 'paste_blocked': 0}
            with ThreadPoolExecutor(4) as pool:
                codes = list(pool.map(lambda _: c.put(f'/api/units/{ord_}', headers=w, json=body).status_code, range(4)))
            assert codes == [200] * 4
