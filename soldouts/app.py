"""The rep tool: today's sold-outs, what to do about each and why, and a way to mark a merchant.

    python3 -m soldouts.app            # http://localhost:8080
    PORT=8090 APP_PASSWORD=... python3 -m soldouts.app

Sold-outs come from the sandbox (GET /soldouts/today) when SANDBOX_KEY is set; otherwise from
routing/input/todays_soldouts.csv and the page says "demo data". Marks go to the sandbox
(PUT /merchants/{id}/mark) and are also kept in data/marks_local.json so the page works offline.
"""
import base64
import csv
import json
import os
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
            return {r["rep_id"]: r for r in csv.DictReader(open(p, newline=""))}
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


STATE = None


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        pw = os.environ.get("APP_PASSWORD")
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                return base64.b64decode(h[6:]).decode().split(":", 1)[1] == pw
            except Exception:
                return False
        return False

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _gate(self):
        if self._auth_ok():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="sold-outs"')
        self.end_headers()
        return False

    def do_GET(self):
        if not self._gate():
            return
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if path == "/":
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/board":
            try:
                rate = float(params["rate"]) if params.get("rate") else None
                rate = None if rate is None else min(max(rate, 0.0), 500.0)
            except ValueError:
                rate = None
            return self._send(200, STATE.board(params.get("rep") or None, rate))
        if path == "/api/marks":
            return self._send(200, STATE.marks())
        if path == "/healthz":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
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
