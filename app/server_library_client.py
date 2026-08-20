"""HTTP client for the server-owned Juweier music library.

The Windows desktop application must never interpret the server's ``G:`` path
as a local drive.  It only receives catalog metadata and audio streams through
the API exposed by ``server/mobile_api.py``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_SERVER_URL = "https://api.db0888.com"


class ServerLibraryError(RuntimeError):
    pass


class ServerLibraryClient:
    def __init__(self, base_url: str, token: str = "", timeout: int = 30):
        self.base_url = (base_url or DEFAULT_SERVER_URL).strip().rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        if not self.base_url.startswith(("http://", "https://")):
            raise ServerLibraryError("AI 服务器地址必须以 http:// 或 https:// 开头")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json", "User-Agent": "Juweier-Music/3.2.5"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            raise ServerLibraryError(str(detail)) from exc
        except Exception as exc:
            raise ServerLibraryError(f"无法连接服务器：{exc}") from exc

    def health(self) -> dict:
        return self._request("GET", "/health")

    def scan(self) -> dict:
        return self._request("POST", "/api/v1/library/scan")

    def import_link(self, url: str) -> dict:
        return self._request("POST", "/api/v1/library/import-url", {"url": url})

    def songs(self, query: str = "", category: str = "全部") -> dict:
        path = "/api/v1/library?" + urllib.parse.urlencode({
            "q": query, "category": category, "limit": 100000,
        })
        return self._request("GET", path)

    def queue_processing(
        self, track_id: int, arrangement_mode: str = "乐队现场版",
        transpose: int = 0, output: str = "wav_mp3",
    ) -> dict:
        return self._request(
            "POST", f"/api/v1/library/{int(track_id)}/process",
            {"arrangement_mode": arrangement_mode, "transpose": transpose, "output": output},
        )

    def job(self, job_id: str) -> dict:
        safe_id = urllib.parse.quote(str(job_id), safe="")
        return self._request("GET", f"/api/v1/jobs/{safe_id}")

    def download(self, url: str, destination: Path) -> Path:
        absolute = urllib.parse.urljoin(self.base_url + "/", url)
        headers = {"Accept": "*/*", "User-Agent": "Juweier-Music/3.2.5"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(absolute, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=max(60, self.timeout)) as response, part.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
            part.replace(destination)
            return destination
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise ServerLibraryError(f"服务器歌曲下载失败：{exc}") from exc


def load_desktop_server_config(config_file: Path) -> dict:
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {
        "server": str(data.get("server") or DEFAULT_SERVER_URL).strip().rstrip("/"),
        "token": str(data.get("token") or "").strip(),
    }
