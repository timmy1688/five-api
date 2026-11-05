"""Exercise the built Audit page with synthetic API responses, no vendor calls.

Start `npm run preview -- --host 127.0.0.1 --port 5186` in frontend first.
Requires the optional Playwright package and an installed Chromium browser.

Checks that request details stay out of the way by default and that the
report keeps listing every request in its downloaded text.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect

TOTAL = 60
FLAGGED = 3
UNAVAILABLE = 2


def build_requests():
    """Return synthetic saved requests: a few concerns hidden among many clear ones."""
    items = []
    for number in range(TOTAL):
        if number in (7, 21, 40):
            verdict = "flagged:prompt_injection"
        elif number in (11, 33):
            verdict = "unavailable"
        else:
            verdict = "clear"
        text = f"User asks about task number {number}. " + "Long paragraph of saved request text. " * 12
        items.append({
            "request_id": f"req-{number:03d}",
            "created_at": f"2026-11-04T10:{number % 60:02d}:00",
            "model_requested": "deepseek-chat",
            "status_code": 200,
            "keyword_hit": number == 7,
            "ai_review": verdict,
            "excerpt": text,
            "saved": text,
        })
    return items


async def verify(base: str, executable: str | None, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    items = build_requests()
    reviewed = []

    async def api(route):
        path = route.request.url.split("/api/", 1)[1].split("?", 1)[0]
        if path == "me":
            body = {"id": 1, "username": "demo-admin", "role": "platform_admin", "must_change_password": False}
        elif path == "security":
            body = {"ai_audit": {"enabled": True, "model": "demo-model"}}
        elif path == "audit/keys":
            body = {"items": [{"api_key_id": 1, "api_key_name": "alice-key", "request_count": TOTAL}]}
        elif path == "audit/keys/1/requests":
            body = {"items": items, "total": TOTAL}
        elif path == "audit/review":
            # Pretend the review model finishes the unavailable requests cleanly.
            request_id = route.request.post_data_json["request_ids"][0]
            reviewed.append(request_id)
            body = {"items": [{"request_id": request_id, "ai_review": "clear"}]}
        else:
            raise AssertionError(f"Unexpected API request: {path}")
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=executable, headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN",
                                                accept_downloads=True)
            context.set_default_timeout(10000)
            await context.add_init_script("localStorage.setItem('token', 'synthetic-ui-token'); localStorage.setItem('locale', 'zh')")
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("**/api/**", api)
            await page.goto(base + "/audit")
            await page.get_by_text("alice-key", exact=True).first.click()
            rows = page.locator(".audit-row")

            # 1. Details are folded by default: no request rows on screen except the report sample.
            toggle = page.locator(".list-toggle")
            await expect(toggle).to_be_visible()
            await expect(toggle).to_have_attribute("aria-expanded", "false")
            await expect(page.locator(".request-list")).to_have_count(0)
            await expect(rows).to_have_count(1)  # the preview sample row only
            await page.screenshot(path=str(output / "audit-before-report.png"), full_page=True, animations="disabled")

            # 2. Generating the report lists only the requests that need attention.
            await page.get_by_role("button", name="生成报告", exact=True).first.click()
            concerns = FLAGGED + UNAVAILABLE
            await expect(rows).to_have_count(concerns)
            await expect(page.get_by_text(f"这里只列出 {concerns} 条需要关注的请求", exact=False)).to_be_visible()
            report_height = round((await page.locator(".report-paper").bounding_box())["height"])
            await page.screenshot(path=str(output / "audit-report-concerns.png"), full_page=True, animations="disabled")

            # 3. Flagged rows come first; one click opens the full text, a second closes it.
            first = rows.first
            await expect(first.locator(".row-body")).to_have_count(0)
            await first.locator(".row-line").click()
            await expect(first.locator(".excerpt")).to_be_visible()
            await expect(first.locator(".row-line")).to_have_attribute("aria-expanded", "true")
            await first.locator(".row-line").click()
            await expect(first.locator(".row-body")).to_have_count(0)

            # 4. The scope toggle shows everything, and back again.
            await page.get_by_role("button", name=f"显示全部 {TOTAL} 条", exact=True).click()
            await expect(rows).to_have_count(TOTAL)
            await page.get_by_role("button", name="只看需要关注的", exact=True).click()
            await expect(rows).to_have_count(concerns)

            # 5. The download is still complete, not the concern-only view.
            async with page.expect_download() as download_info:
                await page.get_by_role("button", name="下载报告", exact=True).click()
            download = await download_info.value
            text = Path(await download.path()).read_text(encoding="utf-8")
            assert text.count("deepseek-chat") == TOTAL, "Downloaded report must keep all requests"

            # 6. The folded list opens on demand and gets its own scroll area.
            await toggle.click()
            await expect(toggle).to_have_attribute("aria-expanded", "true")
            await expect(page.locator(".request-list .audit-row")).to_have_count(TOTAL)
            list_row = page.locator(".request-list .audit-row").nth(5)
            await list_row.locator(".row-line").click()
            await expect(list_row.locator(".excerpt")).to_be_visible()
            await page.screenshot(path=str(output / "audit-list-open.png"), full_page=True, animations="disabled")
            await toggle.click()
            await expect(page.locator(".request-list")).to_have_count(0)

            # 7. A manual review with the list folded runs cleanly and the report follows the new verdicts.
            await page.get_by_role("button", name="审查这个 Key", exact=True).click()
            await expect(page.get_by_text("下面这份报告已经填好", exact=False)).to_be_visible()
            assert reviewed == ["req-011", "req-033"], reviewed
            await expect(rows).to_have_count(FLAGGED)
            await expect(page.locator(".request-list")).to_have_count(0)

            # 8. Mobile layout does not overflow.
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), \
                "Page overflows mobile viewport"
            await page.screenshot(path=str(output / "audit-report-mobile.png"), full_page=True, animations="disabled")

            assert not errors, errors
            print(f"PASS: folded list, concern-only report ({concerns} of {TOTAL}), row expand, scope toggle, "
                  f"complete download, mobile; report card height {report_height}px")
        except Exception:
            if "page" in locals():
                await page.screenshot(path=str(output / "audit-failure.png"), full_page=True, animations="disabled")
            raise
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5186")
    parser.add_argument("--browser")
    parser.add_argument("--output", type=Path, default=Path("../.cache/audit-ui"))
    args = parser.parse_args()
    asyncio.run(verify(args.url.rstrip("/"), args.browser, args.output.resolve()))


if __name__ == "__main__":
    main()
