from playwright.async_api import expect


async def verify_models(page, base, model, probe_model):
    await page.goto(base + "/models")
    await expect(page.get_by_role("heading", name="Model Hub", exact=True)).to_be_visible()
    await expect(page.get_by_role("link", name="Reconciliation", exact=True)).to_have_count(0)
    await page.locator(".model-search input").fill("five-smoke")
    card = page.locator(".model-card").filter(has=page.get_by_role("heading", name=model, exact=True))
    await expect(card).to_be_visible()
    await card.get_by_role("button", name="Health check", exact=True).click()
    drawer = page.get_by_role("dialog", name=model, exact=True)
    await expect(drawer).to_be_visible()
    async with page.expect_response(lambda r: r.url.endswith("/api/models/probe") and r.request.method == "POST") as pending:
        await drawer.get_by_role("button", name="Health check", exact=True).click()
    result = await pending.value
    assert result.status == 200 and (await result.json())["status"] == "healthy"
    await drawer.locator(".el-drawer__close-btn").click()
    await expect(drawer).not_to_be_visible()
    card = page.locator(".model-card").filter(has=page.get_by_role("heading", name=probe_model, exact=True))
    await card.get_by_role("button", name="Degradation check (reference)", exact=True).click()
    drawer = page.get_by_role("dialog", name=probe_model, exact=True)
    async with page.expect_response(lambda r: r.url.endswith("/api/models/probe") and r.request.method == "POST") as pending:
        await drawer.get_by_role("button", name="Degradation check (reference)", exact=True).click()
    result = await pending.value
    assert result.status == 200 and (await result.json())["score"] == 100
    await expect(drawer.get_by_text("100/100", exact=False)).to_be_visible()
    await drawer.locator(".el-drawer__close-btn").click()
    await page.get_by_role("button", name="Scheduled checks", exact=True).click()
    dialog = page.get_by_role("dialog", name="Scheduled checks", exact=True)
    await expect(dialog.get_by_role("spinbutton").first).to_have_value("15")
    await expect(dialog.get_by_role("spinbutton").nth(1)).to_have_value("24")
    await dialog.get_by_role("button", name="Cancel", exact=True).click()
    print("PASS: model hub pricing, real HTTP health/degradation checks and schedule settings")
