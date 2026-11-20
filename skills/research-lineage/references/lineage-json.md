# lineage.json

The agent-curated input to `lineage page` and `lineage report-section`. Lives in the topic work folder next to `data/`.
Text fields accept `**bold**`; everything else is escaped. Full example: `examples/les/lineage.json`.

```jsonc
{
  "meta": {
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
    "expansion_note": "why widening was skipped"  // shown when expanded_dir is omitted
  },
  "lanes": [                                  // index = lane number
    {"label": ["B. 전하 평형", "(QEq)"],         // 1 or 2 short lines
     "how": "NN이 전기음성도를 예측하고 QEq 선형계를 풂",   // stage table: how this branch gets its charges/info
     "limit": "O(N³) 풀이, 절연체 과분극"}                // stage table: its key limitation (cite where known)
  ],
  "nodes": [
    {"id": "g4", "lane": 3, "year": 2021, "title": "4G-HDNNP", "sub": "Ko 2021",   // sub = first author + year
     "openalex": "W3086372695",              // or "url" when the work is not in OpenAlex
     "note": "one line: what it changed",    // shown in the tooltip
     "key": true}                             // optional: the seed or the focus paper
  ],
  "edges": [ ["cent", "g4", "s"] ],          // earlier -> later; s = builds on, d = conceptual, m = main-path order
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
     "level": "fulltext",                     // fulltext | abstract | metadata
     "evidence": "LES p.1",                  // section/page where it was read
     "version": "arXiv v2",                  // optional: version actually read; default = link kind
     "openalex": "W3086372695"},
    {"year": "2026", "work": "Grasselli 외 (관점)", "what": "…", "change": "…", "lane": null,  // review/perspective
     "level": "fulltext", "evidence": "§II.2", "openalex": "W7128713787"}
  ],
  "limits": ["corpus bias, whose taxonomy, coverage gaps"]
}
```

Evidence labels on the page and in the report chapter follow snu-library-scholarly-access: `fulltext` = **본문 확인**, `abstract` = **초록만 확인**, `metadata` = **미확인**.

`lineage page` and `lineage report-section` refuse to render and lists problems when: a top-level key is missing, a lane index is out of range, a node lacks `openalex`/`url`, a box title or subtitle is wider than the box (Hangul counts about twice a Latin letter), more than 50 nodes, an edge points at an unknown node or has a type other than s/d/m, a row level is not one of the three values, or there are more than 12 lanes.

It prints warnings (and still renders) for more than 10 lanes, lanes with fewer than 2 nodes, more than 40 nodes, and edges that run backward in time.
