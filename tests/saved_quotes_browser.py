"""Browser acceptance for the actual saved quote/account/cart UI; synthetic local data."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def review_app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("saved-quotes")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # No inherited payment, email, database, storage or authentication credentials.
    env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
    env["PYTHONPATH"] = str(ROOT)
    env['QUOTE_REVIEW_ORIGIN'] = f'http://127.0.0.1:{port}'
    log = (tmp / "streamlit.log").open("w+")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "tests/saved_quotes_review_app.py",
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--global.developmentMode=false",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        origin = f"http://127.0.0.1:{port}"
        for attempt in range(100):
            try:
                if urlopen(origin + "/_stcore/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("Local review fixture did not start")
        yield origin, tmp
    finally:
        process.terminate()
        process.wait(timeout=15)
        log.close()


def test_account_retrieval_purchasing_and_cart_screenshots(review_app):
    origin, out = review_app
    with sync_playwright() as browser:
        chromium = browser.chromium.launch()
        page = chromium.new_page(viewport={"width": 1440, "height": 1100})
        page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        expect.set_options(timeout=30000)
        page.goto(origin + "/My_Quotes?fixture_quote=1")
        expect(
            page.get_by_role("heading", name="My Quotes", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Review current pricing")
        ).to_be_visible()
        page.screenshot(path=str(out / "account-and-retrieval.png"), full_page=True)
        qid = page.get_by_label('Find a Quote by number').input_value()
        page.get_by_label('Find a Quote by number').fill('Q-NOT-AVAILABLE')
        page.get_by_role('button',name='Find a Quote',exact=True).click()
        expect(page.get_by_text('Quote not available for this account.',exact=True)).to_be_visible()
        page.get_by_label('Find a Quote by number').fill(qid)
        page.get_by_role('button',name='Find a Quote',exact=True).click()
        expect(page.get_by_role('button',name='Email saved PDF to me')).to_be_visible()
        page.screenshot(path=str(out/'find-by-number.png'),full_page=True)
        page.get_by_role('button',name='Email saved PDF to me').click()
        expect(page.get_by_text('Quote email captured for review. No email was sent.',exact=True)).to_be_visible()
        page.reload()
        email_url = page.get_by_role('link',name='Captured quote email link',exact=True).get_attribute('href')
        assert '/My_Quotes?quote='+qid in email_url
        page.goto(email_url)
        expect(page.get_by_role('button',name='Review current pricing')).to_be_visible()
        page.screenshot(path=str(out/'quote-email-return.png'),full_page=True)
        page.get_by_text("Share with Purchasing", exact=True).click()
        expect(
            page.get_by_role("button", name="Send purchasing invitation")
        ).to_be_visible()
        page.screenshot(path=str(out / "share-with-purchasing.png"), full_page=True)
        page.get_by_label('Purchaser email',exact=True).fill('purchasing@example.test')
        page.get_by_role('button',name='Send purchasing invitation').click()
        expect(page.get_by_text('Invitation captured for review. No email was sent.',exact=True)).to_be_visible()
        page.reload()
        invite_url=page.get_by_role('link',name='Captured invitation email link',exact=True).get_attribute('href')
        assert '/My_Quotes?quote='+qid+'&invite=' in invite_url
        expired_url=page.get_by_role('link',name='Expired synthetic invitation',exact=True).get_attribute('href')
        owner=page
        page=chromium.new_page(viewport={'width':1440,'height':1100})
        page.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(invite_url+'&actor=stranger')
        page.get_by_role('button',name='Accept purchasing invitation').click()
        expect(page.get_by_text('Quote not available for this account.',exact=True)).to_be_visible()
        page.screenshot(path=str(out/'wrong-buyer-denied.png'),full_page=True)
        page.goto(expired_url+'&actor=buyer')
        page.get_by_role('button',name='Accept purchasing invitation').click()
        expect(page.get_by_text('Quote not available for this account.',exact=True)).to_be_visible()
        page.screenshot(path=str(out/'expired-invitation-denied.png'),full_page=True)
        page.goto(invite_url+'&actor=buyer')
        page.get_by_role('button',name='Accept purchasing invitation').click()
        expect(
            page.get_by_text("Signed in as: purchasing@example.test", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Review current pricing").click()
        expect(
            page.get_by_role("button", name="Continue in Quote Cart")
        ).to_be_enabled()
        page.screenshot(path=str(out / "purchaser-price-review.png"), full_page=True)
        page.get_by_role("button", name="Continue in Quote Cart").click()
        expect(
            page.get_by_role("heading", name="Quote Cart", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("REVIEW PLATE", exact=False).first).to_be_visible()
        page.screenshot(path=str(out / "existing-cart-handoff.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(out / "existing-cart-mobile.png"), full_page=True)
        assert page.locator('[data-testid="stException"]').count() == 0
        owner.goto(origin+'/My_Quotes?quote='+qid)
        owner.get_by_text('Share with Purchasing',exact=True).click()
        # The first fixture invitation is expired; revoke the newly accepted one.
        owner.get_by_role('button',name='Revoke access',exact=True).last.click()
        page.goto(origin+'/My_Quotes?quote='+qid+'&actor=buyer')
        expect(page.get_by_text('Quote not available for this account.',exact=True)).to_be_visible()
        page.screenshot(path=str(out/'revoked-buyer-denied.png'),full_page=True)
        chromium.close()
