"""Offline PRG feedback and display-format regression coverage."""
from datetime import datetime
import unittest
from unittest.mock import patch
from starlette.requests import Request
from mysql.connector import Error
from csrf_test_support import csrf_post
from test_isolation import IsolationFixture
from offline_test_support import main, database
from ui_helpers import consume_flash, display_datetime


class FlashTests(IsolationFixture):
    def assert_flash_once(self, response, en, zh):
        self.assertEqual(response.status_code, 303)
        page = self.client.get(response.headers["location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-toast>', page.text)
        self.assertIn(f'data-en="{en}" data-zh="{zh}"', page.text)
        self.assertNotIn('data-toast>', self.client.get(response.headers["location"]).text)

    def test_record_create_edit_delete_prg(self):
        response = csrf_post(self.client, "/notes", data={"title": "Feedback fixture", "return_to": "/"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], "/")
        self.assert_flash_once(response, "Record created", "记录已创建")
        note_id = next(n["id"] for n in database.get_notes(self.a) if n["title"] == "Feedback fixture")
        response = csrf_post(self.client, f"/notes/{note_id}/edit", data={"title": "Edited fixture"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], f"/notes/{note_id}")
        self.assert_flash_once(response, "Changes saved", "修改已保存")
        response = csrf_post(self.client, f"/notes/{note_id}/delete", follow_redirects=False)
        self.assertEqual(response.headers["location"], "/notes")
        self.assert_flash_once(response, "Record deleted", "记录已删除")

    def test_type_create_rename_delete_prg(self):
        response = csrf_post(self.client, "/types", data={"name": "Feedback Type"}, follow_redirects=False)
        self.assert_flash_once(response, "Type created", "类型已创建")
        type_id = next(t["id"] for t in database.get_types(self.a) if t["name"] == "Feedback Type")
        response = csrf_post(self.client, f"/types/{type_id}/rename", data={"name": "Renamed Type"}, follow_redirects=False)
        self.assert_flash_once(response, "Type saved", "类型已保存")
        response = csrf_post(self.client, f"/types/{type_id}/delete", data={"return_to": f"/notes?type={type_id}"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], "/notes")
        self.assert_flash_once(response, "Type deleted", "类型已删除")

    def test_failed_operations_do_not_create_toast(self):
        cases = [("/notes", {"title": ""}, 400),
                 (f"/notes/{self.na}/edit", {"title": "x", "type_id": "bad"}, 400),
                 (f"/notes/{self.nb}/delete", {}, 404),
                 (f"/types/{self.ta}/delete", {}, 403)]
        database.add_type(self.a, "In use")
        used = next(t["id"] for t in database.get_types(self.a) if t["name"] == "In use")
        database.add_note(self.a, "Used", "", "", used)
        cases.append((f"/types/{used}/delete", {}, 409))
        for path, data, status in cases:
            with self.subTest(path=path):
                response = csrf_post(self.client, path, data=data, follow_redirects=False)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('data-toast>', response.text)
                self.assertNotIn('data-toast>', self.client.get("/notes").text)
        self.assertEqual(self.client.post("/notes", data={"title": "No token"}).status_code, 403)
        with patch.object(main, "add_note", side_effect=Error("synthetic failure")):
            response = csrf_post(self.client, "/notes", data={"title": "Failure"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('data-toast>', self.client.get("/notes").text)

    def test_error_rerender_does_not_consume_pending_flash(self):
        csrf_post(self.client, "/notes", data={"title": "Saved"}, follow_redirects=False)
        error = csrf_post(self.client, "/notes", data={"title": "", "return_to": "/"})
        self.assertEqual(error.status_code, 400)
        self.assertNotIn('data-toast>', error.text)
        self.assertIn('data-en="Record created"', self.client.get("/").text)
        self.assertNotIn('data-toast>', self.client.get("/").text)

    def test_user_input_cannot_supply_flash_html(self):
        payload = '<img src=x onerror=alert(1)>'
        response = csrf_post(self.client, "/notes", data={"title": payload, "ui_flash": payload}, follow_redirects=False)
        page = self.client.get(response.headers["location"])
        self.assertIn('data-en="Record created"', page.text)
        self.assertNotIn(payload, page.text)
        self.assertNotIn('data-toast>', self.client.get('/notes?ui_flash=record_created').text)

    def test_dates_render_consistently_on_all_record_pages(self):
        self.raw.execute("UPDATE notes SET created_at=?, updated_at=? WHERE id=?", ("2026-09-21 18:25:26", "2026-09-21 18:25:26", self.na))
        self.raw.commit()
        for path in ("/", "/notes", f"/notes/{self.na}"):
            page = self.client.get(path)
            self.assertIn('data-en="Updated Sep 21, 2026, 18:25"', page.text)
            self.assertIn('data-zh="更新于 2026年9月21日 18:25"', page.text)
            self.assertIn('datetime="2026-09-21T18:25:26"', page.text)
        self.assertEqual(database.get_note(self.a, self.na)["updated_at"], "2026-09-21 18:25:26")


class PresentationHelpersTests(unittest.TestCase):
    def test_fixed_messages_only_and_single_consumption(self):
        for key in ('<script>alert(1)</script>', [], {}, None, 'unknown'):
            session = {"ui_flash": key, "user_id": 1, "csrf_token": "preserved"}
            request = Request({"type": "http", "method": "GET", "session": session})
            self.assertIsNone(consume_flash(request))
            self.assertEqual(session, {"user_id": 1, "csrf_token": "preserved"})
        request = Request({"type": "http", "method": "GET", "session": {"ui_flash": "record_saved"}})
        self.assertEqual(consume_flash(request), ("Changes saved", "修改已保存"))
        self.assertIsNone(consume_flash(request))

    def test_datetime_objects_strings_and_empty_values(self):
        expected = {"iso": "2026-09-21T18:25:26", "en": "Sep 21, 2026, 18:25", "zh": "2026年9月21日 18:25"}
        self.assertEqual(display_datetime(datetime(2026, 9, 21, 18, 25, 26)), expected)
        self.assertEqual(display_datetime("2026-09-21 18:25:26"), expected)
        self.assertEqual(display_datetime("2026-01-02 03:04:59")["en"], "Jan 2, 2026, 03:04")
        for value in (None, "", "invalid"):
            self.assertEqual(display_datetime(value), {"iso": "", "en": "—", "zh": "—"})


if __name__ == "__main__":
    unittest.main()
