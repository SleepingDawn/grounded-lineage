// snu-report Typst theme (included before the body, after Quarto's article template).
// Korean typography after KRDS (one sans family, 1.6 line height, >= 4.5:1 contrast);
// measure and quiet tables after Tufte.
#let snu-ink = rgb("#1d232b")
#let snu-muted = rgb("#5b6470")
#let snu-accent = rgb("#1f5f99")
#let snu-rule = rgb("#d5dae1")
#let snu-head-rule = rgb("#9aa3ae")
#let snu-head-bg = rgb("#eef2f6")
#let snu-zebra = rgb("#f8f9fb")
#let snu-callout-bg = rgb("#f1f6fb")

#set text(lang: "ko", fill: snu-ink, hyphenate: false)
#set par(leading: 0.95em, spacing: 1.3em, justify: false)
#show link: set text(fill: snu-accent)
#set page(footer: context {
  set text(size: 8pt, fill: snu-muted)
  grid(columns: (1fr, auto), snu-report-title, counter(page).display("1 / 1", both: true))
})

#show heading.where(level: 2): it => block(above: 2.0em, below: 0.9em, sticky: true, {
  set text(size: 14pt, weight: "bold")
  it.body
  v(-0.5em)
  line(length: 100%, stroke: 0.6pt + snu-rule)
})
#show heading.where(level: 3): it => block(above: 1.6em, below: 0.7em, sticky: true, {
  set text(size: 11.5pt, weight: "bold", fill: snu-accent)
  it.body
})
#show heading.where(level: 4): it => block(above: 1.3em, below: 0.6em, sticky: true, {
  set text(size: 10.5pt, weight: "bold")
  it.body
})

#set table(
  stroke: (x, y) => (top: if y <= 1 { 0.8pt + snu-head-rule } else { 0.4pt + snu-rule }, bottom: 0.4pt + snu-rule),
  fill: (x, y) => if y == 0 { snu-head-bg } else if calc.even(y) { snu-zebra },
  inset: (x: 5pt, y: 4.5pt),
)
#show table: set text(size: 8.8pt)
#show table: set par(leading: 0.7em, justify: false)
#show table.cell.where(y: 0): set text(weight: "bold")

#show quote: it => block(fill: snu-callout-bg, inset: (x: 11pt, y: 9pt), radius: 3pt, width: 100%,
  stroke: (left: 2.5pt + snu-accent), it.body)
#show figure.caption: set text(size: 9pt, fill: snu-muted)
#show raw: set text(size: 8.8pt)
