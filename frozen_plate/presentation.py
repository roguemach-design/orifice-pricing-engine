"""Local email rendering only. No delivery provider or live email calls."""

from email.message import EmailMessage
from datetime import datetime
from html import escape as e

TEMPLATE_VERSION = "frozen-plate-email-v1"
APPROVAL_COPY = (
    "By clicking below, you confirm that you have reviewed the attached drawing and "
    "approve the dimensions, material, quantity, and configured options shown for manufacture."
)
BUTTON = "VERIFY & APPROVE ATTACHED DRAWING"
CSS = """input[type=hidden]{display:none}button{min-height:54px;appearance:none}body{margin:0;background:#f2f4f7;color:#192637;font:16px/1.6 Arial,sans-serif}
main{max-width:640px;margin:48px auto;background:white;border:1px solid #dce2e8;border-radius:12px;overflow:hidden}
header{background:#0e1117;color:white;padding:26px 36px;letter-spacing:2px;font-weight:bold;font-size:24px}
header small{display:block;font-size:11px;font-weight:normal;letter-spacing:1.5px;color:#00bcd4}
article{padding:32px 36px}h1{font-size:27px;line-height:1.25;margin:0 0 20px}p{margin:16px 0}
.details{background:#f3f6f9;padding:18px 22px;border-left:3px solid #00bcd4;margin:22px 0}
.details div{padding:2px 0}button,.button{box-sizing:border-box;display:block;text-align:center;width:100%;background:#00bcd4;color:#0e1117;border:0;border-radius:5px;padding:17px 12px;font:bold 14px Arial;text-decoration:none;cursor:pointer}
footer{border-top:1px solid #e1e6eb;padding:20px 36px;font-size:12px;color:#607083}.attachment{display:block;border:1px solid #cbd6df;padding:12px;margin:20px 0;color:#145b80;text-decoration:none;border-radius:4px}.eyebrow{font-size:12px;letter-spacing:1.5px;color:#21734d;font-weight:bold}
@media(max-width:680px){main{margin:15px}article,header,footer{padding:24px}h1{font-size:24px}}"""


def page(body, title="O-Plates | Rogue Machine"):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{CSS}</style></head><body><main><header>O-PLATES<small>ROGUE MACHINE LLC</small></header><article>{body}</article><footer>Precision orifice plates • Rogue Machine LLC</footer></main></body></html>'


def details(context):
    return (
        '<div class="details">'
        + "".join(
            f"<div><b>{label}:</b> {e(str(context[key]))}</div>"
            for label, key in [
                ("Order", "order_id"),
                ("Line", "line_id"),
                ("Drawing", "drawing"),
                ("Revision", "revision"),
                ("Quantity", "quantity"),
            ]
        )
        + "</div>"
    )


def email_html(context, url, *, csrf=None, pdf_url=None):
    button = (
        f'<form action="{e(url, quote=True)}" method="post"><input type="hidden" name="csrf" value="{e(csrf, quote=True)}"><button type="submit">{BUTTON}</button></form>'
        if csrf is not None
        else f'<a class="button" href="{e(url, quote=True)}">{BUTTON}</a>'
    )
    attachment = (
        f'<a class="attachment" href="{e(pdf_url, quote=True)}">PDF attachment · {e(context["filename"])}</a>'
        if pdf_url
        else f'<div class="attachment">PDF attachment · {e(context["filename"])}</div>'
    )
    return page(
        "<h1>Your O-Plate drawing is ready for confirmation.</h1>"
        + details(context)
        + "<p>Please review the attached drawing carefully.</p>"
        + attachment
        + f"<p>{APPROVAL_COPY}</p>"
        + button
        + "<p>Questions about your drawing?<br>Reply to your O-Plates order contact.</p>"
    )


def success_html(context, approved_at, historical=False):
    display_date = datetime.fromisoformat(approved_at).strftime("%d %b %Y, %H:%M UTC")
    extra = (
        "<p>A newer drawing revision now requires separate approval. This records your earlier approval only.</p>"
        if historical
        else ""
    )
    return page(
        '<p class="eyebrow">DRAWING APPROVED</p><h1>YOUR ORDER IS IN PRODUCTION</h1>'
        + "<p>Your O-Plate drawing has been approved.</p>"
        + details(context)
        + f'<p>Revision {e(context["revision"])} was approved on {e(display_date)}.</p>'
        + extra
        + "<p>Thank you. Rogue Machine will coordinate the next steps for your order.</p>"
    )


def message_html(kind):
    messages = {
        "superseded": (
            "A newer drawing is available.",
            "Please review the most recent O-Plates confirmation email before approving the drawing.",
        ),
        "invalid": (
            "We could not use this approval link.",
            "Please contact your O-Plates order contact for a current confirmation drawing.",
        ),
        "pending": (
            "Your drawing is awaiting approval.",
            "This email client cannot securely submit the approval action. Please contact your O-Plates order contact.",
        ),
    }
    title, message = messages.get(kind, messages["invalid"])
    return page(f"<h1>{title}</h1><p>{message}</p>")


def mime_email(context, url, pdf):
    msg = EmailMessage()
    msg["From"] = "O-Plates prototype <no-send@example.invalid>"
    msg["To"] = "prototype-customer@example.invalid"
    msg["Subject"] = (
        f'O-Plates drawing confirmation — {context["drawing"]} {context["revision"]}'
    )
    msg.set_content(
        f"{APPROVAL_COPY}\n\n{BUTTON}\n{url}\n\nReview the attached PDF. Prototype only: no mail was sent."
    )
    msg.add_alternative(email_html(context, url), subtype="html")
    msg.add_attachment(
        pdf, maintype="application", subtype="pdf", filename=context["filename"]
    )
    return msg.as_bytes()
