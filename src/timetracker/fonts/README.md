# Bundled fonts

Roboto, by Christian Robertson, under the Apache License 2.0 (`LICENSE.txt`).

Invoice PDFs are typeset with these files rather than whatever the machine
happens to have installed, so an invoice looks the same on macOS, Windows, and
WSL. `formats/pdf.py` hands the directory to Typst and turns system fonts off.

Spreadsheets can't embed fonts, so they ask for Arial instead, which Excel has
on both Windows and macOS.
