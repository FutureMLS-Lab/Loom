/* Research Factory - a dedicated front end for Loom's AR pipeline.
 *
 * Same origin as Loom, so the server's HTTP Basic auth and project scoping
 * apply unchanged and there is no token to manage here. Every call goes to the
 * existing /api/ar/* endpoints; this file adds no backend of its own.
 */

'use strict';

const S = {
  project: '',
  catalog: null,
  view: 'fleet',      // fleet | studio | paper
  slug: '',           // the studio or paper currently open
  parent: '',         // studio to return to from a paper
  data: null,         // last /ar payload for the open task
  picked: new Set(),
  timer: null,
  busy: false,
};

const $ = (sel) => document.querySelector(sel);
const el = (id) => document.getElementById(id);

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function toast(message, bad = false) {
  const host = el('toasts');
  const node = document.createElement('div');
  node.className = 'rf-toast' + (bad ? ' rf-toast--bad' : '');
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => node.remove(), bad ? 7000 : 4000);
}

// ===== API =====

async function api(path, opts = {}) {
  const sep = path.includes('?') ? '&' : '?';
  const url = S.project ? `${path}${sep}project=${encodeURIComponent(S.project)}` : path;
  const res = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  let body = null;
  try { body = await res.json(); } catch { /* empty or non-JSON */ }
  if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status}`);
  return body || {};
}

const taskPath = (slug, suffix = '') => `/api/tasks/${encodeURIComponent(slug)}/ar${suffix}`;

async function act(slug, action, body, label) {
  if (S.busy) return null;
  S.busy = true;
  try {
    return await api(taskPath(slug, '/' + action), {
      method: 'POST',
      body: JSON.stringify(body || {}),
    });
  } catch (err) {
    toast(`${label || action} failed: ${err.message}`, true);
    return null;
  } finally {
    S.busy = false;
  }
}

// ===== routing =====

function show(view) {
  S.view = view;
  for (const name of ['fleet', 'studio', 'paper']) {
    el(`view-${name}`).hidden = name !== view;
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openFleet() {
  S.slug = ''; S.data = null;
  show('fleet');
  loadFleet();
  writeHash('');
}

function openStudio(slug) {
  S.slug = slug; S.parent = slug; S.picked = new Set(); S.data = null;
  show('studio');
  loadTask();
  writeHash(`studio/${slug}`);
}

function openPaper(slug, parent) {
  S.slug = slug;
  if (parent) S.parent = parent;
  S.data = null;
  show('paper');
  loadTask();
  writeHash(`paper/${slug}`);
}

function writeHash(value) {
  const next = value ? `#${value}` : '#';
  if (window.location.hash !== next) history.replaceState(null, '', next);
}

function readHash() {
  const [kind, slug] = window.location.hash.replace(/^#/, '').split('/');
  if (kind === 'studio' && slug) openStudio(decodeURIComponent(slug));
  else if (kind === 'paper' && slug) openPaper(decodeURIComponent(slug));
  else openFleet();
}

// ===== fleet =====

function stageBadge(paper) {
  if (paper.awaiting_you) return '<span class="rf-pill rf-pill--wait">needs you</span>';
  if (paper.stage === 'delivered') return '<span class="rf-pill rf-pill--done">delivered</span>';
  if (paper.plateaued) return '<span class="rf-pill rf-pill--stuck">stalled</span>';
  if (paper.loop_running) return '<span class="rf-pill rf-pill--live">running</span>';
  return '<span class="rf-pill">idle</span>';
}

async function loadFleet() {
  let d;
  try { d = await api('/api/ar/overview'); }
  catch (err) { toast(err.message, true); return; }
  if (S.view !== 'fleet') return;

  const t = d.totals || {};
  el('stat-studios').innerHTML = `<b>${t.studios || 0}</b> studios`;
  el('stat-papers').innerHTML = `<b>${t.papers || 0}</b> papers`;
  el('stat-cost').innerHTML = `<b>$${(t.cost_usd || 0).toFixed(2)}</b> spent`;
  const waiting = el('stat-waiting');
  waiting.hidden = !t.awaiting_you;
  waiting.innerHTML = `<b>${t.awaiting_you}</b> waiting on you`;
  el('fleet-root').textContent = d.root || '';

  const groups = [...(d.studios || [])];
  if ((d.orphans || []).length) {
    groups.push({ slug: '', title: 'Unattached papers', direction: '', children: d.orphans });
  }
  const host = el('fleet-list');
  if (!groups.length) {
    host.innerHTML = '<div class="rf-empty">No studios yet. Start one to mine a direction and turn it into papers.</div>';
    return;
  }
  host.innerHTML = groups.map((s) => {
    const rows = (s.children || []).map((p) => `
      <div class="rf-paper-row" data-paper="${esc(p.slug)}" data-parent="${esc(s.slug)}">
        <div>
          <div class="rf-paper-row__title">${esc(p.title)}</div>
          <div class="rf-paper-row__stage">${esc(p.stage_label)}${p.best_rating ? ` · best ${p.best_rating}/10` : ''}</div>
        </div>
        <span class="rf-stat"><b>${p.round}/${p.max_rounds}</b></span>
        <span class="rf-stat"><b>$${(p.cost_usd || 0).toFixed(2)}</b></span>
        ${stageBadge(p)}
      </div>`).join('');
    const head = s.slug
      ? `<div class="rf-studio__head" data-studio="${esc(s.slug)}">
           <div>
             <div class="rf-studio__name">${esc(s.title)}</div>
             <div class="rf-studio__meta">${esc(s.direction)} · ${esc(s.venue)} · ${s.ideas} idea(s) · ${s.papers_found} paper(s) mined</div>
           </div>
           <span class="rf-pill">${esc(s.mode === 'seed' ? 'my idea' : 'auto')}</span>
         </div>`
      : `<div class="rf-studio__head"><div class="rf-studio__name">${esc(s.title)}</div></div>`;
    return `<article class="rf-studio">${head}
      <div class="rf-children">${rows || '<div class="rf-hint">No papers spawned yet.</div>'}</div>
    </article>`;
  }).join('');

  host.querySelectorAll('[data-studio]').forEach((node) => {
    node.addEventListener('click', () => openStudio(node.dataset.studio));
  });
  host.querySelectorAll('[data-paper]').forEach((node) => {
    node.addEventListener('click', () => openPaper(node.dataset.paper, node.dataset.parent));
  });
}

// ===== one task (studio or paper) =====

async function loadTask() {
  const slug = S.slug;
  if (!slug) return;
  let d;
  try { d = await api(taskPath(slug)); }
  catch (err) { toast(err.message, true); return; }
  if (S.slug !== slug) return;
  S.data = d;
  const state = d.state || {};
  if (state.role === 'paper') { show('paper'); renderPaper(d, state); }
  else { show('studio'); renderStudio(d, state); }
}

function renderLog(id, lines, running) {
  const node = el(id);
  const text = (lines || []).join('\n');
  node.hidden = !text;
  if (!text) return;
  if (node.textContent !== text) {
    const pinned = running || node.scrollTop + node.clientHeight >= node.scrollHeight - 24;
    node.textContent = text;
    if (pinned) node.scrollTop = node.scrollHeight;
  }
  node.classList.toggle('is-running', !!running);
}

// ===== studio =====

function renderStudio(d, state) {
  el('studio-title').textContent = d.title || S.slug;
  el('studio-eyebrow').textContent =
    `Studio · ${String(state.venue || '').toUpperCase()} · ${d.direction_label || ''}`;
  el('studio-sub').textContent = state.seed_idea
    || `Mining ${d.direction_label} and proposing ideas grounded in what it finds.`;

  const logs = d.logs || {};
  renderLog('papers-log', logs.papers, state.papers_status === 'running');
  renderLog('ideas-log', logs.ideas, state.ideas_status === 'running');

  const papers = state.papers || [];
  const ideas = state.ideas || [];
  el('papers-status').textContent = state.papers_status === 'running'
    ? 'mining…'
    : (state.papers_error || `${papers.length} paper(s)`);
  el('ideas-status').textContent = state.ideas_status === 'running'
    ? 'generating — a few minutes…'
    : (state.ideas_error || `${ideas.length} idea(s)`);

  el('papers-list').innerHTML = papers.map((p) => `
    <li>
      <a href="${esc(p.url)}" target="_blank" rel="noreferrer">${esc(p.title)}</a>
      ${p.venue ? `<span class="rf-pill">${esc(p.venue)}</span>` : ''}
      <p>${esc(p.published)} · ${esc((p.summary || '').slice(0, 200))}</p>
    </li>`).join('');

  el('ideas-list').innerHTML = ideas.map((idea) => {
    const spawned = idea.status === 'spawned';
    const edges = (idea.derived_from || []).map((e) =>
      `<span class="rf-edge-chip">${esc(e.relation)} · ${esc(e.title || e.paper)}</span>`).join('');
    return `<article class="rf-idea${spawned ? ' is-spawned' : ''}${S.picked.has(idea.id) ? ' is-picked' : ''}" data-idea="${esc(idea.id)}">
      <div class="rf-idea__head">
        <input type="checkbox" data-pick="${esc(idea.id)}" ${S.picked.has(idea.id) ? 'checked' : ''} ${spawned ? 'disabled' : ''} />
        <span class="rf-idea__title">${esc(idea.title)}</span>
        <span class="rf-idea__score">${Number(idea.score || 0).toFixed(2)}</span>
      </div>
      <div class="rf-idea__body">
        ${idea.hypothesis ? `<p><b>Hypothesis.</b> ${esc(idea.hypothesis)}</p>` : ''}
        ${idea.novelty ? `<p><b>New because.</b> ${esc(idea.novelty)}</p>` : ''}
        ${idea.metric ? `<p><b>Metric.</b> ${esc(idea.metric)}</p>` : ''}
        ${edges ? `<div class="rf-edges">${edges}</div>` : ''}
        ${spawned && idea.child_slug ? `<p><a href="#paper/${esc(idea.child_slug)}" data-open-paper="${esc(idea.child_slug)}">Open the paper →</a></p>` : ''}
      </div>
    </article>`;
  }).join('') || '<div class="rf-empty">No ideas yet. Mine the field first, then generate.</div>';

  el('ideas-list').querySelectorAll('[data-pick]').forEach((box) => {
    box.addEventListener('change', () => {
      if (box.checked) S.picked.add(box.dataset.pick); else S.picked.delete(box.dataset.pick);
      box.closest('.rf-idea').classList.toggle('is-picked', box.checked);
      updateSpawnLabel();
    });
  });
  el('ideas-list').querySelectorAll('[data-open-paper]').forEach((link) => {
    link.addEventListener('click', (ev) => { ev.preventDefault(); openPaper(link.dataset.openPaper, S.slug); });
  });
  updateSpawnLabel();
  drawGraph(papers, ideas);
}

function updateSpawnLabel() {
  const n = S.picked.size;
  el('btn-spawn').textContent = n ? `Create ${n} paper${n === 1 ? '' : 's'}` : 'Create papers';
}

// ===== knowledge graph =====
//
// A small force simulation rather than a charting library: the graph is two
// node kinds and one edge kind, and 120 lines of Verlet-ish relaxation keeps
// the page dependency-free and instant to load.

// Readable on the paper-white ground, and distinguishable under the common
// colour-vision deficiencies.
const RELATION_COLOR = {
  extends: '#15803d',
  contradicts: '#be123c',
  combines: '#7c3aed',
  ports: '#0369a1',
  'controls-for': '#b45309',
  'relates-to': '#8a8f97',
};

const NODE_STYLE = {
  idea: { fill: '#4f46e5', stroke: '#312e81', width: '2' },
  paper: { fill: '#ffffff', stroke: '#8a8f97', width: '1.4' },
  external: { fill: '#f5f3ed', stroke: '#cfc9bb', width: '1.2' },
};

let GRAPH = { nodes: [], links: [], raf: 0, drag: null };

function graphNodesFrom(papers, ideas) {
  const nodes = [];
  const links = [];
  const byKey = new Map();

  const addPaper = (key, label, url, mined) => {
    if (byKey.has(key)) return byKey.get(key);
    const node = {
      id: key, kind: mined ? 'paper' : 'external',
      label, url, r: mined ? 7 : 5.5,
      x: 0, y: 0, vx: 0, vy: 0,
    };
    byKey.set(key, node);
    nodes.push(node);
    return node;
  };

  papers.forEach((p) => {
    const key = p.arxiv_id || p.title;
    if (key) addPaper(key, p.title, p.url, true);
  });

  ideas.forEach((idea) => {
    const node = {
      id: `idea:${idea.id}`, kind: 'idea', label: idea.title,
      idea, r: 9 + Math.min(5, Number(idea.score || 0) * 5),
      x: 0, y: 0, vx: 0, vy: 0,
    };
    nodes.push(node);
    (idea.derived_from || []).forEach((edge) => {
      // Prefer an exact arXiv id, then a loose title match against what we
      // mined, and otherwise show the cited work as an external node - a paper
      // the model knew about that the arXiv query never surfaced.
      let target = edge.paper && byKey.get(edge.paper);
      if (!target && edge.title) {
        const needle = edge.title.toLowerCase();
        for (const [, cand] of byKey) {
          if (cand.label.toLowerCase().includes(needle) || needle.includes(cand.label.toLowerCase())) {
            target = cand; break;
          }
        }
      }
      if (!target) {
        target = addPaper(edge.paper || edge.title, edge.title || edge.paper,
          edge.paper ? `https://arxiv.org/abs/${edge.paper}` : '', false);
      }
      links.push({ source: node, target, relation: edge.relation });
    });
  });

  // A mined paper nobody derived from is not part of a derivation graph - it
  // is just a search result, and it is already listed under Recent work. With
  // thirty of them they crowd the connected subgraph into a corner, so keep
  // only the papers an idea actually points at.
  const connected = new Set();
  links.forEach((l) => { connected.add(l.source.id); connected.add(l.target.id); });
  const kept = nodes.filter((n) => n.kind === 'idea' || connected.has(n.id));
  return { nodes: kept, links, dropped: nodes.length - kept.length };
}

function drawGraph(papers, ideas) {
  const svg = el('graph');
  const { nodes, links, dropped } = graphNodesFrom(papers || [], ideas || []);
  el('graph-empty').hidden = nodes.length > 0;
  const counts = nodes.length
    ? `<span class="rf-legend-item">${nodes.filter((n) => n.kind === 'idea').length} ideas · `
      + `${nodes.length - nodes.filter((n) => n.kind === 'idea').length} cited works`
      + `${dropped ? ` · ${dropped} mined but uncited` : ''}</span>`
    : '';
  el('graph-legend').innerHTML = nodes.length
    ? counts + Object.entries(RELATION_COLOR).map(([name, color]) =>
        `<span class="rf-legend-item"><span class="rf-legend-dot" style="background:${color}"></span>${name}</span>`).join('')
    : '';
  cancelAnimationFrame(GRAPH.raf);
  svg.innerHTML = '';
  if (!nodes.length) return;

  const w = svg.clientWidth || 900;
  const h = svg.clientHeight || 520;
  nodes.forEach((n, i) => {
    // Seed ideas and papers on two rings so the first frame is already legible.
    const ring = n.kind === 'idea' ? 0.22 : 0.40;
    const a = (i / nodes.length) * Math.PI * 2;
    n.x = w / 2 + Math.cos(a) * w * ring;
    n.y = h / 2 + Math.sin(a) * h * ring;
  });

  const ns = 'http://www.w3.org/2000/svg';
  const gLinks = document.createElementNS(ns, 'g');
  const gNodes = document.createElementNS(ns, 'g');
  svg.append(gLinks, gNodes);

  links.forEach((link) => {
    link.line = document.createElementNS(ns, 'line');
    link.line.setAttribute('class', 'rf-edge-line');
    link.line.setAttribute('stroke', RELATION_COLOR[link.relation] || RELATION_COLOR['relates-to']);
    link.line.setAttribute('stroke-opacity', '0.65');
    gLinks.appendChild(link.line);
  });

  nodes.forEach((node) => {
    const g = document.createElementNS(ns, 'g');
    g.setAttribute('class', `rf-node is-${node.kind}`);
    const style = NODE_STYLE[node.kind] || NODE_STYLE.paper;
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('r', String(node.r));
    c.setAttribute('fill', style.fill);
    c.setAttribute('stroke', style.stroke);
    c.setAttribute('stroke-width', style.width);
    const label = document.createElementNS(ns, 'text');
    const short = node.label.length > 34 ? node.label.slice(0, 33) + '…' : node.label;
    label.textContent = short;
    label.setAttribute('x', String(node.r + 6));
    label.setAttribute('y', '3.5');
    g.append(c, label);
    gNodes.appendChild(g);
    node.g = g;

    g.addEventListener('pointerdown', (ev) => {
      GRAPH.drag = node; node.fixed = true;
      g.setPointerCapture(ev.pointerId);
    });
    g.addEventListener('pointermove', (ev) => {
      if (GRAPH.drag !== node) return;
      const pt = svgPoint(svg, ev);
      node.x = pt.x; node.y = pt.y; node.vx = node.vy = 0;
    });
    g.addEventListener('pointerup', () => { GRAPH.drag = null; node.fixed = false; });
    g.addEventListener('click', () => {
      if (node.kind === 'idea') {
        const card = document.querySelector(`[data-idea="${CSS.escape(node.idea.id)}"]`);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else if (node.url) {
        window.open(node.url, '_blank', 'noreferrer');
      }
    });
  });

  GRAPH = { nodes, links, raf: 0, drag: GRAPH.drag };
  let alpha = 1;
  const step = () => {
    alpha *= 0.99;
    simulate(nodes, links, w, h, alpha);
    links.forEach((l) => {
      l.line.setAttribute('x1', l.source.x); l.line.setAttribute('y1', l.source.y);
      l.line.setAttribute('x2', l.target.x); l.line.setAttribute('y2', l.target.y);
    });
    nodes.forEach((n) => n.g.setAttribute('transform', `translate(${n.x},${n.y})`));
    if (alpha > 0.008) GRAPH.raf = requestAnimationFrame(step);
  };
  step();
}

function svgPoint(svg, ev) {
  const rect = svg.getBoundingClientRect();
  return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
}

function simulate(nodes, links, w, h, alpha) {
  // Repulsion between every pair, springs along the edges, and a gentle pull
  // to the middle. Node counts here are tens, so O(n^2) is free.
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.hypot(dx, dy) || 0.01;
      let push = (9000 * alpha) / (dist * dist);
      // Labels sit to the right of a node, so two nodes at the same height
      // collide long before their circles do. Push hard when that close.
      if (dist < 120) push += (120 - dist) * 0.09 * alpha;
      dx /= dist; dy /= dist;
      a.vx -= dx * push; a.vy -= dy * push;
      b.vx += dx * push; b.vy += dy * push;
    }
  }
  links.forEach((l) => {
    const dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
    const dist = Math.hypot(dx, dy) || 0.01;
    const force = (dist - 190) * 0.010 * alpha;
    const ux = (dx / dist) * force, uy = (dy / dist) * force;
    l.source.vx += ux; l.source.vy += uy;
    l.target.vx -= ux; l.target.vy -= uy;
  });
  nodes.forEach((n) => {
    n.vx += (w / 2 - n.x) * 0.0016 * alpha;
    n.vy += (h / 2 - n.y) * 0.0016 * alpha;
    if (!n.fixed) {
      n.x += (n.vx *= 0.82);
      n.y += (n.vy *= 0.82);
    }
    const pad = 70;
    n.x = Math.max(pad, Math.min(w - pad, n.x));
    n.y = Math.max(24, Math.min(h - 24, n.y));
  });
}

// ===== paper =====

const STAGES = [
  ['draft', 'Draft'],
  ['await_draft_review', 'Your review'],
  ['loop', 'Rounds'],
  ['await_final_review', 'Final review'],
  ['delivered', 'Delivered'],
];

function renderPaper(d, state) {
  const idea = state.idea || {};
  el('paper-title').textContent = idea.title || S.slug;
  el('paper-eyebrow').textContent = `Paper · ${String(state.venue || '').toUpperCase()}`;
  el('paper-hypothesis').textContent = idea.hypothesis || '';

  const at = STAGES.findIndex(([id]) => id === state.stage);
  el('paper-pipeline').innerHTML = STAGES.map(([id, label], i) => {
    const cls = i < at ? 'is-done' : (i === at ? 'is-current' : '');
    const extra = id === 'loop' ? `${state.round || 0} of ${state.max_rounds || 0}` : '';
    return `<li class="${cls}"><b>${esc(label)}</b>${esc(extra)}</li>`;
  }).join('');

  const meta = [];
  if (d.best_rating) meta.push(`best rating ${d.best_rating}/10`);
  if (Number(state.cost_usd) > 0) meta.push(`$${Number(state.cost_usd).toFixed(2)} spent`);
  if (state.stop_reason) meta.push(`stopped early: ${state.stop_reason}`);
  if (state.pdf_error) meta.push(state.pdf_error);
  if (d.paper_dir) meta.push(d.paper_dir);
  el('paper-meta').textContent = meta.join(' · ');

  // gate
  const atDraft = state.stage === 'await_draft_review';
  const atFinal = state.stage === 'await_final_review';
  const gate = el('paper-gate');
  gate.hidden = !(atDraft || atFinal);
  gate.dataset.gate = atDraft ? 'draft' : 'final';
  if (!gate.hidden) {
    el('gate-title').textContent = atDraft ? 'Draft gate' : 'Final gate';
    el('gate-hint').textContent = atDraft
      ? 'The skeleton draft is ready. Approve to open the author/reviewer rounds, or send it back with notes.'
      : `The loop is done. Approve to deliver, or send it back for another batch of rounds.`;
    el('btn-gate-approve').textContent = atDraft ? 'Approve draft' : 'Approve and deliver';
  }

  // scores
  const rounds = state.rounds || [];
  const scored = rounds.filter((r) => (r.review || {}).scores);
  el('score-chart').innerHTML = scored.map((r) => {
    const v = Number(r.review.scores.rating || 0);
    return `<div class="rf-score-bar" title="round ${r.n}">
      <span class="rf-score-bar__v">${v || '–'}</span>
      <div class="rf-score-bar__fill" style="height:${Math.max(3, v * 7)}px"></div>
      <span class="rf-score-bar__n">${r.n}</span>
    </div>`;
  }).join('');

  const loop = d.loop || {};
  const bits = [loop.running ? 'loop running' : 'loop stopped'];
  if (loop.last_action) bits.push(loop.last_action);
  if (loop.last_error) bits.push(`error: ${loop.last_error}`);
  if (d.plateaued) bits.push('score has stalled — the author was told to change tack');
  el('loop-status').textContent = bits.join(' · ');
  renderLog('review-log', (d.logs || {}).review, state.review_status === 'running' || loop.running);

  el('rounds-list').innerHTML = rounds.slice().reverse().map((r) => {
    const review = r.review || null;
    const author = r.author || null;
    const scores = (review && review.scores) || {};
    const chips = Object.entries(scores)
      .map(([k, v]) => `<span class="rf-pill">${esc(k)} ${esc(v)}</span>`).join(' ');
    return `<li class="rf-round">
      <div class="rf-round__head">
        <span class="rf-round__n">${r.n === 0 ? 'Draft' : `Round ${r.n}`}</span>
        <span class="rf-round__headline">${esc((review && review.headline) || (r.review_error ? `review failed: ${r.review_error}` : 'in progress…'))}</span>
        ${chips}
        ${review ? `<button type="button" class="rf-btn rf-btn--sm" data-review="${r.n}">Read review</button>` : ''}
      </div>
      ${author && author.summary ? `<pre class="rf-round__summary">${esc(author.summary.slice(0, 1200))}</pre>` : ''}
    </li>`;
  }).join('') || '<div class="rf-empty">No rounds yet.</div>';

  el('rounds-list').querySelectorAll('[data-review]').forEach((btn) => {
    btn.addEventListener('click', () => openReview(Number(btn.dataset.review)));
  });

  renderSubmission(d.submission);
}

function renderSubmission(sub) {
  const box = el('submission-section');
  box.hidden = !sub;
  if (!sub) return;
  el('submission-checks').innerHTML = (sub.checks || []).map((c) =>
    `<li class="${c.ok ? 'is-ok' : 'is-bad'}"><b>${c.ok ? '✓' : '✗'}</b>
      <span>${esc(c.label)}${c.detail ? ` <em>${esc(c.detail)}</em>` : ''}</span></li>`).join('');
  el('submission-command').textContent = sub.command || '';
}

async function openReview(n) {
  try {
    const d = await api(taskPath(S.slug, `/review/${n}`));
    el('review-modal-title').textContent = n === 0 ? 'Draft review' : `Round ${n} review`;
    el('review-body').innerHTML = miniMarkdown(d.review || '');
    el('review-modal').hidden = false;
  } catch (err) { toast(err.message, true); }
}

// Reviews are the only markdown this page renders, and they follow a fixed
// template: headings, bullets, bold, inline code.
function miniMarkdown(md) {
  const lines = String(md).split('\n');
  const out = [];
  let list = false;
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      if (!list) { out.push('<ul>'); list = true; }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    if (list) { out.push('</ul>'); list = false; }
    const head = line.match(/^(#{1,4})\s+(.*)$/);
    if (head) out.push(`<h2>${inline(head[2])}</h2>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push('</ul>');
  return out.join('\n');
}

// ===== polling =====

function startPolling() {
  if (S.timer) clearInterval(S.timer);
  S.timer = setInterval(() => {
    if (document.hidden) return;
    if (S.view === 'fleet') loadFleet();
    else loadTask();
  }, 6000);
}

// ===== wiring =====

document.querySelectorAll('[data-back]').forEach((btn) => {
  btn.addEventListener('click', () => {
    if (S.view === 'paper' && S.parent) openStudio(S.parent);
    else openFleet();
  });
});
el('btn-refresh').addEventListener('click', () => (S.view === 'fleet' ? loadFleet() : loadTask()));

el('btn-mine').addEventListener('click', async () => {
  await act(S.slug, 'mine', { venue_only: el('studio-venue-only').checked }, 'Mining');
  loadTask();
});
el('btn-ideas').addEventListener('click', async () => {
  await act(S.slug, 'ideas', { count: Number(el('studio-count').value || 6) }, 'Idea generation');
  loadTask();
});
el('btn-link').addEventListener('click', async () => {
  await act(S.slug, 'link', {}, 'Linking ideas');
  loadTask();
});
el('btn-spawn').addEventListener('click', async () => {
  if (!S.picked.size) { toast('Pick at least one idea first.'); return; }
  const d = await act(S.slug, 'spawn', { idea_ids: [...S.picked] }, 'Creating papers');
  if (!d) return;
  S.picked = new Set();
  toast(`Created ${(d.spawned || []).length} paper task(s).`);
  (d.errors || []).forEach((e) => toast(e, true));
  loadTask();
});

el('btn-paper-build').addEventListener('click', async () => {
  const d = await act(S.slug, 'build', {}, 'Build');
  if (d && d.build && !d.build.ok) toast(d.build.error || 'Build failed', true);
  loadTask();
});
el('btn-paper-pdf').addEventListener('click', () => {
  const sep = '?';
  window.open(`${taskPath(S.slug, '/pdf')}${sep}project=${encodeURIComponent(S.project)}`, '_blank');
});
el('btn-paper-submission').addEventListener('click', async () => {
  const d = await act(S.slug, 'submission', {}, 'Submission prep');
  if (d && d.submission) {
    toast(d.submission.ready ? `Ready for ${d.submission.venue_label}.` : 'Not ready — see the checklist.');
  }
  loadTask();
});
el('btn-loop-start').addEventListener('click', async () => { await act(S.slug, 'loop/start', {}, 'Start loop'); loadTask(); });
el('btn-loop-stop').addEventListener('click', async () => { await act(S.slug, 'loop/stop', {}, 'Stop loop'); loadTask(); });
el('btn-review-now').addEventListener('click', async () => { await act(S.slug, 'review', {}, 'Review'); loadTask(); });

['approve', 'reject'].forEach((decision) => {
  el(`btn-gate-${decision}`).addEventListener('click', async () => {
    const gate = el('paper-gate').dataset.gate || 'draft';
    await act(S.slug, 'gate', { gate, decision, note: el('gate-note').value }, 'Gate');
    el('gate-note').value = '';
    loadTask();
  });
});

el('btn-review-close').addEventListener('click', () => { el('review-modal').hidden = true; });
el('review-modal').addEventListener('click', (ev) => {
  if (ev.target.id === 'review-modal') el('review-modal').hidden = true;
});
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!el('review-modal').hidden) el('review-modal').hidden = true;
  else if (!el('studio-modal').hidden) el('studio-modal').hidden = true;
});

// --- new studio ---

el('btn-new-studio').addEventListener('click', () => {
  const cat = S.catalog || {};
  const dir = el('new-direction');
  if (!dir.options.length) {
    dir.innerHTML = (cat.directions || []).map((x) => `<option value="${esc(x.id)}">${esc(x.label)}</option>`).join('');
    el('new-venue').innerHTML = (cat.venues || []).map((x) => `<option value="${esc(x.id)}">${esc(x.label)}</option>`).join('');
    if (cat.default_venue) el('new-venue').value = cat.default_venue;
    if (cat.default_max_rounds) el('new-rounds').value = cat.default_max_rounds;
  }
  el('studio-modal-status').textContent = '';
  el('studio-modal').hidden = false;
  el('new-title').focus();
});
el('btn-studio-cancel').addEventListener('click', () => { el('studio-modal').hidden = true; });
el('new-direction').addEventListener('change', () => {
  el('new-custom-direction').hidden = el('new-direction').value !== 'custom';
});
document.querySelectorAll('input[name="new-mode"]').forEach((radio) => {
  radio.addEventListener('change', () => {
    const seeded = document.querySelector('input[name="new-mode"]:checked').value === 'seed';
    el('new-seed-label').textContent = seeded
      ? 'What the paper should be about'
      : 'What the paper should be about (optional)';
  });
});
el('btn-studio-create').addEventListener('click', async () => {
  const title = el('new-title').value.trim();
  const mode = document.querySelector('input[name="new-mode"]:checked').value;
  const seed = el('new-seed').value.trim();
  const status = el('studio-modal-status');
  if (!title) { status.textContent = 'A name is required.'; return; }
  if (mode === 'seed' && !seed) { status.textContent = 'Describe the idea, or switch to auto.'; return; }
  status.textContent = 'Creating…';
  try {
    const { meta } = await api('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title, kind: 'ar', agent: 'cursor',
        ar_direction: el('new-direction').value,
        ar_custom_direction: el('new-custom-direction').value.trim(),
        ar_venue: el('new-venue').value,
        ar_mode: mode,
        ar_seed_idea: seed,
        ar_max_rounds: Number(el('new-rounds').value || 10),
      }),
    });
    el('studio-modal').hidden = true;
    el('new-title').value = ''; el('new-seed').value = '';
    openStudio(meta.slug);
  } catch (err) {
    status.textContent = err.message;
  }
});

// ===== boot =====

(async function init() {
  try {
    S.catalog = await api('/api/ar/catalog');
    S.project = S.catalog.project || '';
  } catch (err) {
    toast(`Could not reach Loom: ${err.message}`, true);
  }
  if (!S.project) {
    toast('No AR project registered yet — restart Loom to create one.', true);
  }
  readHash();
  startPolling();
  window.addEventListener('hashchange', readHash);
  window.addEventListener('resize', () => {
    if (S.view === 'studio' && S.data) {
      const st = S.data.state || {};
      drawGraph(st.papers || [], st.ideas || []);
    }
  });
})();
