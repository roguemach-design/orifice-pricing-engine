"""O-Plates commercial quotation, ported from the owner-approved revision 2 renderer.

One function, render_quote(path, quote), draws the whole document from a plain dict so
the same layout handles one plate, many plates, and multi-page overflow. Page totals
("Page x of y") use a dry-run layout pass, then a real render.

Usage: python quote_pdf.py <fonts_dir> <assets_dir> <prices.json> <out_dir>
"""
import json, os, sys
from datetime import date, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from io import BytesIO
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from decimal import Decimal
from customer_safety import PRODUCT_FIELDS
from material_labels import MATERIAL_COPY

ASSETS = Path(__file__).resolve().parent / "assets"
for weight in ("400", "500", "600", "700"):
    path = ASSETS / "fonts" / f"Plex-{weight}.ttf"
    name = "P" + weight
    if path.exists():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    else:
        pdfmetrics.registerFont(pdfmetrics.Font(name, "Helvetica-Bold" if weight in ("600", "700") else "Helvetica", "WinAnsiEncoding"))

QUOTE_VALID_DAYS = 30
SUPPLIER = {"name": "Rogue Machine LLC", "addr1": "400 Public Rd",
            "city_state_zip": "Yorkville, OH 43971", "country": "United States",
            "phone": "+1 304-639-0595", "email": "sales@o-plates.com"}


def new_quote_meta():
    return {"quote_id": "Q-" + uuid4().hex[:10].upper(),
            "created_at": datetime.now(ZoneInfo("America/New_York"))}


def quote_filename(quote_id):
    return f"O-Plates_Quote_{quote_id}.pdf"


def document_from_cart(lines, customer, meta, pricing_ref):
    return {"quote_id": meta["quote_id"], "issued": meta["created_at"].astimezone(ZoneInfo("America/New_York")).date(),
            "customer": dict(customer), "pricing_ref": pricing_ref,
            "lines": [{"inputs": dict(l["inputs"]), "unit_price": l["unit_price"],
                       "total_price": l["line_total"],
                       "qty_mult": l.get("qty_discount_multiplier", 1),
                       "weight": l.get("estimated_total_weight_lb", 0)} for l in lines]}


def subtotal(lines):
    # Add authoritative extended prices; never derive them from rounded unit prices.
    return sum((Decimal(str(l["total_price"])) for l in lines), Decimal("0"))

# ---------- design tokens (print translation of the site palette) ----------
INK = HexColor("#0B0E14")        # deep charcoal: body text
NAVY = HexColor("#0F1420")       # dark navy: table header bar, rules
ACCENT = HexColor("#4B7DFF")     # accent blue: brand bar, step numbers
ACCENT_DK = HexColor("#2A55D6")  # accent for text on light fills (contrast)
TINT = HexColor("#EEF3FF")       # accent tint: status pill, ordering panel
PANEL = HexColor("#F4F6FA")      # neutral panel fill
RULE = HexColor("#D8DEE8")       # hairlines
MUTED = HexColor("#5A6578")      # labels, secondary text
SAMPLE = HexColor("#C2410C")     # mockup-only banner

W, H = LETTER
M = 42                          # side margin (0.58 in)
TOP = H - 40
FOOT_H = 46                     # footer zone height
BOTTOM = M + FOOT_H - 8         # lowest y content may use

COL_NUM, COL_DESC = M + 8, M + 34
COL_QTY, COL_UNIT, COL_EXT = W - M - 166, W - M - 82, W - M - 8   # right edges


def money(v): return f"${v:,.2f}"
def inch(v, p=3):
    """3 decimals minimum; keep a 4th only when it carries information (e.g. 0.0625)."""
    s = f"{v:.4f}"
    if s.endswith("0"):
        s = f"{v:.{p}f}"
    return f"{s} in"
def fdate(d): return d.strftime("%b %-d, %Y")


MATERIAL_SHORT = {k: v[0] for k, v in MATERIAL_COPY.items()}
MATERIAL = {k: v.replace(" SS", " Stainless Steel") for k, v in MATERIAL_SHORT.items()}


def spec_rows(i):
    """Labels follow customer_safety.PRODUCT_FIELDS (units moved into the values).
    Rows are built only from QuoteRequest fields present on the line; nothing is defaulted."""
    rows = []
    for key in ("material", "thickness", "paddle_dia", "bore_dia", "bore_tolerance", "handle_width", "handle_length_from_bore"):
        if key not in i or i[key] is None:
            continue
        label = PRODUCT_FIELDS[key].split(" (")[0]
        value = MATERIAL.get(i[key], i[key]) if key == "material" else inch(i[key])
        if key == "bore_tolerance": value = "± " + value
        rows.append((label, str(value)))
    if "handle_hole_enabled" in i:
        if i["handle_hole_enabled"]:
            parts = []
            if i.get("handle_hole_diameter") is not None: parts.append("Ø" + inch(i["handle_hole_diameter"]))
            if i.get("handle_hole_center_from_handle_end") is not None: parts.append("center " + inch(i["handle_hole_center_from_handle_end"]) + " from end")
            value = ", ".join(parts) or "Selected; size per confirmation drawing"
        else: value = "None"
        rows.append((PRODUCT_FIELDS["handle_hole_enabled"], value))
    if "chamfer" in i:
        value = "None"
        if i["chamfer"]:
            value = inch(i["chamfer_width"]) if i.get("chamfer_width") else "Selected; size per confirmation drawing"
            if i.get("chamfer_angle_degrees"): value += f" × {i['chamfer_angle_degrees']:g}°"
            if i.get("chamfer_side"): value += f", {i['chamfer_side']} face"
        rows.append((PRODUCT_FIELDS["chamfer"], value))
    if "handle_label" in i:
        label = (i["handle_label"] or "").strip()
        rows.append((PRODUCT_FIELDS["handle_label"], f'“{label}”' if label and label != "No label" else "None"))
    if "ships_in_days" in i:
        rows.append((PRODUCT_FIELDS["ships_in_days"].split(" (")[0], f"{i['ships_in_days']} calendar days (est.)"))
    return rows


def line_title(i):
    return f"Handled orifice plate — {MATERIAL_SHORT.get(i['material'], i['material'])}, {inch(i['thickness'])}"


class Doc:
    def __init__(self, path, q, total_pages=None):
        self.q = q
        self.dry = total_pages is None
        self.c = canvas.Canvas(path if not self.dry else BytesIO(), pagesize=LETTER, invariant=1)
        self.c.setTitle(f"O-Plates Quotation {q['quote_id']}")
        self.c.setAuthor("O-Plates (Rogue Machine LLC)")
        self.c.setSubject("Commercial quotation - not an order, invoice or manufacturing drawing")
        self.page = 1
        self.total = total_pages or 0

    # ---------- primitives ----------
    def t(self, x, y, s, size=9, w="400", color=INK, anchor="l", cs=0):
        c = self.c
        c.setFillColor(color)
        width = pdfmetrics.stringWidth(s, "P" + w, size) + cs * max(len(s) - 1, 0)
        x = x - width if anchor == "r" else x - width / 2 if anchor == "c" else x
        to = c.beginText(); to.setFont("P" + w, size); to.setCharSpace(cs)
        to.setTextOrigin(x, y); to.textOut(s); to.setCharSpace(0); c.drawText(to)

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.6, r=0):
        c = self.c
        if fill is not None: c.setFillColor(fill)
        if stroke is not None: c.setStrokeColor(stroke); c.setLineWidth(lw)
        (c.roundRect if r else c.rect)(x, y, w, h, *( [r] if r else [] ),
                                        fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)

    def hline(self, x1, x2, y, color=RULE, lw=0.6):
        self.c.setStrokeColor(color); self.c.setLineWidth(lw); self.c.line(x1, y, x2, y)

    def wrap(self, s, size, w, width):
        # Split long tokens too: emails/markings must stay within the column.
        lines, cur = [], ""
        for word in str(s).split():
            trial = (cur + " " + word).strip()
            if pdfmetrics.stringWidth(trial, "P" + w, size) <= width:
                cur = trial
                continue
            if cur: lines.append(cur)
            cur = ""
            for char in word:
                if cur and pdfmetrics.stringWidth(cur + char, "P" + w, size) > width:
                    lines.append(cur); cur = ""
                cur += char
        if cur: lines.append(cur)
        return lines or [""]

    # ---------- page furniture ----------
    def sample_banner(self):
        if self.q.get("sample"):
            self.t(W / 2, H - 16, self.q.get("banner", "MOCKUP  ·  SYNTHETIC SAMPLE DATA  ·  NOT A VALID QUOTATION"),
                   6.5, "600", SAMPLE, "c", cs=0.8)

    def wordmark(self, x, y, size=24):
        self.rect(x, y - 2, 4, size * 0.78, fill=ACCENT)
        self.t(x + 11, y, "O-PLATES", size, "700", INK, cs=size * 0.06)

    def footer(self):
        q, y = self.q, M + 14
        self.hline(M, W - M, y + 18, RULE, 0.8)
        self.t(M, y + 6, "O-Plates  ·  o-plates.com  ·  sales@o-plates.com  ·  +1 304-639-0595", 7.5, "500", INK)
        self.t(M, y - 5, "O-Plates is the customer-facing brand of Rogue Machine LLC, "
                          "400 Public Rd, Yorkville, OH 43971, United States.", 6.5, "400", MUTED)
        self.t(W - M, y + 6, f"{q['quote_id']}  ·  Page {self.page} of {self.total or '?'}", 7.5, "600", INK, "r")
        self.t(W - M, y - 5, "Quotation only — not an order or invoice", 6.5, "400", MUTED, "r")

    def first_header(self):
        q = self.q
        self.sample_banner()
        y = TOP - 22
        self.wordmark(M, y)
        self.t(M + 11, y - 16, "Orifice plates, configured and priced online", 8.5, "400", MUTED)
        # right: title + meta
        self.t(W - M, y, "QUOTATION", 19, "700", INK, "r", cs=2.2)
        meta = [("Quote no.", q["quote_id"])]
        if q.get("supersedes"):
            meta.append(("Supersedes", q["supersedes"]))
        meta += [("Date issued", fdate(q["issued"])),
                 ("Valid through", fdate(q["issued"] + timedelta(days=30)))]
        my = y - 18
        for lab, val in meta:
            self.t(W - M - 150, my, lab.upper(), 6.5, "600", MUTED, cs=0.5)
            self.t(W - M, my, val, 9, "600", INK, "r")
            my -= 12.5
        # status pill
        s = "PREPARED FOR PURCHASING REVIEW"
        sw = pdfmetrics.stringWidth(s, "P600", 6.8) + 0.6 * (len(s) - 1) + 16
        self.rect(W - M - sw, my - 6, sw, 14, fill=TINT, stroke=ACCENT, lw=0.6, r=7)
        self.t(W - M - sw / 2, my - 1.6, s, 6.8, "600", ACCENT_DK, "c", cs=0.6)
        top_rule = my - 18
        self.hline(M, W - M, top_rule, NAVY, 1.4)
        return top_rule

    def cont_header(self):
        self.sample_banner()
        y = TOP - 14
        self.wordmark(M, y, 15)
        self.t(W - M, y, f"QUOTATION {self.q['quote_id']}  (continued)", 9.5, "600", INK, "r", cs=0.4)
        self.hline(M, W - M, y - 12, NAVY, 1.4)
        return y - 12

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        return self.cont_header() - 14

    # ---------- blocks ----------
    def parties(self, y):
        q = self.q
        colw = (W - 2 * M - 14) / 2
        boxes = []
        sup = [("b", "Rogue Machine LLC"), ("", "O-Plates (customer-facing brand)"),
               ("", "400 Public Rd"), ("", "Yorkville, OH 43971"), ("", "United States"),
               ("", "+1 304-639-0595  ·  sales@o-plates.com")]
        cu = q["customer"]
        cust = []
        if cu.get("company"): cust.append(("b", cu["company"]))
        if cu.get("name"): cust.append(("", cu["name"]))
        for k in ("addr1", "addr2", "city_state_zip", "country"):
            if cu.get(k): cust.append(("", cu[k]))
        contact = "  ·  ".join(v for v in (cu.get("phone"), cu.get("email")) if v)
        if contact: cust.append(("", contact))
        pc = cu.get("purchasing") or " · ".join(cu.get(k, "").strip() for k in ("purchasing_name", "purchasing_email") if cu.get(k, "").strip())
        if pc:
            cust.append(("gap", ""))
            cust.append(("lab", "PURCHASING CONTACT"))
            cust.append(("", pc))
        if not cust:
            cust = [("i", "Customer details not provided")]
        cust = [(kind, part) for kind, value in cust for part in self.wrap(value, 9 if kind == "b" else 8.4, "600" if kind == "b" else "400", colw - 24)]
        lines = max(len(sup), len(cust))
        h = 26 + lines * 11.5
        for k, (title, rows) in enumerate((("SUPPLIER", sup), ("PREPARED FOR", cust))):
            x = M + k * (colw + 14)
            self.rect(x, y - h, colw, h, fill=PANEL)
            self.rect(x, y - h, 2.5, h, fill=ACCENT if k == 0 else NAVY)
            self.t(x + 12, y - 14, title, 6.8, "600", MUTED, cs=0.8)
            yy = y - 28
            for kind, s in rows:
                if kind == "gap":
                    yy -= 3; continue
                if kind == "lab":
                    self.t(x + 12, yy, s, 6.3, "600", MUTED, cs=0.6)
                else:
                    self.t(x + 12, yy, s, 9 if kind == "b" else 8.4,
                           "600" if kind == "b" else "400", MUTED if kind == "i" else INK)
                yy -= 11.5
        # small supplier logo (official asset, unaltered)
        logo = str(ASSETS / "Rogue Machine Logo.jpg")
        if os.path.exists(logo) and not self.dry:
            self.c.drawImage(logo, M + colw - 62, y - 22, width=50, height=50 * 713 / 2048, mask=None)
        return y - h - 12

    def summary(self, y):
        q = self.q
        lines = q["lines"]
        qty = sum(l["inputs"]["quantity"] for l in lines)
        lts = sorted({l["inputs"]["ships_in_days"] for l in lines})
        lt = " / ".join(str(d) for d in lts) + " days"
        sub = subtotal(lines)
        cells = [("LINE ITEMS", str(len(lines))), ("TOTAL QUANTITY", f"{qty} plate{'s' if qty != 1 else ''}"),
                 ("LEAD TIME (EST.)", lt), ("QUOTED SUBTOTAL", money(sub))]
        cw = (W - 2 * M) / 4
        h = 38
        self.hline(M, W - M, y, RULE); self.hline(M, W - M, y - h, RULE)
        for k, (lab, val) in enumerate(cells):
            x = M + k * cw
            if k: self.c.setStrokeColor(RULE); self.c.line(x, y - h + 7, x, y - 7)
            self.t(x + 10, y - 13, lab, 6.3, "600", MUTED, cs=0.7)
            self.t(x + 10, y - 29, val, 12.5 if k == 3 else 11, "700" if k == 3 else "600",
                   ACCENT_DK if k == 3 else INK)
        return y - h - 16

    def table_header(self, y):
        h = 18
        self.rect(M, y - h, W - 2 * M, h, fill=NAVY)
        ty = y - 12
        self.t(COL_NUM, ty, "#", 6.8, "600", white, cs=0.6)
        self.t(COL_DESC, ty, "ITEM AND SPECIFICATION", 6.8, "600", white, cs=0.6)
        self.t(COL_QTY, ty, "QTY", 6.8, "600", white, "r", cs=0.6)
        self.t(COL_UNIT, ty, "UNIT PRICE", 6.8, "600", white, "r", cs=0.6)
        self.t(COL_EXT, ty, "EXTENDED", 6.8, "600", white, "r", cs=0.6)
        return y - h

    SPEC_LAB = 128

    def spec_layout(self, rows):
        colw = (W - M - 8 - COL_DESC - 18) / 2
        half = (len(rows) + 1) // 2
        out = []
        for col in (rows[:half], rows[half:]):
            lw = max((pdfmetrics.stringWidth(l, "P500", 7.8) for l, _ in col), default=0) + 12
            out.append((lw, [(lab, self.wrap(val, 7.8, "400", colw - lw)) for lab, val in col]))
        n = max(sum(len(v) for _, v in items) for _, items in out)
        return colw, out, n

    def line_height(self, line):
        _, _, n = self.spec_layout(spec_rows(line["inputs"]))
        return 38 + n * 10.6 + 10

    def line_item(self, y, n, line):
        i = line["inputs"]
        y -= 16
        self.t(COL_NUM, y, f"{n:02d}", 9, "700", ACCENT_DK)
        self.t(COL_DESC, y, line_title(i), 10, "600", INK)
        self.t(COL_QTY, y, str(i["quantity"]), 10, "600", INK, "r")
        self.t(COL_UNIT, y, money(line["unit_price"]), 10, "500", INK, "r")
        self.t(COL_EXT, y, money(line["total_price"]), 10, "700", INK, "r")
        if line.get("qty_mult", 1) < 1:
            self.t(COL_UNIT, y - 11, f"incl. {round((1 - line['qty_mult']) * 100)}% qty pricing", 6.5, "500", MUTED, "r")
        colw, wrapped, nrows = self.spec_layout(spec_rows(i))
        yy0 = y - (22 if line.get("qty_mult", 1) < 1 else 18)
        for col, (lw, items) in enumerate(wrapped):
            x = COL_DESC + col * (colw + 18)
            yy = yy0
            for lab, vals in items:
                self.t(x, yy, lab, 7.8, "500", MUTED)
                for j, v in enumerate(vals):
                    self.t(x + lw, yy - j * 10.6, v, 7.8, "400", INK)
                yy -= len(vals) * 10.6
        bottom = yy0 - (nrows - 1) * 10.6 - 12
        self.hline(M, W - M, bottom, RULE)
        return bottom

    def totals_and_terms(self, y):
        q = self.q
        sub = subtotal(q["lines"])
        wt = sum(l.get("weight", 0) for l in q["lines"])
        # totals block (right)
        bw = 232
        bx = W - M - bw
        y -= 8
        rows = [("Quoted subtotal", money(sub), True),
                ("Shipping", "Selected at checkout", False),
                ("Sales tax", "Calculated at checkout, if applicable", False),
                ("Amount due", "Confirmed at checkout", False)]
        yy = y - 16
        self.t(bx, yy, rows[0][0], 10, "600", INK)
        self.t(W - M - 8, yy - 1, rows[0][1], 15, "700", INK, "r")
        yy -= 10
        self.hline(bx, W - M, yy, NAVY, 1.1)
        for lab, val, _ in rows[1:]:
            yy -= 14
            self.t(bx, yy, lab, 8.2, "500", MUTED)
            self.t(W - M - 8, yy, val, 8.2, "500", INK, "r")
        tot_bottom = yy - 8
        # shipping planning (left)
        self.t(M, y - 14, "SHIPPING PLANNING", 6.5, "600", MUTED, cs=0.7)
        self.t(M, y - 28, f"Estimated total weight: {wt:,.2f} lb", 8.4, "400", INK)
        note = ("Ships from the Ohio Valley. Carrier and service are selected at checkout; "
                "transit time is in addition to the manufacturing lead time.")
        for j, L in enumerate(self.wrap(note, 8.0, "400", bx - M - 24)):
            self.t(M, y - 41 - j * 10.4, L, 8.0, "400", MUTED)
        y = min(tot_bottom, y - 58) - 6

        # ordering + terms panels, side by side
        colw = (W - 2 * M - 14) / 2
        live = False  # Phase 1: saved-quote ordering copy is intentionally unavailable.
        link = f"o-plates.com/quotes/{q['quote_id']}"
        steps = [
            f"View or order this quote at {link}. Sign in to open it, or find it under My Quotes in your account.",
            "Select Review & Order. Current prices and lead times are confirmed before payment.",
            "Choose shipping and pay through secure Stripe checkout.",
            "Review and approve the confirmation drawing sent with your order. Manufacture follows approval.",
        ] if live else [
            "Sign in at o-plates.com and open the configurator.",
            "Enter each line exactly as specified on this quotation and add it to your cart.",
            "Review the current price and lead time. The checkout amount governs.",
            "Select shipping and pay through secure Stripe checkout.",
            "Review and approve the confirmation drawing sent with your order. Manufacture follows approval.",
        ]
        terms = [
            f"This quotation may be referenced through {fdate(q['issued'] + timedelta(days=30))} (30 days).",
            "Prices and available lead times are revalidated at checkout and may change.",
            "Lead time is an estimated ship time, not a guaranteed delivery date. Drawing review and changes can affect timing.",
            "Plates are made to order to the specifications listed. Any change creates a new quote revision with its own number.",
            "This is a quotation only. It is not an order, an invoice or an approved manufacturing drawing.",
        ]
        def panel_h(items, num):
            n = 0
            for s in items:
                n += len(self.wrap(s, 7.9, "400", colw - (40 if num else 32)))
            return 28 + n * 10.2 + len(items) * 3 + 28
        h = max(panel_h(steps, True), panel_h(terms, False))
        if y - h < BOTTOM:
            y = self.new_page()
        for k, (title, items) in enumerate((("HOW TO ORDER FROM THIS QUOTATION", steps), ("QUOTATION TERMS", terms))):
            x = M + k * (colw + 14)
            self.rect(x, y - h, colw, h, fill=TINT if k == 0 else PANEL)
            self.rect(x, y - h, 2.5, h, fill=ACCENT if k == 0 else NAVY)
            self.t(x + 12, y - 15, title, 6.8, "600", ACCENT_DK if k == 0 else MUTED, cs=0.8)
            yy = y - 30
            for n, s in enumerate(items, 1):
                if k == 0:
                    self.c.setFillColor(ACCENT); self.c.circle(x + 18, yy + 2.8, 5.2, fill=1, stroke=0)
                    self.t(x + 18, yy + 0.4, str(n), 6.5, "700", white, "c")
                    tx, tw_ = x + 29, colw - 40
                else:
                    self.c.setFillColor(NAVY); self.c.rect(x + 13, yy + 2, 2.6, 2.6, fill=1, stroke=0)
                    tx, tw_ = x + 21, colw - 32
                for j, L in enumerate(self.wrap(s, 7.9, "400", tw_)):
                    self.t(tx, yy - j * 10.2, L, 7.9, "400", INK)
                yy -= len(self.wrap(s, 7.9, "400", tw_)) * 10.2 + 3
            if k == 0:
                self.hline(x + 12, x + colw - 12, y - h + 28, HexColor("#C9D6FB"))
                if live:
                    self.t(x + 12, y - h + 17, "Ordering for a colleague? Ask them to use Share with Purchasing.", 7.4, "600", INK)
                    self.t(x + 12, y - h + 7, f"PO, invoicing or vendor setup: sales@o-plates.com, ref. {q['quote_id']}.", 7.4, "400", INK)
                else:
                    self.t(x + 12, y - h + 17, "Purchase order, invoicing or vendor setup?", 7.6, "600", INK)
                    self.t(x + 12, y - h + 7, f"sales@o-plates.com · Reference {q['quote_id']} before ordering.", 6.9, "400", INK)
            else:
                self.t(x + 12, y - h + 17, f"Pricing reference: {q['pricing_ref']}", 7.0, "400", MUTED)
                self.t(x + 12, y - h + 7, "Terms of Sale: o-plates.com/terms.html", 7.0, "500", INK)
                self.c.linkURL("https://www.o-plates.com/terms.html", (x + 12, y - h + 5, x + colw - 12, y - h + 15), relative=0)
        return y - h

    # ---------- document ----------
    def build(self):
        y = self.first_header() - 14
        y = self.parties(y)
        y = self.summary(y)
        y = self.table_header(y)
        for n, line in enumerate(self.q["lines"], 1):
            if self.line_height(line) > TOP - 58 - BOTTOM:
                raise ValueError("A specification exceeds a full page; shorten the customer marking before generating.")
            if y - self.line_height(line) < BOTTOM:
                y = self.new_page()
                y = self.table_header(y)
            y = self.line_item(y, n, line)
        need = 80
        if y - need < BOTTOM:
            y = self.new_page()
        self.totals_and_terms(y)
        self.footer()
        self.c.showPage()
        if not self.dry:
            self.c.save()
        return self.page


def render_quote(path, q):
    pages = Doc(path, q).build()          # dry run for page count
    Doc(path, q, total_pages=pages).build()
    return pages


def render_quote_pdf(doc: dict) -> bytes:
    """Render an immutable priced snapshot; no API, pricing or session side effects."""
    output = BytesIO()
    render_quote(output, doc)
    return output.getvalue()
