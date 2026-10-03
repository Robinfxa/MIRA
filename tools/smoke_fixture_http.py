"""Run the replay composition on loopback and exercise its existing HTTP contract."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code = f'''import uvicorn
from pathlib import Path
from mira.config.loader import load_settings
from mira.entrypoints.http.app import create_app
settings = load_settings(root=Path({str(ROOT)!r}), environ={{"MIRA_PROFILE":"replay"}},
    overrides={{"http":{{"port":{port},"allowed_origins":["http://127.0.0.1:{port}"]}}}})
uvicorn.run(create_app(settings), host="127.0.0.1", port={port}, log_level="error")
'''
    server = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{port}"

    def call(path, body=None, token=None, method=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Mira-Session-Token"] = token
        request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        with opener.open(request, timeout=2) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                _, health = call("/api/v1/health")
                break
            except URLError:
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Loopback service failed to become ready") from None
                time.sleep(0.02)
        assert health["mode"] == "mock" and not health["live_llm"]
        status, created = call("/api/v1/sessions", {"client_instance_id": str(uuid4())})
        assert status == 201
        token = created["session_token"]
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        request = {"request_id": str(uuid4()), "activity_seq": 1,
                   "presentation_cutoff": 0, "text": "local synthetic fixture"}
        status, _ = call(path + "/inputs", request, token)
        assert status == 202
        deadline = time.monotonic() + 2
        while True:
            _, state = call(path, token=token)
            if state["sealed"]:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert len(state["active_grants"]) == 2 and not state["presented_effects"]
        effect = state["active_grants"][0]
        _, state = call(path + "/receipts", {
            "effect_id": effect["id"], "digest": effect["digest"], "output_epoch": 1,
            "activity_seq": 1, "presentation_seq": 1}, token)
        assert len(state["presented_effects"]) == 1
        _, stopped = call(path + "/stop", {"activity_seq": 2, "presentation_cutoff": 1}, token)
        assert stopped["active_grants"] == [] and len(stopped["presented_effects"]) == 1
        _, duplicate = call(path + "/inputs", request, token)
        assert duplicate == stopped
        status, _ = call(path, token=token, method="DELETE")
        assert status == 204
        print("Loopback replay: health/create/input/grants/receipt/stop/duplicate/delete passed.")
        print("Synthetic fixture HTTP only; not microphone, browser or device validation.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
        stdout, stderr = server.communicate()
        if stdout:
            print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)


if __name__ == "__main__":
    main()
