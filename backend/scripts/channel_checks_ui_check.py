"""Exercise the built channel-check UI with synthetic API responses, no vendor calls.

Start `npm run preview -- --host 127.0.0.1 --port 5186` in frontend first.
Requires the optional Playwright package and an installed Chromium browser.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def verify(base: str, executable: str | None, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    channel = {"id": 1, "name": "Chat-only demo", "provider": "openai", "base_url": "https://demo.test/v1",
               "api_key": "***", "key_count": 1, "models": ["model-a", "model-b"], "model_mapping": {},
               "price_multiplier": 1, "price_overrides": {}, "priority": 0, "weight": 1, "is_enabled": True}
    requested = []
    hold = False
    entered, release = asyncio.Event(), asyncio.Event()

    async def api(route):
        path = route.request.url.split("/api/", 1)[1].split("?", 1)[0]
        if path == "me":
            body = {"id": 1, "username": "demo-admin", "role": "platform_admin", "must_change_password": False}
        elif path == "channels":
            body = {"total": 1, "items": [channel]}
        elif path == "channels/health/status":
            body = {"1": {"healthy": True, "fail_count": 0, "disabled_at": None}}
        elif path == "channels/1/test":
            model = route.request.post_data_json["model"]
            requested.append(model)
            entered.set()
            if hold:
                await release.wait()
            checks = []
            for kind in ("models", "chat", "chat_stream", "responses", "responses_stream"):
                passed = not kind.startswith("responses")
                checks.append({"kind": kind, "status": "passed" if passed else "failed",
                               "status_code": 200 if passed else 404, "latency_ms": 125,
                               "first_text_ms": 48 if kind == "chat_stream" else None,
                               "error": "" if passed else "Responses endpoint is not available"})
            body = {"success": False, "model": model, "actual_model": model, "checks": checks}
        else:
            raise AssertionError(f"Unexpected API request: {path}")
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=executable, headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
            context.set_default_timeout(10000)
            await context.add_init_script("localStorage.setItem('token', 'synthetic-ui-token'); localStorage.setItem('locale', 'zh')")
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("**/api/**", api)
            await page.goto(base + "/channels")
            await page.get_by_role("button", name="测试", exact=True).click()
            dialog = page.get_by_role("dialog", name="接口检测 · Chat-only demo", exact=True)
            await expect(dialog).to_be_visible()
            assert not requested, "Opening the dialog must not make billable checks"

            async def select_both():
                await dialog.locator(".el-select__wrapper").click()
                await page.get_by_role("option", name="model-b", exact=True).click()
                await dialog.get_by_role("heading").click()

            await select_both()
            await dialog.get_by_role("button", name="开始检测", exact=True).click()
            await expect(dialog.get_by_text("已完成 10 项检测，6 项通过。", exact=False)).to_be_visible()
            assert requested == ["model-a", "model-b"]
            await expect(dialog.locator(".el-table__body .el-tag").filter(has_text="通过")).to_have_count(6)
            await expect(dialog.locator(".el-table__body .el-tag").filter(has_text="失败")).to_have_count(4)
            await expect(dialog.locator(".check-table").get_by_text("Responses endpoint is not available", exact=True)).to_have_count(4)
            await page.screenshot(path=str(output / "channel-checks-desktop.png"), full_page=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Page overflows mobile viewport"
            await page.screenshot(path=str(output / "channel-checks-mobile.png"), full_page=True)
            await page.set_viewport_size({"width": 1440, "height": 1000})
            await dialog.get_by_role("button", name="关闭", exact=True).click()

            await page.get_by_role("button", name="测试", exact=True).click()
            await expect(dialog.locator(".el-table")).to_have_count(0)
            await select_both()
            hold = True
            entered.clear()
            requested.clear()
            await dialog.get_by_role("button", name="开始检测", exact=True).click()
            await asyncio.wait_for(entered.wait(), timeout=10)
            await dialog.get_by_role("button", name="完成当前模型后停止", exact=True).click()
            release.set()
            await expect(dialog.get_by_text("已完成 5 项检测，3 项通过。", exact=False)).to_be_visible()
            assert requested == ["model-a"], "Stopping must not start a second model"
            await expect(dialog.locator(".el-table__body .el-tag").filter(has_text="未检测")).to_have_count(5)
            assert not errors, errors
            print("PASS: model selection, independent endpoint results, reopening, batch stop, mobile layout, no browser errors")
        except Exception:
            if "page" in locals():
                await page.screenshot(path=str(output / "channel-checks-failure.png"), full_page=True)
            raise
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5186")
    parser.add_argument("--browser")
    parser.add_argument("--output", type=Path, default=Path("../.cache/channel-checks-ui"))
    args = parser.parse_args()
    asyncio.run(verify(args.url.rstrip("/"), args.browser, args.output.resolve()))


if __name__ == "__main__":
    main()
