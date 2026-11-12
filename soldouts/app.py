"""The rep tool: today's sold-outs, what to do about each and why, and a way to mark a merchant.

    python3 -m soldouts.app            # http://localhost:8080
    PORT=8090 APP_PASSWORD=... python3 -m soldouts.app   # with a sign-in page (one team password)
    OPEN_SIGN_IN=1 python3 -m soldouts.app                # same sign-in page, one tap, no password

Sold-outs come from the sandbox (GET /soldouts/today) when SANDBOX_KEY is set; otherwise from
routing/input/todays_soldouts.csv and the page says "demo data". Marks go to the sandbox
(PUT /merchants/{id}/mark) and are also kept in data/marks_local.json so the page works offline.
"""
import base64
import csv
import hashlib
import hmac
import html
import json
import math
import os
import secrets
import sys
import threading
import time
from datetime import date
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from soldouts import config, context, decide, detect, sandbox, texts

STATIC = Path(__file__).parent / "static"
LOCAL_MARKS = config.DATA / "marks_local.json"
DEMO = config.ROOT / "routing" / "input" / "todays_soldouts.csv"
_lock = threading.Lock()


class State:
    def __init__(self):
        self.ctx = context.load()
        self.uplift = config.load_uplift()
        self.reps = self._reps()
        self.flags_llm = self._json(config.DATA / "flags_llm.json")
        self.flags_rules = {}
        self.cache = {"at": 0, "rows": [], "source": ""}

    @staticmethod
    def _json(p):
        return json.loads(p.read_text()) if p.exists() else {}

    def _reps(self):
        p = config.PACK / "reps.csv"
        if p.exists():
            with open(p, newline="") as f:
                return {r["rep_id"]: r for r in csv.DictReader(f)}
        ids = sorted({m["rep_id"] for m in self.ctx["merchants"].values()})
        return {i: {"rep_id": i, "rep_name": i, "team": ""} for i in ids}

    def soldouts(self):
        if time.time() - self.cache["at"] < 300:
            return self.cache["rows"], self.cache["source"]
        rows, source = None, "demo data (routing/input/todays_soldouts.csv)"
        if sandbox.available():
            try:
                rows, source = sandbox.soldouts_today(), "sandbox: GET /soldouts/today"
            except sandbox.SandboxError as e:
                print("sandbox unavailable, using demo data:", e, file=sys.stderr)
        if rows is None:
            rows = list(csv.DictReader(open(DEMO, newline="")))
        self.cache = {"at": time.time(), "rows": rows, "source": source}
        self.queue_llm(rows)
        return rows, source

    def _llm_worker(self, mids, on_date):
        """Background: read new merchants' text with the LLM once, cache it. The page uses rules until then."""
        for mid in mids:
            try:
                items = texts.load(config.PACK, {mid})
                res = detect.detect({mid: items}, "llm", on_date)
                with _lock:
                    self.flags_llm.update(res)
                    (config.DATA / "flags_llm.json").write_text(json.dumps(self.flags_llm, indent=1, ensure_ascii=False))
            except (Exception, SystemExit) as e:  # budget, network: keep the rules flags
                print("llm flags skipped for", mid, e, file=sys.stderr)
                if isinstance(e, SystemExit):
                    return
        self.llm_running = False

    def queue_llm(self, rows):
        if getattr(self, "llm_running", False) or not sandbox.available() or not config.PACK.exists():
            return
        todo = sorted({r["merchant_id"] for r in rows} - set(self.flags_llm))
        if todo:
            self.llm_running = True
            on_date = (rows[0].get("sold_out_at") or date.today().isoformat())[:10]
            threading.Thread(target=self._llm_worker, args=(todo, on_date), daemon=True).start()

    def flags_for(self, mid, on_date):
        if mid in self.flags_llm:
            return self.flags_llm[mid]
        if mid not in self.flags_rules and config.PACK.exists():
            items = texts.load(config.PACK, {mid})
            self.flags_rules[mid] = detect.detect({mid: items}, "rules", on_date).get(mid, {"flags": [], "backend": "rules"})
        return self.flags_rules.get(mid, {"flags": [], "backend": "none"})

    def marks(self):
        local = self._json(LOCAL_MARKS)
        try:
            remote = sandbox.marks()
        except sandbox.SandboxError:
            remote = {}
        return {**local, **remote}

    def board(self, rep=None, hourly=None):
        rows, source = self.soldouts()
        marks = self.marks()
        out = []
        for r in rows:
            mid = r["merchant_id"]
            m = self.ctx["merchants"].get(mid)
            if not m or (rep and m["rep_id"] != rep):
                continue
            so = {"deal_id": r["deal_id"], "merchant_id": mid,
                  "sold_out_date": (r.get("sold_out_date") or r.get("sold_out_at") or date.today().isoformat())[:10],
                  "callback_promised": r.get("callback_promised", "0")}
            f = self.flags_for(mid, so["sold_out_date"])
            d = decide.decide(so, m, self.ctx["schedules"], f.get("flags", []), self.uplift, marks.get(mid), hourly)
            out.append({**d.to_dict(), "merchant_id": mid, "merchant": m["name"], "city": m["city"],
                        "category": m["category"], "band": m["band"], "rep_id": m["rep_id"], "deal_id": r["deal_id"],
                        "sold_out_date": so["sold_out_date"], "cap": r.get("cap"), "mark": marks.get(mid),
                        "flags_backend": f.get("backend"), "ai_verdict": f.get("verdict", ""),
                        "all_flags": f.get("flags", [])})
        order = {decide.CALL: 0, decide.OTHER: 1, decide.LATER: 2, decide.SKIP: 3}
        out.sort(key=lambda x: (order[x["action"]], "callback" not in x["headline"], -(x["value_gbp"] or 0)))
        return {"source": source, "rows": out, "hourly_rate": config.REP_HOURLY_COST_GBP if hourly is None else hourly,
                "hourly_rate_default": config.REP_HOURLY_COST_GBP,
                "reps": sorted(self.reps.values(), key=lambda r: r["rep_id"])}

    def set_mark(self, body):
        mid, mark = body["merchant_id"], body["mark"]
        reason = (body.get("reason") or "").strip()[:300]
        by = (body.get("marked_by") or "").strip()[:20]
        if mid not in self.ctx["merchants"] or mark not in decide.MARKS or not reason or not by:
            raise ValueError("merchant_id, mark, reason and marked_by are required")
        entry = {"merchant_id": mid, "mark": mark, "reason": reason, "marked_by": by, "at": date.today().isoformat()}
        with _lock:
            local = self._json(LOCAL_MARKS)
            local[mid] = entry
            LOCAL_MARKS.write_text(json.dumps(local, indent=1))
        synced = False
        if sandbox.available():
            try:
                sandbox.set_mark(mid, mark, reason, by)
                synced = True
            except sandbox.SandboxError as e:
                print("mark not synced:", e, file=sys.stderr)
        return {**entry, "synced_to_sandbox": synced}


def parse_rate(text):
    """The page's ?rate= (rep cost, £ per hour). A number from 0 to 500; anything else means the default."""
    try:
        rate = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate):
        return None
    return min(max(rate, 0.0), 500.0)


# ---- sign-in ----------------------------------------------------------------------------------
# One team password (APP_PASSWORD). The sign-in page sets a signed cookie, so the password itself isn't
# sent with every request (it was, with the browser's Basic pop-up). Basic auth still works for scripts
# (curl -u x:$APP_PASSWORD). No APP_PASSWORD = no sign-in, for running it locally.
# OPEN_SIGN_IN=1 keeps the sign-in page but drops the password: one tap signs you in (used for the
# hand-in copy, so whoever has the link can open it). Basic auth with APP_PASSWORD still works then.
COOKIE = "soldouts_session"
SESSION_DAYS = 30
MAX_FAILS, FAIL_WINDOW_S = 8, 600        # wrong passwords from one address before a 10-minute pause
_fails = {}
_PROCESS_KEY = secrets.token_hex(32)     # signs cookies when there is no APP_PASSWORD (open sign-in)


def open_sign_in():
    return os.environ.get("OPEN_SIGN_IN", "").strip().lower() in ("1", "true", "yes", "on")


def session_key():
    """What cookies are signed with: the team password, or a key that lives as long as the process."""
    return os.environ.get("APP_PASSWORD") or _PROCESS_KEY


def _sig(pw, issued):
    key = hmac.new(pw.encode(), b"soldouts-session-v1", hashlib.sha256).digest()
    return hmac.new(key, issued.encode(), hashlib.sha256).hexdigest()


def make_session(pw, now=None):
    issued = str(int(time.time() if now is None else now))
    return f"{issued}.{_sig(pw, issued)}"


def session_ok(pw, value, now=None):
    """True for a cookie made by make_session with this password, at most SESSION_DAYS old.
    Changing APP_PASSWORD signs everyone out."""
    try:
        issued, sig = value.split(".", 1)
        age = (time.time() if now is None else now) - int(issued)
    except (AttributeError, ValueError):
        return False
    return 0 <= age <= SESSION_DAYS * 86400 and hmac.compare_digest(sig, _sig(pw, issued))


def password_ok(pw, given):
    h = lambda s: hashlib.sha256((s or "").encode()).digest()
    return hmac.compare_digest(h(pw), h(given))


def safe_next(target):
    """Where to go after signing in: a path on this site only (never //host or a full URL)."""
    t = (target or "/").strip()
    if not t.startswith("/") or t.startswith("//") or "\\" in t or urlsplit(t).netloc or t.startswith("/login"):
        return "/"
    return t


def too_many_fails(ip, now=None):
    now = time.time() if now is None else now
    if len(_fails) > 1000:                                   # forget addresses that went quiet
        for k in [k for k, v in _fails.items() if not v or now - v[-1] >= FAIL_WINDOW_S]:
            del _fails[k]
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW_S]
    return len(_fails[ip]) >= MAX_FAILS


def note_fail(ip, now=None):
    _fails.setdefault(ip, []).append(time.time() if now is None else now)


def login_page(error="", next_path="/", open_mode=None):
    page = (STATIC / "login.html").read_text(encoding="utf-8")
    if open_sign_in() if open_mode is None else open_mode:
        start, end = page.index("<!--password-->"), page.index("<!--/password-->") + len("<!--/password-->")
        page = page[:start] + page[end:]
        mode, sub = " open", "No password needed. Sign in to see today's list."
    else:
        mode, sub = "", "Use the team password you were given."
    return (page.replace("{{error_class}}", " has-error" if error else "")
                .replace("{{mode_class}}", mode)
                .replace("{{sub}}", sub)
                .replace("{{error}}", html.escape(error))
                .replace("{{next}}", html.escape(next_path, quote=True))).encode()


STATE = None


class Handler(BaseHTTPRequestHandler):
    def _client_ip(self):
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1"):                       # behind nginx on the same machine
            fwd = self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For", "").split(",")[-1]
            ip = fwd.strip() or ip
        return ip

    def _cookie(self):
        try:
            c = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return c[COOKIE].value if COOKIE in c else ""

    def _auth_ok(self):
        pw = os.environ.get("APP_PASSWORD")
        if not pw and not open_sign_in():
            return True                                       # running locally: no sign-in at all
        if session_ok(session_key(), self._cookie()):
            return True
        h = self.headers.get("Authorization", "")
        if pw and h.startswith("Basic "):
            try:
                return password_ok(pw, base64.b64decode(h[6:]).decode().split(":", 1)[1])
            except Exception:
                return False
        return False

    def _send(self, code, body, ctype="application/json", cookie=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if ctype.startswith("text/html"):
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _session_cookie(self, value, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
        return f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def _gate(self):
        """Signed in, or: pages go to the sign-in page, API calls get a 401 (no browser pop-up)."""
        if self._auth_ok():
            return True
        if self.path.startswith("/api/"):
            self._send(401, {"error": "signed out", "sign_in": "/login"})
        else:
            self._redirect("/login?next=" + quote(self.path, safe=""))
        return False

    def _login(self):
        pw = os.environ.get("APP_PASSWORD", "")
        n = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
        form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        nxt = safe_next(form.get("next", ["/"])[0])
        signed_in = lambda: self._redirect(nxt, self._session_cookie(make_session(session_key()), SESSION_DAYS * 86400))
        if open_sign_in() or not pw:
            return signed_in()                                # no password to check
        ip = self._client_ip()
        with _lock:
            blocked = too_many_fails(ip)
        html_type = "text/html; charset=utf-8"
        if blocked:
            return self._send(429, login_page("Too many wrong tries. Wait 10 minutes, then try again.", nxt), html_type)
        if password_ok(pw, form.get("password", [""])[0]):
            return signed_in()
        with _lock:
            note_fail(ip)
        time.sleep(0.6)                                       # slows down guessing
        self._send(401, login_page("That password didn't work. Check it and try again.", nxt), html_type)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/healthz":
            return self._send(200, {"ok": True})
        if path == "/login":
            nxt = safe_next(parse_qs(query).get("next", ["/"])[0])
            if self._auth_ok():
                return self._redirect(nxt)
            return self._send(200, login_page("", nxt), "text/html; charset=utf-8")
        if path == "/logout":
            return self._redirect("/login", self._session_cookie("", 0))
        if not self._gate():
            return
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if path == "/":
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/board":
            return self._send(200, STATE.board(params.get("rep") or None, parse_rate(params.get("rate"))))
        if path == "/api/marks":
            return self._send(200, STATE.marks())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.partition("?")[0] == "/login":
            return self._login()
        if not self._gate():
            return
        if self.path != "/api/mark":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(200, STATE.set_mark(body))
        except (ValueError, KeyError) as e:
            self._send(400, {"error": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    global STATE
    STATE = State()
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"sold-outs tool on http://{host}:{port}  (sandbox: {'on' if sandbox.available() else 'off, demo data'})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
