"""Tiny client for the Groupon UK sandbox API. Key from SANDBOX_KEY (env or .env), never logged."""
import json
import os
import time
import urllib.error
import urllib.request

from soldouts import config

config.load_env_file()
BASE = os.environ.get("SANDBOX_BASE", "https://desk-production-6adc.up.railway.app/api/sandbox/v1")


class SandboxError(Exception):
    pass


def available():
    return bool(os.environ.get("SANDBOX_KEY"))


def request(method, path, body=None, params=None, retries=3):
    url = BASE + path
    if params:
        url += "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v is not None)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {os.environ.get('SANDBOX_KEY', '')}", "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(1.2)
                continue
            raise SandboxError(f"{method} {path}: HTTP {e.code} {e.read()[:200].decode(errors='replace')}")
        except urllib.error.URLError as e:
            raise SandboxError(f"{method} {path}: {e.reason}")


def get_all(path, **params):
    out, cursor = [], None
    while True:
        page = request("GET", path, params={**params, "limit": 1000, "cursor": cursor})
        out += page["data"]
        cursor = page.get("next_cursor")
        if not cursor:
            return out


def soldouts_today():
    return get_all("/soldouts/today")


def marks():
    if not available():
        return {}
    r = request("GET", "/marks")
    rows = r.get("data", []) if isinstance(r, dict) else (r or [])
    return {m["merchant_id"]: m for m in rows if m.get("merchant_id")}


def set_mark(merchant_id, mark, reason, marked_by):
    return request("PUT", f"/merchants/{merchant_id}/mark", {"mark": mark, "reason": reason, "marked_by": marked_by})


def me():
    return request("GET", "/me")
