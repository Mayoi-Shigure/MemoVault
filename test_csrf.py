"""CSRF integration tests with real signed sessions and an in-memory SQL adapter."""
import base64
import json
import secrets
from unittest.mock import patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import test_isolation
from offline_test_support import main, database
from csrf_test_support import Forms, token_from_page, csrf_post
from security import get_csrf_token, is_csrf_token, verify_csrf_token


class CSRFTests(test_isolation.IsolationFixture):
    def setUp(self):
        super().setUp()
        self.identity_patch.stop()
        self.password = 'offline-csrf-test-password'
        self.raw.execute('UPDATE users SET password_hash=?', (main.hash_password(self.password),))
        self.raw.commit()
        self.other = TestClient(main.app)
        self.addCleanup(self.other.close)
        for client, name in ((self.client, 'A'), (self.other, 'B')):
            response = csrf_post(client, '/login', data=dict(login=name, password=self.password),
                                 follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        self.token_a = token_from_page(self.client, '/notes')
        self.token_b = token_from_page(self.other, '/notes')
        database.add_type(self.a, 'A custom')
        database.add_type(self.b, 'B custom')
        self.custom_a = next(t['id'] for t in database.get_types(self.a) if not t['is_default'])
        self.custom_b = next(t['id'] for t in database.get_types(self.b) if not t['is_default'])

    def writes(self, note, custom):
        return (
            ('/notes', {'title': 'Created'}),
            (f'/notes/{note}/edit', {'title': 'Changed'}),
            (f'/notes/{note}/delete', {}),
            ('/types', {'name': 'Created'}),
            (f'/types/{custom}/rename', {'name': 'Changed'}),
            (f'/types/{custom}/delete', {}),
        )

    def session(self, client):
        payload = TimestampSigner(main.session_secret).unsign(client.cookies.get('session'))
        return json.loads(base64.b64decode(payload))

    def assert_csrf_failure(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'detail': 'CSRF validation failed'})

    def test_missing_wrong_and_malformed_tokens_preserve_all_data(self):
        before = self.snapshot()
        for path, fields in self.writes(self.na, self.custom_a):
            for token in (None, '', secrets.token_urlsafe(32), '非ASCII', 'x' * 10000):
                with self.subTest(path=path, missing=token is None):
                    data = dict(fields)
                    if token is not None:
                        data['csrf_token'] = token
                    self.assert_csrf_failure(self.client.post(path, data=data))
                    self.assertEqual(self.snapshot(), before)

    def test_other_session_token_rejected_for_every_write(self):
        self.assertNotEqual(self.token_a, self.token_b)
        before = self.snapshot()
        for path, fields in self.writes(self.nb, self.custom_b):
            with self.subTest(path=path):
                self.assert_csrf_failure(self.other.post(path, data=dict(fields, csrf_token=self.token_a)))
                self.assertEqual(self.snapshot(), before)

    def test_valid_csrf_does_not_bypass_ownership(self):
        before = self.snapshot()
        for path, fields in self.writes(self.na, self.custom_a)[1:3] + self.writes(self.na, self.custom_a)[4:]:
            with self.subTest(path=path):
                response = self.other.post(path, data=dict(fields, csrf_token=self.token_b))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.snapshot(), before)
        for path in ('/notes', f'/notes/{self.nb}/edit'):
            response = self.other.post(path, data=dict(title='changed', type_id=self.ta, csrf_token=self.token_b))
            self.assertEqual(response.status_code, 404)
            self.assertEqual(self.snapshot(), before)

    def test_valid_token_owner_can_complete_record_and_type_lifecycle(self):
        def post(path, **fields):
            response = self.client.post(path, data=dict(fields, csrf_token=self.token_a), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        other_before = database.get_note(self.b, self.nb)
        post('/types', name='New type')
        type_id = next(t['id'] for t in database.get_types(self.a) if t['name'] == 'New type')
        post(f'/types/{type_id}/rename', name='Renamed')
        self.assertEqual(database.get_type(self.a, type_id)['name'], 'Renamed')
        post('/notes', title='New note', type_id=type_id)
        note_id = next(n['id'] for n in database.get_notes(self.a) if n['title'] == 'New note')
        post(f'/notes/{note_id}/edit', title='Edited', type_id=type_id)
        self.assertEqual(database.get_note(self.a, note_id)['title'], 'Edited')
        post(f'/notes/{note_id}/delete')
        self.assertIsNone(database.get_note(self.a, note_id))
        post(f'/types/{type_id}/delete')
        self.assertIsNone(database.get_type(self.a, type_id))
        self.assertEqual(database.get_note(self.b, self.nb), other_before)

    def test_logout_failure_preserves_authenticated_session(self):
        before = self.session(self.client)
        for fields in ({}, {'csrf_token': ''}, {'csrf_token': secrets.token_urlsafe(32)},
                       {'csrf_token': self.token_b}):
            self.assert_csrf_failure(self.client.post('/logout', data=fields, follow_redirects=False))
            self.assertEqual(self.session(self.client), before)
            self.assertEqual(self.client.get('/').context['current_user']['id'], self.a)
        self.assertEqual(self.client.get('/logout').status_code, 405)

    def test_logout_confirmation_controls_and_form(self):
        class Page(Forms):
            def __init__(self, html):
                self.elements = []
                super().__init__(html)

            def handle_starttag(self, tag, attrs):
                self.elements.append((tag, dict(attrs), self.current))
                super().handle_starttag(tag, attrs)

        response = self.client.get('/notes')
        page = Page(response.text)
        triggers = [(tag, attrs, form) for tag, attrs, form in page.elements
                    if attrs.get('data-modal-open') == 'logout-modal']
        self.assertEqual(len(triggers), 2)
        for tag, attrs, form in triggers:
            self.assertEqual((tag, attrs['type'], attrs['role']), ('button', 'button', 'menuitem'))
            self.assertEqual(attrs['aria-controls'], 'logout-modal')
            self.assertIsNone(form)
        backdrop = next(attrs for _, attrs, _ in page.elements if attrs.get('id') == 'logout-modal')
        self.assertEqual(backdrop['aria-hidden'], 'true')
        dialog = next(attrs for _, attrs, _ in page.elements if attrs.get('aria-labelledby') == 'logout-title')
        self.assertEqual(dialog['role'], 'dialog')
        self.assertEqual(dialog['aria-modal'], 'true')
        self.assertEqual(dialog['aria-describedby'], 'logout-description')
        description = next(attrs for _, attrs, _ in page.elements if attrs.get('id') == 'logout-description')
        self.assertEqual(description['data-en'], 'Are you sure you want to sign out?')
        self.assertEqual(description['data-zh'], '确定要退出当前账户吗？')
        forms = [form for form in page.forms if form.get('action') == '/logout']
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form['method'], 'POST')
        fields = {field['name']: field['value'] for field in form['inputs']}
        self.assertEqual(fields, {'csrf_token': self.token_a})
        buttons = [attrs for tag, attrs, parent in page.elements if tag == 'button' and parent is form]
        self.assertEqual(len(buttons), 2)
        cancel = next(button for button in buttons if button['type'] == 'button')
        self.assertIn('data-modal-close', cancel)
        self.assertIn('data-modal-initial-focus', cancel)
        self.assertEqual((cancel['data-en'], cancel['data-zh']), ('Cancel', '取消'))
        confirm = next(button for button in buttons if button['type'] == 'submit')
        self.assertEqual((confirm['data-en'], confirm['data-zh']), ('Sign out', '退出登录'))
        self.assertEqual(self.session(self.client)['user_id'], self.a)
        response = self.client.post(form['action'], data=fields, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/')
        self.assertIsNone(self.client.cookies.get('session'))

    def test_logout_clears_token_and_old_token_fails_in_new_session(self):
        response = self.client.post('/logout', data={'csrf_token': self.token_a}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/')
        self.assertIn('expires=Thu, 01 Jan 1970', response.headers['set-cookie'])
        self.assertIsNone(self.client.cookies.get('session'))
        self.assertEqual(self.client.get('/notes', follow_redirects=False).status_code, 303)
        self.assert_csrf_failure(self.client.post('/logout', data={'csrf_token': self.token_a}))
        fresh = token_from_page(self.client)
        self.assertNotEqual(fresh, self.token_a)
        self.assert_csrf_failure(self.client.post('/login', data=dict(login='A', password=self.password,
                                                                     csrf_token=self.token_a)))

    def test_login_rotates_token_even_when_signing_in_as_same_user(self):
        response = self.client.post('/login', data=dict(login='A', password=self.password,
                                                       csrf_token=self.token_a), follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        new_token = token_from_page(self.client, '/')
        self.assertNotEqual(new_token, self.token_a)
        self.assert_csrf_failure(self.client.post('/types', data=dict(name='Old token', csrf_token=self.token_a)))
        self.assertEqual(self.client.post('/types', data=dict(name='Fresh token', csrf_token=new_token),
                                         follow_redirects=False).status_code, 303)

    def test_login_and_register_reject_invalid_csrf_before_business_logic(self):
        before = self.snapshot()
        with TestClient(main.app) as anonymous:
            token_from_page(anonymous)
            for path in ('/login', '/register'):
                for token in (None, '', secrets.token_urlsafe(32), self.token_a):
                    fields = dict(login='A', username='C', email='c@example.com', password=self.password,
                                  confirm_password=self.password)
                    if token is not None:
                        fields['csrf_token'] = token
                    with patch.object(main, 'get_user_by_login') as lookup, patch.object(main, 'create_user') as create:
                        self.assert_csrf_failure(anonymous.post(path, data=fields))
                        lookup.assert_not_called()
                        create.assert_not_called()
                    self.assertNotIn('user_id', self.session(anonymous))
                    self.assertEqual(self.snapshot(), before)

    def test_registration_prg_then_login_rotates_anonymous_token(self):
        with TestClient(main.app) as anonymous:
            token = token_from_page(anonymous, '/register')
            response = anonymous.post('/register', data=dict(username='C', email='c@example.com',
                password=self.password, confirm_password=self.password, csrf_token=token), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/register?success=1')
            self.assertNotIn('user_id', self.session(anonymous))
            self.assertEqual(anonymous.get(response.headers['location']).status_code, 200)
            response = anonymous.post('/login', data=dict(login='C', password=self.password, csrf_token=token),
                                      follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertNotEqual(token_from_page(anonymous, '/'), token)
            self.assertEqual(len(database.get_types(self.session(anonymous)['user_id'])), 6)

    def test_get_pages_and_every_post_form_have_matching_hidden_token(self):
        for path in ('/', '/notes', f'/notes/{self.na}', f'/notes/{self.na}/edit', '/login', '/register'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                forms = Forms(response.text).forms
                self.assertTrue(forms)
                for form in forms:
                    tokens = [f for f in form['inputs'] if f.get('name') == 'csrf_token']
                    if form.get('method', 'GET').upper() == 'POST':
                        self.assertEqual(len(tokens), 1)
                        self.assertEqual(tokens[0]['type'], 'hidden')
                        self.assertEqual(tokens[0]['value'], self.token_a)
                    else:
                        self.assertEqual(tokens, [])

    def test_validation_error_forms_keep_token_and_passwords_are_not_refilled(self):
        before = self.snapshot()
        for path in ('/', '/notes', f'/notes/{self.na}', f'/notes/{self.na}/edit'):
            response = self.client.post('/notes', data=dict(title='', return_to=path, csrf_token=self.token_a))
            self.assertEqual(response.status_code, 400)
            for form in Forms(response.text).forms:
                if form.get('method', '').upper() == 'POST':
                    tokens = [f['value'] for f in form['inputs'] if f.get('name') == 'csrf_token']
                    self.assertEqual(tokens, [self.token_a])
        for path, fields, status in (('/login', dict(login='A', password='wrong-password'), 401),
                                    ('/register', dict(username='C', email='c@example.com',
                                                       password=self.password, confirm_password='different'), 400)):
            response = self.client.post(path, data=dict(fields, csrf_token=self.token_a))
            self.assertEqual(response.status_code, status)
            for form in Forms(response.text).forms:
                for field in form['inputs']:
                    if field.get('type') == 'password':
                        self.assertNotIn('value', field)
            self.assertEqual(self.session(self.client)['csrf_token'], self.token_a)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_session_get_provisions_token_but_post_does_not(self):
        payload = base64.b64encode(json.dumps({'user_id': self.a}).encode())
        cookie = TimestampSigner(main.session_secret).sign(payload).decode()
        self.client.cookies.set('session', cookie, domain='testserver.local', path='/')
        before = self.snapshot()
        self.assert_csrf_failure(self.client.post('/types', data=dict(name='Legacy', csrf_token=self.token_a)))
        self.assertNotIn('csrf_token', self.session(self.client))
        token = token_from_page(self.client, '/notes')
        self.assertTrue(is_csrf_token(token))
        self.assertEqual(token_from_page(self.client, '/'), token)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_file_json_and_query_tokens_are_rejected(self):
        before = self.snapshot()
        self.assert_csrf_failure(self.client.post('/types', data={'name': 'Duplicate',
                                               'csrf_token': [self.token_a, self.token_a]}))
        self.assert_csrf_failure(self.client.post('/types', data={'name': 'File'},
            files={'csrf_token': ('token.txt', self.token_a, 'text/plain')}))
        self.assert_csrf_failure(self.client.post('/types', json=dict(name='JSON', csrf_token=self.token_a)))
        self.assert_csrf_failure(self.client.post('/types', params={'csrf_token': self.token_a}, data={'name': 'Query'}))
        self.assertEqual(self.snapshot(), before)

    def test_token_without_authentication_cannot_write(self):
        before = self.snapshot()
        with TestClient(main.app) as anonymous:
            token = token_from_page(anonymous)
            response = anonymous.post('/notes', data=dict(title='Anonymous', csrf_token=token), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/login')
        self.assertEqual(self.snapshot(), before)

    def test_invalid_token_types_are_safe_and_validation_does_not_generate(self):
        for invalid in (None, 123, True, [], {}, b'bytes', '', '中' * 43, 'x' * 42, 'x' * 44):
            self.assertFalse(verify_csrf_token({'csrf_token': self.token_a}, invalid))
            session = {'csrf_token': invalid}
            self.assertFalse(verify_csrf_token(session, self.token_a))
            self.assertEqual(session, {'csrf_token': invalid})
        session = {}
        self.assertFalse(verify_csrf_token(session, self.token_a))
        self.assertEqual(session, {})
        token = get_csrf_token(session)
        self.assertTrue(verify_csrf_token(session, token))
        self.assertEqual(get_csrf_token(session), token)

    def test_csrf_failure_does_not_disclose_resource_existence(self):
        before = self.snapshot()
        for path in (f'/notes/{self.na}/edit', f'/notes/{self.nb}/edit', '/notes/99999/edit',
                     '/notes/not-an-int/edit', f'/types/{self.custom_a}/delete', '/types/99999/delete'):
            self.assert_csrf_failure(self.client.post(path, data={}))
        self.assertEqual(self.snapshot(), before)
