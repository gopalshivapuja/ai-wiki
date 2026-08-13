"""HTTP client for the deployed wiki.

The CLI talks to the running app rather than the database, so it needs no direct database
access and cannot corrupt anything the API would have refused.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_TIMEOUT = 300


class WikiError(RuntimeError):
    """Something the user needs to read, not a stack trace."""


class Wiki:
    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = (url or os.environ.get("WIKI_URL", "http://localhost:8000")).rstrip("/")
        self.token = token or os.environ.get("WIKI_TOKEN", "")
        if not self.token:
            raise WikiError(
                "No token. Set WIKI_TOKEN, or pass --token. Get one with:\n"
                f"  curl -X POST {self.url}/api/auth/login -H 'Content-Type: application/json' "
                '-d \'{"email":"you@example.com","password":"..."}\''
            )

    def _request(self, method: str, path: str, *, params=None, body=None, timeout=DEFAULT_TIMEOUT):
        url = f"{self.url}/api{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:400]
            if exc.code == 401:
                raise WikiError("The wiki rejected the token (401). It may have expired.") from exc
            if exc.code == 403:
                raise WikiError(f"Refused (403): {detail}") from exc
            raise WikiError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise WikiError(f"Could not reach {self.url}: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode()

    def get(self, path: str, **params):
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict | None = None):
        return self._request("POST", path, body=body or {})

    def upload(self, path: str, file: Path, fields: dict[str, str] | None = None):
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for key, value in (fields or {}).items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{file.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
        )
        parts.append(file.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            f"{self.url}/api{path}",
            data=b"".join(parts),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise WikiError(f"Upload failed: HTTP {exc.code}: {exc.read().decode()[:300]}") from exc

    # --- queue ---------------------------------------------------------------

    def queue_depth(self) -> int:
        """How much work is outstanding across the whole queue, not one page.

        The listing used to return only its newest page, and a cleanup that trusted it
        cancelled a third of a 195-job queue and reported it empty.
        """
        return self.get("/jobs", limit=1).get("active", 0)

    def wait_for_queue(self, on_tick=None, poll: int = 15, timeout: int = 24 * 3600) -> None:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            depth = self.queue_depth()
            if on_tick:
                on_tick(depth)
            if depth == 0:
                return
            time.sleep(poll)
        raise WikiError("Timed out waiting for the queue to drain")

    def wait_for_job(self, job_id: int, poll: int = 3, timeout: int = 1800) -> dict:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get(f"/jobs/{job_id}")
            if job["status"] in ("done", "failed", "cancelled"):
                return job
            time.sleep(poll)
        raise WikiError(f"Job {job_id} did not finish in {timeout}s")
