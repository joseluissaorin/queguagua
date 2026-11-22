"""AlsaClient: a plain httpx client for www.alsa.es, the way its own pages talk to it.

ALSA's website is a Liferay portal. Pages are server-rendered and embed their state; the interactive parts
call *portlet resources* (`p_p_lifecycle=2`, JSON in and out) and *portlet actions* (`p_p_lifecycle=1`,
which need Liferay's CSRF token `p_auth` and return a new page). The purchase keeps its cart in the server
session (JSESSIONID), so a booking is a sequence of calls on one cookie jar.

In front of it sit Imperva/Incapsula and a queue-it "KnownUser" check. When no queue is active, queue-it
answers any request without its cookie (or with one that expired, ~20 min) with a redirect to
alsa.queue-it.net that immediately bounces back with a `queueittoken`; we follow that bounce and resend
the original request. A real waiting room, a challenge page, 403 or 429 stop the command (BlockedError):
the CLI never tries to get past them.

Cookies and the last `p_auth` are kept in the cache dir (`session.json`, mode 0600) so a logged-in Alsa
Plus session survives between commands. Since the search and the cart live in that server session, one
command uses it at a time (`session.lock`): a search run in the middle of a purchase would replace the
cart under it. Nothing here logs or echoes cookies, passwords or bodies.
"""

import contextlib
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from . import cachefile, config, pageparams
from .errors import AlsaError, ApiShapeError, BlockedError, MaintenanceError, UpstreamError

try:
    import fcntl
except ImportError:  # Windows: no lock
    fcntl = None

_QUEUE_HOST = "queue-it.net"
_CHALLENGE = re.compile(r"_Incapsula_Resource|Incapsula incident ID|Request unsuccessful\. Incapsula", re.I)
_MAINTENANCE = re.compile(r"estamos realizando mejoras en nuestro sistema", re.I)
_RETRYABLE = {500, 502, 503, 504}
_MAX_TRIES = 3


def _is_html(resp: httpx.Response) -> bool:
    return "html" in resp.headers.get("content-type", "").lower()


class AlsaClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, persist: bool = True,
                 timeout: float = config.TIMEOUT):
        self.persist = persist
        self.retries: list[dict] = []
        self._p_auth: str | None = None
        self._lock_fd: int | None = None
        self.http = httpx.Client(
            http2=transport is None,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        if persist:
            self._lock()
            self._load()

    # ---- lifecycle -----------------------------------------------------------------------------------

    def __enter__(self) -> "AlsaClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.persist:
            self.save()
        self.http.close()
        self._unlock()

    def _lock(self) -> None:
        if fcntl is None:
            return
        path = config.cache_dir() / "session.lock"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return  # no cache dir: nothing is shared either
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("alsa: another queguagua command is using the ALSA session; waiting for it to finish.",
                  file=sys.stderr)
            fcntl.flock(fd, fcntl.LOCK_EX)
        self._lock_fd = fd

    def _unlock(self) -> None:
        if self._lock_fd is None:
            return
        with contextlib.suppress(OSError):
            os.close(self._lock_fd)  # closing the descriptor releases the lock
        self._lock_fd = None

    @property
    def _session_path(self):
        return config.cache_dir() / "session.json"

    def _load(self) -> None:
        data = cachefile.read_json(self._session_path)
        if not isinstance(data, dict):
            return
        now = time.time()
        for c in data.get("cookies", []):
            try:
                if c.get("expires") and c["expires"] < now:
                    continue
                self.http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
            except (KeyError, TypeError):
                continue
        tok = data.get("p_auth")
        if isinstance(tok, str) and re.fullmatch(r"[A-Za-z0-9]{4,32}", tok):
            self._p_auth = tok

    def save(self) -> None:
        cookies = []
        for c in self.http.cookies.jar:
            cookies.append({"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                            "expires": c.expires})
        cachefile.write_json(self._session_path, {"saved_at": time.time(), "p_auth": self._p_auth,
                                                  "cookies": cookies})

    def forget_session(self) -> None:
        """Drop every cookie (logout, or a session ALSA no longer accepts)."""
        self.http.cookies.clear()
        self._p_auth = None
        cachefile.remove(self._session_path)

    def cookies_for_browser(self) -> list[dict]:
        """The jar in Playwright's add_cookies() shape, to hand a checkout over to a browser."""
        out = []
        for c in self.http.cookies.jar:
            item = {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/",
                    "secure": True, "httpOnly": False, "sameSite": "Lax"}
            if c.expires:
                item["expires"] = float(c.expires)
            out.append(item)
        return out

    # ---- low level -----------------------------------------------------------------------------------

    def _note_retry(self, what: str, tries: int, errors: list[str], recovered: bool) -> None:
        self.retries.append({"request": what, "tries": tries, "errors": errors, "recovered": recovered})

    def _pass_queue(self, location: str) -> None:
        """Follow queue-it's bounce. With no queue active it returns straight to www.alsa.es."""
        try:
            r = self.http.get(location, follow_redirects=True, headers={"Accept": "text/html"})
        except httpx.HTTPError as exc:
            raise UpstreamError(f"queue-it didn't answer ({type(exc).__name__})") from None
        host = urlsplit(str(r.url)).hostname or ""
        if _QUEUE_HOST in host:
            raise BlockedError("ALSA has a queue-it waiting room active right now; try again later",
                               details={"waiting_room": True})
        self._check_block(r)
        self._absorb(r)

    def _check_block(self, r: httpx.Response) -> None:
        if _is_html(r) and _MAINTENANCE.search(r.text[:3000]):
            raise MaintenanceError("ALSA is down for maintenance (\"estamos realizando mejoras en nuestro sistema\")",
                                   status=r.status_code)
        if r.status_code in (403, 429):
            raise BlockedError(f"ALSA refused the request ({r.status_code})", status=r.status_code)
        if _is_html(r) and r.status_code >= 400 and _CHALLENGE.search(r.text[:5000]):
            raise BlockedError("Imperva/Incapsula bot protection answered instead of ALSA", status=r.status_code)
        if _is_html(r) and len(r.content) < 4000 and _CHALLENGE.search(r.text):
            raise BlockedError("Imperva/Incapsula bot protection answered instead of ALSA", status=r.status_code)

    def _absorb(self, r: httpx.Response) -> None:
        """Remember the CSRF token from any HTML page we get."""
        if _is_html(r) and r.status_code == 200:
            tok = pageparams.auth_token(r.text)
            if tok:
                self._p_auth = tok

    def send(self, method: str, url: str, *, what: str, retry: bool | None = None, **kw: Any) -> httpx.Response:
        """One request with queue-it handling, same-site redirects followed (GET), block detection and up to
        3 tries for a 5xx or dropped connection (only when `retry`, default: GET only)."""
        if retry is None:
            retry = method.upper() == "GET"
        errors: list[str] = []
        tries = 0
        queue_passes = 0
        while True:
            tries += 1
            try:
                r = self.http.request(method, url, **kw)
                hops = 0
                while r.is_redirect and hops < 8:
                    loc = r.headers.get("location", "")
                    target = str(r.url.join(loc))
                    host = urlsplit(target).hostname or ""
                    if _QUEUE_HOST in host:
                        if queue_passes >= 2:
                            raise BlockedError("queue-it keeps redirecting; ALSA may have a waiting room")
                        queue_passes += 1
                        self._pass_queue(target)
                        r = self.http.request(method, url, **kw)  # resend the original request
                        hops = 0
                        continue
                    if host.endswith("alsa.es") or not host:
                        r = self.http.get(target, headers={"Accept": kw.get("headers", {}).get("Accept", "*/*")})
                        hops += 1
                        continue
                    break  # an off-site redirect (payment gateway): the caller handles it
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as exc:
                errors.append(f"connection dropped ({type(exc).__name__})")
                if retry and tries < _MAX_TRIES:
                    time.sleep(tries)
                    continue
                if len(errors) > 1:
                    self._note_retry(what, tries, errors, False)
                raise UpstreamError(f"couldn't reach ALSA for {what} ({type(exc).__name__})") from None
            except httpx.TimeoutException:
                raise UpstreamError(f"ALSA didn't answer {what} in time") from None
            if r.status_code in _RETRYABLE and not (_is_html(r) and _CHALLENGE.search(r.text[:5000])):
                errors.append(f"server error ({r.status_code})")
                if retry and tries < _MAX_TRIES:
                    time.sleep(tries)
                    continue
                if len(errors) > 1:
                    self._note_retry(what, tries, errors, False)
                raise UpstreamError(f"ALSA failed {what} ({r.status_code})", status=r.status_code)
            self._check_block(r)
            if errors:
                self._note_retry(what, tries, errors, True)
            self._absorb(r)
            return r

    # ---- Liferay helpers -----------------------------------------------------------------------------

    def page(self, path: str = "/", params: dict | None = None, *, what: str = "page") -> httpx.Response:
        url = config.BASE + path
        r = self.send("GET", url, params=params, what=what, headers={"Accept": "text/html,application/xhtml+xml"})
        if r.is_redirect:  # Imperva/queue-it sometimes need one more round on a brand-new cookie jar
            time.sleep(1)
            r = self.send("GET", url, params=params, what=what, headers={"Accept": "text/html,application/xhtml+xml"})
        if r.status_code != 200:
            raise ApiShapeError(f"unexpected status for {what}", status=r.status_code)
        return r

    def p_auth(self, *, fresh: bool = False) -> str:
        if fresh or not self._p_auth:
            r = self.page("/", what="home page")
            if not pageparams.auth_token(r.text):
                raise ApiShapeError("no Liferay auth token on ALSA's home page")
        return self._p_auth  # type: ignore[return-value]

    @staticmethod
    def resource_url(path: str, portlet: str, resource_id: str, params: dict | None = None) -> str:
        q = {"p_p_id": portlet, "p_p_lifecycle": "2", "p_p_state": "normal", "p_p_mode": "view",
             "p_p_resource_id": resource_id, "p_p_cacheability": "cacheLevelPage"}
        if params:
            q.update({k: v for k, v in params.items() if v is not None})
        return f"{config.BASE}{path}?{urlencode(q)}"

    def resource(self, path: str, portlet: str, resource_id: str, *, params: dict | None = None,
                 json_body: Any = None, form: dict | None = None, method: str | None = None,
                 retry: bool | None = None, url: str | None = None) -> httpx.Response:
        """Call a portlet resource. `url` overrides the built URL (pages hand out ready-made ones)."""
        target = url or self.resource_url(path, portlet, resource_id, params)
        if url and params:
            target += ("&" if "?" in target else "?") + urlencode(params)
        headers = {"Accept": "application/json, text/plain, */*", "Origin": config.BASE,
                   "Referer": config.BASE + path}
        kw: dict[str, Any] = {"headers": headers}
        if json_body is not None:
            kw["content"] = json.dumps(json_body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
            method = method or "POST"
        elif form is not None:
            kw["data"] = form
            method = method or "POST"
        return self.send(method or "GET", target, what=resource_id, retry=retry, **kw)

    def resource_json(self, *args: Any, **kw: Any) -> Any:
        r = self.resource(*args, **kw)
        rid = args[2] if len(args) > 2 else kw.get("resource_id", "resource")
        if r.status_code != 200:
            raise ApiShapeError(f"{rid} answered {r.status_code}", status=r.status_code)
        try:
            return r.json()
        except ValueError:
            if _is_html(r):
                raise BlockedError(f"{rid} returned an HTML page instead of JSON") from None
            raise ApiShapeError(f"{rid} didn't return JSON") from None

    def action(self, path: str, portlet: str, action: str, *, params: dict | None = None,
               form: dict | None = None, method: str = "GET", retry: bool | None = None) -> httpx.Response:
        """Run a portlet action (needs p_auth) and return the page it renders."""
        q = {"p_p_id": portlet, "p_p_lifecycle": "1", "p_p_state": "normal", "p_p_mode": "view",
             f"_{portlet}_javax.portlet.action": action, "p_auth": self.p_auth()}
        if params:
            q.update({k: v for k, v in params.items() if v is not None})
        headers = {"Accept": "text/html,application/xhtml+xml", "Origin": config.BASE,
                   "Referer": config.BASE + path}
        kw: dict[str, Any] = {"headers": headers, "params": q}
        if form is not None:
            kw["data"] = form
        r = self.send(method, config.BASE + path, what=action, retry=retry, **kw)
        if r.status_code != 200 and not r.is_redirect:
            raise ApiShapeError(f"{action} answered {r.status_code}", status=r.status_code)
        return r


def raise_for_alsa(payload: Any, what: str, exc: type[AlsaError]) -> None:
    """Many resources answer 200 with {"status": "error", "errorMessage": ...} or {"error": true, ...}."""
    if not isinstance(payload, dict):
        return
    if payload.get("status") == "error" or payload.get("error") is True:
        msg = payload.get("errorMessage") or payload.get("message") or None
        raise exc(f"ALSA refused {what}", alsa_message=(msg or "")[:300] or None)
