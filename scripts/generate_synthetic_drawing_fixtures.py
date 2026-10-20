from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1] / "drawing_corpus" / "synthetic"

FIXTURES = {
    "clean_digital.pdf": [
        "GLOBAL UNITS: IN",
        "PLATE OUTSIDE DIAMETER: 8.000 IN",
        "BORE DIAMETER: 2.375 IN",
        "PLATE THICKNESS: 0.250 IN",
        "MATERIAL: 316 SS",
        "QUANTITY: 4",
        "BORE TOLERANCE: +0.002 / -0.002 IN",
        "CHAMFER: 0.030 IN X 45 DEG",
        "MARKING: FE-101",
        "CUSTOMER PART NUMBER: CP-1001",
        "DRAWING NUMBER: DWG-1001",
        "REVISION: B",
    ],
    "missing_field.pdf": [
        "GLOBAL UNITS: IN",
        "PLATE OUTSIDE DIAMETER: 6.000 IN",
        "BORE DIAMETER: 1.500 IN",
        "MATERIAL: 304 SS",
        "QUANTITY: 1",
        "BORE TOLERANCE: +/-0.005 IN",
        "CHAMFER: NONE",
        "DRAWING NUMBER: DWG-MISSING",
        "REVISION: A",
    ],
    "ambiguous_conflict.pdf": [
        "GLOBAL UNITS: IN",
        "PLATE OUTSIDE DIAMETER: 8.000 IN",
        "BORE DIAMETER: 2.000 IN",
        "BORE DIAMETER: 2.125 IN",
        "PLATE THICKNESS: 0.250 IN",
        "MATERIAL: CARBON STEEL",
        "QUANTITY: 2",
        "BORE TOLERANCE: +/-0.005 IN",
        "CHAMFER: NONE",
    ],
    "unsupported_value.pdf": [
        "GLOBAL UNITS: IN",
        "PLATE OUTSIDE DIAMETER: 60.000 IN",
        "BORE DIAMETER: 2.000 IN",
        "PLATE THICKNESS: 0.250 IN",
        "MATERIAL: TITANIUM",
        "QUANTITY: 1",
        "BORE TOLERANCE: +/-0.005 IN",
        "CHAMFER: NONE",
    ],
    "metric_normalization.pdf": [
        "GLOBAL UNITS: MM",
        "PLATE OUTSIDE DIAMETER: 203.200 MM",
        "BORE DIAMETER: 50.800 MM",
        "PLATE THICKNESS: 6.350 MM",
        "MATERIAL: 316 SS",
        "QUANTITY: 3",
        "BORE TOLERANCE: +/-0.127 MM",
        "CHAMFER: 0.762 MM X 45 DEG",
        "DRAWING NUMBER: DWG-METRIC",
        "REVISION: C",
    ],
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for filename, lines in FIXTURES.items():
        output = ROOT / filename
        pdf = canvas.Canvas(
            str(output), pagesize=letter, pageCompression=1, invariant=1
        )
        pdf.setTitle(f"Synthetic O-Plates fixture: {filename}")
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(54, 740, "SYNTHETIC TEST FIXTURE - NOT A CUSTOMER DRAWING")
        pdf.setFont("Helvetica", 11)
        y = 700
        for line in lines:
            pdf.drawString(72, y, line)
            y -= 28
        pdf.showPage()
        pdf.save()


if __name__ == "__main__":
    main()
