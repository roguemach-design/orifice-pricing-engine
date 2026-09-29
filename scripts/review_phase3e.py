"""Development-only Phase 3E exports; run from repository root.

--reference /path/to/owner-crop.png optionally creates a debug comparison.
--update-fixture explicitly refreshes the hash after intentional visual changes.
"""

import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manufacturing_drawing import text
from reportlab.pdfgen.canvas import Canvas

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path)
parser.add_argument("--update-fixture", action="store_true")
args = parser.parse_args()
subprocess.run(
    [sys.executable, "prototype_manufacturing.py", "--chamfer-review"], check=True
)
out = Path("prototype_output")
main = out / "current/OP-PROTOTYPE-001"
chamfer = out / "chamfer-review/OP-EXAMPLE-CHAMFER-NOT-DEFAULT"
debug = out / "debug"
debug.mkdir(exist_ok=True)
for stem in (main, chamfer):
    subprocess.run(
        [
            "pdftoppm",
            "-scale-to",
            "1200",
            "-singlefile",
            "-png",
            str(stem) + ".pdf",
            str(stem),
        ],
        check=True,
    )
subprocess.run(
    [
        "pdftoppm",
        "-r",
        "240",
        "-x",
        "1220",
        "-y",
        "1610",
        "-W",
        "680",
        "-H",
        "560",
        "-singlefile",
        "-png",
        str(chamfer) + ".pdf",
        str(debug / "phase3e-chamfer-detail"),
    ],
    check=True,
)
if args.reference:
    temporary = debug / "comparison.pdf"
    c = Canvas(str(temporary), pagesize=(1500, 1000), invariant=1)
    text(c, 35, 970, "OWNER REFERENCE / COMPOSITION ONLY", 18)
    text(c, 800, 970, "O-PLATES / PHASE 3E / MANUFACTURING PRINT", 16)
    c.drawImage(
        str(args.reference),
        20,
        20,
        width=750,
        height=925,
        preserveAspectRatio=True,
        anchor="c",
    )
    c.drawImage(
        str(main) + ".png",
        795,
        20,
        width=695,
        height=925,
        preserveAspectRatio=True,
        anchor="c",
    )
    c.showPage()
    c.save()
    subprocess.run(
        [
            "pdftoppm",
            "-scale-to",
            "1600",
            "-singlefile",
            "-png",
            str(temporary),
            str(debug / "phase3e-comparison"),
        ],
        check=True,
    )
    temporary.unlink()
if args.update_fixture:
    Path("tests/fixtures/phase3e-manufacturing-print.sha256").write_text(
        sha256(main.with_suffix(".pdf").read_bytes()).hexdigest() + "\n"
    )
