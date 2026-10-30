"""Actual canonical My Orders on desktop/mobile, loopback-only synthetic data."""

from hashlib import sha256
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from browser_auth import customer_app, sign_in


@pytest.mark.parametrize("width", [1280, 390])
def test_order_history_detail_archive_download_and_logout(
    customer_app, width, tmp_path
):
    state, api = customer_app
    pdf = (Path(__file__).parent / "fixtures/legacy-v3e.pdf").read_bytes()
    digest = sha256(pdf).hexdigest()
    order = dict(
        id="order-1",
        order_number_display="OP-0016",
        status="completed",
        payment_mode="OWNER TEST",
        created_at="2026-10-27T13:23:00Z",
        amount_total_usd=123.45,
        line_count=2,
        lines=[
            {
                "line_id": "line-1",
                "specifications": {"material": "304", "quantity": 1, "paddle_dia": 3},
            },
            {
                "line_id": "line-2",
                "specifications": {
                    "material": "316",
                    "quantity": 2,
                    "chamfer": True,
                    "chamfer_width": 0.062,
                },
            },
        ],
    )
    revision = dict(
        id="revision-1",
        number=1,
        current=True,
        approved=True,
        approved_at="2026-10-27T13:37:00Z",
        created_at="2026-10-27T13:23:00Z",
        specifications={"material": "304"},
        pdf_sha256=digest,
        pdf_size=len(pdf),
        filename="drawing.pdf",
    )
    state.update(
        order_history={"orders": [order], "total": 1},
        order_detail=order,
        drawing_pdf=pdf,
        drawing_hash=digest,
        drawing_archive=[
            dict(
                id="plate-1",
                line_id="line-1",
                current_revision="revision-1",
                lifecycle="CUSTOMER_APPROVED",
                revisions=[revision],
            )
        ],
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": 1000})
        page = context.new_page()
        page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith((state["ui"] + "/", api + "/"))
                else route.abort()
            ),
        )
        try:
            page.goto(state["ui"] + "/My_Orders")
            sign_in(page)
            expect(
                page.get_by_role("heading", name="OP-0016", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_role("combobox", name="Select an order", exact=True)
            ).to_have_count(0)
            page.get_by_role("textbox", name="Find an order", exact=True).fill(
                "OP-0016"
            )
            page.get_by_role("textbox", name="Find an order", exact=True).press("Tab")
            page.screenshot(
                path=str(tmp_path / f"my-orders-{width}-list.png"), full_page=True
            )
            page.get_by_role("button", name="View order", exact=True).click()
            expect(
                page.get_by_role("heading", name="Plate 1 · 304", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_role("heading", name="Plate 2 · 316", exact=True)
            ).to_be_attached()
            expect(
                page.get_by_text(
                    "Historical chamfer specification is incomplete.", exact=False
                )
            ).to_be_attached()
            page.get_by_role("button", name="View approved drawing", exact=True).click()
            expect(
                page.get_by_text("Stored drawing PDF · page 1", exact=True)
            ).to_be_attached()
            expect(page.get_by_test_id("stImage").locator("img")).to_be_visible()
            with page.expect_download() as result:
                page.get_by_role(
                    "button", name="Download approved PDF", exact=True
                ).click()
            download = result.value
            assert sha256(Path(download.path()).read_bytes()).hexdigest() == digest
            page.screenshot(
                path=str(tmp_path / f"my-orders-{width}-drawing.png"), full_page=True
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            )
            expect(page.get_by_test_id("stException")).to_have_count(0)
            page.get_by_role("button", name="Log out", exact=True).click()
            expect(
                page.get_by_role("button", name="Download approved PDF", exact=True)
            ).to_have_count(0)
            expect(
                page.get_by_role("heading", name="OP-0016", exact=True)
            ).to_have_count(0)
        finally:
            context.close()
            browser.close()
