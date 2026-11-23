# lineage.json

The agent-curated input to `lineage page` and `lineage report-section`. Lives in the topic work folder next to `data/`.
Text fields accept `**bold**`; everything else is escaped. Full examples: `examples/les/lineage.json` (lineage mode, a computational-materials method), `examples/transit/lineage.json` (topic mode, transport policy, below). The snippets below come from the LES example; they show the format, not what lanes, vocabulary or verdicts should be: those come from your topic, in any engineering field.

```jsonc
{
  "meta": {
    "mode": "lineage",                        // "lineage" (default) or "topic": lanes = the reader's questions (below)
    "page_title": "LES 계보도",              // 2–4 word name, used as <title>
    "slug": "les_lineage",                    // output file name
    "date": "2026-11-20",
    "headline": "…은 어디서 왔고, 지금 어디로 가나",
    "lede": "one or two sentences: scope and method",
    "seed_label": "Cheng, npj Comput. Mater. 11:80 (2025)",
    "seed_ids": ["W4408876037"],
    "papers_read": ["W…"],                    // only papers whose text you retrieved and read
    "data_dir": "data",
    "expanded_dir": "data_x",                 // omit if not widened
    "focus_regex": "long-range|electrostat",  // marks on-topic titles in the expansion list
    "expansion_note": "why widening was skipped",  // shown when expanded_dir is omitted
    "era_focus": "both",                      // optional: both (default) | origin | current — the era the question asks about
    "era_note": "asks where the method began", // optional: why; shown in the check's era line
    "figure_source": "OpenAlex 인용 코퍼스 + 원문 21편"  // optional: source named in the figure footer
  },
  "lanes": [                                  // index = lane number
    {"label": ["B. 전하 평형", "(QEq)"],         // 1 or 2 short lines
     "how": "NN이 전기음성도를 예측하고 QEq 선형계를 풂",   // stage table: how this branch gets its charges/info
     "limit": "O(N³) 풀이, 절연체 과분극"}                // stage table: its key limitation (cite where known)
  ],
  "nodes": [
    {"id": "g4", "lane": 3, "year": 2021, "title": "4G-HDNNP", "sub": "Ko 2021",   // sub = first author + year
     "openalex": "W3086372695",              // or "url" when the work is not in OpenAlex; neither found:
                                             // "unlinked": "why" (box not clickable; check warns)
     "design": "model",                      // optional: model | observational | experiment | quasi | review
     "ref": 12,                               // optional: the report's reference number ("Ko 2021 [12]")
     "evidence": "ko2021",                    // optional: stem of evidence/ko2021.json in the topic folder;
                                             // the side panel and the corner badge come from that record
     "note": "one line: what it changed",    // shown in the tooltip
     "key": true}                             // optional: the seed or the focus paper
  ],
  "edges": [ ["cent", "g4", "s"],           // earlier -> later; s = builds on, d = conceptual, m = main-path order;
                                             // e = evaluates: study -> the event node it evaluates (topic mode);
                                             // x = disputes / contradicts (study <-> study, no direction)
    {"from": "g4", "to": "les", "type": "s",  // object form (any type): records WHY "les built on g4"
     "basis": "method",                       // cites | method | data | authors | conceptual
     "evidence": "Cheng 2025 §II.B"},        // locator: section/page, or an evidence key "cheng2025:p3"
    ["camp_a", "camp_b", "x"] ],
  "contested": [                              // optional: claims the field disagrees on (shown as a 쟁점 table)
    {"claim": "propagon 기여 비율",
     "side_a": {"nodes": ["larkin14"], "says": "~6%, MFP ~10 nm에서 포화"},
     "side_b": {"nodes": ["fiorentino24"], "says": "무시할 만큼 작음"},
     "metric_note": "MFP 정의와 cutoff가 다름",  // why the numbers differ (measurement, definition, system)
     "status": "open"}                         // open | resolved | partly
  ],
  "link_overrides": {"W4323721113": {"url": "https://proceedings.mlr.press/…", "kind": "proceedings", "venue": "ICML 2023"}},
  "axes": [                                   // the questions that split the field
    {"question": "① 전하를 어디서 얻는가",
     "items": [ {"label": "QEq로 전역 결정 (B)", "text": "CENT → 4G-HDNNP …"} ]},
    {"question": "② …", "text": "paragraph with **bold** allowed"}
  ],
  "axes_note": "optional caveat",
  "vocabulary": [                             // concept blocks used for widening (step 5); shown on the page
    {"concept": "장거리 정전기", "terms": ["long-range", "nonlocal", "electrostatic", "Ewald", "Coulomb"],
     "noise": ["photovoltaic"], "source": "OpenAlex 태그 + Grasselli §II–III 용어"}
  ],
  "verdict": [ {"tag": "현재 기본값", "title": "…", "points": ["evidence-backed point", "…"]} ],
  "trends": [                                 // the text flow: numbered main trends, each with cited points
    {"title": "\"DFT 전하로 학습하지 않는다\"", "points": ["what moved from what to what (Author Year [n])", "…"]}
  ],
  "one_line": "the whole lineage in one or two sentences",
  "evidence": {
    "main_path_tail": 8,                      // how many final main-path papers to show
    "main_path_note": "why the earlier part is omitted",
    "rpys_years": [1921, 1995, 2007],         // precursor and parent-founder peaks; generic tools dropped
    "rpys_note": "which peaks were dropped and why",
    "cluster_labels": {"0": "응용 리뷰", "1": "장거리 방법"}
  },
  "rows": [
    {"year": "2021", "work": "4G-HDNNP (Ko 외)", "what": "…", "change": "…", "lane": 3,
     "level": "fulltext",                     // fulltext | excerpts | secondary | abstract | metadata (mirrors the evidence record)
     "evidence": "LES p.1",                  // section/page where it was read
     "version": "arXiv v2",                  // optional: version actually read; default = link kind
     "openalex": "W3086372695"},
    {"year": "2026", "work": "Grasselli 외 (관점)", "what": "…", "change": "…", "lane": null,  // review/perspective
     "level": "fulltext", "evidence": "§II.2", "openalex": "W7128713787"}
  ],
  "limits": ["corpus bias, whose taxonomy, coverage gaps"]
}
```

Evidence labels on the page and in the report chapter follow snu-library-scholarly-access: `fulltext` = **본문 확인**, `excerpts` = **발췌 확인**, `secondary` = **인용 맥락만** (known only from a citing paper), `abstract` = **초록만 확인**, `metadata` = **미확인**.

## Edges with a basis, disputes and contested claims

- **Edge objects.** Any edge may be an object `{"from", "to", "type", "basis", "evidence"}` instead of the array; both forms can be mixed and render the same. Give every `s` edge a `basis` and an `evidence` locator: `cites` (the later paper cites the earlier one and says it builds on it), `method`, `data`, `authors` (same group continues the line), `conceptual`. An `s` edge with no basis beyond "it seemed to follow" belongs in `d`.
- **x edges** (disputes/contradicts) join two studies that give conflicting answers. They are drawn as a red-toned dash-dot line with no arrowhead and a ringed **≠** at the midpoint; the pattern and marker, not the colour alone, set them apart. The legend inside the figure lists them; they never get a "backward in time" warning.
- **contested** lists the disputes as claims with two sides (`nodes` = node ids, `says` = that side's answer), `metric_note` (why the numbers can differ) and `status`. The page and the report chapter show a **쟁점** table: claim | A | B | 측정 차이 | 상태 | 근거 수준. A side's evidence level comes from the `rows` of its nodes (a row belongs to a node when it has the same `openalex` or `url`, or `"node": "<id>"`).
- Files without these fields render as before (plus the badges, toggles and panel below). Topic mode accepts them the same way (the 쟁점 section follows 답이 갈리는 지점).

## Topic mode

For a topic question ("도시 대중교통 정기권은 효과가 있나") the lanes are the **reader's questions**, not the agent's themes. Set `"meta": {"mode": "topic"}`. Everything above still applies; seed, corpus and widening fields are optional.

- **Question lanes**: `question` (short; it replaces the label as the lane header, numbered Q1, Q2, … in lane order) and `answer` (1–2 lines: the current answer with its key number). The answer is drawn as a bold, tinted **지금의 답** cell at the end of the lane, after the latest year. `label` is optional.
- **Events lane** (at most one): `{"kind": "events", "label": "정책·사건"}` holds the real-world events the studies evaluate: nodes with `"kind": "event"`, `id`, `year`, `title` (a pill label: about 8 Hangul or 13 Latin characters), optional `url` and `note`. It is drawn as the first, narrower column with pill markers. Link a study to the event it evaluates with an `e` edge (thin dotted, muted); events take no other edges. An events lane in lineage mode is drawn the same way.
- **Design**: give every study a `design`. Boxes are coloured by design, with a legend (모형·이론, 관찰자료, 실험(무작위), 준실험(DiD·합성대조), 리뷰) drawn inside the figure, so the report PNG carries it too. In lineage mode `design` is optional and colours only the boxes that have it.
- **Same-lane edges** that would cross a box in between bow out along the right side of the column.
- **Report chapter**: `## n. 질문별 연구 지도`. Its first table is *question | current answer | key studies* (`sub`, `[ref]` when set, design), then one line listing the events and the studies that evaluate them. Sections with no content (axes, trends, rows, data evidence without `analysis.json`) are left out; the page leaves them out the same way.

```jsonc
{
  "meta": {"mode": "topic", "page_title": "대중교통 정기권 지도", "slug": "transit_passes_map", "date": "2026-11-23",
           "headline": "…", "lede": "…", "data_dir": "data"},
  "lanes": [
    {"kind": "events", "label": "정책·사건"},
    {"question": "정기권·무제한권은 이용을 얼마나 늘리나?", "answer": "단기 +2.7~12%, 주로 기존 이용자 통행 증가"},
    {"question": "가격은 어떻게 정하나?", "answer": "가입료+한계비용 이부요금에 소득·혼잡 반영"}
  ],
  "nodes": [
    {"id": "ev_metrocard", "kind": "event", "lane": 0, "year": 1998, "title": "MetroCard", "note": "뉴욕 무제한 승차권 도입"},
    {"id": "hirsch", "lane": 1, "year": 2000, "title": "MetroCard 평가", "sub": "Hirsch 2000",
     "openalex": "W1989650281", "design": "observational", "ref": 7},
    {"id": "sherman", "lane": 2, "year": 1967, "title": "클럽형 정기권", "sub": "Sherman 1967",
     "openalex": "W577854925", "design": "model"}
  ],
  "edges": [["hirsch", "ev_metrocard", "e"]]
}
```

## Evidence panel, badges and controls

- **Boxes open a side panel**, not the paper: a click, a tap or Enter on a focused box opens it (right-hand drawer on wide screens, bottom sheet on narrow ones; Esc or × closes it). It shows the title, authors and year, venue, the version read, the derived read label with its locator, each criterion judgment with section/page and `read_mode`, the `results` table (value, range, unit, page), and two buttons: **원문 열기** (the journal-first link) and **기록 보기** (`evidence/<stem>.json`, relative to the page). Hovering with a mouse or focusing a box still highlights its lineage and shows the tooltip.
- **Where the panel data comes from.** A node with `"evidence": "<stem>"` gets a slim copy of `evidence/<stem>.json` embedded at build time; its label is derived by `evidence.derive_label` (from `access`, `read_via`, each locator's `read_mode`), never typed by hand. A node without one falls back to its `rows` (same `openalex`/`url`, or `"node": "<id>"`): the strongest row level, else 미확인. A stem whose file is missing is a warning in `lineage check`, `page` and `report-section`.
- **Evidence badge** (box's top-right corner): 본문 확인 filled dot, 발췌 확인 half dot, 인용 맥락만 dashed ring, 초록만 확인 hollow ring, 미확인 none. The legend inside the figure lists them.
- **Design** colours are the Okabe–Ito colour-blind-safe set (model #0072B2, observational #009E73, experiment #D55E00, quasi #E69F00, review #CC79A7), the same in light and dark mode, plus a one-letter tag in the top-left corner (모/관/실/준/리). Box text stays in the ink colour. The topic **지금의 답** cell has a neutral ink border; clicking it lists that question's studies with their labels in the panel.
- **Controls**: lane/question highlight; edge-type toggles (only the types in use: 직접 확장 s, 개념 연결 d, 주경로 m, 사건 평가 e, 상충 x); **긴 연결 줄이기** draws edges spanning more than 15 years faint with a small target label at their start ("→ Marcolongo 2016"), on by default above 40 nodes; **화면 맞춤** scales the map to the screen width. The year column sticks while the map scrolls sideways, and the lane headers while the page scrolls.
- **Figure footer** (page SVG and report PNG): date, how many studies are 본문/발췌/인용 맥락/초록/미확인, and the source (`meta.figure_source`, else OpenAlex plus evidence/ and rows when present).

## Embed variant and reports

`lineage page . --embed` writes `<slug>_embed.html`: the map, the lane and edge controls, the legend and the panel only (no header, tables, search log or rerun commands), with a transparent background. Inside a report it posts its height to the frame (`{type: "snu-embed-height", height}`) and takes the report's light/dark mode and colour/font tokens (`{type: "snu-embed-theme", theme, vars}`; `--snu-ink`, `--snu-muted`, `--snu-rule`, `--snu-accent`, `--snu-head-bg`, `--snu-surface`, `--snu-font`). Opened on its own it follows `prefers-color-scheme`.

`lineage report-section` writes the embed page next to the chapter and points the figure at it, with the PNG for the PDF:

```markdown
![계보도. … 상자를 누르면 근거 패널이 열립니다](les_lineage_embed.html "static=figs/lineage.png")
```

`render-report` (Quarto) turns any image whose target is a local `.html` file into an auto-sized, sandboxed frame in the HTML output; the PDF uses the `static=` image (default: the same path with `.png`, when it exists) or leaves the figure out with a warning. `"height=480"` sets the frame height used until the page reports its own (default 640 px). The older `![…](figs/lineage.png "interactive=page.html")` form still inlines the full page (`--no-embed`). The built-in reportlab PDF engine does not read HTML figures; it skips them with a warning.

## Validation (`lineage check`)

`lineage page` and `lineage report-section` refuse to render and list problems when: a top-level key is missing, `meta.mode` is not lineage/topic, a lane index is out of range, a study node lacks `openalex`/`url` and gives no `unlinked` reason, a box title or subtitle (or event pill title) is wider than the box (Hangul counts about twice a Latin letter), more than 50 nodes, an edge points at an unknown node or has a type other than s/d/m/e/x, an edge object has a `basis` outside the five values or a non-string `evidence`, a `contested` entry lacks `claim`, has a side without `nodes`, names an unknown node, or has a `status` other than open/resolved/partly, an `e` edge does not run from a study to an event, an event node is joined by a non-`e` edge, an event node sits outside the events lane or a study node inside it, there is more than one events lane, a `design` is not one of the five values, an `evidence` value is not a bare file stem, a row level is not one of the three values, or there are more than 12 lanes. In topic mode, also when a non-event lane has no `question`.

It prints warnings (and still renders) for more than 10 lanes, lanes with fewer than 2 nodes, unlinked study nodes, more than 40 nodes, edges that run backward in time (`e` and `x` edges excepted), and edges drawn through another box. In topic mode, also for a question lane without `answer`, more than 5 question lanes, and studies without `design`.

Then, offline from the local corpus (`data_dir` and `expanded_dir`: `corpus.json`, and `refs_meta.json` for works outside it), it checks the claims (skip with `--no-corpus`). All are warnings, so older files stay valid:

| code | when |
|---|---|
| `edge_no_citation_link` | an `s` edge whose nodes both have OpenAlex IDs and whose later work's reference list is local, but the later work does not cite the earlier one (same year: either direction). Record the basis, use `d`, or look for a preprint/journal split |
| `edge_no_basis` | `s` edges without `basis`/`evidence` (one line listing them) |
| `contested_side_not_fulltext` | a node on a contested side has no row read in full text (level below `fulltext`, or no row at all) |
| `contested_without_x_edge` | a contested claim with no `x` edge between its two sides |
| `unsaturated_search` | `data/queries.json` exists and no logged query reached novelty < 10% |
| `not_found_without_search_log` | verdict, trends or limits say something was not found (찾지 못, not found, …) but `data/searches.json` is missing |
| `era_recent_thin` | ≥ 10 field papers and ≥ 15% of the field are from the last three years, but fewer than 2 study boxes are (off when `meta.era_focus` is `origin`) |
| `era_founders_thin` | fewer than 2 of the 10 most-cited ancestors in `analysis.json` are boxes (off when `meta.era_focus` is `current`; generic tools may stay out) |

Summary lines follow: `s edges: n with citation link, m without, k unverifiable (no OpenAlex/refs)`, and `era: x% of n field papers from <years>, k/m boxes; j/10 most-cited ancestors are boxes; focus <focus>`. An invalid `meta.era_focus` is a problem.

The report chapter adds a **검색 방법과 범위** section only when there is something to say: an unsaturated query log, searches logged with `lineage log-search`, or `adoption`/`mentions` runs (listed by id so verdict text can cite `adoption#n`).

