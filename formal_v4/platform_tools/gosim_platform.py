#!/usr/bin/env python3
"""Read-only client for the GOSIM survey26 platform (Supabase backend). Standard library only.

The website (https://create.gosim.org/survey26/platform) is a static Vue app that talks to one Supabase
project: GoTrue auth, PostgREST (tables + RPCs), Storage, and the edge function `observer-portal`
(the competition workspace). This module sends the same read requests the website sends.

Environment:
  GOSIM_EMAIL, GOSIM_PASSWORD   account credentials (never written anywhere by this module)
  GOSIM_PROXY                   HTTP proxy for every request; default http://127.0.0.1:7890
                                ("none" or "" = direct; *.supabase.co is not reachable directly from this host)
  GOSIM_SESSION_FILE            optional path of a 0600 JSON session cache (access/refresh token); unset = no cache
  GOSIM_SUPABASE_URL, GOSIM_ANON_KEY   override the public project URL / anon key

SAFETY: only an explicit allowlist of read-only RPCs and portal actions can be called. Uploading, preparing,
confirming ("approve"), evaluating, withdrawing, final-version selection, evidence, team variables/egress,
key claims and every other write are refused locally before any request is sent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SUPABASE_URL = os.environ.get("GOSIM_SUPABASE_URL", "https://vdiemcofukuxglqsmlyz.supabase.co").rstrip("/")
# Public anon key, embedded in the site's JS bundle (assets/supabase-*.js) and in the starter kit.
ANON_KEY = os.environ.get("GOSIM_ANON_KEY") or (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZkaWVtY29mdWt1eGdscXNtbHl6Iiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3ODg5NTU3OTcsImV4cCI6MjEwNDUzMTc5N30.qMbZ_C3iKq70SdGDYQPPUD0LMBst-xBspZ-zj_gn75w")
DEFAULT_PROXY = "http://127.0.0.1:7890"

# Read-only RPCs (PostgREST /rest/v1/rpc/<name>), all called by the website or the official CLI to display data.
READ_RPCS = frozenset({
    "me", "current_competition", "my_observer_phase", "team_members", "team_capacity",
    "observer_evaluation_quota", "observer_final_versions", "observer_quota_reset_notice",
    "observer_board", "observer_card_board", "leaderboard", "queue_position", "sophon_solvers",
})
# Read-only observer-portal actions. NOT allowed (writes / quota): upload, submit_zip, submit_repository, approve,
# evaluate, set_final_version, withdraw, evidence, save_*/delete_*/set_* (team variables, domains, egress, model),
# personal_model, local_access, accept_csv, disable_provider.
READ_PORTAL = frozenset({"list", "diagnostics", "agent_log", "download_result"})
# Read-only tables (GET /rest/v1/<table>).
READ_TABLES = frozenset({"phases", "scenarios", "observer_phase_settings", "phase_scenarios", "teams", "announcements",
                         "observer_batches", "observer_runs", "observer_projects", "observer_revisions"})


class PlatformError(RuntimeError):
    def __init__(self, status: int, message: str, path: str = ""):
        super().__init__(f"HTTP {status} {path}: {message}")
        self.status, self.message, self.path = status, message, path


def _jwt_claims(token: str) -> dict:
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Client:
    def __init__(self, url: str = SUPABASE_URL, key: str = ANON_KEY, proxy: str | None = None, timeout: float = 90.0,
                 retries: int = 3):
        self.url, self.key, self.timeout, self.retries = url.rstrip("/"), key, timeout, retries
        proxy = os.environ.get("GOSIM_PROXY", DEFAULT_PROXY) if proxy is None else proxy
        self.proxy = None if proxy.strip().lower() in ("", "none", "direct") else proxy.strip()
        handler = urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy} if self.proxy else {})
        self.opener = urllib.request.build_opener(handler)
        self.session: dict | None = None
        self.session_file = Path(os.environ["GOSIM_SESSION_FILE"]) if os.environ.get("GOSIM_SESSION_FILE") else None

    # ------------------------------------------------------------------ transport
    def _send(self, method: str, url: str, *, body=None, data: bytes | None = None, headers: dict | None = None,
              auth: bool = True) -> tuple[int, dict, bytes]:
        hdrs = {"apikey": self.key, "Authorization": "Bearer " + (self.jwt if auth else self.key)} if url.startswith(self.url) else {}
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        last = None
        for attempt in range(self.retries):
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    return resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")
                msg = text
                try:
                    detail = json.loads(text)
                    if isinstance(detail, dict):
                        msg = (detail.get("message") or detail.get("msg") or detail.get("error_description")
                               or detail.get("error") or text)
                except Exception:
                    pass
                if exc.code in (502, 503, 504) and attempt + 1 < self.retries:
                    last = PlatformError(exc.code, str(msg)[:400], url.replace(self.url, ""))
                    time.sleep(2 * (attempt + 1))
                    continue
                raise PlatformError(exc.code, str(msg)[:400], url.replace(self.url, "").split("?token=")[0]) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"network failure for {url.split('?')[0]}: {last}")

    def _json(self, method: str, path: str, **kw):
        status, headers, raw = self._send(method, self.url + path, **kw)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    # ------------------------------------------------------------------ auth
    @property
    def jwt(self) -> str:
        if not self.session:
            raise RuntimeError("not logged in")
        return self.session["access_token"]

    def _store(self, res: dict) -> None:
        self.session = {"access_token": res["access_token"], "refresh_token": res.get("refresh_token"),
                        "expires_at": int(res.get("expires_at") or time.time() + int(res.get("expires_in", 3600)))}
        if self.session_file:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.session_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w") as fh:
                json.dump(self.session, fh)

    def login(self, email: str | None = None, password: str | None = None) -> dict:
        """Password grant (the website's sign-in), or a cached/refreshed session when GOSIM_SESSION_FILE is set."""
        if self.session_file and self.session_file.exists():
            try:
                cached = json.loads(self.session_file.read_text())
                if cached.get("expires_at", 0) - 120 > time.time():
                    self.session = cached
                    return self.identity()
                if cached.get("refresh_token"):
                    res = self._json("POST", "/auth/v1/token?grant_type=refresh_token",
                                     body={"refresh_token": cached["refresh_token"]}, auth=False)
                    self._store(res)
                    return self.identity()
            except Exception:
                pass
        email = email or os.environ.get("GOSIM_EMAIL")
        password = password or os.environ.get("GOSIM_PASSWORD")
        if not email or not password:
            raise SystemExit("set GOSIM_EMAIL and GOSIM_PASSWORD")
        res = self._json("POST", "/auth/v1/token?grant_type=password", body={"email": email, "password": password}, auth=False)
        self._store(res)
        return self.identity()

    def identity(self) -> dict:
        c = _jwt_claims(self.jwt)
        return {"user_id": c.get("sub"), "email": c.get("email"), "role": c.get("role"),
                "expires_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c.get("exp", 0)))}

    # ------------------------------------------------------------------ read-only API surface
    def rpc(self, name: str, **args):
        if name not in READ_RPCS:
            raise PermissionError(f"RPC {name!r} is not on the read-only allowlist")
        return self._json("POST", f"/rest/v1/rpc/{name}", body=args)

    def portal(self, action: str, **fields):
        if action not in READ_PORTAL:
            raise PermissionError(f"portal action {action!r} is not on the read-only allowlist")
        res = self._json("POST", "/functions/v1/observer-portal", body={"action": action, **fields})
        if isinstance(res, dict) and res.get("error"):
            raise PlatformError(400, str(res["error"]), "/functions/v1/observer-portal")
        return res.get("data") if isinstance(res, dict) else res

    def table(self, table: str, query: str = ""):
        if table not in READ_TABLES:
            raise PermissionError(f"table {table!r} is not on the read-only allowlist")
        return self._json("GET", f"/rest/v1/{table}" + (("?" + query) if query else ""))

    def storage_list(self, bucket: str, prefix: str, limit: int = 1000) -> list:
        # POST is the Storage API's list verb (same as supabase-js storage.list); it does not modify anything.
        return self._json("POST", f"/storage/v1/object/list/{bucket}",
                          body={"prefix": prefix, "limit": limit, "offset": 0, "sortBy": {"column": "name", "order": "asc"}}) or []

    def storage_download(self, bucket: str, path: str) -> bytes:
        _, _, raw = self._send("GET", f"{self.url}/storage/v1/object/{bucket}/{urllib.parse.quote(path)}")
        return raw

    def get_url(self, url: str) -> bytes:
        """GET a signed download URL returned by the portal (Supabase storage or GitHub artifact)."""
        if not url.startswith("https://"):
            raise ValueError("refusing non-https download URL")
        _, _, raw = self._send("GET", url, auth=False)
        return raw

    # ------------------------------------------------------------------ helpers
    def phases(self) -> list:
        return self.table("phases", "select=id,slug,name_en,name_zh,sort_order,starts_at,ends_at,is_active,leaderboard_mode,"
                                    "counts_for_final,observer_settings:observer_phase_settings(projects_enabled,daily_batches,"
                                    "sealed,repeat_runs)&order=sort_order") or []

    def scenario_names(self, ids) -> dict:
        ids = sorted({i for i in ids if i})
        out = {}
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            for row in self.table("scenarios", "select=id,slug,name&id=in.(" + ",".join(chunk) + ")") or []:
                out[row["id"]] = row
        return out


def utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def to_bjt(iso: str | None) -> str | None:
    """'2026-10-04T09:51:00+00:00' -> '2026-10-04 17:51:00 BJT' (UTC+8)."""
    if not iso:
        return None
    from datetime import datetime, timedelta, timezone
    try:
        text = iso.replace("Z", "+00:00")
        if "." in text:
            head, rest = text.split(".", 1)
            frac = "".join(ch for ch in rest if ch.isdigit())
            tz = rest[len(frac):]
            text = head + "." + (frac + "000000")[:6] + tz
        dt = datetime.fromisoformat(text)
        return (dt.astimezone(timezone(timedelta(hours=8)))).strftime("%Y-%m-%d %H:%M:%S BJT")
    except ValueError:
        return iso


if __name__ == "__main__":
    c = Client()
    print(json.dumps(c.login(), indent=2))
    me = c.rpc("me")
    team = (me or {}).get("team") or {}
    print(json.dumps({"team": {k: team.get(k) for k in ("id", "name")}, "competition": c.rpc("current_competition")}, indent=2))
    sys.exit(0)
