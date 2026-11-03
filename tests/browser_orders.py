"""Actual canonical My Orders on desktop/mobile, loopback-only synthetic data."""

from hashlib import sha256
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from browser_auth import customer_app, sign_in


@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("width", [320, 375, 390, 768, 1080, 1920])
def test_order_history_detail_archive_download_and_logout(
    customer_app, width, embedded, tmp_path
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
            # Sign in through the existing configurator account control, then
            # enter the authenticated canonical history route. My Orders' guest
            # guard does not expose the configurator's "Sign in" button.
            page.goto(state["ui"] + "/Quote")
            sign_in(page)
            page.goto(
                api + "/orders-landing" if embedded else state["ui"] + "/My_Orders"
            )
            scope = page.frame_locator("#plate-configurator") if embedded else page
            expect(
                scope.get_by_role("heading", name="OP-0016", exact=True)
            ).to_be_visible()
            expect(
                scope.get_by_role("combobox", name="Select an order", exact=True)
            ).to_have_count(0)
            scope.get_by_role("textbox", name="Find an order", exact=True).fill(
                "OP-0016"
            )
            scope.get_by_role("textbox", name="Find an order", exact=True).press("Tab")
            page.screenshot(
                path=str(tmp_path / f"my-orders-{width}-list.png"), full_page=True
            )
            scope.get_by_role("button", name="View order", exact=True).click()
            expect(
                scope.get_by_role("heading", name="Plate 1 · 304", exact=True)
            ).to_be_visible()
            width_available = scope.locator(".st-key-orders_workspace").evaluate(
                "e=>e.clientWidth"
            )
            (tmp_path / "dimensions.json").write_text(
                __import__("json").dumps(
                    {
                        "viewport": width,
                        "embedded": embedded,
                        "content": width_available,
                        "rail": scope.locator(".st-key-orders_rail").evaluate(
                            "e=>e.getBoundingClientRect().width"
                        ),
                    }
                )
            )
            if width_available < 900:
                expect(scope.locator(".st-key-orders_rail")).to_be_hidden()
            else:
                expect(scope.locator(".st-key-orders_rail")).to_be_visible()
            scope.locator(
                ".st-key-orders_workspace"
            ).element_handle().owner_frame().wait_for_function(
                "()=>{const e=document.querySelector('.st-key-orders_workspace');return e&&e.scrollWidth<=e.clientWidth+1}",
                timeout=5000,
            )

            scope.get_by_role("combobox", name="Select plate", exact=True).click()
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "ArrowDown"
            )
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "Enter"
            )
            expect(
                scope.get_by_role("heading", name="Plate 2 · 316", exact=True)
            ).to_be_visible()
            expect(
                scope.get_by_text(
                    "Historical chamfer specification is incomplete.", exact=False
                )
            ).to_be_attached()
            scope.get_by_role("combobox", name="Select plate", exact=True).click()
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "ArrowUp"
            )
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "Enter"
            )
            expect(
                scope.get_by_role("heading", name="Plate 1 · 304", exact=True)
            ).to_be_visible()
            scope.get_by_role(
                "button", name="View approved drawing", exact=True
            ).click()
            expect(
                scope.get_by_text("Stored drawing PDF · page 1", exact=True)
            ).to_be_attached()
            expect(scope.get_by_test_id("stImage").locator("img")).to_be_visible()
            with page.expect_download() as result:
                scope.get_by_role(
                    "button", name="Download approved PDF", exact=True
                ).click()
            download = result.value
            assert sha256(Path(download.path()).read_bytes()).hexdigest() == digest
            scope.locator(".st-key-orders_workspace").screenshot(
                path=str(tmp_path / f"my-orders-{width}-drawing.png")
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            )
            expect(scope.get_by_test_id("stException")).to_have_count(0)
            # Canonical plate/filter state must survive a real customer-route remount.
            scope.get_by_role("combobox", name="Select plate", exact=True).click()
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "ArrowDown"
            )
            scope.get_by_role("combobox", name="Select plate", exact=True).press(
                "Enter"
            )
            expect(
                scope.get_by_role("heading", name="Plate 2 · 316", exact=True)
            ).to_be_visible()
            scope.get_by_role("link", name="Quote Cart", exact=True).click()
            expect(
                scope.get_by_role("heading", name="Quote Cart", exact=True)
            ).to_be_visible()
            scope.get_by_role("link", name="My Orders", exact=True).click()
            expect(
                scope.get_by_role("heading", name="Plate 2 · 316", exact=True)
            ).to_be_visible()
            scope.get_by_role("button", name="← Back to Orders", exact=True).click()
            expect(
                scope.get_by_role("textbox", name="Find an order", exact=True)
            ).to_have_value("OP-0016")
            scope.get_by_role("button", name="Log out", exact=True).click()
            expect(
                scope.get_by_role("button", name="Download approved PDF", exact=True)
            ).to_have_count(0)
            expect(
                scope.get_by_role("heading", name="OP-0016", exact=True)
            ).to_have_count(0)
        except Exception:
            (tmp_path / "overflow.json").write_text(
                __import__("json").dumps(
                    scope.locator(".st-key-orders_workspace").evaluate(
                        "e=>{const r=e.getBoundingClientRect();return{outer:{width:e.clientWidth,scroll:e.scrollWidth},bad:[...e.querySelectorAll('*')].map(x=>({tag:x.tagName,cl:x.className,id:x.dataset.testid,w:x.getBoundingClientRect().width,right:x.getBoundingClientRect().right-r.right,style:x.getAttribute('style'),html:x.outerHTML.slice(0,700),parent:x.parentElement?.outerHTML.slice(0,1000)})).filter(x=>x.right>1)}}"
                    )
                )
            )
            page.screenshot(
                path=str(tmp_path / f"my-orders-{width}-failure.png"), full_page=True
            )
            raise
        finally:
            context.close()
            browser.close()
