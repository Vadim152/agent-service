from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

from opencode_adapter_app.config import AdapterSettings


class OpenCodeServerError(RuntimeError):
    pass


class OpenCodeHeadlessServer:
    def __init__(self, *, settings: AdapterSettings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._stdout_handle = None
        self._stderr_handle = None

    @property
    def base_url(self) -> str:
        return f"http://{self._settings.server_host}:{self._settings.server_port}"

    def ensure_started(self) -> str:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self._is_ready():
                return self.base_url
            self._stop_locked()
            self._start_locked()
            return self.base_url

    def shutdown(self) -> None:
        with self._lock:
            self._stop_locked()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> Any:
        self.ensure_started()
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_payload,
                timeout=timeout_s,
            )
            response.raise_for_status()
        except Exception as exc:
            raise OpenCodeServerError(f"OpenCode server request failed: {exc}") from exc
        if not response.content:
            return {}
        return response.json()

    def stream_events(
        self,
        *,
        directory: str,
        stop_event: threading.Event,
    ) -> Iterator[dict[str, Any]]:
        self.ensure_started()
        timeout = httpx.Timeout(connect=5.0, read=1.0, write=5.0, pool=5.0)
        while not stop_event.is_set():
            try:
                with httpx.stream(
                    "GET",
                    f"{self.base_url}/event",
                    params={"directory": directory},
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()
                    buffer: list[str] = []
                    for raw_line in response.iter_lines():
                        if stop_event.is_set():
                            return
                        line = raw_line.strip()
                        if not line:
                            payload = _decode_sse_chunk(buffer)
                            buffer = []
                            if payload is not None:
                                yield payload
                            continue
                        buffer.append(line)
                    payload = _decode_sse_chunk(buffer)
                    if payload is not None:
                        yield payload
            except httpx.ReadTimeout:
                continue
            except Exception as exc:
                if not stop_event.is_set():
                    raise OpenCodeServerError(f"OpenCode event stream failed: {exc}") from exc

    def _is_ready(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/config", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    def _start_locked(self) -> None:
        log_dir = self._settings.work_root
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "opencode-serve.stdout.log"
        stderr_path = log_dir / "opencode-serve.stderr.log"
        self._stdout_handle = stdout_path.open("a", encoding="utf-8")
        self._stderr_handle = stderr_path.open("a", encoding="utf-8")
        command = [
            self._settings.binary,
            *self._settings.binary_args,
            "serve",
            "--hostname",
            self._settings.server_host,
            "--port",
            str(self._settings.server_port),
        ]
        if self._settings.print_logs:
            command.append("--print-logs")
        env = self._settings.build_child_env()
        self._process = subprocess.Popen(
            command,
            cwd=str(self._settings.work_root.parent),
            stdin=subprocess.DEVNULL,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        deadline = time.time() + max(5.0, self._settings.run_start_timeout_ms / 1000.0)
        while time.time() < deadline:
            if self._process.poll() is not None:
                raise OpenCodeServerError("OpenCode headless server exited before becoming ready")
            if self._is_ready():
                return
            time.sleep(0.2)
        raise OpenCodeServerError("OpenCode headless server did not become ready in time")

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            deadline = time.time() + (self._settings.graceful_kill_timeout_ms / 1000.0)
            while time.time() < deadline and process.poll() is None:
                time.sleep(0.05)
            if process.poll() is None:
                process.kill()
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)


def _decode_sse_chunk(lines: list[str]) -> dict[str, Any] | None:
    if not lines:
        return None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    raw = "\n".join(data_lines).strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
