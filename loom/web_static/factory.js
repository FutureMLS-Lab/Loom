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
  graphSel: '',              // node the user clicked into, '' when nothing is
  graphHide: new Set(),      // relations switched off in the legend
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
  // Every poll re-renders through here, so only move the viewport when the
  // view actually changed. Scrolling the reader to the top every six seconds
  // makes the page unusable while a job is running.
  const changed = S.view !== view;
  S.view = view;
  for (const name of ['fleet', 'studio', 'paper']) {
    el(`view-${name}`).hidden = name !== view;
  }
  if (changed) window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openFleet() {
  S.slug = ''; S.data = null;
  show('fleet');
  loadFleet();
  writeHash('');
}

function openStudio(slug) {
  S.slug = slug; S.parent = slug; S.picked = new Set(); S.data = null;
  S.graphSel = ''; S.graphHide = new Set();
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
    const edges = (idea.derived_from || []).map((e) => {
      const mark = e.verified === true ? ' ✓' : (e.paper && e.verified === false ? ' ✗' : '');
      const cls = e.verified === false && e.paper ? ' is-unverified' : '';
      return `<span class="rf-edge-chip${cls}" title="${esc(e.real_title || '')}">`
        + `${esc(e.relation)} · ${esc(e.title || e.paper)}${mark}</span>`;
    }).join('');
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
  renderSteps(state, papers, ideas);
  drawGraph(papers, ideas);
}

// Each step reports its own state, and the first unfinished one is marked
// current so there is always one obvious next thing to press.
function renderSteps(state, papers, ideas) {
  const edges = ideas.reduce((n, i) => n + (i.derived_from || []).length, 0);
  const spawned = ideas.filter((i) => i.status === 'spawned').length;
  const running = (job) => state[`${job}_status`] === 'running';

  const steps = [
    {
      id: 'mine',
      done: papers.length > 0,
      state: running('papers') ? 'mining…'
        : papers.length ? `${papers.length} papers mined`
        : (state.papers_error || 'not run yet'),
    },
    {
      id: 'ideas',
      done: ideas.length > 0,
      state: running('ideas') ? 'generating, a few minutes…'
        : ideas.length ? `${ideas.length} ideas`
        : (state.ideas_error || 'not run yet'),
    },
    {
      id: 'link',
      done: edges > 0,
      state: running('link') ? 'grounding and verifying…'
        : edges ? `${edges} citations across ${ideas.filter((i) => (i.derived_from || []).length).length} ideas`
        : (state.link_error || 'ideas are not grounded yet'),
    },
    {
      id: 'spawn',
      done: spawned > 0,
      state: spawned ? `${spawned} paper task(s) created` : 'nothing picked yet',
    },
  ];
  const current = steps.findIndex((s) => !s.done);
  steps.forEach((s, i) => {
    const node = document.querySelector(`.rf-step[data-step="${s.id}"]`);
    if (!node) return;
    node.classList.toggle('is-done', s.done);
    node.classList.toggle('is-current', i === current);
    const label = el(`step-${s.id}-state`);
    if (label) label.textContent = s.state;
  });
}

function updateSpawnLabel() {
  const n = S.picked.size;
  el('btn-spawn').textContent = n ? `Create ${n} paper${n === 1 ? '' : 's'}` : 'Create papers';
}

// ===== knowledge graph =====
//
// The data is bipartite - ideas derive from prior work, never from each other -
// so it is drawn as two columns rather than relaxed into a force layout. A
// force graph of the same edges was unreadable: labels sit beside their node
// and collide long before the circles do, and the result looked like tangle
// however it was tuned. Columns cannot overlap, and reading left to right is
// the same direction as "this idea came from that paper".

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

// The relation read as a sentence. Colour alone means holding a six-item
// legend in your head; the wording lets a selected edge explain itself.
const RELATION_TEXT = {
  extends: 'builds on',
  contradicts: 'argues against',
  combines: 'combines',
  ports: 'ports the method from',
  'controls-for': 'controls for',
  'relates-to': 'relates to',
};

const NODE_STYLE = {
  idea: { fill: '#4f46e5', stroke: '#312e81', width: '2' },
  paper: { fill: '#ffffff', stroke: '#8a8f97', width: '1.4' },
  external: { fill: '#f5f3ed', stroke: '#cfc9bb', width: '1.2' },
};

function graphNodesFrom(papers, ideas) {
  const nodes = [];
  const links = [];
  const byKey = new Map();

  const addPaper = (key, label, url, mined) => {
    if (byKey.has(key)) return byKey.get(key);
    const node = {
      id: key, kind: mined ? 'paper' : 'external',
      label, url, r: mined ? 6.5 : 5, x: 0, y: 0,
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
      idea, r: 8 + Math.min(4, Number(idea.score || 0) * 4), x: 0, y: 0,
      hover: idea.hypothesis || idea.title,
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
      // What OpenAlex confirmed about this citation, shown beside the node so
      // an unverified reference is visible rather than implied.
      if (edge.verified === true) {
        target.meta = `✓${edge.cited_by ? ` ${edge.cited_by} cites` : ''}`;
        target.hover = `${edge.real_title || target.label}${edge.year ? ` (${edge.year})` : ''}`;
      } else if (edge.paper && edge.verified === false) {
        target.meta = '✗ unverified';
        target.hover = `${target.label} — arXiv ${edge.paper} could not be confirmed`;
      }
      links.push({ source: node, target, relation: edge.relation, edge });
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

const SVG_NS = 'http://www.w3.org/2000/svg';
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

function svgEl(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

function drawGraph(papers, ideas) {
  const svg = el('graph');
  const all = graphNodesFrom(papers || [], ideas || []);

  // Legend switches drop a relation's edges, and any cited work left with
  // nothing pointing at it goes with them - a lone circle in the left column
  // would otherwise read as "cited by nothing", which is not what it means.
  const links = all.links.filter((l) => !S.graphHide.has(l.relation || 'relates-to'));
  const live = new Set();
  links.forEach((l) => { live.add(l.source.id); live.add(l.target.id); });
  const nodes = all.nodes.filter((n) => n.kind === 'idea' || live.has(n.id));
  const works = nodes.filter((n) => n.kind !== 'idea');
  const ours = nodes.filter((n) => n.kind === 'idea');

  drawLegend(all, works.length, ours.length);
  svg.innerHTML = '';
  const empty = el('graph-empty');
  if (!links.length) {
    // Either nothing has been generated yet, or the legend has every relation
    // switched off - which looks identical without saying so.
    empty.textContent = all.links.length
      ? 'Every relation is hidden. Turn one back on in the legend below.'
      : 'Run steps 1 to 3 and the graph appears here.';
    empty.hidden = false;
    svg.removeAttribute('height');
    renderGraphDetail(null, []);
    return;
  }
  empty.hidden = true;

  // Order the left column so edges cross as little as possible: a cited work
  // sits at the average height of the ideas that cite it.
  const rows = Math.max(works.length, ours.length);
  const rowH = 34;
  const top = 28;
  const height = top * 2 + Math.max(1, rows - 1) * rowH;
  const width = svg.clientWidth || 900;
  const leftX = 210;
  const rightX = Math.max(leftX + 220, width - 330);

  ours.forEach((n, i) => { n.x = rightX; n.y = top + i * (ours.length > 1 ? (height - 2 * top) / (ours.length - 1) : 0); });
  works.forEach((n) => {
    const mine = links.filter((l) => l.target === n).map((l) => l.source.y);
    n.order = mine.length ? mine.reduce((a, b) => a + b, 0) / mine.length : height;
  });
  works.sort((a, b) => a.order - b.order);
  works.forEach((n, i) => { n.x = leftX; n.y = top + i * (works.length > 1 ? (height - 2 * top) / (works.length - 1) : 0); });

  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('height', String(height));
  const gLinks = svgEl('g');
  const gTags = svgEl('g');
  const gNodes = svgEl('g');
  svg.append(gLinks, gTags, gNodes);

  links.forEach((link) => {
    const { source: a, target: b } = link;
    const mid = (a.x + b.x) / 2;
    link.path = svgEl('path', {
      class: 'rf-edge-line',
      d: `M ${b.x} ${b.y} C ${mid} ${b.y}, ${mid} ${a.y}, ${a.x} ${a.y}`,
      stroke: RELATION_COLOR[link.relation] || RELATION_COLOR['relates-to'],
      'stroke-opacity': 0.55,
    });
    gLinks.appendChild(link.path);

    // Revealed only while one end is in focus - labelling all eighteen at once
    // would bury the picture it explains. Sat a quarter along from the paper
    // rather than at the midpoint: every edge of one idea converges on the
    // same point, so midpoint labels land on top of each other, while near the
    // papers they inherit the row spacing and stay apart.
    const t = 0.25;
    const u = 1 - t;
    const tag = svgEl('text', {
      class: 'rf-edge-tag',
      x: u * u * u * b.x + 3 * u * t * (u + t) * mid + t * t * t * a.x,
      y: (u * u * u + 3 * u * u * t) * b.y + (3 * u * t * t + t * t * t) * a.y - 5,
      'text-anchor': 'middle', opacity: '0',
      fill: RELATION_COLOR[link.relation] || RELATION_COLOR['relates-to'],
    });
    tag.textContent = RELATION_TEXT[link.relation] || link.relation || '';
    link.tag = tag;
    gTags.appendChild(tag);
  });

  const paint = (node, side) => {
    const g = svgEl('g', {
      class: `rf-node is-${node.kind}`, transform: `translate(${node.x},${node.y})`,
      tabindex: '0', role: 'button',
      'aria-label': `${node.kind === 'idea' ? 'Idea' : 'Cited work'}: ${node.label}`,
    });
    const style = NODE_STYLE[node.kind] || NODE_STYLE.paper;
    // A generous invisible target. The circles are 5-8px across, which is a
    // hard thing to hit and an easy thing to fall off mid-read.
    g.appendChild(svgEl('rect', {
      class: 'rf-node-hit',
      x: side === 'left' ? -230 : -(node.r + 10), y: -rowH / 2,
      width: 230 + node.r + 10, height: rowH, fill: 'transparent',
    }));
    g.appendChild(svgEl('circle', {
      class: 'rf-node-dot',
      r: node.r, fill: style.fill, stroke: style.stroke, 'stroke-width': style.width,
    }));
    const label = svgEl('text', {
      x: side === 'left' ? -(node.r + 8) : node.r + 8,
      y: 3.5,
      'text-anchor': side === 'left' ? 'end' : 'start',
    });
    label.textContent = clip(node.label, side === 'left' ? 26 : 40);
    g.appendChild(label);
    if (side === 'left' && node.meta) {
      const meta = svgEl('text', { x: node.r + 8, y: 3.5, class: 'rf-node-meta' });
      meta.textContent = node.meta;
      g.appendChild(meta);
    }
    const select = () => {
      S.graphSel = S.graphSel === node.id ? '' : node.id;
      applyGraphFocus(nodes, links);
    };
    g.addEventListener('click', (ev) => { ev.stopPropagation(); select(); });
    g.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(); }
    });
    // Hover is a preview only. It used to be the only way to isolate a node,
    // which meant the answer vanished the moment you moved to read it.
    g.addEventListener('mouseenter', () => { if (!S.graphSel) applyGraphFocus(nodes, links, node); });
    g.addEventListener('mouseleave', () => { if (!S.graphSel) applyGraphFocus(nodes, links); });
    gNodes.appendChild(g);
    node.g = g;
  };

  works.forEach((n) => paint(n, 'left'));
  ours.forEach((n) => paint(n, 'right'));

  const heading = (x, text, anchor) => {
    const t = svgEl('text', { x, y: 14, class: 'rf-graph-heading', 'text-anchor': anchor });
    t.textContent = text;
    svg.appendChild(t);
  };
  heading(leftX, 'PRIOR WORK', 'end');
  heading(rightX, 'IDEAS', 'start');

  svg.onclick = () => { S.graphSel = ''; applyGraphFocus(nodes, links); };
  applyGraphFocus(nodes, links);
}

// Dim everything off the focused node's edges and name the relations that
// remain. `hover` is the transient version; with nothing hovered it falls back
// to whatever is selected, and to the plain picture when neither is set.
function applyGraphFocus(nodes, links, hover) {
  const focus = hover || nodes.find((n) => n.id === S.graphSel) || null;
  const mine = focus ? links.filter((l) => l.source === focus || l.target === focus) : [];
  const near = new Set(focus ? [focus] : []);
  mine.forEach((l) => { near.add(l.source); near.add(l.target); });

  nodes.forEach((n) => {
    n.g.classList.toggle('is-dim', Boolean(focus) && !near.has(n));
    n.g.classList.toggle('is-selected', Boolean(S.graphSel) && n.id === S.graphSel);
  });
  links.forEach((l) => {
    const on = !focus || mine.includes(l);
    l.path.setAttribute('stroke-opacity', focus ? (on ? '0.95' : '0.07') : '0.55');
    l.path.classList.toggle('is-lit', Boolean(focus) && on);
    if (l.tag) l.tag.setAttribute('opacity', focus && on ? '1' : '0');
  });
  renderGraphDetail(hover ? null : focus, mine);
}

// What the picture cannot say: full titles, whether a citation checked out,
// and where to go next. Clicking a node used to jump straight to arXiv, which
// took you off the page before you knew what you had clicked.
function renderGraphDetail(node, links) {
  const host = el('graph-detail');
  if (!host) return;
  if (!node) {
    host.innerHTML = '<p class="rf-detail-hint">Click any node to see what it is,'
      + ' what it connects to, and where to open it. Use the legend to hide a relation.</p>';
    return;
  }
  const rel = (l) => `<span class="rf-detail-rel" style="color:${RELATION_COLOR[l.relation] || RELATION_COLOR['relates-to']}">`
    + `${esc(RELATION_TEXT[l.relation] || l.relation || 'relates to')}</span>`;

  if (node.kind === 'idea') {
    const idea = node.idea || {};
    host.innerHTML = `
      <div class="rf-detail-head">
        <span class="rf-pill rf-pill--idea">idea</span>
        <b>${esc(idea.title || node.label)}</b>
        <span class="rf-detail-score">${Number(idea.score || 0).toFixed(2)}</span>
      </div>
      ${idea.hypothesis ? `<p class="rf-detail-body">${esc(idea.hypothesis)}</p>` : ''}
      <ul class="rf-detail-links">${links.map((l) =>
        `<li>${rel(l)} <span>${esc(l.target.label)}</span>${
          l.edge && l.edge.verified === true ? '<span class="rf-detail-ok">verified</span>' : ''}${
          l.edge && l.edge.verified === false && l.edge.paper ? '<span class="rf-detail-bad">unverified</span>' : ''}</li>`).join('')
        || '<li class="rf-detail-hint">No grounding recorded for this idea.</li>'}</ul>
      <div class="rf-detail-actions">
        <button type="button" class="rf-btn rf-btn--ghost rf-btn--sm" data-detail="card">Show the full card</button>
        ${idea.child_slug ? '<button type="button" class="rf-btn rf-btn--ghost rf-btn--sm" data-detail="paper">Open the paper</button>' : ''}
      </div>`;
    host.querySelector('[data-detail="card"]').onclick = () => {
      const card = document.querySelector(`[data-idea="${CSS.escape(idea.id)}"]`);
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('is-flash');
        setTimeout(() => card.classList.remove('is-flash'), 1200);
      }
    };
    const open = host.querySelector('[data-detail="paper"]');
    if (open) open.onclick = () => openPaper(idea.child_slug, S.slug);
    return;
  }

  const verified = node.meta && node.meta.startsWith('✓');
  host.innerHTML = `
    <div class="rf-detail-head">
      <span class="rf-pill">${node.kind === 'paper' ? 'mined' : 'cited'}</span>
      <b>${esc(node.hover || node.label)}</b>
      ${verified ? `<span class="rf-detail-ok">${esc(node.meta.slice(1).trim() || 'verified')}</span>`
        : (node.meta ? `<span class="rf-detail-bad">${esc(node.meta.replace('✗', '').trim())}</span>` : '')}
    </div>
    <ul class="rf-detail-links">${links.map((l) =>
      `<li><span>${esc(l.source.label)}</span> ${rel(l)} this</li>`).join('')}</ul>
    <div class="rf-detail-actions">
      ${node.url ? `<a class="rf-btn rf-btn--ghost rf-btn--sm" href="${esc(node.url)}" target="_blank" rel="noreferrer">Open on arXiv</a>` : ''}
    </div>`;
}

// Counts make the legend a summary as well as a control, and switching a
// relation off is the quickest way to read a busy picture.
function drawLegend(all, workCount, ideaCount) {
  const host = el('graph-legend');
  if (!all.links.length) { host.innerHTML = ''; return; }
  const counts = {};
  all.links.forEach((l) => {
    const r = l.relation || 'relates-to';
    counts[r] = (counts[r] || 0) + 1;
  });
  host.innerHTML = `<span class="rf-legend-count">${ideaCount} ideas · ${workCount} cited works`
    + `${all.dropped ? ` · ${all.dropped} mined but uncited` : ''}</span>`
    + Object.keys(counts).sort().map((name) => {
      const off = S.graphHide.has(name);
      return `<button type="button" class="rf-legend-item${off ? ' is-off' : ''}" data-rel="${esc(name)}"`
        + ` aria-pressed="${off ? 'false' : 'true'}" title="${off ? 'Show' : 'Hide'} ${esc(name)} edges">`
        + `<span class="rf-legend-dot" style="background:${RELATION_COLOR[name] || RELATION_COLOR['relates-to']}"></span>`
        + `${esc(name)}<span class="rf-legend-n">${counts[name]}</span></button>`;
    }).join('');

  host.querySelectorAll('[data-rel]').forEach((btn) => {
    btn.onclick = () => {
      const name = btn.dataset.rel;
      if (S.graphHide.has(name)) S.graphHide.delete(name); else S.graphHide.add(name);
      S.graphSel = '';
      const st = (S.data && S.data.state) || {};
      drawGraph(st.papers || [], st.ideas || []);
    };
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
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && S.graphSel) {
      S.graphSel = '';
      const st = (S.data && S.data.state) || {};
      drawGraph(st.papers || [], st.ideas || []);
    }
  });
  window.addEventListener('resize', () => {
    if (S.view === 'studio' && S.data) {
      const st = S.data.state || {};
      drawGraph(st.papers || [], st.ideas || []);
    }
  });
})();
