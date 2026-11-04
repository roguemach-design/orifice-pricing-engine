"""Session-only PDF delivery, revision switching and real canvas interaction."""

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from playwright.sync_api import sync_playwright, expect, Error
from browser_auth import customer_app, sign_in
from browser_orders import seed_orders, click_drawing_control


@contextmanager
def workspace(state, api, *, mobile=False, embedded=False, width=None):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": width or (390 if mobile else 1080), "height": 1000},
            has_touch=mobile,
            is_mobile=mobile,
        )
        page = context.new_page()
        # Any unintended provider/CDN request is blocked, including PDF.js assets.
        page.route(
            "**/*",
            lambda r: (
                r.continue_()
                if r.request.url.startswith((state["ui"] + "/", api + "/"))
                else r.abort()
            ),
        )
        try:
            page.goto(state["ui"] + "/Quote")
            sign_in(page)
            page.goto(
                api + "/orders-landing" if embedded else state["ui"] + "/My_Orders"
            )
            scope = page.frame_locator("#plate-configurator") if embedded else page
            scope.get_by_role("button", name="View order", exact=True).click()
            viewer = scope.frame_locator(
                'iframe[title="customer_pdf_viewer.oplates_approved_pdf"]'
            )
            yield page, viewer, context, browser
        finally:
            context.close()
            browser.close()


def wait_pdf(viewer):
    expect(viewer.locator("#status")).to_contain_text("Verified stored PDF")
    expect(viewer.locator("canvas")).to_be_visible()
    # Actual painted drawing pixels, not only a visible empty canvas/status.
    frame = viewer.locator("canvas").element_handle().owner_frame()
    frame.wait_for_function(
        "()=>{const c=document.querySelector('canvas');if(!c?.width||!c.height)return false;const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let dark=0;for(let i=0;i<d.length;i+=4)if(d[i+3]>0&&d[i]<100&&d[i+1]<100&&d[i+2]<100)dark++;return dark>100;}",
        timeout=5000,
    )


def test_multipage_historical_revision_and_browser_url_privacy(customer_app, tmp_path):
    state, api = customer_app
    pdf, digest = seed_orders(state)
    source = pdfium.PdfDocument(pdf)
    multi = pdfium.PdfDocument.new()
    multi.import_pages(source)
    multi.import_pages(source)
    out = BytesIO()
    multi.save(out)
    multi.close()
    source.close()
    pdf = out.getvalue()
    digest = sha256(pdf).hexdigest()
    current = state["drawing_archive"][0]["revisions"][0]
    current.update(number=2, pdf_sha256=digest, pdf_size=len(pdf))
    state.update(drawing_pdf=pdf, drawing_hash=digest)
    old = (Path(__file__).parent / "fixtures/legacy-v6.pdf").read_bytes()
    old_digest = sha256(old).hexdigest()
    historical = dict(
        current,
        id="revision-old",
        number=1,
        current=False,
        pdf_sha256=old_digest,
        pdf_size=len(old),
    )
    pending = dict(
        current, id="revision-pending", number=3, current=False, approved=False
    )
    state["drawing_archive"][0]["revisions"] += [historical, pending]
    state["drawing_revisions"] = {
        "revision-old": {"content": old, "hash": old_digest, "revision": "revision-old"}
    }
    with workspace(state, api) as (page, viewer, context, browser):
        wait_pdf(viewer)
        expect(viewer.locator("#pages")).to_have_text("Page 1 / 2")
        viewer.get_by_role("button", name="Next drawing page", exact=True).click()
        expect(viewer.locator("#pages")).to_have_text("Page 2 / 2")
        wait_pdf(viewer)
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        with page.expect_download() as dl:
            viewer.get_by_role(
                "button", name="Download approved PDF", exact=True
            ).click()
        assert dl.value.url.startswith("blob:")
        assert Path(dl.value.path()).read_bytes() == pdf
        assert not any("/media/" in url or "token=" in url for url in requests)
        component_url = page.locator(
            'iframe[title="customer_pdf_viewer.oplates_approved_pdf"]'
        ).get_attribute("src")
        anonymous = browser.new_context()
        try:
            public = anonymous.request.get(component_url)
            assert public.ok and digest not in public.text()
            assert (
                anonymous.request.get(
                    api + "/me/orders/order-1/drawings/revision-1/pdf"
                ).status
                == 401
            )
            with pytest.raises(Error):
                anonymous.new_page().goto(dl.value.url)
        finally:
            anonymous.close()
        selector = page.get_by_role("combobox", name="Approved revision", exact=True)
        selector.click()
        selector.press("ArrowDown")
        selector.press("Enter")
        expect(page.get_by_text("SHA-256 · " + old_digest, exact=True)).to_be_visible()
        wait_pdf(viewer)
        expect(viewer.locator("#pages")).to_have_text("Page 1 / 1")
        with page.expect_download() as dl:
            viewer.get_by_role(
                "button", name="Download approved PDF", exact=True
            ).click()
        assert Path(dl.value.path()).read_bytes() == old
        assert not any("revision-pending/pdf" in p for p in state["protected_paths"])
        private_blob = dl.value.url
        page.get_by_role("button", name="Log out", exact=True).click()
        expect(
            page.locator('iframe[title="customer_pdf_viewer.oplates_approved_pdf"]')
        ).to_have_count(0)
        with pytest.raises(Error):
            context.new_page().goto(private_blob)
        page.goto(state["ui"] + "/My_Orders")
        expect(page.get_by_role("heading", name="OP-0016", exact=True)).to_have_count(0)
        assert state["sends"] == 1


@pytest.mark.parametrize("mismatch", ["hash", "revision", "size", "unapproved"])
def test_browser_integrity_failure_has_no_drawing_or_download(customer_app, mismatch):
    state, api = customer_app
    seed_orders(state)
    revision = state["drawing_archive"][0]["revisions"][0]
    if mismatch == "hash":
        state["drawing_pdf"] = b"tampered"
    if mismatch == "revision":
        state["drawing_revisions"] = {"revision-1": {"revision": "different"}}
    if mismatch == "size":
        revision["pdf_size"] += 1
    if mismatch == "unapproved":
        revision["approved"] = False
    with workspace(state, api) as (page, viewer, context, browser):
        expect(
            page.get_by_text(
                (
                    "No approved PDF is available for this plate."
                    if mismatch == "unapproved"
                    else "Drawing verification failed. No file was displayed or downloaded."
                ),
                exact=True,
            )
        ).to_be_visible()
        expect(
            page.locator('iframe[title="customer_pdf_viewer.oplates_approved_pdf"]')
        ).to_have_count(0)


@pytest.mark.parametrize("mobile", [False, True])
def test_zoom_pan_keyboard_and_touch(customer_app, mobile, tmp_path):
    state, api = customer_app
    seed_orders(state)
    with workspace(state, api, mobile=mobile) as (page, viewer, context, browser):
        wait_pdf(viewer)
        viewer.get_by_role("button", name="Full screen", exact=True).click()
        expect(
            viewer.get_by_role("button", name="Exit full screen", exact=True)
        ).to_be_visible()
        wait_pdf(viewer)
        surface = viewer.locator("#surface")
        surface.focus()
        surface.press("+")
        expect(viewer.locator("#zoom")).to_have_text("125%")
        wait_pdf(viewer)
        if mobile:
            box = surface.bounding_box()
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            cdp = context.new_cdp_session(page)
            cdp.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchStart",
                    "touchPoints": [
                        {"x": cx - 25, "y": cy, "id": 0},
                        {"x": cx + 25, "y": cy, "id": 1},
                    ],
                },
            )
            cdp.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [
                        {"x": cx - 35, "y": cy, "id": 0},
                        {"x": cx + 35, "y": cy, "id": 1},
                    ],
                },
            )
            cdp.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [
                        {"x": cx - 70, "y": cy, "id": 0},
                        {"x": cx + 70, "y": cy, "id": 1},
                    ],
                },
            )
            cdp.send(
                "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
            )
            expect(viewer.locator("#zoom")).not_to_have_text("125%")
            wait_pdf(viewer)
        for _ in range(4):
            viewer.get_by_role("button", name="Zoom in", exact=True).click()
        wait_pdf(viewer)
        surface.evaluate("e=>{e.scrollLeft=0;e.scrollTop=0}")
        box = surface.bounding_box()
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 60, y - 80, steps=5)
        page.mouse.up()
        assert surface.evaluate("e=>e.scrollLeft>0||e.scrollTop>0")
        viewer.get_by_role("button", name="Fit page", exact=True).click()
        expect(viewer.locator("#zoom")).to_have_text("100%")
        wait_pdf(viewer)
        viewer.locator("#viewer").screenshot(
            path=str(
                tmp_path / ("viewer-mobile.png" if mobile else "viewer-desktop.png")
            )
        )


@pytest.mark.parametrize("width", [390, 1920])
def test_review_capture_in_actual_landing_shell(customer_app, width, tmp_path):
    """Owner review boards use a repository sample PDF and explicitly synthetic order."""
    state, api = customer_app
    seed_orders(state)
    content = (Path(__file__).parent / "fixtures/legacy-v6.pdf").read_bytes()
    digest = sha256(content).hexdigest()
    spec = {
        "material": "304",
        "thickness": 0.125,
        "paddle_dia": 5.0,
        "bore_dia": 1.548,
        "handle_width": 2.0,
        "handle_len": 10.5,
        "quantity": 1,
        "chamfer": False,
    }
    state["order_detail"]["order_number_display"] = "DEMO-0042"
    state["order_detail"]["lines"][0]["specifications"] = spec
    revision = state["drawing_archive"][0]["revisions"][0]
    revision.update(pdf_sha256=digest, pdf_size=len(content), specifications=spec)
    state.update(drawing_pdf=content, drawing_hash=digest)
    with workspace(state, api, mobile=width == 390) as (page, viewer, context, browser):
        page.set_viewport_size({"width": width, "height": 1000})
        page.goto(api + "/orders-landing")
        scope = page.frame_locator("#plate-configurator")
        scope.get_by_role("button", name="View order", exact=True).click()
        viewer = scope.frame_locator(
            'iframe[title="customer_pdf_viewer.oplates_approved_pdf"]'
        )
        viewer.get_by_role("button", name="Fit page", exact=True).click()
        wait_pdf(viewer)
        # A tall review board captures the actual scrolling UI at its original width.
        page.set_viewport_size({"width": width, "height": 5000})
        viewer.get_by_role("button", name="Fit page", exact=True).click()
        wait_pdf(viewer)
        available = scope.locator(".st-key-orders_workspace").evaluate(
            "e=>e.clientWidth"
        )
        assert available <= 918
        if width == 1920:
            assert available == 918
            assert (
                scope.locator(".st-key-orders_rail").evaluate("e=>e.clientWidth") == 200
            )
        else:
            expect(scope.locator(".st-key-orders_rail")).to_be_hidden()
        name = "mobile" if width == 390 else "desktop"
        scope.locator(".st-key-orders_workspace").screenshot(
            path=str(tmp_path / f"implemented-{name}.png")
        )
        page.set_viewport_size(
            {"width": width, "height": 844 if width == 390 else 1000}
        )
        viewer.get_by_role("button", name="Full screen", exact=True).click()
        expect(
            viewer.get_by_role("button", name="Exit full screen", exact=True)
        ).to_be_visible()
        wait_pdf(viewer)
        page.screenshot(path=str(tmp_path / f"viewer-{name}-fullscreen.png"))


@pytest.mark.parametrize("width", [390, 1080, 1920])
def test_embedded_fullscreen_exit_restores_position_and_immediate_download(
    customer_app, width, tmp_path
):
    """Native fullscreen must return to the drawing, not strand its iframe off-screen."""
    state, api = customer_app
    pdf, digest = seed_orders(state)
    with workspace(state, api, embedded=True, width=width, mobile=width == 390) as (
        page,
        viewer,
        context,
        browser,
    ):
        viewer.get_by_role("button", name="Fit page", exact=True).click()
        wait_pdf(viewer)
        page.evaluate("""() => {
          document.addEventListener('fullscreenchange', () => {
            if (document.fullscreenElement) window.fullscreenEntryY = scrollY;
          });
        }""")
        for _ in range(3):
            viewer.locator("canvas").scroll_into_view_if_needed()
            viewer.get_by_role("button", name="Full screen", exact=True).click()
            expect(
                viewer.get_by_role("button", name="Exit full screen", exact=True)
            ).to_be_visible()
            viewer.get_by_role("button", name="Exit full screen", exact=True).click()
            page.wait_for_function("!document.fullscreenElement")
            assert abs(page.evaluate("scrollY - window.fullscreenEntryY")) <= 1
            with page.expect_download() as result:
                viewer.get_by_role(
                    "button", name="Download approved PDF", exact=True
                ).click()
            assert Path(result.value.path()).read_bytes() == pdf
            assert sha256(Path(result.value.path()).read_bytes()).hexdigest() == digest
            wait_pdf(viewer)
        page.screenshot(path=str(tmp_path / f"fullscreen-return-{width}.png"))


@pytest.mark.parametrize("width", [390, 768, 1080])
def test_fit_receives_real_clicks_after_host_scroll(customer_app, width):
    """Default smooth scrolling stays enabled; accepted commands must render their fit."""
    state, api = customer_app
    seed_orders(state)
    with workspace(state, api, embedded=True, width=width, mobile=width == 390) as (
        page,
        viewer,
        context,
        browser,
    ):
        page.emulate_media(reduced_motion="no-preference")
        assert (
            page.evaluate("getComputedStyle(document.documentElement).scrollBehavior")
            == "smooth"
        )
        click_drawing_control(page, viewer, "Fit page")
        wait_pdf(viewer)
        canvas = viewer.locator("canvas")
        baseline = canvas.evaluate(
            "e=>[parseFloat(e.style.width),parseFloat(e.style.height)]"
        )
        viewer.locator("#toolbar").evaluate("""e => {
          window.receivedDrawingClicks = [];
          e.addEventListener('click', event => {
            if (event.target.tagName === 'BUTTON') window.receivedDrawingClicks.push(event.target.id);
          });
        }""")
        for _ in range(6):
            # Exercise the same canvas-to-toolbar scroll transition as the original failure.
            canvas.scroll_into_view_if_needed()
            for name, label, factor in [
                ("Zoom in", "125%", 1.25),
                ("Fit page", "100%", 1),
                ("Zoom out", "80%", 0.8),
                ("Fit page", "100%", 1),
            ]:
                click_drawing_control(page, viewer, name)
                expect(viewer.locator("#zoom")).to_have_text(label)
                wait_pdf(viewer)
                size = canvas.evaluate(
                    "e=>[parseFloat(e.style.width),parseFloat(e.style.height)]"
                )
                assert size == pytest.approx([n * factor for n in baseline], abs=1)
        frame = canvas.element_handle().owner_frame()
        assert (
            frame.evaluate("window.receivedDrawingClicks")
            == ["in", "fit", "out", "fit"] * 6
        )
