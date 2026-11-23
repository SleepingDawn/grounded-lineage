"""adoption and timeline: charts from a lineage data folder (data/adoption.json, data/analysis.json)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import VizError, finish


def data_dir(topic: Path) -> Path:
    for d in (topic / "data", topic):
        if (d / "analysis.json").exists() or (d / "adoption.json").exists():
            return d
    return topic / "data"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VizError(f"cannot read {path.name}: {exc}") from exc


# ---------------------------------------------------------------- adoption

def build_adoption(topic: Path, entry_id: str | None = None) -> tuple[dict, dict]:
    path = data_dir(topic) / "adoption.json"
    if not path.exists():
        raise VizError(f"no data/adoption.json under {topic} (run `lineage adoption` first)")
    log = _load(path)
    if isinstance(log, dict):
        log = [log]
    if not log:
        raise VizError("data/adoption.json is empty")
    if entry_id:
        want = entry_id if entry_id.startswith("adoption#") else f"adoption#{entry_id}"
        hits = [e for e in log if e.get("id") == want]
        if not hits:
            raise VizError(f"{want} not in data/adoption.json (ids: {', '.join(str(e.get('id')) for e in log)})")
        entry = hits[0]
    else:
        entry = log[-1]
    per_year = entry.get("per_year") or {}
    rows = []
    for y, v in sorted(per_year.items()):
        scope, method = int(v.get("scope") or 0), int(v.get("method") or 0)
        rows.append({"year": str(y), "scope": scope, "method": method,
                     "share": v.get("share", round(method / scope, 3) if scope else 0.0),
                     "counts": f"{method}/{scope}"})
    if not rows:
        raise VizError(f"{entry.get('id')} has no per-year counts")
    num, den = int(entry.get("numerator") or 0), int(entry.get("denominator") or 0)
    overall = entry.get("share", round(num / den, 3) if den else 0.0)
    top = max([r["share"] for r in rows] + [overall])
    ymax = min(1.0, max(0.1, -(-(top * 1.2) // 0.1) * 0.1))
    x = {"field": "year", "type": "ordinal", "title": "출판 연도", "axis": {"labelAngle": 0, "labelOverlap": True}}
    tooltip = [{"field": "year", "title": "연도"}, {"field": "share", "title": "비율", "format": ".0%"},
               {"field": "method", "title": "분자 (방법 일치)"}, {"field": "scope", "title": "분모 (대상 일치 전진 논문)"}]
    spec = finish({
        "width": "container", "height": 240, "autosize": {"type": "fit-x", "contain": "padding"},
        "layer": [
            {"data": {"values": rows}, "layer": [
                {"mark": {"type": "bar", "color": "#0072B2", "cornerRadiusTopLeft": 2, "cornerRadiusTopRight": 2},
                 "encoding": {"x": x, "y": {"field": "share", "type": "quantitative", "title": "채택 비율",
                                            "axis": {"format": ".0%"}, "scale": {"domain": [0, round(ymax, 2)]}},
                              "tooltip": tooltip}},
                {"mark": {"type": "text", "dy": -6, "fontSize": 9, "color": "#59636e",
                          "opacity": {"expr": f"width / {len(rows)} < 34 ? 0 : 1"}},
                 "encoding": {"x": x, "y": {"field": "share", "type": "quantitative"}, "text": {"field": "counts"},
                              "tooltip": tooltip}},
            ]},
            {"data": {"values": [{"share": overall, "text": f"전체 {num}/{den} ({overall:.0%})"}]}, "layer": [
                {"mark": {"type": "rule", "color": "#D55E00", "strokeDash": [4, 3], "strokeWidth": 1.4},
                 "encoding": {"y": {"field": "share", "type": "quantitative"}}},
                {"mark": {"type": "text", "align": "left", "baseline": "bottom", "dx": 2, "dy": -3, "fontSize": 10,
                          "color": "#D55E00"},
                 "encoding": {"y": {"field": "share", "type": "quantitative"}, "x": {"value": 0},
                              "text": {"field": "text"}}},
            ]},
        ],
    })
    meta = {"id": entry.get("id"), "years": len(rows), "notes": [],
            "source": (f"data/adoption.json {entry.get('id')} ({entry.get('date', '?')}): 전진 인용 논문 중 "
                       f"/{entry.get('scope')}/ 일치 {den}편, 그중 /{entry.get('method')}/ 일치 {num}편"
                       + (f", {entry.get('since')}년 이후" if entry.get("since") else "")
                       + (f"; 초록 없는 {entry.get('no_abstract')}편은 제목만 검색(하한)" if entry.get("no_abstract")
                          else ""))}
    return spec, meta


# ---------------------------------------------------------------- timeline

def _peak_label(tops: list) -> str:
    if not tops:
        return ""
    first = str(tops[0]).split("|")[0].strip()
    return re.sub(r"\s+\d{4}$", "", first)


def chosen_peaks(topic: Path, analysis: dict) -> tuple[list, str]:
    peaks = [p for p in analysis.get("rpys_peaks") or [] if isinstance(p, (list, tuple)) and len(p) >= 3]
    lineage = topic / "lineage.json"
    if lineage.exists():
        try:
            keep = (json.loads(lineage.read_text(encoding="utf-8")).get("evidence") or {}).get("rpys_years")
        except (OSError, json.JSONDecodeError):
            keep = None
        if keep:
            return sorted((p for p in peaks if p[0] in keep), key=lambda p: p[0]), "lineage.json evidence.rpys_years"
    return sorted(peaks[:6], key=lambda p: p[0]), "상위 6개 봉우리"


def build_timeline(topic: Path) -> tuple[dict, dict]:
    path = data_dir(topic) / "analysis.json"
    if not path.exists():
        raise VizError(f"no data/analysis.json under {topic} (run `lineage analyze` first)")
    an = _load(path)
    panels, parts, notes = [], [], []
    series = [s for s in an.get("rpys_series") or [] if isinstance(s, (list, tuple)) and len(s) >= 3]
    if series:
        total = sum(max(0, s[1]) for s in series) or 1
        acc, start = 0, series[0][0]
        for s in series:  # skip the sparse early tail: start where 0.5% of references are reached
            acc += max(0, s[1])
            if acc / total >= 0.005:
                start = s[0] // 10 * 10
                break
        peaks, peak_src = chosen_peaks(topic, an)
        start = min([start] + [p[0] for p in peaks])
        line = [{"year": s[0], "n": s[1], "dev": s[2]} for s in series if s[0] >= start]
        marks = [{"year": p[0], "n": p[1], "dev": p[2], "who": _peak_label(p[3] if len(p) > 3 else []),
                  "refs": "; ".join(str(t).split("|")[0].strip() + " " + (str(t).split("|")[2].strip()[:50]
                                    if len(str(t).split("|")) > 2 else "") for t in (p[3] if len(p) > 3 else [])[:3])
                  or "-"} for p in peaks if p[0] >= start]
        for i, m in enumerate(marks):  # alternate label heights so neighbouring peaks do not collide
            m["alt"] = i % 2
        xq = {"field": "year", "type": "quantitative", "title": "참고문헌 출판 연도",
              "axis": {"format": "d", "labelOverlap": True}, "scale": {"zero": False, "nice": False}}
        panels.append({
            "title": {"text": "RPYS 스펙트럼", "subtitle": f"표시 봉우리: {peak_src}"},
            "width": 600, "height": 190,
            "layer": [
                {"data": {"values": line},
                 "mark": {"type": "area", "color": "#56B4E9", "opacity": 0.25, "line": {"color": "#0072B2"}},
                 "encoding": {"x": xq, "y": {"field": "dev", "type": "quantitative",
                                             "title": "중앙값 대비 편차 (인용 수)"},
                              "tooltip": [{"field": "year", "title": "연도"}, {"field": "n", "title": "인용 수"},
                                          {"field": "dev", "title": "5년 중앙값 대비"}]}},
                {"data": {"values": marks}, "layer": [
                    {"mark": {"type": "point", "filled": True, "size": 46, "color": "#D55E00"},
                     "encoding": {"x": xq, "y": {"field": "dev", "type": "quantitative"},
                                  "tooltip": [{"field": "year", "title": "봉우리"}, {"field": "n", "title": "인용 수"},
                                              {"field": "refs", "title": "대표 문헌"}]}},
                    {"transform": [{"filter": "datum.alt == 0"}],
                     "mark": {"type": "text", "dy": -9, "fontSize": 9, "color": "#59636e"},
                     "encoding": {"x": xq, "y": {"field": "dev", "type": "quantitative"}, "text": {"field": "year"}}},
                    {"transform": [{"filter": "datum.alt == 1"}],
                     "mark": {"type": "text", "dy": -19, "fontSize": 9, "color": "#59636e"},
                     "encoding": {"x": xq, "y": {"field": "dev", "type": "quantitative"}, "text": {"field": "year"}}},
                ]},
            ],
        })
        parts.append(f"RPYS {line[0]['year']}–{line[-1]['year']}, 봉우리 {len(marks)}개")
    else:
        notes.append("rpys_series 없음")
    fwd = an.get("forward_by_year") or {}
    fwd_rows = sorted(({"year": int(k), "n": int(v)} for k, v in fwd.items() if str(k).isdigit()),
                      key=lambda r: r["year"])
    if fwd_rows:
        panels.append({
            "title": {"text": "씨앗 논문을 인용한 논문 (연도별)"},
            "width": 600, "height": 150,
            "data": {"values": fwd_rows},
            "mark": {"type": "bar", "color": "#009E73", "cornerRadiusTopLeft": 2, "cornerRadiusTopRight": 2},
            "encoding": {"x": {"field": "year", "type": "ordinal", "title": "출판 연도",
                               "axis": {"labelAngle": 0, "labelOverlap": True}},
                         "y": {"field": "n", "type": "quantitative", "title": "논문 수"},
                         "tooltip": [{"field": "year", "title": "연도"}, {"field": "n", "title": "논문 수"}]},
        })
        parts.append(f"전진 인용 {sum(r['n'] for r in fwd_rows)}편")
    else:
        notes.append("forward_by_year 없음")
    if not panels:
        raise VizError("analysis.json has neither rpys_series nor forward_by_year")
    spec = finish({"usermeta": {"responsive": "concat", "axisAllowance": 72},
                   "vconcat": panels, "spacing": 22, "resolve": {"scale": {"x": "independent"}}})
    meta = {"panels": len(panels), "notes": notes,
            "source": "data/analysis.json (" + ", ".join(parts) + ")"}
    return spec, meta
