(function(){
  const N = __NODES__, E = __EDGES__, LANES = __LANES__, KIND = __KIND__;
  const svg = document.getElementById('tree'), stage = document.getElementById('stage');
  const tip = document.getElementById('tip');
  const out = {}, inn = {};
  E.forEach(([s,t]) => { (out[s] = out[s] || []).push(t); (inn[t] = inn[t] || []).push(s); });
  function walk(start, adj){ const seen = new Set([start]), st=[start];
    while (st.length){ const v = st.pop(); (adj[v]||[]).forEach(u => { if(!seen.has(u)){ seen.add(u); st.push(u);} }); }
    return seen; }
  const nodes = [...svg.querySelectorAll('.node')], edges = [...svg.querySelectorAll('.e')];
  let laneSel = null;
  function clear(){ svg.classList.remove('focus'); nodes.forEach(n=>n.classList.remove('on')); edges.forEach(e=>e.classList.remove('on')); }
  function applyLane(){ clear(); if (laneSel === null) return;
    svg.classList.add('focus');
    nodes.forEach(n => { if (+n.dataset.lane === laneSel) n.classList.add('on'); });
    edges.forEach(e => { const a = N[e.dataset.s], b = N[e.dataset.t];
      if (a.lane === laneSel && b.lane === laneSel) e.classList.add('on'); }); }
  function lineage(id){ clear(); svg.classList.add('focus');
    const set = new Set([...walk(id, out), ...walk(id, inn)]);
    nodes.forEach(n => { if (set.has(n.dataset.id)) n.classList.add('on'); });
    edges.forEach(e => { if (set.has(e.dataset.s) && set.has(e.dataset.t)) e.classList.add('on'); }); }
  function showTip(el){ const d = N[el.dataset.id];
    const lane = LANES[d.lane];
    tip.innerHTML = '<div class="k"><i style="background:var(--c'+d.lane+')"></i>'+lane+'</div>'
      + '<div class="t"></div><div class="m"></div><div class="n"></div><div class="lk"></div>';
    tip.querySelector('.t').textContent = d.t;
    tip.querySelector('.m').textContent = [d.by, d.venue, d.year, d.cites!=null ? ('인용 '+d.cites.toLocaleString()) : ''].filter(Boolean).join(' · ');
    tip.querySelector('.n').textContent = d.note;
    tip.querySelector('.lk').textContent = '누르면 '+KIND[d.kind]+' 원문이 새 탭에서 열림 ↗';
    tip.hidden = false;
    const sr = stage.getBoundingClientRect(), r = el.getBoundingClientRect();
    let x = r.right - sr.left + 10, y = r.top - sr.top - 6;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > sr.width - 4) x = r.left - sr.left - w - 10;
    if (x < 4) { x = Math.max(4, r.left - sr.left); y = r.bottom - sr.top + 8; }
    y = Math.min(Math.max(4, y), Math.max(4, stage.scrollHeight - h - 4));
    tip.style.left = x + 'px'; tip.style.top = y + 'px'; }
  function leave(){ tip.hidden = true; applyLane(); }
  nodes.forEach(n => {
    n.addEventListener('mouseenter', () => { lineage(n.dataset.id); showTip(n); });
    n.addEventListener('focus', () => { lineage(n.dataset.id); showTip(n); });
    n.addEventListener('mouseleave', leave); n.addEventListener('blur', leave);
  });
  document.querySelectorAll('.lanebtn').forEach(b => b.addEventListener('click', () => {
    const v = b.dataset.lane === 'all' ? null : +b.dataset.lane;
    laneSel = (laneSel === v) ? null : v;
    document.querySelectorAll('.lanebtn').forEach(x => x.setAttribute('aria-pressed',
      String(x.dataset.lane === 'all' ? laneSel === null : +x.dataset.lane === laneSel)));
    applyLane(); }));
})();
