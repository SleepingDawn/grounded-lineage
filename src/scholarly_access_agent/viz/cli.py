"""`scholarly-access-agent viz <kind> <topic folder>`: build one chart and write its HTML page + .vl.json."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import effects, lineage_charts, matrix, novelty
from .common import VizError, today, write_chart

KINDS = {
    "effects": "Dot-and-whisker of evidence results matching --quantity, coloured by design, filled by read depth.",
    "matrix": "Gap-matrix heatmap (ideas/matrix.json, else the first table of ideas/matrix.md -> matrix.json).",
    "novelty": "Per card: closest papers by overlap grade (None..Exact), filled by read depth, verdict at right.",
    "adoption": "Per-year forward-only adoption share from data/adoption.json (latest entry, or --id N).",
    "timeline": "Forward citations by year and the RPYS spectrum with chosen peaks, from data/analysis.json.",
}
TITLES = {"effects": "효과 크기", "matrix": "공백 행렬", "novelty": "새로움 판정", "adoption": "방법 채택 비율",
          "timeline": "인용 시간선"}


def _band(text: str) -> tuple[float, float]:
    try:
        lo, hi = (float(x) for x in text.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--band takes LO,HI, e.g. 1.3,1.4") from exc
    return lo, hi


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scholarly-access-agent viz",
                                 description="Vega-Lite charts from a topic folder, written as standalone HTML "
                                             "(+ .vl.json) for ![caption](figs/x.html) report embedding.")
    sub = ap.add_subparsers(dest="kind", required=True)
    for kind, help_text in KINDS.items():
        p = sub.add_parser(kind, help=help_text, description=help_text)
        p.add_argument("topic", help="topic folder (holds evidence/, ideas/, data/)")
        p.add_argument("-o", "--out", help=f"output HTML; a relative path is inside the topic folder "
                                           f"(default figs/{kind}.html)")
        p.add_argument("--date", help="date shown in the footer (default today)")
        if kind == "effects":
            p.add_argument("--quantity", required=True, help="regex on results[].quantity (case-insensitive)")
            p.add_argument("--unit", help="keep only results in this unit (needed when units are mixed)")
            p.add_argument("--band", type=_band, metavar="LO,HI", help="shaded reference band, e.g. an experiment range")
            p.add_argument("--band-label", help="label for the band")
            p.add_argument("--sort", choices=("year", "value"), default="year", help="row order (default year)")
        if kind == "adoption":
            p.add_argument("--id", help="adoption entry id (3 or adoption#3); default the latest")
        if kind == "matrix":
            p.add_argument("--no-write-json", action="store_true",
                           help="do not write ideas/matrix.json when parsing matrix.md")
    return ap


def build(kind: str, topic: Path, a: argparse.Namespace) -> tuple[dict, dict]:
    if kind == "effects":
        return effects.build(topic, a.quantity, unit=a.unit, band=a.band, band_label=a.band_label, sort=a.sort)
    if kind == "matrix":
        return matrix.build(topic, write_json=not a.no_write_json)
    if kind == "novelty":
        return novelty.build(topic)
    if kind == "adoption":
        return lineage_charts.build_adoption(topic, a.id)
    return lineage_charts.build_timeline(topic)


def default_name(kind: str, a: argparse.Namespace) -> str:
    if kind == "effects":
        slug = re.sub(r"[^a-z0-9]+", "-", a.quantity.lower()).strip("-")[:30]
        return f"effects-{slug}.html" if slug else "effects.html"
    return f"{kind}.html"


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    a = parser().parse_args(argv)
    topic = Path(a.topic).expanduser()
    if not topic.is_dir():
        print(f"viz: not a folder: {a.topic}", file=sys.stderr)
        return 2
    try:
        spec, meta = build(a.kind, topic, a)
    except VizError as exc:
        print(f"viz {a.kind}: {exc}", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path("figs") / default_name(a.kind, a)
    if not out.is_absolute():
        out = topic / out
    if out.suffix.lower() != ".html":
        out = out.with_suffix(".html")
    caption = f"자료: {meta['source']}" + "".join(f" · {n}" for n in meta.get("notes") or []) \
        + f" · 작성 {a.date or today()}"
    title = TITLES[a.kind] + (f" — {topic.resolve().name}")
    html_path, vl_path = write_chart(spec, out, title, caption)
    print(f"wrote {html_path}")
    print(f"      {vl_path}")
    print(caption)
    return 0
