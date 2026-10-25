"""Optional browser checks used by scripts.smoke_tenants --ui.

Install playwright into the local development venv. Reuses an installed Chromium
or PLAYWRIGHT_CHROMIUM_EXECUTABLE; never downloads browsers during the check.
"""
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def verify_ui(username: str, password: str, tenant_token: str, tenant_ids: list[int], platform_key_ids: list[int], model: str, probe_model: str):
    base = os.environ.get("FIVE_SMOKE_UI_URL", "http://127.0.0.1:5001")
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if not executable:
        candidates = list((Path.home() / ".cache/ms-playwright").glob(
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
        executable = str(sorted(candidates)[-1]) if candidates else None
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=executable, headless=True, args=["--no-sandbox"],
        )
        try:
            context = await browser.new_context(locale="en-US")
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base + "/login")
            await page.locator("input").nth(0).fill(username)
            await page.locator("input").nth(1).fill(password)
            await page.locator("button[type=submit]").click()
            await expect(page.locator(".sidebar")).to_be_visible()
            assert not await page.get_by_role("menuitem", name="Roles", exact=True).count()
            await page.get_by_role("menuitem", name="Tenant accounts", exact=True).click()
            await page.get_by_role("button", name="Create tenant", exact=True).click()
            dialog = page.get_by_role("dialog", name="Create tenant", exact=True)
            fields = dialog.locator(".el-form-item")
            customer = username + "-ui"
            await fields.nth(0).locator("input").fill(customer)
            await fields.nth(2).locator("input").fill(customer)
            await fields.nth(3).locator("input").fill(password)
            async with page.expect_response(lambda r: r.url.endswith("/api/tenants") and r.request.method == "POST") as pending:
                await dialog.get_by_role("button", name="Save", exact=True).click()
            response = await pending.value
            assert response.status == 201, "tenant form submission"
            tenant_ids.append((await response.json())["id"])
            await expect(dialog).not_to_be_visible()
            await expect(page.get_by_text(customer, exact=True).first).to_be_visible()

            from scripts.settings_ui_check import verify_settings
            await verify_settings(page, base, platform_key_ids)
            from scripts.model_ui_check import verify_models
            await verify_models(page, base, model, probe_model)

            tenant_context = await browser.new_context(locale="en-US")
            await tenant_context.add_init_script(
                "localStorage.setItem('token'," + json.dumps(tenant_token) + ");localStorage.setItem('locale','en');"
            )
            tenant_page = await tenant_context.new_page()
            tenant_page.on("pageerror", lambda error: errors.append(str(error)))
            await tenant_page.goto(base + "/keys")
            await expect(tenant_page.locator(".sidebar .el-menu-item")).to_have_count(1)
            await expect(tenant_page.get_by_role("menuitem", name="API Keys", exact=True)).to_be_visible()
            await tenant_page.get_by_role("button", name="Create Key", exact=True).click()
            create = tenant_page.get_by_role("dialog", name="Create Key", exact=True)
            await create.locator("input").first.fill("ui-created-key")
            async with tenant_page.expect_response(lambda r: r.url.endswith("/api/keys") and r.request.method == "POST") as pending:
                await create.get_by_role("button", name="Save", exact=True).click()
            response = await pending.value
            assert response.status == 201, "tenant key form"
            raw = (await response.json())["key"]
            raw_dialog = tenant_page.get_by_role("dialog", name="API Key Created", exact=True, include_hidden=True)
            await expect(raw_dialog).to_be_visible()
            assert await raw_dialog.locator("input").input_value() == raw, "one-time key display"
            assert raw not in await tenant_page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
            await raw_dialog.locator(".el-dialog__headerbtn").click()
            await expect(raw_dialog).not_to_be_visible()
            await expect(raw_dialog.locator("input")).to_have_value("")
            await tenant_page.goto(base + "/admins")
            await expect(tenant_page).to_have_url(base + "/keys")
            assert not errors, "browser runtime errors: " + "; ".join(errors)
            await tenant_context.close()
            await context.close()
            print("PASS: browser platform login and tenant provisioning, minimal tenant navigation,")
            print("      key creation, one-time secret cleanup and route guard")
        finally:
            await browser.close()
