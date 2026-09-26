# formats/pdf.py
#
# Author: Patrick Beal
#
# Invoice as a PDF, typeset with Typst

import tempfile
from pathlib import Path

from timetracker.clock import format_duration
from timetracker.errors import TimeTrackerError
from timetracker.formats import header, range_label, text_value, total_row
from timetracker.invoice import InvoiceDocument, period_label
from timetracker.report import Report
from timetracker.user import address_lines, full_name


# Roboto travels with the package, so an invoice typesets the same on a Mac, on
# Windows, and on a bare WSL image that has no system fonts at all
FONT_DIR = Path(__file__).parent.parent / "fonts"


def render_pdf(document: InvoiceDocument, path: Path):
    try:
        import typst
    except ImportError:
        raise TimeTrackerError(
            "PDF output needs typst. Reinstall the app with `uv sync`."
        ) from None

    source = _typst_source(document)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Typst compiles from a file, so the generated source goes to a temp file
    with tempfile.TemporaryDirectory() as folder:
        typ_file = Path(folder) / "invoice.typ"
        typ_file.write_text(source)
        _compile(typst, typ_file, path, Path(folder))


def _compile(typst, source_file: Path, path: Path, root: Path):
    """
    Typesets with only the bundled fonts, so nothing the machine has installed
    can change the result. Older typst builds lack the flags, and fall back to
    whatever they can find.
    """
    try:
        typst.compile(
            source_file,
            output=path,
            root=root,
            font_paths=[FONT_DIR],
            ignore_system_fonts=True,
        )
    except TypeError:
        typst.compile(source_file, output=path, root=root)


# The palette of docs/invoice-example/, shared with the spreadsheet
INK = "#223642"
STRIPE = "#f6f8f9"
FONT = "Roboto"  # the one face bundled in fonts/, so it is always present


def _typst_source(document: InvoiceDocument) -> str:
    user = document.user
    sender = [full_name(user), *address_lines(user)]

    title = f"HOURLY INVOICE \\\n{_esc(period_label(document))}"
    if document.predicted:
        title += " \\\n(DRAFT)"

    lines = [
        '#set page(paper: "us-letter", margin: 0.7in)',
        f'#set text(size: 10pt, font: "{FONT}")',
        f'#let ink = rgb("{INK}")',
        f'#let stripe = rgb("{STRIPE}")',
        "",
        # The banner: title on the left, invoice number on the right
        "#block(fill: ink, inset: 12pt, width: 100%)[",
        "  #grid(",
        "    columns: (1fr, auto),",
        "    align: (left + horizon, right + top),",
        f'    text(fill: white, size: 18pt, weight: "bold")[{title}],',
        f"    text(fill: white)[*INVOICE NUMBER:* {document.number}],",
        "  )",
        "]",
        "",
        "#v(1.2em)",
        # Each address block sits over a rule, as in the example
        _address_block("From:", sender),
        "",
        _address_block("Bill To:", [document.client_name]),
        "",
        "#v(0.4em)",
        "#table(",
        "  columns: (auto, auto, auto, auto, 1fr),",
        "  align: (left + horizon, left + horizon, right + horizon, "
        "right + horizon, left + horizon),",
        "  inset: 7pt,",
        "  stroke: 0.5pt + ink,",
        # Row 0 is the header; data rows alternate white and the stripe shade
        "  fill: (_, row) => if row == 0 { ink } "
        "else if calc.odd(row) { white } else { stripe },",
        "  table.header(",
        "    "
        + ", ".join(
            f'text(fill: white, weight: "bold")[{heading}]'
            for heading in ("Date", "Project", "Hours", "Amount", "Description")
        )
        + ",",
        "  ),",
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


def _address_block(heading: str, body_lines: list[str]) -> str:
    """A bold label and its lines, each underlined by a rule like the example's."""
    rule = "#line(length: 100%, stroke: 1.5pt + ink)"
    return "\n".join(
        [
            f'#text(size: 12pt, weight: "bold")[{heading}]',
            rule,
            # Bare, not wrapped in brackets: markup would print those literally
            _block(body_lines),
            rule,
        ]
    )


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


# --- Reports ---

# Wider reports get a landscape page so the columns fit
LANDSCAPE_ABOVE = 5


def render_report_pdf(report: Report, path: Path):
    """A report as a PDF table, with a total row."""
    try:
        import typst
    except ImportError:
        raise TimeTrackerError(
            "PDF output needs typst. Reinstall the app with `uv sync`."
        ) from None

    source = _report_source(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        typ_file = Path(folder) / "report.typ"
        typ_file.write_text(source)
        _compile(typst, typ_file, path, Path(folder))


def _report_source(report: Report) -> str:
    flipped = ", flipped: true" if len(report.fields) > LANDSCAPE_ABOVE else ""
    # The description takes the leftover width; everything else fits its content
    widths = ", ".join(
        "1fr" if field == "description" else "auto" for field in report.fields
    )

    lines = [
        f'#set page(paper: "us-letter", margin: 0.7in{flipped})',
        f'#set text(size: 9pt, font: "{FONT}")',
        "#show heading: set text(size: 15pt)",
        "",
        "= Time Report",
        _esc(range_label(report)),
        "",
        "#v(0.5em)",
        "#table(",
        f"  columns: ({widths}),",
        "  align: ("
        + ", ".join(
            "right" if field in ("id", "duration", "rate", "pay") else "left"
            for field in report.fields
        )
        + "),",
        "  table.header("
        + ", ".join(f"[*{_esc(header(report, f))}*]" for f in report.fields)
        + "),",
    ]

    for row in report.rows:
        lines.append("  " + ", ".join(_report_cell(f, row[f]) for f in report.fields))
        lines[-1] += ","

    total = total_row(report)
    lines += [
        "  table.hline(),",
        "  "
        + ", ".join(
            f"[*{_cell_body(f, total[f])}*]" if total[f] is not None else "[]"
            for f in report.fields
        )
        + ",",
        ")",
    ]
    return "\n".join(lines) + "\n"


def _report_cell(field: str, value) -> str:
    return f"[{_cell_body(field, value)}]"


def _cell_body(field: str, value) -> str:
    """Values as text, with newlines turned into Typst line breaks."""
    text = text_value(field, value)
    return _block(text.split("\n")) if "\n" in text else _esc(text)
