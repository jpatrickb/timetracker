# formats/pdf.py
#
# Author: Patrick Beal
#
# Invoice as a PDF, typeset with Typst

import tempfile
from pathlib import Path

from timetracker.clock import format_duration
from timetracker.errors import TimeTrackerError
from timetracker.invoice import InvoiceDocument, period_label
from timetracker.user import address_lines, full_name


def render_pdf(document: InvoiceDocument, path: Path):
    try:
        import typst
    except ImportError:
        raise TimeTrackerError(
            "PDF output needs typst. Install it with `uv sync --extra pdf`."
        ) from None

    source = _typst_source(document)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Typst compiles from a file, so the generated source goes to a temp file
    with tempfile.TemporaryDirectory() as folder:
        typ_file = Path(folder) / "invoice.typ"
        typ_file.write_text(source)
        typst.compile(typ_file, output=path, root=Path(folder))


def _typst_source(document: InvoiceDocument) -> str:
    user = document.user
    sender = [full_name(user), *address_lines(user)]

    lines = [
        '#set page(paper: "us-letter", margin: 0.9in)',
        "#set text(size: 10pt)",
        "#show heading: set text(size: 16pt)",
        "",
        f"= HOURLY INVOICE {_esc(period_label(document))}",
        "",
        "#grid(",
        "  columns: (1fr, auto),",
        "  [",
        f"    *From:* \\\n{_block(sender)}",
        "",
        f"    *Bill To:* \\\n{_esc(document.client_name)}",
        "  ],",
        "  [",
        f"    #align(right)[*INVOICE NUMBER:* {document.number}"
        + (" \\\n#text(fill: red)[DRAFT]" if document.predicted else "")
        + "]",
        "  ],",
        ")",
        "",
        "#v(1em)",
        "#table(",
        "  columns: (auto, auto, auto, auto, 1fr),",
        "  align: (left, left, right, right, left),",
        "  table.header([*Date*], [*Project*], [*Hours*], [*Amount*], [*Description*]),",
    ]

    for row in document.rows:
        lines.append(
            "  "
            + ", ".join(
                [
                    f"[{row.day.strftime('%-m/%-d/%Y')}]",
                    f"[{_esc(row.project or '')}]",
                    f"[{format_duration(row.seconds)}]",
                    f"[{_money(row.cents)}]",
                    f"[{_block((row.description or '').split(chr(10)))}]",
                ]
            )
            + ","
        )

    lines += [
        "  table.hline(),",
        "  "
        + ", ".join(
            [
                "[*Total*]",
                "[]",
                f"[*{format_duration(document.total_seconds)}*]",
                f"[*{_money(document.total_cents)}*]",
                "[]",
            ]
        )
        + ",",
        ")",
    ]

    if user["payment_notes"]:
        lines += ["", "#v(1em)", _esc(user["payment_notes"])]

    return "\n".join(lines) + "\n"


def _money(cents: int | None) -> str:
    return "" if cents is None else f"\\${cents / 100:,.2f}"


def _block(text_lines: list[str]) -> str:
    """Joins lines with Typst's line break, skipping blank ones."""
    return " \\\n".join(_esc(line) for line in text_lines if line.strip())


def _esc(text: str) -> str:
    """Escapes the characters Typst treats as markup."""
    for character in ("\\", "#", "$", "*", "_", "`", "<", ">", "@", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text
