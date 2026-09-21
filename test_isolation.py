"""Offline integration tests: execute application SQL against an in-memory adapter.
Never connects to MySQL. MySQL DDL/collation still requires staging verification.
"""
import sqlite3
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from csrf_test_support import csrf_post
from mysql.connector import IntegrityError, Error
from offline_test_support import main, database


class Cursor:
    def __init__(self, connection, dictionary):
        self.raw = connection.cursor()
        self.dictionary = dictionary
    def execute(self, sql, params=()):
        try:
            self.raw.execute(sql.replace('%s', '?').replace(' FOR UPDATE', ''), params)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc), errno=1062 if 'UNIQUE' in str(exc) else 1451) from exc
    def fetchone(self):
        row = self.raw.fetchone()
        return dict(row) if row is not None and self.dictionary else row
    def fetchall(self):
        return [dict(r) if self.dictionary else r for r in self.raw.fetchall()]
    @property
    def rowcount(self): return self.raw.rowcount
    @property
    def lastrowid(self): return self.raw.lastrowid
    def close(self): self.raw.close()


class Connection:
    def __init__(self, raw): self.raw = raw
    def cursor(self, dictionary=False): return Cursor(self.raw, dictionary)
    def start_transaction(self): self.raw.execute('BEGIN')
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): pass


class IsolationFixture(unittest.TestCase):
    def setUp(self):
        guard = patch('mysql.connector.connect', side_effect=AssertionError('Real MySQL is forbidden in isolation tests'))
        guard.start()
        self.addCleanup(guard.stop)
        self.raw = sqlite3.connect(':memory:', check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.raw.executescript('''PRAGMA foreign_keys=ON;
        CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE,
          password_hash TEXT, email_verified INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE types(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          name TEXT COLLATE NOCASE, is_default INTEGER NOT NULL DEFAULT 0,
          UNIQUE(user_id,name), UNIQUE(user_id,id));
        CREATE TABLE notes(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          title TEXT, content TEXT, url TEXT, type_id INTEGER,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id,type_id) REFERENCES types(user_id,id));''')
        self.addCleanup(self.raw.close)
        p = patch.object(database, 'get_db_connection', side_effect=lambda: Connection(self.raw))
        p.start(); self.addCleanup(p.stop)
        self.a = database.create_user('A', 'a@example.com', 'hash')
        self.b = database.create_user('B', 'b@example.com', 'hash')
        self.ta = database.get_types(self.a)[0]['id']
        self.tb = database.get_types(self.b)[0]['id']
        self.na = database.add_note(self.a, 'A private', 'alpha', 'https://a.example.com', self.ta)
        self.nb = database.add_note(self.b, 'B private', 'beta', 'https://b.example.com', self.tb)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        p = patch.object(main, 'get_current_user', return_value={'id': self.a, 'username': 'A'})
        self.identity = p.start(); self.addCleanup(p.stop)
        self.identity_patch = p

    def snapshot(self):
        # Read every row directly, independently of ownership-filtered helpers.
        return {table: [dict(row) for row in self.raw.execute(f'SELECT * FROM {table} ORDER BY id')]
                for table in ('users', 'types', 'notes')}

    def as_user2(self):
        self.identity.return_value = {'id': self.b, 'username': 'B'}


class IsolationTests(IsolationFixture):
    def test_user2_cannot_read_or_edit_user1_record(self):
        self.as_user2()
        for suffix in ('', '/edit'):
            with self.subTest(suffix=suffix):
                response = self.client.get(f'/notes/{self.na}{suffix}')
                self.assertEqual(response.status_code, 404)
                for secret in ('A private', 'alpha', 'https://a.example.com'):
                    self.assertNotIn(secret, response.text)

    def test_user2_direct_edit_preserves_all_user1_data(self):
        self.as_user2()
        before = self.snapshot()
        response = self.post(f'/notes/{self.na}/edit', title='stolen', content='changed',
                             url='https://attacker.example.com', type_id=self.tb, user_id=self.a)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(database.get_note(self.a, self.na)['title'], 'A private')

    def test_user2_delete_preserves_user1_record(self):
        self.as_user2()
        before = self.snapshot()
        self.assertEqual(self.post(f'/notes/{self.na}/delete', user_id=self.a).status_code, 404)
        self.assertIsNotNone(database.get_note(self.a, self.na))
        self.assertEqual(self.snapshot(), before)

    def test_user2_foreign_type_create_and_edit_preserve_all_data(self):
        self.as_user2()
        before = self.snapshot()
        for path in ('/notes', f'/notes/{self.nb}/edit'):
            with self.subTest(path=path):
                response = self.post(path, title='changed', content='changed content',
                                     url='https://changed.example.com', type_id=self.ta, user_id=self.a)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.snapshot(), before)
        for operation in (
            lambda: database.add_note(self.b, 'changed', 'changed', 'changed', self.ta),
            lambda: database.update_note(self.b, self.nb, 'changed', 'changed', 'changed', self.ta),
        ):
            with self.assertRaises(database.ResourceNotFound):
                operation()
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.raw.execute('''SELECT COUNT(*) FROM notes n JOIN types t
            ON n.type_id=t.id WHERE n.user_id != t.user_id''').fetchone()[0], 0)

    def test_user2_cannot_rename_or_delete_user1_custom_type(self):
        database.add_type(self.a, 'A secret custom type')
        custom = next(t for t in database.get_types(self.a) if not t['is_default'])
        self.as_user2()
        before = self.snapshot()
        # Unused custom type: neither default protection nor in-use protection can mask an ownership bug.
        for action in ('rename', 'delete'):
            with self.subTest(action=action):
                response = self.post(f"/types/{custom['id']}/{action}", name='stolen', user_id=self.a)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(database.get_type(self.a, custom['id']), custom)
                self.assertEqual(self.snapshot(), before)
        self.assertFalse(database.update_type_name(self.b, custom['id'], 'stolen'))
        self.assertFalse(database.delete_type(self.b, custom['id']))
        self.assertEqual(self.snapshot(), before)

    def test_user2_library_search_filters_and_sidebar_are_isolated(self):
        database.add_type(self.a, 'A secret custom type')
        custom = next(t for t in database.get_types(self.a) if not t['is_default'])
        self.as_user2()
        for path, key, expected in (
            ('/', 'recent_notes', [self.nb]), ('/notes', 'notes', [self.nb]),
            ('/notes?q=A%20private', 'notes', []), ('/notes?q=alpha', 'notes', []),
            (f'/notes?type={self.tb}', 'notes', [self.nb]),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([n['id'] for n in response.context[key]], expected)
                self.assertEqual([n['id'] for n in response.context['sidebar_records']], [self.nb])
                own_ids = {t['id'] for t in database.get_types(self.b)}
                self.assertEqual({t['id'] for t in response.context['sidebar_types']}, own_ids)
                if 'types' in response.context:
                    self.assertEqual({t['id'] for t in response.context['types']}, own_ids)
                self.assertNotIn('A secret custom type', response.text)
                # The search field legitimately echoes q; check result rows above and record links here.
                self.assertNotIn(f'href="/notes/{self.na}"', response.text)
                if 'q=' not in path:
                    self.assertNotIn('A private', response.text)
        for foreign_type in (self.ta, custom['id']):
            self.assertEqual(self.client.get(f'/notes?type={foreign_type}').status_code, 404)
            self.assertIsNone(database.get_type(self.b, foreign_type))

    def test_owners_can_read_edit_and_user2_can_complete_record_lifecycle(self):
        for owner, note_id, type_id in ((self.a, self.na, self.ta), (self.b, self.nb, self.tb)):
            self.identity.return_value = {'id': owner}
            for suffix in ('', '/edit'):
                response = self.client.get(f'/notes/{note_id}{suffix}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['note']['id'], note_id)
            response = self.post(f'/notes/{note_id}/edit', title='updated', content='new content',
                                 url='updated.example.com', type_id=type_id)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], f'/notes/{note_id}')
            row = database.get_note(owner, note_id)
            self.assertEqual((row['title'], row['content'], row['url'], row['type_id'], row['user_id']),
                             ('updated', 'new content', 'https://updated.example.com', type_id, owner))
        user1_before = database.get_note(self.a, self.na)
        self.assertEqual(self.post('/types', name='B custom').status_code, 303)
        custom = next(t for t in database.get_types(self.b) if t['name'] == 'B custom')['id']
        self.assertEqual(self.post(f'/types/{custom}/rename', name='B renamed').status_code, 303)
        self.assertEqual(database.get_type(self.b, custom)['name'], 'B renamed')
        self.assertEqual(self.post('/notes', title='B new', content='created', url='new.example.com',
                                   type_id=custom, user_id=self.a).status_code, 303)
        row = next(n for n in database.get_notes(self.b) if n['title'] == 'B new')
        self.assertEqual((row['user_id'], row['type_id'], row['content'], row['url']),
                         (self.b, custom, 'created', 'https://new.example.com'))
        self.assertEqual(self.client.get(f"/notes/{row['id']}").context['note']['id'], row['id'])
        self.assertEqual(self.post(f"/notes/{row['id']}/edit", title='B revised', content='revised',
                                   url='revised.example.com', type_id=self.tb).status_code, 303)
        revised = database.get_note(self.b, row['id'])
        self.assertEqual((revised['title'], revised['content'], revised['url'], revised['type_id']),
                         ('B revised', 'revised', 'https://revised.example.com', self.tb))
        response = self.post(f"/notes/{row['id']}/delete")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/notes')
        self.assertIsNone(database.get_note(self.b, row['id']))
        self.assertEqual(self.post(f'/types/{custom}/delete').status_code, 303)
        self.assertIsNone(database.get_type(self.b, custom))
        self.assertEqual(database.get_note(self.a, self.na), user1_before)

    def test_registration_and_real_sessions_keep_new_users_isolated(self):
        database.add_type(self.a, 'A secret custom type')
        before = self.snapshot()
        # Exercise real registration, password verification, signed cookies and user lookup.
        self.identity_patch.stop()
        new_type_ids = set()
        for username in ('C', 'D'):
            with TestClient(main.app) as client:
                response = csrf_post(client, '/register', data=dict(username=username,
                    email=f'{username}@example.com', password='safe-test-password',
                    confirm_password='safe-test-password'), follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers['location'], '/register?success=1')
                user = database.get_user_by_login(username)
                types = database.get_types(user['id'])
                self.assertEqual(len(types), 6)
                self.assertEqual({t['name'] for t in types}, set(database.DEFAULT_TYPES))
                self.assertTrue(all(t['is_default'] for t in types))
                ids = {t['id'] for t in types}
                self.assertTrue(ids.isdisjoint(new_type_ids | {t['id'] for t in before['types']}))
                new_type_ids.update(ids)
                self.assertEqual(database.get_notes(user['id']), [])
                self.assertEqual(csrf_post(client, '/login', data=dict(login=username,
                    password='safe-test-password'), follow_redirects=False).status_code, 303)
                response = client.get('/notes')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['notes'], [])
                self.assertEqual(response.context['sidebar_records'], [])
                self.assertEqual({t['id'] for t in response.context['sidebar_types']}, ids)
                self.assertNotIn('A secret custom type', response.text)
                self.assertEqual(client.get(f'/notes/{self.na}').status_code, 404)
        after = self.snapshot()
        self.assertEqual(after['notes'], before['notes'])
        self.assertEqual([t for t in after['types'] if t['user_id'] in (self.a, self.b)], before['types'])
    def post(self, path, **data):
        return csrf_post(self.client, path, data=data, follow_redirects=False)
    def test_reads_search_sidebar_counts(self):
        self.assertEqual([n['id'] for n in database.get_notes(self.a)], [self.na])
        self.assertIsNone(database.get_note(self.a, self.nb))
        self.assertEqual(database.search_notes(self.a, 'beta'), [])
        self.assertEqual(database.get_notes_by_type(self.a, self.tb), [])
        self.assertEqual([n['id'] for n in database.get_sidebar_records(self.a)], [self.na])
        self.assertEqual(sum(t['record_count'] for t in database.get_types_with_counts(self.a)), 1)
        self.assertEqual(database.get_type_record_count(self.a, self.tb), 0)
        for path in ['/', '/notes', '/notes?q=beta']:
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertNotIn('B private', result.text)
        self.assertEqual(self.client.get(f'/notes?type={self.tb}').status_code, 404)
    def test_guessed_records_and_writes(self):
        for ident in [self.nb, 9999]:
            for suffix in ['', '/edit']:
                self.assertEqual(self.client.get(f'/notes/{ident}{suffix}').status_code, 404)
            self.assertEqual(self.post(f'/notes/{ident}/edit', title='stolen').status_code, 404)
            self.assertEqual(self.post(f'/notes/{ident}/delete').status_code, 404)
        self.assertEqual(database.get_note(self.b, self.nb)['title'], 'B private')
        with self.assertRaises(database.ResourceNotFound):
            database.update_note(self.a, self.nb, 'x', '', '', None)
        with self.assertRaises(database.ResourceNotFound): database.delete_note(self.a, self.nb)
    def test_foreign_type_rejected(self):
        for type_id in [self.tb, 9999]:
            self.assertEqual(self.post('/notes', title='x', type_id=type_id).status_code, 404)
            self.assertEqual(self.post(f'/notes/{self.na}/edit', title='x', type_id=type_id).status_code, 404)
            with self.assertRaises(database.ResourceNotFound): database.add_note(self.a, 'x', '', '', type_id)
            with self.assertRaises(database.ResourceNotFound): database.update_note(self.a, self.na, 'x', '', '', type_id)
        self.assertEqual(len(database.get_notes(self.a)), 1)
    def test_type_names_and_ownership(self):
        self.assertTrue(database.add_type(self.a, 'Work'))
        self.assertTrue(database.add_type(self.b, 'Work'))
        self.assertFalse(database.add_type(self.a, 'Work'))
        self.assertFalse(database.add_type(self.a, 'work'))
        work = next(t for t in database.get_types(self.b) if t['name']=='Work')['id']
        for ident in [work, 9999]:
            self.assertEqual(self.post(f'/types/{ident}/rename', name='Other').status_code, 404)
            self.assertEqual(self.post(f'/types/{ident}/delete').status_code, 404)
            self.assertFalse(database.update_type_name(self.a, ident, 'Other'))
            self.assertFalse(database.delete_type(self.a, ident))
    def test_defaults(self):
        for user in [self.a, self.b]:
            types = database.get_types(user)
            self.assertEqual({t['name'] for t in types}, set(database.DEFAULT_TYPES))
            self.assertTrue(all(t['is_default'] for t in types))
        self.assertTrue({t['id'] for t in database.get_types(self.a)}.isdisjoint(t['id'] for t in database.get_types(self.b)))
        for t in database.get_types(self.a):
            self.assertEqual(self.post(f"/types/{t['id']}/rename", name='x').status_code, 403)
            self.assertEqual(self.post(f"/types/{t['id']}/delete").status_code, 403)
            self.assertFalse(database.update_type_name(self.a, t['id'], 'x'))
            self.assertFalse(database.delete_type(self.a, t['id']))
    def test_ungrouped_and_browser_owner_ignored(self):
        self.assertEqual(self.post('/notes', title='ungrouped', user_id=self.b).status_code, 303)
        row = database.get_ungrouped_notes(self.a)[0]
        self.assertEqual(row['user_id'], self.a)
        self.assertEqual(database.get_ungrouped_count(self.a), 1)
        self.assertEqual(database.get_ungrouped_count(self.b), 0)
        self.assertEqual(self.post(f'/notes/{self.na}/edit', title='updated', type_id='').status_code, 303)
        self.assertIsNone(database.get_note(self.a, self.na)['type_id'])
    def test_registration_rolls_back_each_default_failure(self):
        original = Cursor.execute
        for fail_at in range(6):
            calls = [0]
            def execute(cursor, sql, params=()):
                if 'INSERT INTO types' in sql:
                    calls[0] += 1
                    if calls[0] == fail_at+1: raise Error('injected failure')
                return original(cursor, sql, params)
            with patch.object(Cursor, 'execute', execute), self.assertRaises(Error):
                database.create_user('C', 'c@example.com', 'hash')
            self.assertEqual(self.raw.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
            self.assertEqual(self.raw.execute('SELECT COUNT(*) FROM types').fetchone()[0], 12)
    def test_unauthenticated_routes(self):
        database.add_type(self.a, 'Anonymous must not change this')
        custom = next(t['id'] for t in database.get_types(self.a) if not t['is_default'])
        before = self.snapshot()
        # Use the actual authentication dependency with an empty cookie jar.
        self.identity_patch.stop()
        self.identity.return_value = None
        for method, path in [('GET','/notes'),('GET',f'/notes/{self.na}'),
             ('GET',f'/notes/{self.na}/edit'),('POST','/notes'),('POST',f'/notes/{self.na}/edit'),
             ('POST',f'/notes/{self.na}/delete'),('POST','/types'),('POST',f'/types/{custom}/rename'),('POST',f'/types/{custom}/delete')]:
            response = self.client.request(method, path, data={'title':'x', 'content':'changed',
                'url':'https://changed.example.com', 'type_id':self.ta, 'name':'changed'}, follow_redirects=False)
            self.assertEqual(response.status_code,303, path)
            self.assertEqual(response.headers['location'],'/login')
            self.assertEqual(self.snapshot(), before, path)
            self.assertNotIn('A private', response.text)
        for path in ['/notes/not-an-int/edit', '/notes/1/edit']:
            response = self.client.post(path, data={}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        for path in ['/','/login','/register']: self.assertEqual(self.client.get(path).status_code,200)

if __name__ == '__main__': unittest.main()
