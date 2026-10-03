"""Offline Chromium UI smoke against the actual ASGI application via TestClient.

Requires playwright and an installed browser; not part of zero-network unit tests.
This verifies Mock DOM/control behavior, not microphone, TTS or physical devices.
"""
import json
import shutil
import base64
import re
import sys
from uuid import uuid4
from fastapi.testclient import TestClient
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/verification"
sys.path.insert(0, str(ROOT / "apps/api/src"))
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app


def module_url(path: Path) -> str:
    """Resolve this small local ES-module graph into data URLs; never fetch network."""
    source = path.read_text()
    source = re.sub(r"from ['\"](\.[^'\"]+)['\"]", lambda match:
                    "from '" + module_url((path.parent / match[1]).resolve()) + "'", source)
    return "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()


MAIN_URL = module_url(ROOT / "apps/web/dist/app/main.js")
HTML = (ROOT / "apps/web/index.html").read_text()
HTML = HTML.replace('<link rel="stylesheet" href="/assets/app.css">',
                    '<style>' + (ROOT / "apps/web/public/app.css").read_text() + '</style>')
HTML = HTML.replace('<script type="module" src="/dist/app/main.js"></script>', '')


def mount(page, client) -> None:
    def asgi_request(path, method, headers, body):
        response = client.request(method, path, headers=headers, content=body)
        return {"status": response.status_code, "body": response.text}
    page.expose_function("__miraAsgi", asgi_request)
    page.set_content(HTML)
    page.evaluate("""() => {
      // Only the test harness replaces fetch; production source is unchanged.
      window.fetch = async (path, init = {}) => {
        const r = await window.__miraAsgi(path, init.method || 'GET', init.headers || {}, init.body || null);
        return new Response(r.status === 204 ? null : r.body, {status: r.status, headers: {'Content-Type':'application/json'}});
      };
      if (!crypto.randomUUID) Object.defineProperty(crypto, 'randomUUID', {value: () =>
        '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
          (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c)/4).toString(16))});
    }""")
    page.evaluate("url => { import(url).catch(error => { throw error; }); }", MAIN_URL)

checks: list[str] = []

with TestClient(create_app(Settings())) as client, sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=shutil.which("chromium"), args=["--no-sandbox"])
    desktop = browser.new_context(viewport={"width": 1280, "height": 1100})
    page = desktop.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    mount(page, client)
    expect(page.locator("fieldset")).to_be_enabled()
    assert page.locator("[data-status]").inner_text() == "idle"
    checks.append("browser starts in truthful Mock mode")

    page.get_by_role("button", name="看照片", exact=True).click()
    expect(page.locator("[data-photo]")).to_be_visible()
    page.get_by_role("button", name="停止回应", exact=True).click()
    expect(page.locator("[data-status]")).to_have_text("stopped")
    page.wait_for_timeout(1100)
    expect(page.locator("[data-photo]")).to_be_visible()
    assert "还没有接入真实素材" not in page.locator("[data-subtitle]").inner_text()
    checks.append("stop retains already displayed mock media and rejects pending caption")

    page.get_by_role("button", name="听雨", exact=True).click()
    expect(page.locator("[data-stage]")).to_have_attribute("data-scene", "rain_window")
    expect(page.locator("[data-status]")).to_have_text("idle")
    checks.append("new explicit request works after stop without an extra unlock click")

    page.get_by_role("button", name="注入生成失败", exact=True).click()
    expect(page.locator("[data-status]")).to_have_text("error")
    expect(page.locator("[data-error]")).to_have_text("generation_failed")
    checks.append("synthetic provider failure remains failure, not quiet success")

    page.get_by_role("button", name="不要拍我", exact=True).click()
    expect(page.locator("[data-pose]")).to_contain_text("相机已放低")
    expect(page.locator("[data-status]")).to_have_text("idle")
    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    checks.append("desktop no page errors or horizontal overflow")
    page.screenshot(path=str(OUTPUT / "previews/desktop.png"), full_page=True)

    mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                                 device_scale_factor=1)
    phone = mobile.new_page()
    mount(phone, client)
    expect(phone.locator("fieldset")).to_be_enabled()
    assert phone.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    phone.get_by_role("button", name="看照片", exact=True).click()
    phone.get_by_role("button", name="停止回应", exact=True).click()
    expect(phone.locator("[data-status]")).to_have_text("stopped")
    phone.wait_for_timeout(1100)
    expect(phone.locator("[data-photo]")).to_be_hidden()
    checks.append("mobile immediate stop prevents not-yet-displayed media")
    phone.screenshot(path=str(OUTPUT / "previews/mobile.png"), full_page=True)

    page.get_by_role("button", name="释放会话", exact=True).click()
    expect(page.locator("[data-status]")).to_have_text("closed · 刷新可新建")
    checks.append("explicit close releases local session")
    browser.close()

report = {"status": "passed", "checks": checks, "scope": "offline Chromium UI + actual ASGI TestClient; browser localhost navigation is blocked by environment policy",
          "not_tested": ["direct browser networking", "real device", "Safari", "microphone", "audio", "live providers"]}
(OUTPUT / "browser-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
