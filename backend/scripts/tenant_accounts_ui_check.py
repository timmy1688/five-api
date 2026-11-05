"""Exercise tenant and administrator account screens with synthetic API responses, no real accounts.

Start `npm run preview -- --host 127.0.0.1 --port 5186` in frontend first.
Requires the optional Playwright package and an installed Chromium browser.

Checks that generated passwords are shown once and dropped, that no screen asks the
administrator to type someone else's password, that the new password rule is
explained before the request is sent, that a tenant is created from its username
alone, and that the budget dialog adds, reduces and sets totals without a mandatory reason.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect

TENANT_PASSWORD = "kTq7-mN4x-Pw9c-Hs2d"
RESET_PASSWORD = "Zr5w-Yd8e-Qf3n-Bk6j"
ADMIN_PASSWORD = "Gh4m-Vc7p-Xs9t-Ln2a"


async def verify(base: str, executable: str | None, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    tenant = {"id": 1, "name": "Acme", "description": "", "username": "acme", "account_id": 10,
              "quota_total": "20", "quota_used": "3", "quota_occupied": "2", "quota_remaining": "15",
              "quota_reset_day": None, "window_limits": {}, "window_spend": {}, "is_enabled": True,
              "allowed_models": [], "max_keys": 100, "rpm_limit": 120, "tpm_limit": 100000,
              "concurrent_limit": 10, "key_count": 0,
              "created_at": "2026-11-05T10:00:00", "updated_at": "2026-11-05T10:00:00"}
    admins = [
        {"id": 1, "username": "root", "role": "platform_admin", "is_active": True, "must_change_password": False,
         "created_at": "2026-11-01T10:00:00", "tenant_id": None},
        {"id": 2, "username": "second", "role": "platform_admin", "is_active": True, "must_change_password": False,
         "created_at": "2026-11-02T10:00:00", "tenant_id": None},
    ]
    calls: list[tuple[str, str, dict]] = []

    async def api(route):
        request = route.request
        path = request.url.split("/api/", 1)[1].split("?", 1)[0]
        body = request.post_data_json if request.post_data else {}
        calls.append((request.method, path, body))
        status = 200
        if path == "me":
            data = {"id": 1, "username": "root", "role": "platform_admin", "is_active": True,
                    "must_change_password": False, "tenant_id": None, "created_at": "2026-11-01T10:00:00"}
        elif path == "tenants" and request.method == "GET":
            data = {"total": 1, "items": [tenant]}
        elif path == "models":
            data = {"total": 0, "items": []}
        elif path == "tenants/1" and request.method == "GET":
            data = tenant
        elif path == "tenants/1/quota":
            data = {**tenant, "quota_total": body["quota_total"]}
        elif path == "tenants" and request.method == "POST":
            assert "password" not in body, "The console must not send a typed password"
            assert "name" not in body, "The username doubles as the tenant name"
            status, data = 201, {**tenant, "id": 2, "name": body["username"], "username": body["username"],
                                 "temporary_password": TENANT_PASSWORD}
        elif path == "tenants/1/password":
            data = {"message": "ok", "temporary_password": RESET_PASSWORD}
        elif path == "users" and request.method == "GET":
            data = {"total": 2, "items": admins}
        elif path == "users" and request.method == "POST":
            assert "password" not in body, "The console must not send a typed password"
            status, data = 201, {**admins[1], "id": 3, "username": body["username"],
                                 "temporary_password": ADMIN_PASSWORD}
        elif path == "users/2/password":
            data = {"message": "ok", "temporary_password": RESET_PASSWORD}
        elif path == "password":
            raise AssertionError("A weak password must be rejected before it is sent")
        else:
            raise AssertionError(f"Unexpected API request: {request.method} {path}")
        await route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=executable, headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US",
                                                permissions=["clipboard-read", "clipboard-write"])
            context.set_default_timeout(10000)
            await context.add_init_script("localStorage.setItem('token', 'synthetic-ui-token'); localStorage.setItem('locale', 'en')")
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("**/api/**", api)

            # Tenants: creating asks for no password and shows the generated one once.
            await page.goto(base + "/tenants")
            await page.get_by_role("button", name="Create tenant", exact=True).click()
            dialog = page.get_by_role("dialog", name="Create tenant", exact=True)
            await expect(dialog.locator("input[type=password]")).to_have_count(0)
            await expect(dialog.get_by_text("A one-time login password is generated", exact=False)).to_be_visible()
            fields = dialog.locator(".el-form-item")
            await expect(dialog.get_by_text("Name", exact=True)).to_have_count(0)  # username only
            await fields.nth(0).locator("input").fill("globex")
            await dialog.get_by_role("button", name="Save", exact=True).click()
            issued = page.get_by_role("dialog", name="Account created", exact=True)
            await expect(issued).to_be_visible()
            await expect(issued.locator("input")).to_have_value(TENANT_PASSWORD)
            await expect(issued.get_by_text("globex", exact=True)).to_be_visible()
            await expect(issued.get_by_text("shown only once", exact=False)).to_be_visible()
            await issued.get_by_role("button", name="Copy", exact=True).click()
            await expect(page.get_by_text("Copied", exact=True)).to_be_visible()
            assert await page.evaluate("navigator.clipboard.readText()") == TENANT_PASSWORD
            await page.screenshot(path=str(output / "tenant-created.png"), animations="disabled")
            await issued.get_by_role("button", name="I have copied it", exact=True).click()
            await expect(issued).not_to_be_visible()
            hidden = page.get_by_role("dialog", name="Account created", exact=True, include_hidden=True)
            await expect(hidden.locator("input")).to_have_value("")  # dropped once the dialog closes
            assert TENANT_PASSWORD not in await page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")

            # Tenants: reset asks for confirmation first, then shows the new password once.
            before = len(calls)
            await page.get_by_role("button", name="Reset password", exact=True).click()
            confirm = page.get_by_role("dialog", name="Reset password", exact=True)
            await expect(confirm.get_by_text("revoked immediately", exact=False)).to_be_visible()
            assert not any(path == "tenants/1/password" for _, path, _ in calls[before:]), "Reset needs confirmation"
            await confirm.get_by_role("button", name="Cancel", exact=True).click()
            await page.wait_for_timeout(300)
            assert not any(path == "tenants/1/password" for _, path, _ in calls[before:]), "Cancel must not reset"
            await page.get_by_role("button", name="Reset password", exact=True).click()
            await page.get_by_role("dialog", name="Reset password", exact=True).get_by_role(
                "button", name="Reset password", exact=True).click()
            # The confirmation box and the result dialog share a title while one fades out.
            await expect(page.locator(".password-field input")).to_have_value(RESET_PASSWORD)
            await page.get_by_role("button", name="I have copied it", exact=True).click()
            await expect(page.locator(".password-field input:visible")).to_have_count(0)

            # Budget: add, reduce and set without a mandatory reason; the floor is enforced up front.
            fetched = len(calls)
            await page.get_by_role("button", name="Adjust budget", exact=True).click()
            budget = page.get_by_role("dialog", name="Adjust budget · acme", exact=True)
            await expect(budget).to_be_visible()
            assert ("GET", "tenants/1", {}) in calls[fetched:], "The dialog reads live figures, not the table row"
            amount = budget.get_by_role("spinbutton")
            save = budget.get_by_role("button", name="Save", exact=True)
            after = budget.locator(".quota-after")
            await expect(budget.get_by_text("$20.000000", exact=True).first).to_be_visible()  # current total
            await expect(save).to_be_disabled()  # nothing to change yet
            await amount.fill("5.5")
            await expect(after).to_have_text("$25.500000")
            await expect(save).to_be_enabled()
            await budget.get_by_text("Reduce", exact=True).click()
            await amount.fill("16")  # 20 - 16 = 4, below used 3 + occupied 2
            await expect(after).to_have_text("$4.000000")
            await expect(budget.get_by_text("cannot be below used plus occupied", exact=False)).to_be_visible()
            await expect(save).to_be_disabled()
            await amount.fill("15")  # exactly the floor is allowed
            await expect(after).to_have_text("$5.000000")
            await expect(save).to_be_enabled()
            await budget.get_by_text("Set total", exact=True).click()
            await amount.fill("20")
            await expect(save).to_be_disabled()  # same as the current total
            await amount.fill("30")
            await expect(after).to_have_text("$30.000000")
            await page.screenshot(path=str(output / "budget-dialog.png"), animations="disabled")
            await save.click()
            await expect(budget).not_to_be_visible()
            quota_calls = [body for method, path, body in calls if path == "tenants/1/quota"]
            assert len(quota_calls) == 1 and quota_calls[0]["quota_total"] == "30.000000"
            assert quota_calls[0]["reason"] == "" and len(quota_calls[0]["operation_id"]) == 36

            # Admins: same flow, and the signed-in administrator cannot reset themselves here.
            await page.goto(base + "/admins")
            rows = page.locator(".el-table__body tr")
            await expect(rows).to_have_count(2)
            await expect(rows.nth(0).get_by_role("button", name="Reset password")).to_have_count(0)
            await expect(rows.nth(1).get_by_role("button", name="Reset password")).to_have_count(1)
            await page.get_by_role("button", name="Add admin", exact=True).first.click()
            add = page.get_by_role("dialog", name="Add admin", exact=True)
            await expect(add.locator("input[type=password]")).to_have_count(0)
            await add.locator("input").first.fill("third")
            await add.get_by_role("button", name="Save", exact=True).click()
            created = page.get_by_role("dialog", name="Administrator created", exact=True)
            await expect(created.locator("input")).to_have_value(ADMIN_PASSWORD)
            await created.get_by_role("button", name="I have copied it", exact=True).click()
            await expect(created).not_to_be_visible()
            await rows.nth(1).get_by_role("button", name="Reset password").click()
            await page.get_by_role("dialog", name="Reset password", exact=True).get_by_role(
                "button", name="Reset password", exact=True).click()
            await expect(page.locator(".password-field input")).to_have_value(RESET_PASSWORD)
            await page.screenshot(path=str(output / "admin-reset.png"), animations="disabled")
            await page.get_by_role("button", name="I have copied it", exact=True).click()
            assert ("PUT", "users/2/password", {}) in calls, "The reset request carries no typed password"

            # Change password: weak passwords are explained before anything is sent.
            await page.goto(base + "/password")
            fields = page.locator("form input")
            await fields.nth(0).fill("current-password")
            for weak, message in (("Short-1a", "at least 12 characters"),
                                  ("alllowercaseletters", "at least three"),
                                  ("A" * 4 + "b" * 4 + "9" * 4 + "x" * 80, "must not exceed 72")):
                await fields.nth(1).fill(weak)
                await fields.nth(2).fill(weak)
                await page.get_by_role("button", name="Save", exact=True).click()
                await expect(page.get_by_text(message, exact=False).last).to_be_visible()
            await page.screenshot(path=str(output / "change-password-rule.png"), animations="disabled")

            assert not errors, errors
            print("PASS: username-only tenant creation, generated passwords shown once and dropped, no typed "
                  "password sent, reset confirmation, self-reset hidden, weak new password explained, "
                  "budget add/reduce/set with floor check and optional note")
        except Exception:
            if "page" in locals():
                await page.screenshot(path=str(output / "account-passwords-failure.png"), full_page=True)
            raise
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5186")
    parser.add_argument("--browser")
    parser.add_argument("--output", type=Path, default=Path("../.cache/account-passwords-ui"))
    args = parser.parse_args()
    asyncio.run(verify(args.url.rstrip("/"), args.browser, args.output.resolve()))


if __name__ == "__main__":
    main()
