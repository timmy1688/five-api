"""Browser verification of scoped saves, grouped accounts and responsive settings."""
from pathlib import Path
from playwright.async_api import expect


async def verify_settings(page, base, platform_key_ids):
    await page.goto(base + "/keys")
    await expect(page.get_by_role("button", name="Create Key", exact=True)).to_be_visible()
    await page.get_by_role("button", name="Create Key", exact=True).click()
    create = page.get_by_role("dialog", name="Create Key", exact=True)
    await create.locator("input").first.fill("platform-smoke")
    async with page.expect_response(lambda r: r.url.endswith("/api/keys") and r.request.method == "POST") as pending:
        await create.get_by_role("button", name="Save", exact=True).click()
    result = await pending.value
    data = await result.json()
    assert result.status == 201 and data["tenant_is_system"]
    platform_key_ids.append(data["id"])
    raw = page.get_by_role("dialog", name="API Key Created", exact=True)
    await expect(raw).to_be_visible()
    await raw.locator(".el-dialog__headerbtn").click()
    await expect(raw).not_to_be_visible()
    await expect(page.get_by_role("menuitem", name="Platform admins", exact=True)).to_be_visible()
    await page.goto(base + "/settings")
    await expect(page.get_by_role("tab")).to_have_count(4)
    general = page.locator("#pane-general")
    try:
        await expect(general.get_by_role("spinbutton").first).to_be_enabled()
    except AssertionError:
        await page.screenshot(path="/tmp/five-settings-debug.png", full_page=True)
        print("Settings state:", await page.locator(".settings-page").evaluate("el => { const s=el.__vueParentComponent.setupState; return {loaded:s.loaded, canWrite:s.canWrite, loading:s.loading, loadError:s.loadError} }"))
        raise
    save = general.get_by_role("button", name="Save gateway settings", exact=True)
    await expect(save).to_be_disabled()
    retention = general.get_by_role("spinbutton").first
    original_days = await retention.input_value()
    await retention.fill(str(int(original_days) + 1)); await retention.press("Tab")
    await expect(save).to_be_enabled()
    await page.get_by_role("tab", name="Routing", exact=True).click()
    routing = page.locator("#pane-routing")
    ttl = routing.get_by_role("spinbutton").first
    original_ttl = await ttl.input_value()
    await ttl.fill(str(int(original_ttl) + 60)); await ttl.press("Tab")
    await expect(routing.get_by_role("button", name="Save routing settings", exact=True)).to_be_enabled()
    assert not await routing.locator(".el-collapse-item__content").first.is_visible()
    await page.get_by_role("tab", name="Gateway", exact=True).click()
    try:
        async with page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT") as pending:
            await save.click()
        response = await pending.value
        assert response.status == 200
        assert set(response.request.post_data_json) == {"log_retention_days", "channel_health_threshold",
                                                         "channel_health_check_interval", "auto_cache_control"}
        await expect(save).to_be_disabled()
        await page.get_by_role("tab", name="Routing", exact=True).click()
        await expect(ttl).to_have_value(str(int(original_ttl) + 60))
        await ttl.fill(original_ttl); await ttl.press("Tab")
        await expect(routing.get_by_role("button", name="Save routing settings", exact=True)).to_be_disabled()
        await page.screenshot(path="/tmp/five-settings-routing.png", full_page=True)
    finally:
        await page.get_by_role("tab", name="Gateway", exact=True).click()
        await retention.fill(original_days); await retention.press("Tab")
        async with page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT"):
            await save.click()
    await page.screenshot(path="/tmp/five-settings-general.png", full_page=True)
    await expect(page.get_by_role("tab", name="Settlement recovery", exact=True)).to_have_count(0)
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.get_by_role("tab", name="Gateway", exact=True).click()
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    await page.screenshot(path="/tmp/five-settings-mobile.png", full_page=True)
    await page.set_viewport_size({"width": 1280, "height": 900})
    print("PASS: grouped accounts, platform-use key creation, settings tabs, scoped save, unsaved edits and mobile layout")
