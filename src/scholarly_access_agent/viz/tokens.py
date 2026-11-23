"""Design tokens: one JSON (data/design_tokens.json) for the report, the lineage map and the viz charts.

Each consumer names its CSS custom properties and the token each one takes (REPORT_VARS, LINEAGE_VARS,
VIZ_VARS); `css_vars()` emits the light `:root{...}` block plus the dark block twice (for the OS setting and
for an explicit `data-theme="dark"`). The report stylesheet is a checked-in file: its token block sits between
two markers and `python -m scholarly_access_agent.viz.tokens --write` rewrites it; the tests fail while it
disagrees with the JSON.

  python -m scholarly_access_agent.viz.tokens            # print the report block
  python -m scholarly_access_agent.viz.tokens --check    # exit 1 when snu-report.css is out of date
  python -m scholarly_access_agent.viz.tokens --write    # rewrite the block in snu-report.css
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TOKENS_FILE = DATA / "design_tokens.json"
REPORT_CSS = DATA / "quarto" / "snu-report.css"
BEGIN, END = "/* tokens:begin (generated from data/design_tokens.json; do not edit) */", "/* tokens:end */"
MODES = ("light", "dark")


@lru_cache(maxsize=1)
def tokens() -> dict:
    return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))


def font_stack(kind: str = "body") -> str:
    """CSS font-family list: names with spaces quoted, generic families bare."""
    generic = {"system-ui", "sans-serif", "serif", "monospace", "ui-monospace", "ui-sans-serif"}
    return ", ".join(f if f in generic else f'"{f}"' for f in tokens()["font"][kind])


def value(path: str, mode: str = "light") -> str:
    """'color.ink' / 'design.model' (per mode) or 'font.body' / 'size.chart_label' (same in both modes)."""
    group, name = path.split(".", 1)
    t = tokens()
    if group == "font":
        return font_stack(name)
    if group == "size":
        return f"{t['size'][name]}px"
    return t[group][mode][name]


def design_colors(mode: str = "light") -> dict[str, str]:
    t = tokens()["design"]
    return {k: t[mode][k] for k in t["order"]}


def design_labels() -> list[tuple[str, str]]:
    """[(key, Korean label)] in the fixed design order."""
    t = tokens()["design"]
    return [(k, t["label"][k]) for k in t["order"]]


def read_depth() -> dict[str, str]:
    return {k: v for k, v in tokens()["read_depth"].items() if not k.startswith("_")}


def _design_vars(prefix: str) -> dict[str, str]:
    return {f"{prefix}{k}": f"design.{k}" for k in tokens()["design"]["order"]}


# --snu-* names are also what the report sends to embedded pages (runtime/quarto_report.py EMBED_SCRIPT).
REPORT_VARS = {
    "--snu-ink": "color.ink", "--snu-muted": "color.muted", "--snu-accent": "color.accent",
    "--snu-rule": "color.rule", "--snu-rule-soft": "color.rule_soft", "--snu-head-bg": "color.head_bg",
    "--snu-zebra": "color.zebra", "--snu-callout": "color.callout", "--snu-surface": "color.surface",
    "--snu-page": "color.page", "--snu-band": "color.band", "--snu-code-bg": "color.code_bg",
    "--snu-code-ink": "color.code_ink", "--snu-font": "font.body", "--snu-mono": "font.mono",
    "--snu-size": "size.report_body",
}
LINEAGE_VARS = {
    "--bg": "color.page", "--surface": "color.surface", "--fg": "color.ink", "--muted": "color.muted",
    "--line": "color.rule", "--band": "color.head_bg", "--link": "color.accent",
    "--f-body": "font.body", "--f-mono": "font.mono",
}
VIZ_VARS = {
    "--fg": "color.ink", "--muted": "color.muted", "--c-surface": "color.surface", "--c-rule": "color.rule",
    "--c-band": "color.band", "--c-band_edge": "color.band_edge",
}


def report_vars() -> dict[str, str]:
    return {**REPORT_VARS, **_design_vars("--snu-d-")}


def lineage_vars() -> dict[str, str]:
    return {**LINEAGE_VARS, **_design_vars("--d-")}


def viz_vars() -> dict[str, str]:
    return {**VIZ_VARS, **_design_vars("--c-d-")}


def _decls(mapping: dict[str, str], mode: str, sep: str) -> str:
    return sep.join(f"{name}: {value(path, mode)};" for name, path in mapping.items())


def css_vars(mapping: dict[str, str], pretty: bool = False) -> str:
    """`:root{light}`, then the dark values for prefers-color-scheme (unless data-theme="light") and for
    data-theme="dark". Only tokens that differ between modes are repeated in the dark blocks."""
    sep, end = ("\n  ", "\n") if pretty else (" ", " ")
    dark_only = {k: p for k, p in mapping.items() if value(p, "dark") != value(p, "light")}
    dark = _decls(dark_only, "dark", sep)
    return (f":root {{{sep}{_decls(mapping, 'light', sep)}{end}}}\n"
            f'@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{{sep}{dark}{end}}} }}\n'
            f':root[data-theme="dark"] {{{sep}{dark}{end}}}\n')


def viz_swap() -> tuple[dict[str, str], dict[str, str]]:
    """(LIGHT, DARK) colour strings the viz page swaps in a Vega-Lite spec when the theme is dark.

    Keys are the names the chart code uses. Two keys may share a light value only when they also share the
    dark one (the swap is by string)."""
    names = {"fg": "color.ink", "muted": "color.muted", "grid": "color.rule", "rule": "color.rule_soft",
             "surface": "color.surface", "band": "color.band", "band_edge": "color.band_edge"}
    names.update({f"d_{k}": f"design.{k}" for k in tokens()["design"]["order"]})
    return ({k: value(p, "light") for k, p in names.items()}, {k: value(p, "dark") for k, p in names.items()})


# ---------------------------------------------------------------- the report stylesheet

def report_block() -> str:
    return f"{BEGIN}\n{css_vars(report_vars(), pretty=True)}{END}"


def report_css_current(text: str | None = None) -> str | None:
    """The token block now in snu-report.css (None when the markers are missing)."""
    text = REPORT_CSS.read_text(encoding="utf-8") if text is None else text
    if BEGIN not in text or END not in text:
        return None
    return text[text.index(BEGIN): text.index(END) + len(END)]


def write_report_css() -> bool:
    text = REPORT_CSS.read_text(encoding="utf-8")
    current = report_css_current(text)
    if current is None:
        raise SystemExit(f"{REPORT_CSS}: token markers missing")
    new = text.replace(current, report_block())
    if new != text:
        REPORT_CSS.write_text(new, encoding="utf-8", newline="\n")
        return True
    return False


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--write" in args:
        print("rewrote" if write_report_css() else "unchanged", REPORT_CSS)
        return 0
    if "--check" in args:
        ok = report_css_current() == report_block()
        print("snu-report.css tokens " + ("in sync" if ok else "OUT OF DATE: run with --write"))
        return 0 if ok else 1
    print(report_block())
    return 0


if __name__ == "__main__":
    sys.exit(main())
