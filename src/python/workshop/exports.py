"""Write CSV and PDF files from figures the agent has already retrieved.

The model supplies columns and rows. The service checks every number against the data returned in the
conversation before a file is written, so an export cannot hold a figure no tool returned.
"""

import csv
import math
import os
import re
import secrets
import textwrap
import time
from datetime import date
from pathlib import Path

EXPORT_DIR = Path(os.getenv("EXPORT_DIR") or Path(__file__).resolve().parents[3] / "logs" / "exports")
EXPORT_NAME = re.compile(r"e[0-9a-f]{20}\.(csv|pdf)")
MAX_ROWS = 1000
MAX_COLUMNS = 20
MAX_TEXT = 200
KEEP_SECONDS = 24 * 3600
PDF_ROWS_PER_PAGE = 24
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


def valid_export_name(name: str) -> bool:
    return bool(EXPORT_NAME.fullmatch(name or ""))


def media_type(name: str) -> str:
    return MEDIA_TYPES[name.rsplit(".", 1)[1]]


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(spec) -> tuple[dict | None, str | None]:
    """Return a cleaned spec, or a plain reason the file cannot be written."""
    if not isinstance(spec, dict):
        return None, "the export request must be a JSON object."
    fmt = str(spec.get("format") or "").lower()
    if fmt not in ("csv", "pdf"):
        return None, "format must be csv or pdf."
    title = str(spec.get("title") or "").strip()[:MAX_TEXT]
    if not title:
        return None, "title is required."
    columns = spec.get("columns")
    if not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS or not all(isinstance(c, str) and c.strip() for c in columns):
        return None, f"columns must be 1 to {MAX_COLUMNS} non-empty names."
    rows = spec.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, "rows must be a non-empty list."
    if len(rows) > MAX_ROWS:
        return None, f"at most {MAX_ROWS} rows; narrow the question or export the top rows."
    clean_rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            return None, f"every row must be a list with exactly {len(columns)} cells, one per column."
        cells = []
        for cell in row:
            if cell is None or isinstance(cell, str):
                cells.append(None if cell is None else cell[:MAX_TEXT])
            elif _is_number(cell):
                cells.append(cell)
            else:
                return None, "cells must be text, numbers or null."
        clean_rows.append(cells)
    return {
        "format": fmt,
        "title": title,
        "note": str(spec.get("note") or "").strip()[:400],
        "columns": [c.strip()[:MAX_TEXT] for c in columns],
        "rows": clean_rows,
    }, None


def numbers(spec: dict) -> list[float]:
    """Every numeric cell, so each can be checked against the data the tools returned."""
    return [c for row in spec["rows"] for c in row if _is_number(c)]


def _safe_cell(cell):
    """Stop a spreadsheet from running a text cell as a formula."""
    if isinstance(cell, str) and re.match(r"[=+@\t\r]|-(?!\d)", cell):
        return "'" + cell
    return cell


def _cleanup() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for old in [*EXPORT_DIR.glob("*.csv"), *EXPORT_DIR.glob("*.pdf")]:
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)


def _write_csv(spec: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads UTF-8
        writer = csv.writer(f)
        writer.writerow([_safe_cell(c) for c in spec["columns"]])
        for row in spec["rows"]:
            writer.writerow(["" if c is None else _safe_cell(c) for c in row])


def _write_pdf(spec: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    def text(value, width: int = 28) -> str:
        shown = "" if value is None else f"{value:,}" if isinstance(value, int) else f"{value:,.10g}" if isinstance(value, float) else str(value)
        return textwrap.fill(shown.replace("$", r"\$"), width)

    columns = [textwrap.fill(c.replace("$", r"\$"), 16) for c in spec["columns"]]
    pages = [spec["rows"][i : i + PDF_ROWS_PER_PAGE] for i in range(0, len(spec["rows"]), PDF_ROWS_PER_PAGE)]
    with PdfPages(path) as pdf:
        for number, page in enumerate(pages, 1):
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            try:
                ax.axis("off")
                fig.text(0.04, 0.95, spec["title"].replace("$", r"\$"), fontsize=14, weight="bold", va="top")
                if spec["note"]:
                    fig.text(0.04, 0.915, textwrap.fill(spec["note"].replace("$", r"\$"), 150), fontsize=8, va="top")
                table = ax.table(
                    cellText=[[text(c) for c in row] for row in page],
                    colLabels=columns,
                    loc="upper center",
                    cellLoc="left",
                )
                table.auto_set_font_size(False)
                table.set_fontsize(7.5)
                table.auto_set_column_width(list(range(len(columns))))
                table.scale(1, 1.6)
                for (r, _), cell in table.get_celld().items():
                    if r == 0:
                        cell.set_facecolor("#e8eef5")
                        cell.set_text_props(weight="bold")
                fig.text(0.04, 0.03, f"Zava Inventory Advisor. Snapshot {date.today().isoformat()}. Page {number} of {len(pages)}.", fontsize=7, color="#555555")
                pdf.savefig(fig)
            finally:
                plt.close(fig)


def write(spec: dict) -> str:
    """Write the file and return its name. Blocking, so call it from a thread."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup()
    name = "e" + secrets.token_hex(10) + "." + spec["format"]
    (_write_csv if spec["format"] == "csv" else _write_pdf)(spec, EXPORT_DIR / name)
    return name
