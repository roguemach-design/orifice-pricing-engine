"""Optional static HTML renders, not browser screenshots or client-compatibility proof.
Run after demo: python -m frozen_plate.render_previews
Requires weasyprint==68.1 and Poppler pdftoppm (review tooling only).
"""

from pathlib import Path
import subprocess
import tempfile
from weasyprint import HTML, CSS


def main():
    output = Path("prototype_output/phase4")
    with tempfile.TemporaryDirectory() as temp:
        for stem in (
            "customer-email-preview",
            "customer-success",
            "internal-sourcing-preview",
            "superseded-link",
        ):
            document = HTML(filename=output / (stem + ".html")).render(
                stylesheets=[
                    CSS(
                        string="@page {size:1000px 1100px;margin:0} select{padding:12px;font-size:16px} code{font-size:12px;overflow-wrap:anywhere}"
                    )
                ]
            )
            if len(document.pages) != 1:
                raise ValueError("preview overflow: " + stem)
            pdf = Path(temp) / (stem + ".pdf")
            document.write_pdf(pdf)
            subprocess.run(
                [
                    "pdftoppm",
                    "-r",
                    "96",
                    "-singlefile",
                    "-png",
                    str(pdf),
                    str(output / stem),
                ],
                check=True,
            )
    print(
        "Four static HTML review renders generated; these are not browser screenshots."
    )


if __name__ == "__main__":
    main()
