"""Start our server on an ephemeral loopback port; exercise real HTTP, then stop.

No external provider, browser, credentials, or production service is involved.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/verification"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIRA_")}
    env.update(PYTHONPATH=str(ROOT / "apps/api/src"), MIRA_PROFILE="test",
               MIRA_HTTP__PORT=str(port), MIRA_PROVIDERS__MOCK_DELAY_MS="5")
    base = f"http://127.0.0.1:{port}"
    checks: list[str] = []
    with (OUTPUT / "local-http-server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "mira"], cwd=ROOT, env=env,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            def request(path, method="GET", body=None, token=None):
                data = None if body is None else json.dumps(body).encode()
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["X-Mira-Session-Token"] = token
                req = urllib.request.Request(base + path, method=method, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=2) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None

            deadline = time.monotonic() + 5
            while True:
                try:
                    assert request("/api/v1/health")["mode"] == "mock"
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.03)
            checks.append("factory starts a real loopback HTTP server")
            result = request("/api/v1/sessions", "POST", {"client_instance_id": str(uuid4())})
            token = result["session_token"]
            path = "/api/v1/sessions/" + result["session"]["session_id"]
            request(path + "/inputs", "POST", {"request_id": str(uuid4()), "activity_seq": 1,
                    "presentation_cutoff": 0, "text": "看照片"}, token)
            deadline = time.monotonic() + 3
            while True:
                state = request(path, token=token)
                if state["sealed"]:
                    break
                if time.monotonic() > deadline:
                    raise AssertionError("Mock failed to seal")
                time.sleep(.01)
            assert len(state["active_grants"]) == 2 and not state["presented_effects"]
            checks.append("two mock ranges granted but not assumed presented")
            first = state["active_grants"][0]
            receipt = {"effect_id": first["id"], "digest": first["digest"], "output_epoch": 1,
                       "activity_seq": 1, "presentation_seq": 1}
            request(path + "/receipts", "POST", receipt, token)
            state = request(path + "/stop", "POST", {"activity_seq": 2, "presentation_cutoff": 1}, token)
            assert state["phase"] == "stopped" and not state["active_grants"]
            assert len(state["presented_effects"]) == 1
            checks.append("stop clears future grants and preserves prior mock receipt")
            duplicate = request(path + "/receipts", "POST", receipt, token)
            assert duplicate["revision"] == state["revision"]
            checks.append("late duplicate receipt is idempotent")
            request(path + "/inputs", "POST", {"request_id": str(uuid4()), "activity_seq": 3,
                    "presentation_cutoff": 1, "text": "听雨"}, token)
            checks.append("new request accepted after explicit stop")
            request(path, "DELETE", token=token)
            checks.append("session release endpoint succeeds")
        finally:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)
    report = {"status": "passed", "checks": checks, "scope": "actual loopback HTTP; Mock only"}
    (OUTPUT / "local-http-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
