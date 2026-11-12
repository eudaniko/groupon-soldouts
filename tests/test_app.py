import base64
import http.client
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.parse import urlencode

from soldouts import app
from soldouts.app import parse_rate


class ParseRateTest(unittest.TestCase):
    def test_number(self):
        self.assertEqual(parse_rate("25"), 25.0)
        self.assertEqual(parse_rate("12.5"), 12.5)

    def test_clamped(self):
        self.assertEqual(parse_rate("-3"), 0.0)
        self.assertEqual(parse_rate("9999"), 500.0)

    def test_junk_means_default(self):
        for text in (None, "", "abc", "nan", "NaN", "inf", "-inf"):
            self.assertIsNone(parse_rate(text), text)


class SessionTest(unittest.TestCase):
    def test_round_trip(self):
        c = app.make_session("pw", now=1000)
        self.assertTrue(app.session_ok("pw", c, now=1000 + 3600))

    def test_rejects_forged_expired_or_other_password(self):
        c = app.make_session("pw", now=1000)
        issued, sig = c.split(".")
        self.assertFalse(app.session_ok("pw", f"{issued}.{'0' * len(sig)}", now=1000))      # forged signature
        self.assertFalse(app.session_ok("pw", f"{int(issued) + 86400}.{sig}", now=90000))   # date moved, old signature
        self.assertFalse(app.session_ok("pw", c, now=1000 + 31 * 86400))                    # older than 30 days
        self.assertFalse(app.session_ok("other", c, now=1000))                              # password changed
        for junk in ("", "abc", None, "1.2.3", "x.y"):
            self.assertFalse(app.session_ok("pw", junk))

    def test_password_check(self):
        self.assertTrue(app.password_ok("s3cret", "s3cret"))
        for wrong in ("", None, "s3cre", "s3cret ", "S3CRET"):
            self.assertFalse(app.password_ok("s3cret", wrong))

    def test_only_local_paths_after_sign_in(self):
        for good in ("/", "/?rep=R10", "/api/board"):
            self.assertEqual(app.safe_next(good), good)
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example", "evil", "", None, "/login?next=/"):
            self.assertEqual(app.safe_next(bad), "/", bad)


class SignInFlowTest(unittest.TestCase):
    """The real server on a free local port, offline (no sandbox key, demo data)."""

    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, {"APP_PASSWORD": "test-pass"})
        cls.env.start()
        os.environ.pop("SANDBOX_KEY", None)
        app.STATE = app.State()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.stop()

    def setUp(self):
        app._fails.clear()
        quiet = mock.patch.object(app.Handler, "log_message", lambda *a: None)
        quiet.start()
        self.addCleanup(quiet.stop)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def sign_in(self, pw, nxt="/"):
        return self.req("POST", "/login", urlencode({"password": pw, "next": nxt}),
                        {"Content-Type": "application/x-www-form-urlencoded"})

    def test_signed_out_pages_go_to_sign_in_and_api_says_401(self):
        r, _ = self.req("GET", "/?rep=R10")
        self.assertEqual((r.status, r.getheader("Location")), (303, "/login?next=%2F%3Frep%3DR10"))
        r, _ = self.req("GET", "/api/board")
        self.assertEqual(r.status, 401)
        self.assertIsNone(r.getheader("WWW-Authenticate"))       # no browser password pop-up any more
        r, body = self.req("GET", "/login?next=%2F%3Frep%3DR10")
        self.assertEqual(r.status, 200)
        self.assertIn(b'name="next" value="/?rep=R10"', body)
        self.assertNotIn(b"{{", body)
        r, _ = self.req("GET", "/healthz")
        self.assertEqual(r.status, 200)

    def test_wrong_then_right_password(self):
        with mock.patch.object(app.time, "sleep"):
            r, body = self.sign_in("nope")
        self.assertEqual(r.status, 401)
        self.assertIn(b"That password didn&#x27;t work", body)
        r, _ = self.sign_in("test-pass", "/?rep=R10")
        self.assertEqual((r.status, r.getheader("Location")), (303, "/?rep=R10"))
        cookie = r.getheader("Set-Cookie")
        for part in ("HttpOnly", "SameSite=Lax", "Path=/", f"Max-Age={30 * 86400}"):
            self.assertIn(part, cookie)
        session = cookie.split(";")[0]
        self.assertEqual(self.req("GET", "/", headers={"Cookie": session})[0].status, 200)
        self.assertEqual(self.req("GET", "/api/marks", headers={"Cookie": session})[0].status, 200)
        r, _ = self.req("GET", "/login", headers={"Cookie": session})   # already signed in
        self.assertEqual((r.status, r.getheader("Location")), (303, "/"))

    def test_no_redirect_to_other_sites(self):
        r, _ = self.sign_in("test-pass", "//evil.example/x")
        self.assertEqual(r.getheader("Location"), "/")

    def test_basic_auth_still_works_for_scripts(self):
        tok = base64.b64encode(b"x:test-pass").decode()
        r, _ = self.req("GET", "/api/marks", headers={"Authorization": "Basic " + tok})
        self.assertEqual(r.status, 200)

    def test_sign_out_clears_the_cookie(self):
        r, _ = self.req("GET", "/logout")
        self.assertEqual((r.status, r.getheader("Location")), (303, "/login"))
        self.assertIn("Max-Age=0", r.getheader("Set-Cookie"))

    def test_too_many_wrong_tries_pause_sign_in(self):
        with mock.patch.object(app.time, "sleep"):
            for _ in range(app.MAX_FAILS):
                self.assertEqual(self.sign_in("nope")[0].status, 401)
            r, body = self.sign_in("test-pass")                      # even the right one waits now
        self.assertEqual(r.status, 429)
        self.assertIn(b"Too many wrong tries", body)


if __name__ == "__main__":
    unittest.main()
