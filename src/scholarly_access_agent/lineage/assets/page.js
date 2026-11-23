(function(){
  const N = __NODES__, E = __EDGES__, LANES = __LANES__, KIND = __KIND__, CFG = __CFG__;
  const svg = document.getElementById('tree'), stage = document.getElementById('stage');
  const sc = stage.querySelector('.scroll'), tip = document.getElementById('tip');
  const panel = document.getElementById('panel'), pk = document.getElementById('pk'),
        pt = document.getElementById('pt'), pb = document.getElementById('pb');
  const framed = CFG.embed && window.parent !== window;
  const out = {}, inn = {};
  E.forEach(([s,t]) => { (out[s] = out[s] || []).push(t); (inn[t] = inn[t] || []).push(s); });
  function walk(start, adj){ const seen = new Set([start]), st=[start];
    while (st.length){ const v = st.pop(); (adj[v]||[]).forEach(u => { if(!seen.has(u)){ seen.add(u); st.push(u);} }); }
    return seen; }
  const nodes = [...svg.querySelectorAll('.node')], edges = [...svg.querySelectorAll('.e')],
        labs = [...svg.querySelectorAll('.elab')], answers = [...svg.querySelectorAll('.ans')];
  const byId = {}; nodes.forEach(n => { byId[n.dataset.id] = n; });
  let laneSel = null, sel = null, opener = null;
  const wrapEl = document.getElementById('wrap') || document.querySelector('.wrap');
  const lv = document.getElementById('lv'), lvBoxes = lv ? [...lv.querySelectorAll('.lvb')] : [];
  const mq = window.matchMedia ? window.matchMedia('(max-width: ' + (CFG.narrow - 0.02) + 'px)') : {matches: false};
  function lvOn(){ return !!(lv && wrapEl && wrapEl.classList.contains('lv-on')); }

  // ------------------------------------------------------------ highlight
  function clear(){ svg.classList.remove('focus');
    [...nodes, ...edges, ...labs, ...answers].forEach(x => x.classList.remove('on')); }
  function applyLane(){ clear(); if (laneSel === null) return;
    svg.classList.add('focus');
    nodes.forEach(n => { if (+n.dataset.lane === laneSel) n.classList.add('on'); });
    answers.forEach(a => { if (+a.dataset.lane === laneSel) a.classList.add('on'); });
    [...edges, ...labs].forEach(e => { const a = N[e.dataset.s], b = N[e.dataset.t];
      if (a.lane === laneSel && b.lane === laneSel) e.classList.add('on'); }); }
  function lineage(id){ clear(); svg.classList.add('focus');
    const set = new Set([...walk(id, out), ...walk(id, inn)]);
    nodes.forEach(n => { if (set.has(n.dataset.id)) n.classList.add('on'); });
    [...edges, ...labs].forEach(e => { if (set.has(e.dataset.s) && set.has(e.dataset.t)) e.classList.add('on'); }); }
  function restore(){ if (sel) lineage(sel); else applyLane(); }

  // ------------------------------------------------------------ small DOM helpers
  function el(tag, cls, text){ const x = document.createElement(tag); if (cls) x.className = cls;
    if (text != null && text !== '') x.textContent = text; return x; }
  const NS = 'http://www.w3.org/2000/svg';
  function badge(label){ const kind = CFG.badge[label]; const s = document.createElementNS(NS, 'svg');
    s.setAttribute('width', '12'); s.setAttribute('height', '12'); s.setAttribute('aria-hidden', 'true');
    if (!kind) return s;
    const c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', '6'); c.setAttribute('cy', '6'); c.setAttribute('r', '4.5');
    c.setAttribute('class', 'bdg ' + kind); s.appendChild(c);
    if (kind === 'half'){ const p = document.createElementNS(NS, 'path'); p.setAttribute('d', 'M6,1.5 A4.5,4.5 0 0 0 6,10.5 Z');
      p.setAttribute('class', 'bdg-h'); s.appendChild(p); }
    s.style.overflow = 'visible'; return s; }
  // badge glyphs reuse the SVG classes: give the inline icons the same look
  const st = document.createElement('style');
  st.textContent = '.lvl .bdg,.lanelist .bdg{fill:var(--surface);stroke:var(--fg);stroke-width:1.2}.lvl .bdg.full,.lanelist .bdg.full{fill:var(--fg)}'
    + '.lvl .bdg.dash,.lanelist .bdg.dash{stroke-dasharray:1.8 1.4}.lvl .bdg-h,.lanelist .bdg-h{fill:var(--fg)}';
  document.head.appendChild(st);
  function laneName(i){ return (CFG.qn[i] ? 'Q' + CFG.qn[i] + '. ' : '') + LANES[i]; }

  // ------------------------------------------------------------ tooltip (mouse and keyboard focus)
  function showTip(el_){ const d = N[el_.dataset.id];
    tip.innerHTML = '<div class="k"><i></i><span></span></div><div class="t"></div><div class="m"></div><div class="n"></div><div class="lk"></div>';
    tip.querySelector('.k i').style.background = 'var(--c' + (+d.lane) + ')';
    tip.querySelector('.k span').textContent = LANES[d.lane] + (d.dz ? ' · ' + d.dz : '') + (d.lab ? ' · ' + d.lab : '');
    tip.querySelector('.t').textContent = d.t;
    tip.querySelector('.m').textContent = [d.by, d.venue, d.year, d.cites!=null ? ('인용 '+d.cites.toLocaleString()) : ''].filter(Boolean).join(' · ');
    tip.querySelector('.n').textContent = d.note;
    tip.querySelector('.lk').textContent = d.ev ? '누르면 사건 정보가 열림' : '누르거나 Enter: 근거 패널';
    tip.hidden = false;
    const sr = stage.getBoundingClientRect(), r = el_.getBoundingClientRect();
    let x = r.right - sr.left + 10, y = r.top - sr.top - 6;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > sr.width - 4) x = r.left - sr.left - w - 10;
    if (x < 4) { x = Math.max(4, r.left - sr.left); y = r.bottom - sr.top + 8; }
    y = Math.min(Math.max(4, y), Math.max(4, stage.scrollHeight - h - 4));
    tip.style.left = x + 'px'; tip.style.top = y + 'px'; }
  function hideTip(){ tip.hidden = true; }

  // ------------------------------------------------------------ side panel
  function head(i, extra){ pk.textContent = ''; const sw = el('i'); sw.style.background = 'var(--c' + i + ')';
    pk.append(sw, el('span', '', laneName(i) + (extra ? ' · ' + extra : ''))); }
  function row(dl, k, v){ if (v == null || v === '') return; dl.append(el('dt', '', k)); const dd = el('dd');
    if (v instanceof Node) dd.append(v); else dd.textContent = v; dl.append(dd); }
  function button(href, text, primary, title){ const a = el('a', 'btn' + (primary ? ' primary' : ''), text);
    a.href = href; a.target = '_blank'; a.rel = 'noopener'; if (title) a.title = title; return a; }
  function nodeItem(id){ const d = N[id]; const li = el('li'), b = el('button');
    b.type = 'button'; b.append(d.lab ? badge(d.lab) : el('span'), el('span', '', d.box + (d.sub ? ' (' + d.sub + ')' : '')));
    b.append(el('span', 's', [d.y, d.dz, d.lab].filter(Boolean).join(' · ')));
    b.addEventListener('click', () => openNode(id, boxFor(id)));
    li.append(b); return li; }
  function show(from){ opener = from || null; panel.hidden = false; place(from);
    pt.focus({preventScroll: true}); post(); }
  function place(from){ if (!CFG.embed || !from) return;
    const sr = stage.getBoundingClientRect(), r = from.getBoundingClientRect();
    if (sr.width <= 720){ panel.style.left = ''; panel.style.right = '';
      panel.style.top = Math.max(0, r.bottom - sr.top + 8) + 'px'; return; }
    panel.style.top = Math.max(0, Math.min(r.top - sr.top - 8, stage.offsetHeight - 120)) + 'px';
    const leftSide = (r.left + r.right) / 2 - sr.left > sr.width - 420;
    panel.style.left = leftSide ? '8px' : 'auto'; panel.style.right = leftSide ? 'auto' : '8px'; }
  function select(id){ sel = id; nodes.forEach(n => n.classList.toggle('sel', n.dataset.id === id));
    lvBoxes.forEach(b => b.classList.toggle('sel', b.dataset.id === id)); lineage(id); }
  function openNode(id, from){ const d = N[id], r = d.rec; hideTip(); select(id);
    pb.textContent = '';
    if (d.ev){ head(d.lane); pt.textContent = d.box + ' (' + d.y + ')';
      if (d.note) pb.append(el('p', 'pn', d.note));
      const who = (inn[id] || []).filter(s => N[s] && !N[s].ev);
      if (who.length){ pb.append(el('h4', '', '이 사건을 평가한 연구')); const ul = el('ul', 'lanelist');
        who.forEach(s => ul.append(nodeItem(s))); pb.append(ul); }
      if (d.u){ const bs = el('div', 'btns'); bs.append(button(d.u, '출처 열기', true)); pb.append(bs); }
      show(from); return; }
    head(d.lane, d.dz);
    pt.textContent = (r && r.title) || d.t;
    const by = (r && r.by) || d.by, yr = (r && r.year) || d.year;
    pb.append(el('p', 'pm', [by, by && String(by).indexOf(String(yr)) >= 0 ? '' : yr].filter(Boolean).join(' · ')));
    const venue = (r && r.venue) || d.venue; if (venue) pb.append(el('p', 'pm', venue));
    const dl = el('dl', 'pl');
    const lv = el('span', 'lvl'); lv.append(badge(d.lab), el('span', '', d.lab + (r && r.at ? ' · ' + r.at : '')));
    row(dl, '근거 수준', lv);
    row(dl, '읽은 판', (r && r.version) || (KIND[d.kind] && d.kind !== 'unknown' ? KIND[d.kind] : ''));
    if (r){ row(dl, '접근', [r.access, r.read_via].filter(Boolean).join(' · ')); row(dl, '발표 형태', r.venue_type); }
    if (d.cites != null) row(dl, '인용', d.cites.toLocaleString());
    pb.append(dl);
    const bs = el('div', 'btns');
    if (d.u) bs.append(button(d.u, '원문 열기', true, KIND[d.kind] ? KIND[d.kind] + ' 원문' : ''));
    if (r) bs.append(button(CFG.evbase + encodeURIComponent(r.stem) + '.json', '기록 보기', false, 'evidence/' + r.stem + '.json'));
    if (bs.childNodes.length) pb.append(bs);
    if (d.note) pb.append(el('p', 'pn', d.note));
    if (r && r.crit && r.crit.length){ pb.append(el('h4', '', '기준별 판단'));
      const ul = el('ul', 'crit');
      r.crit.forEach(c => { const li = el('li'); li.append(el('b', '', c.c), el('span', '', c.j));
        const loc = c.at.map(a => [a.loc, a.m].filter(Boolean).join(' · ')).filter(Boolean).join('; ');
        if (loc) li.append(el('div', 'loc', loc)); ul.append(li); });
      pb.append(ul); }
    if (r && r.res && r.res.length){ pb.append(el('h4', '', '수치 결과'));
      const t = el('table', 'res'), th = el('tr'); ['양', '값', '위치'].forEach(h => th.append(el('th', '', h)));
      const thead = el('thead'); thead.append(th); t.append(thead); const tb = el('tbody');
      r.res.forEach(x => { const tr = el('tr'); tr.append(el('td', '', x.q + (x.cond ? ' (' + x.cond + ')' : '')),
        el('td', 'num', (x.v + ' ' + x.u).trim()), el('td', 'num', [x.at, x.m].filter(Boolean).join(' · ')));
        tb.append(tr); });
      t.append(tb); pb.append(t); }
    if (!r) pb.append(el('p', 'note', '연결된 근거 기록 파일이 없어 근거 표의 수준만 표시합니다.'));
    show(from); }
  function openLane(i, from){ hideTip(); sel = null; nodes.forEach(n => n.classList.remove('sel'));
    laneSel = i; applyLane(); syncLaneButtons();
    head(i); pt.textContent = LANES[i]; pb.textContent = '';
    if (CFG.answers[i]){ pb.append(el('div', 'pm', '지금의 답'), el('div', 'answer-text', CFG.answers[i])); }
    const ids = Object.keys(N).filter(k => N[k].lane === i).sort((a, b) => N[a].y - N[b].y);
    pb.append(el('h4', '', '이 질문의 연구 ' + ids.length + '편'));
    const ul = el('ul', 'lanelist'); ids.forEach(k => ul.append(nodeItem(k))); pb.append(ul);
    show(from); }
  function closePanel(){ if (panel.hidden) return; panel.hidden = true; sel = null;
    nodes.forEach(n => n.classList.remove('sel')); lvBoxes.forEach(b => b.classList.remove('sel')); applyLane();
    if (opener && document.contains(opener)) opener.focus({preventScroll: true}); opener = null; post(); }
  document.getElementById('px').addEventListener('click', closePanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });
  panel.addEventListener('click', e => e.stopPropagation());

  // ------------------------------------------------------------ boxes: hover/focus preview, tap/click/Enter opens the panel
  nodes.forEach(n => {
    n.addEventListener('pointerenter', e => { if (e.pointerType !== 'mouse') return; if (!sel) lineage(n.dataset.id); showTip(n); });
    n.addEventListener('pointerleave', e => { if (e.pointerType !== 'mouse') return; hideTip(); restore(); });
    n.addEventListener('focus', () => { if (!sel) lineage(n.dataset.id); showTip(n); });
    n.addEventListener('blur', () => { hideTip(); restore(); });
    n.addEventListener('click', e => { e.stopPropagation(); openNode(n.dataset.id, n); });
    n.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openNode(n.dataset.id, n); } });
  });
  answers.forEach(a => { a.setAttribute('tabindex', '0'); a.setAttribute('role', 'button');
    a.setAttribute('aria-label', '지금의 답: ' + laneName(+a.dataset.lane) + '. 눌러서 연구 목록 보기');
    a.addEventListener('click', e => { e.stopPropagation(); openLane(+a.dataset.lane, a); });
    a.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openLane(+a.dataset.lane, a); } }); });
  svg.addEventListener('click', () => closePanel());

  // ------------------------------------------------------------ lane, edge-type and view controls
  function syncLaneButtons(){ document.querySelectorAll('.controls .lanebtn[data-lane]').forEach(x => x.setAttribute('aria-pressed',
      String(x.dataset.lane === 'all' ? laneSel === null : +x.dataset.lane === laneSel))); }
  document.querySelectorAll('.controls .lanebtn[data-lane]').forEach(b => b.addEventListener('click', () => {
    const v = b.dataset.lane === 'all' ? null : +b.dataset.lane;
    laneSel = (laneSel === v) ? null : v; syncLaneButtons(); if (!sel) applyLane(); }));
  document.querySelectorAll('.edgebtn').forEach(b => b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on));
    svg.classList.toggle('hide-' + b.dataset.etype, !on); if (lv) lv.classList.toggle('hide-' + b.dataset.etype, !on); }));
  const shortBtn = document.getElementById('shortbtn');
  if (shortBtn) shortBtn.addEventListener('click', () => { const on = shortBtn.getAttribute('aria-pressed') !== 'true';
    shortBtn.setAttribute('aria-pressed', String(on)); svg.classList.toggle('shorten', on); });
  const fitBtn = document.getElementById('fitbtn');
  fitBtn.addEventListener('click', () => { const on = fitBtn.getAttribute('aria-pressed') !== 'true';
    fitBtn.setAttribute('aria-pressed', String(on)); sc.classList.toggle('fit', on); stickX(); stickY(); post(); });

  // ------------------------------------------------------------ sticky year column and lane headers
  const yrs = svg.querySelector('.yrs'), heads = svg.querySelector('.heads'), VBW = svg.viewBox.baseVal.width;
  function scale(){ return (svg.getBoundingClientRect().width / VBW) || 1; }
  function stickX(){ const dx = sc.scrollLeft / scale();
    yrs.setAttribute('transform', dx > 0 ? 'translate(' + dx.toFixed(1) + ',0)' : ''); yrs.classList.toggle('stuck', dx > 0); }
  function stickY(){ if (framed) return; const r = svg.getBoundingClientRect();
    const dy = Math.min(Math.max(0, -r.top / scale()), +heads.dataset.max);
    heads.setAttribute('transform', dy > 0 ? 'translate(0,' + dy.toFixed(1) + ')' : ''); heads.classList.toggle('stuck', dy > 0); }
  sc.addEventListener('scroll', stickX, {passive: true});
  window.addEventListener('scroll', stickY, {passive: true});
  window.addEventListener('resize', () => { stickX(); stickY(); });

  // ------------------------------------------------------------ phones: sideways-scroll cue on the full map
  const hint = document.getElementById('scrollhint'); let scrolled = false;
  function cue(){ const on = mq.matches && !lvOn(), over = sc.scrollWidth > sc.clientWidth + 2;
    stage.classList.toggle('cue', on && over && sc.scrollLeft + sc.clientWidth < sc.scrollWidth - 4);
    if (hint) { const h = !(on && over && !scrolled); if (hint.hidden !== h) { hint.hidden = h; post(); } } }
  sc.addEventListener('scroll', () => { if (sc.scrollLeft > 4) scrolled = true; cue(); }, {passive: true});

  // ------------------------------------------------------------ phones: one lane at a time (tabs, swipe, stubs)
  const tabs = lv ? [...lv.querySelectorAll('.lvtab')] : [], panes = lv ? [...lv.querySelectorAll('.lvp')] : [];
  const lvBtn = document.getElementById('lvbtn');
  let lvPref = null, cur = tabs.length ? +tabs[0].dataset.lane : null;
  function pane(){ return panes.find(p => +p.dataset.lane === cur); }
  function boxFor(id){ if (!lvOn()) return byId[id];
    const d = N[id]; if (!d.ev && d.lane !== cur && panes.some(p => +p.dataset.lane === d.lane)) showLane(d.lane);
    const p = pane(); return (p && p.querySelector('.lvb[data-id="' + CSS.escape(id) + '"]')) || byId[id]; }
  function curve(p0, c1, c2, p3){ return 'M' + p0 + ' C' + c1 + ' ' + c2 + ' ' + p3; }
  function draw(p){ if (!p || p.hidden || !lvOn()) return;
    const g = p.querySelector('.lvg'), ov = p.querySelector('.lve'), layer = ov.querySelector('g');
    const base = g.getBoundingClientRect(), L = +p.dataset.lane;
    ov.setAttribute('viewBox', '0 0 ' + base.width.toFixed(1) + ' ' + base.height.toFixed(1));
    const R = el_ => { const r = el_.getBoundingClientRect();
      return {l: r.left - base.left, r: r.right - base.left, t: r.top - base.top, b: r.bottom - base.top,
              cx: (r.left + r.right) / 2 - base.left, cy: (r.top + r.bottom) / 2 - base.top}; };
    const boxes = {}; p.querySelectorAll('.lvn').forEach(n => { boxes[n.dataset.id] = {n: R(n), b: R(n.querySelector('.lvb'))}; });
    let s = '';
    E.forEach(([a, b], k) => { const A = boxes[a], B = boxes[b]; if (!A || !B) return;
      const t = CFG.et[k], cls = {s: 'e', d: 'e dash', m: 'e main', e: 'e ev', x: 'e dis'}[t] || 'e';
      const mk = t === 'x' ? '' : ' marker-end="url(#lv' + ({m: 'arm', e: 'are'}[t] || 'ar') + L + ')"';
      let p0, c1, c2, p3;
      if (Math.abs(A.b.cx - B.b.cx) > 4){                  // across columns (a study evaluating an event)
        const left = B.b.cx < A.b.cx, x1 = left ? A.b.l : A.b.r, x2 = left ? B.b.r : B.b.l, xm = (x1 + x2) / 2;
        p0 = [x1, A.b.cy]; c1 = [xm, A.b.cy]; c2 = [xm, B.b.cy]; p3 = [x2, B.b.cy];
      } else { const down = B.n.t >= A.n.b - 1;
        const between = down && Object.keys(boxes).some(id => id !== a && id !== b && Math.abs(boxes[id].b.cx - A.b.cx) < 4
          && boxes[id].n.t > A.n.b - 1 && boxes[id].n.b < B.n.t + 1);
        if (down && !between){ const dy = Math.max(10, (B.n.t - A.n.b) / 2);
          p0 = [A.b.cx, A.n.b]; c1 = [A.b.cx, A.n.b + dy]; c2 = [B.b.cx, B.n.t - dy]; p3 = [B.b.cx, B.n.t];
        } else { const x = Math.max(A.b.r, B.b.r);           // bow out along the column's right gutter
          p0 = [A.b.r, A.b.cy]; c1 = [x + 18, A.b.cy]; c2 = [x + 18, B.b.cy]; p3 = [B.b.r, B.b.cy]; } }
      const f = v => v.map(z => z.toFixed(1)).join(',');
      s += '<path d="' + curve(f(p0), f(c1), f(c2), f(p3)) + '" class="' + cls + '" data-type="' + t + '"' + mk + '/>';
      if (t === 'x'){ const mx = (p0[0] + 3 * c1[0] + 3 * c2[0] + p3[0]) / 8, my = (p0[1] + 3 * c1[1] + 3 * c2[1] + p3[1]) / 8;
        s += '<g data-type="x"><circle cx="' + mx.toFixed(1) + '" cy="' + my.toFixed(1) + '" r="6" class="xmk"/><text x="' + mx.toFixed(1)
          + '" y="' + my.toFixed(1) + '" class="xmk-t" style="font-size:10px">≠</text></g>'; } });
    layer.innerHTML = s; }
  function showLane(i, focusTab){ if (!panes.length) return;
    if (!panes.some(p => +p.dataset.lane === i)) return;
    cur = i; tabs.forEach(t => { const on = +t.dataset.lane === i; t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1; if (on && focusTab) t.focus(); });
    panes.forEach(p => { p.hidden = +p.dataset.lane !== i; });
    draw(pane()); post(); }
  function step(d){ const k = tabs.findIndex(t => +t.dataset.lane === cur), n = tabs.length;
    if (n > 1) showLane(+tabs[(k + d + n) % n].dataset.lane, false); }
  function setMode(){ if (!lv || !wrapEl) return;
    const on = mq.matches && (lvPref === null ? !!CFG.lv : lvPref);
    if (on !== lvOn() && !panel.hidden) closePanel();
    wrapEl.classList.toggle('lv-on', on);
    if (lvBtn) lvBtn.setAttribute('aria-pressed', String(mq.matches ? on : (lvPref === null ? !!CFG.lv : lvPref)));
    if (on) draw(pane()); cue(); stickX(); post(); }
  if (lv){
    tabs.forEach((t, k) => { t.addEventListener('click', () => showLane(+t.dataset.lane, false));
      t.addEventListener('keydown', e => { const d = {ArrowRight: 1, ArrowLeft: -1}[e.key];
        if (d){ e.preventDefault(); const n = tabs.length; showLane(+tabs[(k + d + n) % n].dataset.lane, true); }
        else if (e.key === 'Home' || e.key === 'End'){ e.preventDefault();
          showLane(+tabs[e.key === 'Home' ? 0 : tabs.length - 1].dataset.lane, true); } }); });
    lvBoxes.forEach(b => b.addEventListener('click', e => { e.stopPropagation(); openNode(b.dataset.id, b); }));
    lv.querySelectorAll('.stub').forEach(b => b.addEventListener('click', e => { e.stopPropagation();
      showLane(+b.dataset.lane, false); const p = pane(), x = p && p.querySelector('.lvb[data-id="' + CSS.escape(b.dataset.to) + '"]');
      if (x){ x.focus({preventScroll: true}); x.classList.remove('flash'); void x.offsetWidth; x.classList.add('flash'); } }));
    lv.querySelectorAll('.lvans').forEach(a => { a.tabIndex = 0; a.setAttribute('role', 'button');
      a.setAttribute('aria-label', '지금의 답: ' + laneName(+a.dataset.lane) + '. 눌러서 연구 목록 보기');
      a.addEventListener('click', e => { e.stopPropagation(); openLane(+a.dataset.lane, a); });
      a.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openLane(+a.dataset.lane, a); } }); });
    lv.addEventListener('click', () => closePanel());
    const sw = lv.querySelector('.lvpanes'); let x0 = null, y0 = 0;
    sw.addEventListener('touchstart', e => { if (e.touches.length !== 1) { x0 = null; return; }
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, {passive: true});
    sw.addEventListener('touchend', e => { if (x0 === null) return; const t = e.changedTouches[0];
      const dx = t.clientX - x0, dy = t.clientY - y0; x0 = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > 1.6 * Math.abs(dy)) step(dx < 0 ? 1 : -1); }, {passive: true});
    if (lvBtn) lvBtn.addEventListener('click', () => { lvPref = !lvOn(); setMode(); });
    if (mq.addEventListener) mq.addEventListener('change', setMode); else if (mq.addListener) mq.addListener(setMode);
    if (window.ResizeObserver) new ResizeObserver(() => draw(pane())).observe(lv);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => draw(pane()));
  }
  setMode(); cue();
  window.addEventListener('resize', cue);

  // ------------------------------------------------------------ embed: report frame height and theme
  function post(){ if (!framed) return;
    const wrap = document.getElementById('wrap'); let h = wrap.getBoundingClientRect().bottom;
    if (!panel.hidden) h = Math.max(h, panel.getBoundingClientRect().bottom + 8);
    window.parent.postMessage({type: 'snu-embed-height', height: Math.ceil(h + window.scrollY + 8)}, '*'); }
  if (framed){
    const MAP = {'--snu-ink': '--fg', '--snu-muted': '--muted', '--snu-rule': '--line', '--snu-accent': '--link',
                 '--snu-head-bg': '--band', '--snu-surface': '--surface', '--snu-font': '--f-body'};
    window.addEventListener('message', e => { if (e.source !== window.parent) return; const d = e.data;
      if (!d || d.type !== 'snu-embed-theme') return;
      const root = document.documentElement;
      if (d.theme === 'dark' || d.theme === 'light') root.setAttribute('data-theme', d.theme);
      const v = d.vars || {};
      Object.keys(MAP).forEach(k => { const val = v[k];
        if (typeof val === 'string' && val.trim() && val.length < 300 && !/[;{}<>]|url\(/i.test(val)) root.style.setProperty(MAP[k], val.trim());
        else root.style.removeProperty(MAP[k]); });
      post(); });
    if (window.ResizeObserver) new ResizeObserver(post).observe(document.getElementById('wrap'));
    window.addEventListener('load', post); post();
  }
})();
