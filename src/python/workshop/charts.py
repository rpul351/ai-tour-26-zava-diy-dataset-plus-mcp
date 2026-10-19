"""Draw simple charts from figures the agent has already retrieved.

The model supplies labels and values. The service checks every value against the data returned in the
conversation before anything is drawn, so a chart cannot show a number no tool returned.
"""

import math
import os
import re
import secrets
import textwrap
import time
from pathlib import Path

CHART_DIR = Path(os.getenv("CHART_DIR") or Path(__file__).resolve().parents[3] / "logs" / "charts")
CHART_NAME = re.compile(r"c[0-9a-f]{20}\.png")
KINDS = {"bar", "barh", "line", "histogram"}
MAX_POINTS = 40
MAX_VALUES = 1000
MAX_TEXT = 120
KEEP_SECONDS = 24 * 3600


def valid_chart_name(name: str) -> bool:
    return bool(CHART_NAME.fullmatch(name or ""))


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(spec) -> tuple[dict | None, str | None]:
    """Return a cleaned spec, or a plain reason it cannot be drawn."""
    if not isinstance(spec, dict):
        return None, "the chart request must be a JSON object."
    kind = spec.get("kind")
    if kind not in KINDS:
        return None, f"kind must be one of: {', '.join(sorted(KINDS))}."
    title = str(spec.get("title") or "").strip()[:MAX_TEXT]
    if not title:
        return None, "give the chart a title."
    values = spec.get("values")
    if not isinstance(values, list) or not values or not all(_is_number(v) for v in values):
        return None, "values must be a non-empty list of numbers."
    clean = {
        "kind": kind,
        "title": title,
        "x_label": str(spec.get("x_label") or "")[:60],
        "y_label": str(spec.get("y_label") or "")[:60],
        "values": values,
    }
    if kind == "histogram":
        if len(values) < 2 or len(values) > MAX_VALUES:
            return None, f"a histogram needs 2 to {MAX_VALUES} values."
        bins = spec.get("bins", 10)
        clean["bins"] = bins if isinstance(bins, int) and not isinstance(bins, bool) and 2 <= bins <= 30 else 10
        return clean, None
    labels = spec.get("labels")
    if not isinstance(labels, list) or len(labels) != len(values) or not all(isinstance(x, str) for x in labels):
        return None, "labels must be a list of text, one for each value."
    if len(values) > MAX_POINTS:
        return None, f"at most {MAX_POINTS} bars or points; summarise or pick the top ones."
    clean["labels"] = [x[:80] for x in labels]
    return clean, None


def _text(value: str) -> str:
    return value.replace("$", r"\$")


def draw(spec: dict) -> str:
    """Draw the chart as a PNG and return its file name. Blocking, so call it from a thread."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - KEEP_SECONDS
    for old in CHART_DIR.glob("*.png"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    try:
        values, kind = spec["values"], spec["kind"]
        if kind == "bar" and (len(values) > 8 or max(len(x) for x in spec["labels"]) > 14):
            kind = "barh"  # long labels or many bars read better sideways
        if kind == "barh":
            spec = {**spec, "labels": [textwrap.fill(x, 38) for x in spec["labels"]]}
            fig.set_size_inches(8, max(4.5, 0.6 * len(values) + 1.5))
        if kind == "histogram":
            ax.hist(values, bins=spec["bins"], edgecolor="white")
            ax.set_ylabel(_text(spec["y_label"] or "Count"))
        elif kind == "barh":
            bars = ax.barh([_text(x) for x in spec["labels"]][::-1], values[::-1])
            ax.bar_label(bars, labels=[f"{v:,.10g}" for v in values[::-1]], padding=3)
            ax.margins(x=0.12)
            ax.set_ylabel(_text(spec["y_label"]))
        elif kind == "line":
            ax.plot([_text(x) for x in spec["labels"]], values, marker="o")
            ax.set_ylabel(_text(spec["y_label"]))
        else:
            bars = ax.bar([_text(x) for x in spec["labels"]], values)
            ax.bar_label(bars, labels=[f"{v:,.10g}" for v in values], padding=3)
            ax.margins(y=0.12)
            ax.set_ylabel(_text(spec["y_label"]))
        ax.set_title(_text(spec["title"]))
        ax.set_xlabel(_text(spec["x_label"]))
        if kind in ("bar", "line") and max(len(x) for x in spec["labels"]) > 6:
            plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
        ax.grid(axis="y" if kind != "barh" else "x", alpha=0.3)
        fig.tight_layout()
        name = "c" + secrets.token_hex(10) + ".png"
        fig.savefig(CHART_DIR / name, dpi=110)
    finally:
        plt.close(fig)
    return name
