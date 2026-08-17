/* Auto Rebuttal Factory — Conference Studio → Paper Rebuttal. */
'use strict';

const R = {
  view: 'fleet',
  studioId: '',
  paperId: '',
  studio: null,
  paper: null,
  studios: [],
  projects: [],
  busy: false,
  timer: null,
  dirtyResponses: new Set(),
  paperPolicyDirty: false,
  studioPolicyDirty: false,
  agentLive: false,
  agentLiveTouched: false,
};

const el = (id) => document.getElementById(id);
const esc = (value) => String(value == null ? '' : value).replace(
  /[&<>"']/g,
  (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]),
);

function toast(message, bad = false) {
  const node = document.createElement('div');
  node.className = `rb-toast${bad ? ' is-bad' : ''}`;
  node.textContent = message;
  el('toasts').appendChild(node);
  setTimeout(() => node.remove(), bad ? 7500 : 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  let payload = {};
  try { payload = await response.json(); } catch { /* empty response */ }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

function shortTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function markdownInline(value) {
  let text = esc(value);
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return text;
}

function displayMathBlock(lines, start) {
  const first = String(lines[start] || '').trim();
  const opening = first.startsWith('$$') ? '$$' : (first.startsWith('\\[') ? '\\[' : '');
  if (!opening) return null;
  const closing = opening === '$$' ? '$$' : '\\]';
  let end = start;
  let closed = first.slice(opening.length).includes(closing);
  while (!closed && end + 1 < lines.length) {
    end += 1;
    closed = String(lines[end]).includes(closing);
  }
  return {
    end,
    html: `<div class="rb-math-block">${esc(lines.slice(start, end + 1).join('\n'))}</div>`,
  };
}

function renderMarkdown(source) {
  const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let list = '';
  let code = false;
  let codeLines = [];
  const closeList = () => {
    if (list) out.push(`</${list}>`);
    list = '';
  };
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    if (raw.trim().startsWith('```')) {
      closeList();
      if (code) {
        out.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`);
        codeLines = [];
      }
      code = !code;
      continue;
    }
    if (code) {
      codeLines.push(raw);
      continue;
    }
    const math = displayMathBlock(lines, index);
    if (math) {
      closeList();
      out.push(math.html);
      index = math.end;
      continue;
    }
    const next = lines[index + 1] || '';
    if (raw.includes('|') && /^\s*\|?(?:\s*:?-+:?\s*\|)+/.test(next)) {
      closeList();
      const headers = raw.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(lines[index].replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim()));
        index += 1;
      }
      index -= 1;
      out.push(`<div style="overflow:auto"><table><thead><tr>${headers.map((cell) => `<th>${markdownInline(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${markdownInline(row[cellIndex] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }
    const heading = raw.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${markdownInline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = raw.match(/^\s*[-*]\s+(.+)$/);
    const numbered = raw.match(/^\s*\d+[.)]\s+(.+)$/);
    if (bullet || numbered) {
      const type = bullet ? 'ul' : 'ol';
      if (list !== type) {
        closeList();
        list = type;
        out.push(`<${type}>`);
      }
      out.push(`<li>${markdownInline((bullet || numbered)[1])}</li>`);
      continue;
    }
    const quote = raw.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      out.push(`<blockquote>${markdownInline(quote[1])}</blockquote>`);
      continue;
    }
    closeList();
    if (raw.trim()) out.push(`<p>${markdownInline(raw.trim())}</p>`);
  }
  closeList();
  if (codeLines.length) out.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`);
  return out.join('\n');
}

function show(view) {
  const changed = R.view !== view;
  R.view = view;
  for (const name of ['fleet', 'studio', 'paper']) {
    el(`view-${name}`).hidden = name !== view;
  }
  if (changed) window.scrollTo({ top: 0, behavior: 'smooth' });
}

function setButton(id, ok, why = '') {
  const button = el(id);
  if (!button) return;
  button.disabled = !ok;
  button.title = ok ? '' : why;
}

function writeHash(value) {
  const next = value ? `#${value}` : '#';
  if (location.hash !== next) history.replaceState(null, '', next);
}

function openFleet() {
  R.studioId = '';
  R.paperId = '';
  R.studio = null;
  R.paper = null;
  R.dirtyResponses.clear();
  R.paperPolicyDirty = false;
  R.studioPolicyDirty = false;
  writeHash('');
  show('fleet');
  loadFleet();
}

function openStudio(id) {
  R.studioId = id;
  R.paperId = '';
  R.studio = null;
  R.paper = null;
  R.studioPolicyDirty = false;
  writeHash(`studio/${encodeURIComponent(id)}`);
  show('studio');
  loadStudio();
}

function openPaper(id, studioId = '') {
  R.paperId = id;
  if (studioId) R.studioId = studioId;
  R.paper = null;
  R.dirtyResponses.clear();
  R.paperPolicyDirty = false;
  R.agentLive = false;
  R.agentLiveTouched = false;
  writeHash(`paper/${encodeURIComponent(id)}`);
  show('paper');
  loadPaper();
  const orPlan = el('or-plan');
  if (orPlan) { orPlan.innerHTML = ''; el('or-status').textContent = ''; el('btn-or-submit').disabled = true; }
  orRefreshAuth();
}

function readHash() {
  const [kind, id] = location.hash.replace(/^#/, '').split('/');
  if (kind === 'studio' && id) openStudio(decodeURIComponent(id));
  else if (kind === 'paper' && id) openPaper(decodeURIComponent(id));
  else openFleet();
}

function projectBadge(project) {
  if (project.bundle_ready) {
    return '<span class="rb-pill rb-pill--ready">bundle ready</span>';
  }
  if (project.delivery_phase === 'agent_running' || project.delivery_phase === 'validating') {
    return `<span class="rb-pill rb-pill--live">delivery ${esc(project.delivery_phase)}</span>`;
  }
  if (project.delivery_phase === 'blocked') {
    return '<span class="rb-pill rb-pill--bad">delivery blocked</span>';
  }
  if (project.agent_status === 'running') {
    return '<span class="rb-pill rb-pill--live">agent live</span>';
  }
  if (project.active_job) {
    return `<span class="rb-pill rb-pill--live">${esc(project.active_job)} running</span>`;
  }
  if (project.ready) return '<span class="rb-pill rb-pill--ready">ready</span>';
  if (project.error) return '<span class="rb-pill rb-pill--bad">blocked</span>';
  return `<span class="rb-pill">${esc(project.stage || 'intake')}</span>`;
}

function paperRow(project, studioId = '', ordinal = 0, conference = '') {
  const num = ordinal ? `<span class="rb-ordinal">${ordinal}</span>` : '';
  const conf = conference
    ? `<span class="rb-pill rb-pill--conf" title="conference policy this paper answers under">${esc(conference)}</span>`
    : '';
  return `<article class="rb-project" data-paper="${esc(project.id)}" data-studio="${esc(studioId)}">
    ${num}
    <div>
      <h3>${esc(project.title || project.id)}</h3>
      <p>${esc(project.source_path || '')}</p>
    </div>
    ${conf}
    <span class="rb-count">${esc(plural(Number(project.reviewers || 0), 'reviewer'))}</span>
    <span class="rb-count">${esc(plural(Number(project.responses || 0), 'response'))}</span>
    ${projectBadge(project)}
  </article>`;
}

async function loadFleet() {
  let studioPayload;
  let projectPayload;
  try {
    [studioPayload, projectPayload] = await Promise.all([
      api('/api/rebuttal/studios'),
      api('/api/rebuttal/projects'),
    ]);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  R.studios = studioPayload.studios || [];
  R.projects = projectPayload.projects || [];
  const ready = R.projects.filter((item) => item.ready).length;
  const orphanProjects = R.projects.filter((item) => !item.studio_id);
  const spent = R.studios.reduce((sum, item) => sum + Number(item.cost_usd || 0), 0)
    + orphanProjects.reduce((sum, item) => sum + Number(item.cost_usd || 0), 0);
  el('stat-studios').innerHTML = `<b>${R.studios.length}</b> ${R.studios.length === 1 ? 'studio' : 'studios'}`;
  el('stat-papers').innerHTML = `<b>${R.projects.length}</b> ${R.projects.length === 1 ? 'paper' : 'papers'}`;
  el('stat-ready').innerHTML = `<b>${ready}</b> ready`;
  el('stat-cost').innerHTML = `<b>$${spent.toFixed(2)}</b> spent`;
  if (R.view !== 'fleet') return;

  // Papers first: every rebuttal is its own numbered line, whatever studio
  // holds its policy. The studios keep the policy machinery below.
  const paperHost = el('paper-list');
  const confOf = {};
  R.studios.forEach((studio) => { confOf[studio.id] = studio.title || studio.id; });
  const count = el('fleet-paper-count');
  if (count) count.textContent = plural(R.projects.length, 'paper');
  if (!R.projects.length) {
    paperHost.innerHTML =
      '<div class="rb-card">No Paper Rebuttals yet. Approve a conference policy below, then add papers under it.</div>';
  } else {
    paperHost.innerHTML = R.projects.map((project, i) =>
      paperRow(
        project,
        project.studio_id || '',
        i + 1,
        project.studio_id ? confOf[project.studio_id] || '' : 'flat import',
      )).join('');
    paperHost.querySelectorAll('[data-paper]').forEach((node) => {
      node.addEventListener('click', () => openPaper(node.dataset.paper, node.dataset.studio));
    });
  }

  const host = el('studio-list');
  if (!R.studios.length) {
    host.innerHTML = '<div class="rb-card">No Conference Studios yet. Start one above.</div>';
    return;
  }
  host.innerHTML = R.studios.map((studio) => {
    const badge = studio.active_job
      ? `<span class="rb-pill rb-pill--live">${esc(studio.active_job)} running</span>`
      : studio.policy_approved
        ? '<span class="rb-pill rb-pill--ready">policy approved</span>'
        : studio.error
          ? '<span class="rb-pill rb-pill--bad">policy blocked</span>'
          : `<span class="rb-pill">${esc(studio.stage)}</span>`;
    return `<article class="rb-project" data-studio="${esc(studio.id)}">
      <div>
        <h3>${esc(studio.title)}</h3>
        <p>${esc(studio.cfp_url || '')}</p>
      </div>
      <span class="rb-count">${esc(plural(Number(studio.papers || 0), 'paper'))}</span>
      <span class="rb-count">${esc(studio.rebuttal_deadline || 'deadline unknown')}</span>
      ${badge}
    </article>`;
  }).join('');
  host.querySelectorAll('[data-studio]:not([data-paper])').forEach((node) => {
    node.addEventListener('click', () => openStudio(node.dataset.studio));
  });
}

async function createStudio() {
  const conference = el('studio-conference').value.trim();
  const year = Number(el('studio-year').value);
  const cfpUrl = el('studio-cfp-url').value.trim();
  if (!conference || !year || !cfpUrl) {
    el('studio-create-status').textContent = 'Conference, year, and Call for Papers URL are required.';
    return;
  }
  setButton('btn-create-studio', false, 'creating');
  el('studio-create-status').textContent = 'Creating Studio…';
  try {
    const payload = await api('/api/rebuttal/studios', {
      method: 'POST',
      body: JSON.stringify({
        conference,
        year,
        cfp_url: cfpUrl,
        policy_url: el('studio-policy-url').value.trim(),
      }),
    });
    el('studio-create-status').textContent = '';
    openStudio(payload.studio.id);
  } catch (error) {
    el('studio-create-status').textContent = error.message;
    toast(error.message, true);
  } finally {
    setButton('btn-create-studio', true);
  }
}

const STUDIO_STAGES = [
  ['policy_input', 'Official sources'],
  ['await_policy_review', 'Human policy gate'],
  ['active', 'Paper rebuttals'],
  ['closed', 'Conference closed'],
];

function studioStageIndex(stage) {
  if (stage === 'policy_draft') return 0;
  return Math.max(0, STUDIO_STAGES.findIndex(([id]) => id === stage));
}

function renderStudioPipeline(studio) {
  const index = studioStageIndex(studio.stage);
  el('studio-pipeline').innerHTML = STUDIO_STAGES.map(([id, label], position) => {
    const cls = position < index ? 'is-done' : (position === index ? 'is-current' : '');
    return `<li class="${cls}"><b>${position + 1}. ${esc(label)}</b></li>`;
  }).join('');
}

function renderStudioSources(studio) {
  const sources = studio.sources || [];
  const host = el('studio-sources');
  if (!sources.length) {
    host.innerHTML = '<p class="rb-warning">No official source has been fetched yet.</p>';
  } else {
    host.innerHTML = sources.map((source) => `
      <div class="rb-policy-source">
        <b>${source.ok ? '✓' : '×'} ${esc(source.title || source.requested_url || source.url)}</b>
        <a href="${esc(source.url || source.requested_url)}" target="_blank" rel="noreferrer">${esc(source.url || source.requested_url)}</a>
        ${source.error ? `<p class="rb-warning">${esc(source.error)}</p>` : ''}
      </div>`).join('');
  }
  const log = el('studio-log');
  const lines = studio.logs || [];
  const pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent = lines.length ? lines.join('\n') : '(no activity yet)';
  if (pinned || studio.active_job) log.scrollTop = log.scrollHeight;
}

const STUDIO_POLICY_FIELDS = {
  'studio-policy-platform': 'platform',
  'studio-policy-limit': 'character_limit',
  'studio-policy-word-limit': 'word_limit',
  'studio-policy-language': 'response_language',
  'studio-policy-open': 'rebuttal_open_at',
  'studio-policy-deadline': 'rebuttal_deadline',
  'studio-policy-timezone': 'timezone',
  'studio-policy-discussion-end': 'discussion_end',
  'studio-policy-frozen': 'manuscript_frozen',
  'studio-policy-revised-pdf': 'allow_revised_pdf',
  'studio-policy-experiments': 'allow_new_experiments',
  'studio-policy-links': 'allow_links',
  'studio-policy-attachments': 'allow_attachments',
  'studio-policy-global': 'allow_global_response',
  'studio-policy-ac': 'allow_ac_response',
  'studio-policy-anonymous': 'anonymous',
  'studio-policy-score-update': 'reviewers_can_update_scores',
  'studio-policy-instructions': 'submission_instructions',
};

function renderStudioPolicy(studio) {
  if (!R.studioPolicyDirty) {
    const policy = studio.policy || {};
    Object.entries(STUDIO_POLICY_FIELDS).forEach(([id, key]) => {
      const input = el(id);
      if (input.type === 'checkbox') input.checked = Boolean(policy[key]);
      else input.value = policy[key] == null ? '' : policy[key];
    });
  }
  const evidence = studio.policy_evidence || {};
  const proofs = Object.entries(evidence)
    .filter(([, item]) => item && (item.quote || item.source_url))
    .map(([key, item]) => `<div class="rb-policy-proof">
      <b>${esc(key)} · ${esc(item.confidence || 'low')}</b>
      ${item.source_url ? `<a href="${esc(item.source_url)}" target="_blank" rel="noreferrer">${esc(item.source_url)}</a>` : ''}
      ${item.quote ? `<blockquote>${esc(item.quote)}</blockquote>` : ''}
    </div>`).join('');
  el('studio-policy-evidence').innerHTML = proofs || '<p class="rb-status">No source-backed fields yet.</p>';
}

function studioPolicyFromForm() {
  const policy = {};
  Object.entries(STUDIO_POLICY_FIELDS).forEach(([id, key]) => {
    const input = el(id);
    if (input.type === 'checkbox') policy[key] = input.checked;
    else if (input.type === 'number') policy[key] = Number(input.value || 0);
    else policy[key] = input.value.trim();
  });
  return policy;
}

function renderStudioStrategy(studio) {
  const policy = el('studio-policy-markdown');
  const strategy = el('studio-strategy-markdown');
  clearMathTypeset(policy);
  clearMathTypeset(strategy);
  policy.innerHTML = renderMarkdown(studio.policy_markdown || '');
  strategy.innerHTML = renderMarkdown(studio.strategy_markdown || '');
  for (const node of [policy, strategy]) {
    node.mathRevision = Number(node.mathRevision || 0) + 1;
    queueMathTypeset(node);
  }
}

function renderPaperRows(hostId, papers, studioId) {
  const host = el(hostId);
  if (!papers.length) {
    host.innerHTML = '<div class="rb-card">No Paper Rebuttals yet.</div>';
    return;
  }
  host.innerHTML = papers.map((paper) => paperRow(paper, studioId)).join('');
  host.querySelectorAll('[data-paper]').forEach((node) => {
    node.addEventListener('click', () => openPaper(node.dataset.paper, studioId));
  });
}

function renderStudio(studio) {
  R.studio = studio;
  el('studio-stage').textContent = studio.stage || 'policy_input';
  el('studio-title').textContent = studio.title || studio.id;
  el('studio-cfp').innerHTML = `<a href="${esc(studio.cfp_url)}" target="_blank" rel="noreferrer">${esc(studio.cfp_url)}</a>`;
  el('studio-meta').textContent = [
    studio.policy_approved_at ? `policy approved ${shortTime(studio.policy_approved_at)}` : 'policy not approved',
    `${(studio.papers || []).length} paper(s)`,
    `$${Number(studio.cost_usd || 0).toFixed(2)} Studio spend`,
    studio.updated_at ? `updated ${shortTime(studio.updated_at)}` : '',
  ].filter(Boolean).join(' · ');
  renderStudioPipeline(studio);
  renderStudioSources(studio);
  renderStudioPolicy(studio);
  renderStudioStrategy(studio);
  const papers = studio.papers || [];
  el('studio-paper-count').textContent = plural(papers.length, 'paper');
  renderPaperRows('studio-paper-list', papers, studio.id);
  const active = String(studio.active_job || '');
  setButton('btn-discover-policy', !active, active ? `${active} is running` : '');
  setButton('btn-forget-studio', !active, active ? `${active} is running` : '');
  setButton(
    'btn-approve-policy',
    !active && studio.stage === 'await_policy_review' && (studio.sources || []).length > 0,
    active ? `${active} is running` : 'discover and review official policy first',
  );
  setButton('btn-studio-policy-save', !active && (studio.sources || []).length > 0, active ? `${active} is running` : 'discover official policy first');
  setButton('btn-add-paper', !active && studio.stage === 'active', active ? `${active} is running` : 'approve the Conference Policy first');
  el('paper-import-path').disabled = studio.stage !== 'active';
  el('paper-import-title').disabled = studio.stage !== 'active';
}

async function loadStudio() {
  if (!R.studioId) return;
  try {
    const payload = await api(`/api/rebuttal/studios/${encodeURIComponent(R.studioId)}`);
    if (R.studioId === payload.studio.id) renderStudio(payload.studio);
  } catch (error) {
    toast(error.message, true);
  }
}

async function studioAct(action, body = {}) {
  if (R.busy || !R.studioId) return null;
  R.busy = true;
  try {
    return await api(`/api/rebuttal/studios/${encodeURIComponent(R.studioId)}/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  } catch (error) {
    toast(error.message, true);
    return null;
  } finally {
    R.busy = false;
  }
}

async function discoverPolicy() {
  R.studioPolicyDirty = false;
  const payload = await studioAct('discover-policy');
  if (payload && payload.studio) renderStudio(payload.studio);
  else loadStudio();
}

async function saveStudioPolicy() {
  const payload = await studioAct('policy', { policy: studioPolicyFromForm() });
  if (!payload) return;
  R.studioPolicyDirty = false;
  renderStudio(payload.studio);
  toast('Conference policy draft saved.');
}

async function approveStudioPolicy() {
  if (!window.confirm('Approve this Conference Policy for every Paper Rebuttal in the Studio?')) return;
  if (R.studioPolicyDirty) {
    const saved = await studioAct('policy', { policy: studioPolicyFromForm() });
    if (!saved) return;
    R.studioPolicyDirty = false;
    renderStudio(saved.studio);
  }
  const payload = await studioAct('approve-policy');
  if (!payload) return;
  R.studioPolicyDirty = false;
  renderStudio(payload.studio);
  toast('Conference Policy approved. Paper import is now enabled.');
}

async function addPaper() {
  const path = el('paper-import-path').value.trim();
  if (!path) {
    el('paper-import-status').textContent = 'A materials path or an OpenReview forum link is required.';
    return;
  }
  setButton('btn-add-paper', false, 'importing');
  el('paper-import-status').textContent = /^https?:\/\//i.test(path)
    ? 'Fetching the forum — submission PDF and every official review…'
    : 'Scanning Paper package…';
  const payload = await studioAct('add-paper', {
    path,
    title: el('paper-import-title').value.trim(),
    auto_draft: true,
  });
  if (payload) {
    el('paper-import-status').textContent = '';
    el('paper-import-path').value = '';
    el('paper-import-title').value = '';
    loadFleet();
    toast('Paper imported. A dedicated live Rebuttal Agent is starting in tmux.');
    openPaper(payload.project.id, R.studioId);
  } else {
    el('paper-import-status').textContent = 'Paper import failed; see the error notification.';
    loadStudio();
  }
}

async function forgetStudio() {
  if (!R.studioId || !window.confirm('Forget this empty Studio? Policy artifacts remain on disk.')) return;
  try {
    await api(`/api/rebuttal/studios/${encodeURIComponent(R.studioId)}`, {
      method: 'DELETE',
    });
    toast('Conference Studio forgotten; policy artifacts were preserved.');
    openFleet();
  } catch (error) {
    toast(error.message, true);
  }
}

const PAPER_STAGES = [
  ['intake', 'Package intake'],
  ['concerns_ready', 'Concern matrix'],
  ['responses_ready', 'Draft responses'],
  ['validated', 'Content validated'],
  ['approved', 'Responses approved'],
  ['delivery_agent_running', 'Delivery Agent'],
  ['await_delivery_approval', 'Artifact preflight'],
  ['bundle_ready', 'Bundle ready'],
];

function paperStageIndex(stage) {
  const aliases = {
    delivery_validating: 'await_delivery_approval',
    delivery_blocked: 'delivery_agent_running',
  };
  return PAPER_STAGES.findIndex(([id]) => id === (aliases[stage] || stage));
}

function renderPaperPipeline(project) {
  const index = paperStageIndex(project.stage);
  el('pipeline').innerHTML = PAPER_STAGES.map(([id, label], position) => {
    const cls = position < index ? 'is-done' : (position === index ? 'is-current' : '');
    return `<li class="${cls}"><b>${position + 1}. ${esc(label)}</b></li>`;
  }).join('');
}

function renderManifest(project) {
  const manifest = project.manifest || {};
  const files = manifest.files || [];
  const priority = files.filter((item) => item.kind !== 'material');
  const materials = files.filter((item) => item.kind === 'material');
  const shown = [...priority, ...materials.slice(0, 18)];
  el('manifest').innerHTML = `<div class="rb-file-list">${shown.map((item) => `
    <div class="rb-file">
      <b>${esc(item.kind)}</b>
      <span>${esc(item.relative_path)}</span>
      <em>${(Number(item.size || 0) / 1024).toFixed(1)} kB</em>
    </div>`).join('')}</div>
    ${materials.length > 18 ? `<p class="rb-status">+ ${materials.length - 18} additional material files</p>` : ''}
    ${(manifest.warnings || []).map((warning) => `<p class="rb-warning">${esc(warning)}</p>`).join('')}`;
}

function renderPaperPolicy(project) {
  if (R.paperPolicyDirty) return;
  const policy = project.policy || {};
  el('policy-platform').value = policy.platform || 'OpenReview';
  el('policy-limit').value = policy.character_limit || 10000;
  el('policy-target').value = policy.internal_target || 9500;
  el('policy-language').value = policy.response_language || 'English';
  el('policy-frozen').checked = Boolean(policy.manuscript_frozen);
  el('policy-links').checked = Boolean(policy.allow_links);
  el('policy-attachments').checked = Boolean(policy.allow_attachments);
  el('policy-global').checked = Boolean(policy.allow_global_response);
  el('policy-anonymous').checked = Boolean(policy.anonymous);
}

function paperPolicyFromForm() {
  return {
    platform: el('policy-platform').value.trim(),
    character_limit: Number(el('policy-limit').value || 10000),
    internal_target: Number(el('policy-target').value || 9500),
    response_language: el('policy-language').value.trim(),
    manuscript_frozen: el('policy-frozen').checked,
    allow_links: el('policy-links').checked,
    allow_attachments: el('policy-attachments').checked,
    allow_global_response: el('policy-global').checked,
    anonymous: el('policy-anonymous').checked,
  };
}

function renderConcerns(project) {
  const reviewers = project.reviewers || [];
  const count = reviewers.reduce((sum, reviewer) => sum + (reviewer.concerns || []).length, 0);
  el('concern-count').textContent = `${count} concerns · ${reviewers.length} reviewers`;
  const host = el('concerns');
  if (!reviewers.length) {
    host.innerHTML = '<div class="rb-card">Run Analyze reviews to create the concern matrix.</div>';
    return;
  }
  host.innerHTML = reviewers.map((reviewer) => `
    <article class="rb-reviewer">
      <header><h3>${esc(reviewer.label || reviewer.id)}</h3><p>${esc(reviewer.summary || '')}</p></header>
      ${(reviewer.concerns || []).map((concern) => `
        <div class="rb-concern">
          <div class="rb-concern__head">
            <b>${esc(concern.id)}</b>
            <span class="rb-pill">${esc(concern.type)}</span>
            <span class="rb-pill">${esc(concern.severity)}</span>
            <span class="rb-pill">${esc(concern.response_mode)}</span>
          </div>
          <p>${esc(concern.summary || '')}</p>
          ${concern.verbatim ? `<blockquote>${esc(concern.verbatim)}</blockquote>` : ''}
          ${concern.evidence_needed ? `<p><b>Evidence:</b> ${esc(concern.evidence_needed)}</p>` : ''}
        </div>`).join('')}
    </article>`).join('');
}

function responseCountClass(count, policy) {
  if (count > Number(policy.character_limit || 10000)) return 'is-over';
  if (count >= Number(policy.internal_target || 9500)) return 'is-near';
  return '';
}

let mathTypesetQueue = Promise.resolve();

function syncResponseScroll(section, source, target) {
  if (!source || !target) return;
  if (section.scrollSyncSource && section.scrollSyncSource !== source) return;
  const sourceRange = Math.max(0, source.scrollHeight - source.clientHeight);
  const targetRange = Math.max(0, target.scrollHeight - target.clientHeight);
  const ratio = sourceRange ? source.scrollTop / sourceRange : 0;
  const targetTop = Math.max(0, Math.min(targetRange, ratio * targetRange));
  if (Math.abs(target.scrollTop - targetTop) < 0.5) return;
  section.scrollSyncSource = source;
  target.scrollTop = targetTop;
  window.cancelAnimationFrame(section.scrollSyncFrame);
  section.scrollSyncFrame = window.requestAnimationFrame(() => {
    section.scrollSyncSource = null;
  });
}

function bindResponseScrollSync(section) {
  const textarea = section.querySelector('textarea');
  const preview = section.querySelector('[data-preview]');
  textarea.addEventListener(
    'scroll',
    () => syncResponseScroll(section, textarea, preview),
    { passive: true },
  );
  preview.addEventListener(
    'scroll',
    () => syncResponseScroll(section, preview, textarea),
    { passive: true },
  );
}

function clearMathTypeset(node) {
  const mathjax = window.MathJax;
  if (!window.__loomMathJaxReady || typeof mathjax?.typesetClear !== 'function') return;
  try {
    mathjax.typesetClear([node]);
  } catch {
    // A previous asynchronous render may already have released this node.
  }
}

function queueMathTypeset(node, status = null) {
  if (!node) return;
  if (window.__loomMathJaxFailed) {
    if (status) status.textContent = 'TeX source shown · scroll linked';
    return;
  }
  const mathjax = window.MathJax;
  if (!window.__loomMathJaxReady || typeof mathjax?.typesetPromise !== 'function') {
    if (status) status.textContent = 'Loading LaTeX… · scroll linked';
    return;
  }
  const revision = node.mathRevision || 0;
  if (status) status.textContent = 'Rendering LaTeX… · scroll linked';
  mathTypesetQueue = mathTypesetQueue
    .catch(() => {})
    .then(async () => {
      if (!node.isConnected || revision !== (node.mathRevision || 0)) return;
      await mathjax.typesetPromise([node]);
      if (status && node.isConnected && revision === (node.mathRevision || 0)) {
        status.textContent = 'Markdown + LaTeX · scroll linked';
      }
      const section = node.closest('.rb-response');
      if (section && revision === (node.mathRevision || 0)) {
        syncResponseScroll(section, section.querySelector('textarea'), node);
      }
    })
    .catch((error) => {
      if (status) status.textContent = 'Math error · scroll linked';
      console.warn('MathJax preview failed', error);
    });
}

function renderResponsePreview(section, force = false) {
  const textarea = section.querySelector('textarea');
  const preview = section.querySelector('[data-preview]');
  const status = section.querySelector('[data-preview-status]');
  if (!textarea || !preview) return;
  const source = textarea.value;
  if (!force && preview.previewSource === source) return;
  preview.previewSource = source;
  preview.mathRevision = Number(preview.mathRevision || 0) + 1;
  clearMathTypeset(preview);
  preview.innerHTML = source.trim()
    ? renderMarkdown(source)
    : '<p class="rb-preview-empty">Nothing to preview yet.</p>';
  syncResponseScroll(section, textarea, preview);
  queueMathTypeset(preview, status);
}

function scheduleResponsePreview(section, delay = 140) {
  window.clearTimeout(section.previewTimer);
  section.previewTimer = window.setTimeout(() => renderResponsePreview(section), delay);
}

function refreshRenderedMath() {
  document.querySelectorAll('.rb-response').forEach((section) => {
    renderResponsePreview(section, true);
  });
  document.querySelectorAll('.rb-markdown:not([data-preview])').forEach((node) => {
    node.mathRevision = Number(node.mathRevision || 0) + 1;
    queueMathTypeset(node);
  });
}

function updateResponseCounter(section, project) {
  const count = section.querySelector('textarea').value.length;
  const counter = section.querySelector('.rb-char');
  counter.textContent = `${count.toLocaleString()} / ${Number(project.policy.character_limit || 10000).toLocaleString()}`;
  counter.className = `rb-char ${responseCountClass(count, project.policy || {})}`;
}

function createResponseSection(reviewerId, project) {
  const section = document.createElement('article');
  section.className = 'rb-response';
  section.dataset.reviewer = reviewerId;
  section.innerHTML = `<header><h3>${esc(reviewerId)}</h3><span class="rb-char"></span></header>
    <div class="rb-response-compose">
      <label class="rb-response-source">
        <span class="rb-response-pane-label">Markdown source</span>
        <textarea spellcheck="true" aria-label="Response to ${esc(reviewerId)}"></textarea>
      </label>
      <section class="rb-response-preview" aria-label="Rendered response to ${esc(reviewerId)}">
        <div class="rb-response-pane-label">
          <span>Rendered preview</span>
          <small data-preview-status>Loading LaTeX… · scroll linked</small>
        </div>
        <div class="rb-markdown rb-response-preview__body" data-preview></div>
      </section>
    </div>
    <footer><span class="rb-status">Markdown source · saved on disk</span>
      <button type="button" class="rb-btn" data-save>Save response</button></footer>`;
  const textarea = section.querySelector('textarea');
  bindResponseScrollSync(section);
  textarea.addEventListener('input', () => {
    R.dirtyResponses.add(reviewerId);
    section.classList.add('is-dirty');
    updateResponseCounter(section, R.paper || project);
    section.querySelector('[data-save]').disabled = false;
    scheduleResponsePreview(section);
  });
  section.querySelector('[data-save]').addEventListener('click', () => saveResponse(reviewerId));
  return section;
}

function renderResponses(project) {
  const responses = project.responses || {};
  const reviewerIds = Object.keys(responses);
  el('response-count').textContent = plural(reviewerIds.length, 'response');
  const host = el('responses');
  if (!reviewerIds.length) {
    host.innerHTML = '<div class="rb-card">Run Draft responses after the concern matrix is ready.</div>';
    return;
  }
  host.querySelectorAll('.rb-card').forEach((node) => node.remove());
  reviewerIds.forEach((reviewerId) => {
    let section = [...host.querySelectorAll('.rb-response')]
      .find((node) => node.dataset.reviewer === reviewerId);
    if (!section) {
      section = createResponseSection(reviewerId, project);
      host.appendChild(section);
    }
    if (!R.dirtyResponses.has(reviewerId)) {
      const textarea = section.querySelector('textarea');
      const body = responses[reviewerId].body || '';
      if (textarea.value !== body) textarea.value = body;
      section.classList.remove('is-dirty');
      section.querySelector('[data-save]').disabled = true;
    }
    updateResponseCounter(section, project);
    renderResponsePreview(section);
  });
  host.querySelectorAll('.rb-response').forEach((node) => {
    if (!reviewerIds.includes(node.dataset.reviewer)) node.remove();
  });
}

function renderValidation(project) {
  const report = project.validation || {};
  const host = el('validation');
  if (!report.checked_at) {
    host.className = 'rb-validation';
    host.innerHTML = '<p>Validation has not run yet.</p>';
    return;
  }
  host.className = `rb-validation ${report.ready ? 'is-ready' : 'is-blocked'}`;
  host.innerHTML = `<p><b>${report.ready ? 'READY' : 'BLOCKED'}</b> · checked ${esc(shortTime(report.checked_at))}</p>
    ${(report.files || []).map((item) => `<p>${item.ok ? '✓' : '×'} ${esc(item.reviewer_id)} · ${Number(item.characters || 0).toLocaleString()} chars</p>`).join('')}
    ${(report.errors || []).length ? `<ul>${report.errors.map((error) => `<li>${esc(error)}</li>`).join('')}</ul>` : ''}`;
}

function deliveryArtifactLink(project, key, label) {
  const delivery = project.delivery || {};
  const item = key === 'bundle'
    ? delivery.bundle
    : ((delivery.artifacts || {})[key] || null);
  if (!item || !item.name) return '';
  const route = key === 'revised_paper' ? 'revised-paper' : key;
  const url = `/api/rebuttal/projects/${encodeURIComponent(project.id)}/delivery/${route}`;
  const meta = [
    item.pages ? `${Number(item.pages)} page(s)` : '',
    item.size ? `${(Number(item.size) / 1024 / 1024).toFixed(2)} MB` : '',
    item.sha256 ? `SHA ${String(item.sha256).slice(0, 12)}…` : '',
  ].filter(Boolean).join(' · ');
  return `<a class="rb-delivery-artifact" href="${url}" target="_blank" rel="noreferrer">
    <b>${esc(label)}</b><span>${esc(item.name)}</span><small>${esc(meta)}</small>
  </a>`;
}

function renderDelivery(project) {
  const delivery = project.delivery || {};
  const phase = delivery.phase || '';
  const host = el('delivery');
  el('delivery-phase').textContent = phase || 'not started';
  if (!phase) {
    host.className = 'rb-delivery';
    host.innerHTML = `<p>No delivery attempt yet. ${
      project.stage === 'approved'
        ? 'Build the submission package to start the isolated Delivery Agent.'
        : 'Approve the response content first.'
    }</p>`;
    return;
  }
  const validation = delivery.validation || {};
  const figureRedraw = delivery.figure_redraw || {};
  const figureVerification = delivery.figure_verification || {};
  const errors = validation.errors || [];
  const ready = Boolean(validation.ready);
  const blocked = phase === 'blocked' || errors.length > 0;
  const artifacts = [
    deliveryArtifactLink(project, 'revised_paper', 'Revised paper'),
    deliveryArtifactLink(project, 'rebuttal', 'One-page rebuttal'),
    deliveryArtifactLink(project, 'supplement', 'Supplement'),
    deliveryArtifactLink(project, 'bundle', 'Submission bundle'),
  ].filter(Boolean).join('');
  const preflightUrl = `/api/rebuttal/projects/${encodeURIComponent(project.id)}/delivery/preflight`;
  const handoffUrl = `/api/rebuttal/projects/${encodeURIComponent(project.id)}/delivery/handoff`;
  const deliveryFolder = delivery.attempt_path
    ? `${String(delivery.attempt_path).replace(/\/+$/, '')}/deliverables`
    : '';
  host.className = `rb-delivery ${ready ? 'is-ready' : ''} ${blocked ? 'is-blocked' : ''}`;
  host.innerHTML = `<div class="rb-delivery-summary">
      <p><b>${esc(phase.replaceAll('_', ' '))}</b>${delivery.run_id ? ` · run ${esc(delivery.run_id)}` : ''}</p>
      <p>${esc(delivery.summary || project.error || 'The delivery controller is waiting for the next handoff.')}</p>
    </div>
    ${errors.length ? `<div class="rb-delivery-errors"><b>Deterministic preflight blocked this attempt</b>
      <ul>${errors.map((error) => `<li>${esc(error)}</li>`).join('')}</ul></div>` : ''}
    ${(figureRedraw.status || figureVerification.checked_at || phase === 'figure_verification_running') ? `<div class="rb-figure-verification">
      <div class="rb-figure-verification__head">
        <b>Three-model figure verification</b>
        <span class="rb-pill ${figureVerification.all_pass ? 'rb-pill--ready' : ((phase === 'figure_verification_running' || figureRedraw.status === 'running') ? 'rb-pill--live' : 'rb-pill--bad')}">
          ${figureVerification.all_pass ? 'unanimous pass'
            : phase === 'figure_verification_running' ? 'verifying…'
            : figureRedraw.status === 'running' ? 'redraw running'
            : 'waiting for all reviewers'}
        </span>
      </div>
      <p>Final approval unlocks only after all three fixed Paper Reviewer models return PASS on the current PDF.</p>
      ${(figureVerification.reviewers || []).length ? `<div class="rb-figure-reviewers">
        ${figureVerification.reviewers.map((item) => `<div>
          <b>${esc(item.model || 'reviewer')}</b>
          <span>${esc(item.figure_verdict || 'FAIL')} · ${Number((item.scores || {}).rating || 0)}/10</span>
        </div>`).join('')}
      </div>` : ''}
    </div>` : ''}
    ${artifacts ? `<div class="rb-delivery-artifacts">${artifacts}</div>` : ''}
    ${validation.checked_at ? `<div class="rb-delivery-links">
      <a href="${preflightUrl}" target="_blank" rel="noreferrer">Open full preflight</a>
      <a href="${handoffUrl}" target="_blank" rel="noreferrer">Open OpenReview handoff</a>
    </div>` : ''}
    ${delivery.final_approval && delivery.final_approval.approved_at
      ? `<p class="rb-delivery-approved">Final artifact hashes approved ${esc(shortTime(delivery.final_approval.approved_at))}.</p>`
      : ''}
    ${deliveryFolder ? `<div class="rb-delivery-folder">
      <div>
        <b>All files to inspect before approval</b>
        <code>${esc(deliveryFolder)}</code>
      </div>
      <button type="button" class="rb-btn" data-copy-delivery-folder>Copy folder path</button>
    </div>` : ''}`;
  const copyFolder = host.querySelector('[data-copy-delivery-folder]');
  if (copyFolder) {
    copyFolder.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(deliveryFolder);
        toast('Delivery folder path copied.');
      } catch {
        toast(`Delivery folder: ${deliveryFolder}`);
      }
    });
  }
}

function renderPaperActions(project) {
  const active = String(project.active_job || '');
  const manifestReady = Boolean((project.manifest || {}).ready);
  const reviewers = project.reviewers || [];
  const responseCount = Object.keys(project.responses || {}).length;
  const agentRunning = project.agent_status === 'running';
  const delivery = project.delivery || {};
  const deliveryRunning = delivery.agent_status === 'running' || delivery.agent_status === 'validating';
  const contentMutable = [
    'intake', 'concerns_ready', 'responses_ready', 'validated',
  ].includes(project.stage);
  setButton('btn-rescan', !active && !agentRunning && !deliveryRunning, deliveryRunning ? 'stop the delivery agent before rescanning' : (agentRunning ? 'stop the agent before rescanning' : (active ? `${active} is running` : '')));
  setButton('btn-agent-start', !active && manifestReady && !agentRunning && !deliveryRunning && contentMutable, deliveryRunning ? 'delivery is already running' : (agentRunning ? 'agent is already running' : (contentMutable ? 'package needs paper and review PDFs' : 'response content is already approved')));
  setButton('btn-agent-stop', agentRunning, 'agent is not running');
  setButton('btn-validate', !active && !agentRunning && !deliveryRunning && responseCount === reviewers.length && responseCount > 0 && contentMutable, deliveryRunning ? 'delivery is running' : (agentRunning ? 'wait for the agent completion marker' : 'draft every reviewer response first'));
  setButton(
    'btn-approve',
    !active && !agentRunning && !deliveryRunning && Boolean((project.validation || {}).ready) && project.stage === 'validated',
    deliveryRunning ? 'delivery is running' : (agentRunning ? 'wait for the agent to finish' : (active ? `${active} is running` : (project.stage !== 'validated' ? 'responses are already approved or validation must pass' : 'validation must pass first'))),
  );
  const canStartDelivery = ['approved', 'delivery_blocked'].includes(project.stage);
  el('btn-delivery-start').textContent = project.stage === 'delivery_blocked'
    ? 'Re-run Delivery Agent'
    : 'Build submission package';
  setButton(
    'btn-delivery-start',
    !active && !agentRunning && !deliveryRunning && canStartDelivery,
    deliveryRunning ? 'delivery agent is running' : (canStartDelivery ? '' : 'approve response content first'),
  );
  setButton('btn-delivery-stop', delivery.agent_status === 'running', 'delivery agent is not running');
  const verifyingFigures = delivery.phase === 'figure_verification_running';
  el('btn-verify-figures').textContent = verifyingFigures ? 'Verifying figures…' : 'Verify figures';
  setButton(
    'btn-verify-figures',
    project.stage === 'await_delivery_approval' && !verifyingFigures
      && Boolean(((delivery.artifacts || {}).revised_paper || {}).sha256),
    verifyingFigures ? 'the three-model panel is reviewing the figures'
      : 'the delivery preflight must pass first',
  );
  setButton(
    'btn-delivery-approve',
    project.stage === 'await_delivery_approval'
      && Boolean((delivery.validation || {}).ready)
      && Boolean((delivery.figure_verification || {}).all_pass),
    project.stage === 'bundle_ready' ? 'final artifacts are already approved'
      : !Boolean((delivery.figure_verification || {}).all_pass) ? 'all three figure reviewers must pass first'
      : 'strict artifact preflight must pass first',
  );
  setButton('btn-policy-save', !active && !agentRunning && !deliveryRunning, deliveryRunning ? 'stop the delivery agent before changing policy' : (agentRunning ? 'stop the agent before changing policy' : (active ? `${active} is running` : '')));
  el('action-status').textContent = agentRunning
    ? `live Agent running in ${project.tmux_target || 'tmux'}`
    : (deliveryRunning
      ? `Delivery Agent ${delivery.agent_status} in ${delivery.tmux_target || 'tmux'}`
      : (active ? `${active} running — this page polls automatically` : (project.error || delivery.summary || project.agent_summary || '')));
}

function renderAgentPanel(project) {
  const delivery = project.delivery || {};
  const showDelivery = Boolean(
    delivery.tmux_target
    && delivery.phase
    && delivery.phase !== 'invalidated',
  );
  const target = String(showDelivery ? delivery.tmux_target : (project.tmux_target || ''));
  const status = String(showDelivery ? (delivery.agent_status || delivery.phase) : (project.agent_status || 'not started'));
  if (status === 'running' && !R.agentLiveTouched) {
    R.agentLive = true;
  }
  el('agent-pane-title').textContent = showDelivery
    ? 'The Delivery Agent at work'
    : 'The rebuttal agent at work';
  el('agent-pane-description').textContent = showDelivery
    ? 'Read-only live tail of the isolated revised-paper and one-page rebuttal attempt.'
    : 'Read-only live tail of the dedicated Cursor Agent tmux pane.';
  el('agent-live').checked = R.agentLive;
  el('agent-pane-target').textContent = target || 'no pane';
  el('agent-pane-status').textContent = [
    `status: ${status}`,
    showDelivery
      ? (delivery.agent_model ? `model: ${delivery.agent_model}` : '')
      : (project.agent_model ? `model: ${project.agent_model}` : ''),
    showDelivery
      ? (delivery.agent_started_at ? `started: ${shortTime(delivery.agent_started_at)}` : '')
      : (project.agent_started_at ? `started: ${shortTime(project.agent_started_at)}` : ''),
    showDelivery ? (delivery.summary || '') : (project.agent_summary || ''),
  ].filter(Boolean).join(' · ');
  el('agent-pane').hidden = !(R.agentLive && target);
}

function renderPaper(project) {
  R.paper = project;
  if ((project.studio || {}).id) R.studioId = project.studio.id;
  el('project-stage').textContent = project.stage || 'intake';
  el('project-title').textContent = project.title || project.id;
  el('project-path').textContent = project.source_path || '';
  el('project-meta').textContent = [
    (project.studio || {}).title ? `Studio: ${project.studio.title}` : 'Legacy flat import',
    `${(project.reviewers || []).length} reviewer(s)`,
    `${Object.keys(project.responses || {}).length} response(s)`,
    `$${Number(project.cost_usd || 0).toFixed(2)} spent`,
    project.updated_at ? `updated ${shortTime(project.updated_at)}` : '',
  ].filter(Boolean).join(' · ');
  el('output-path').textContent = `Output: ${project.output_path || ''}`;
  el('paper-setup-details').hidden = Boolean((project.studio || {}).id);
  renderPaperPipeline(project);
  renderManifest(project);
  renderPaperPolicy(project);
  renderConcerns(project);
  renderResponses(project);
  renderValidation(project);
  renderDelivery(project);
  renderPaperActions(project);
  renderAgentPanel(project);
  const log = el('activity-log');
  const lines = project.logs || [];
  const pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent = lines.length ? lines.join('\n') : '(no activity yet)';
  if (pinned || project.active_job) log.scrollTop = log.scrollHeight;
}

async function loadPaper() {
  if (!R.paperId) return;
  try {
    const payload = await api(`/api/rebuttal/projects/${encodeURIComponent(R.paperId)}`);
    if (R.paperId === payload.project.id) renderPaper(payload.project);
  } catch (error) {
    toast(error.message, true);
  }
}

async function paperAct(action, body = {}) {
  if (R.busy || !R.paperId) return null;
  R.busy = true;
  try {
    return await api(`/api/rebuttal/projects/${encodeURIComponent(R.paperId)}/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  } catch (error) {
    toast(error.message, true);
    return null;
  } finally {
    R.busy = false;
  }
}

async function savePaperPolicy() {
  const payload = await paperAct('policy', { policy: paperPolicyFromForm() });
  if (!payload) return;
  R.paperPolicyDirty = false;
  renderPaper(payload.project);
  toast('Paper policy override saved.');
}

async function saveResponse(reviewerId) {
  const section = [...document.querySelectorAll('.rb-response')]
    .find((node) => node.dataset.reviewer === reviewerId);
  if (!section) return;
  const payload = await paperAct('save-response', {
    reviewer_id: reviewerId,
    body: section.querySelector('textarea').value,
  });
  if (!payload) return;
  R.dirtyResponses.delete(reviewerId);
  renderPaper(payload.project);
  toast(`Saved response to ${reviewerId}.`);
}

async function runPaperAction(action) {
  const payload = await paperAct(action);
  if (payload && payload.project) renderPaper(payload.project);
  else loadPaper();
  return payload;
}

async function forgetPaper() {
  if (!R.paperId || !window.confirm('Forget this Paper? Source files and rebuttal-output will be preserved.')) return;
  try {
    await api(`/api/rebuttal/projects/${encodeURIComponent(R.paperId)}`, { method: 'DELETE' });
    toast('Paper forgotten; on-disk output was preserved.');
    if (R.studioId) openStudio(R.studioId);
    else openFleet();
  } catch (error) {
    toast(error.message, true);
  }
}

function startPolling() {
  if (R.timer) clearInterval(R.timer);
  R.timer = setInterval(() => {
    if (document.hidden) return;
    loadFleet();
    if (R.view === 'studio') loadStudio();
    if (R.view === 'paper') loadPaper();
  }, 4000);
}

async function pollAgentPane() {
  try {
    const delivery = (R.paper && R.paper.delivery) || {};
    const target = String(
      (delivery.phase !== 'invalidated' && delivery.tmux_target)
      || (R.paper && R.paper.tmux_target)
      || '',
    );
    if (
      R.view === 'paper'
      && R.agentLive
      && target
      && !document.hidden
    ) {
      const payload = await api(
        `/api/tmux/capture?target=${encodeURIComponent(target)}&lines=100`,
      );
      const pane = el('agent-pane');
      const pinned = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 36;
      pane.textContent = payload.text || '(the pane is empty)';
      pane.hidden = false;
      if (pinned) pane.scrollTop = pane.scrollHeight;
    }
  } catch {
    // The pane may be between launch/exit states; the project poll reports it.
  } finally {
    setTimeout(pollAgentPane, 2000);
  }
}

el('btn-create-studio').addEventListener('click', createStudio);
el('btn-refresh').addEventListener('click', () => {
  loadFleet();
  if (R.view === 'studio') loadStudio();
  if (R.view === 'paper') loadPaper();
});
el('btn-studio-back').addEventListener('click', openFleet);
el('btn-paper-back').addEventListener('click', () => {
  if (R.studioId) openStudio(R.studioId);
  else openFleet();
});
el('btn-discover-policy').addEventListener('click', discoverPolicy);
el('btn-approve-policy').addEventListener('click', approveStudioPolicy);
el('btn-studio-policy-save').addEventListener('click', saveStudioPolicy);
el('btn-add-paper').addEventListener('click', addPaper);
el('btn-forget-studio').addEventListener('click', forgetStudio);

el('btn-rescan').addEventListener('click', () => runPaperAction('rescan'));
el('btn-agent-start').addEventListener('click', async () => {
  R.agentLive = true;
  R.agentLiveTouched = false;
  await runPaperAction('start-agent');
});
el('btn-agent-stop').addEventListener('click', () => runPaperAction('stop-agent'));
el('btn-validate').addEventListener('click', () => runPaperAction('validate'));
el('btn-approve').addEventListener('click', async () => {
  if (!window.confirm('Approve these response drafts and start the isolated Delivery Agent?')) return;
  const payload = await runPaperAction('approve');
  if (!payload) return;
  const started = payload.delivery_start || {};
  if (started.ok) toast('Response content approved. Delivery Agent started.');
  else if (started.error) toast(`Responses approved, but delivery could not start: ${started.error}`, true);
  else toast('Response content approved.');
});
el('btn-delivery-start').addEventListener('click', async () => {
  const rerun = R.paper && R.paper.stage === 'delivery_blocked';
  const payload = await runPaperAction(rerun ? 'rerun-delivery' : 'start-delivery');
  if (payload) toast(rerun ? 'Delivery Agent restarted with preflight feedback.' : 'Delivery Agent started.');
});
el('btn-delivery-stop').addEventListener('click', () => runPaperAction('stop-delivery'));
el('btn-verify-figures').addEventListener('click', async () => {
  const payload = await runPaperAction('verify-figures');
  if (payload) toast('Three-model figure verification started.');
});
el('btn-delivery-approve').addEventListener('click', async () => {
  if (!window.confirm('Approve the exact validated PDF hashes and build the manual-upload bundle?')) return;
  const payload = await runPaperAction('approve-delivery');
  if (payload) toast('Final artifact hashes approved. Submission bundle is ready.');
});
el('btn-policy-save').addEventListener('click', savePaperPolicy);
el('btn-forget').addEventListener('click', forgetPaper);

/* ---- OpenReview submission --------------------------------------------------
   Sign in once (password -> token, cached server-side under 0600), dry-run
   the plan, then a separate explicit confirm posts the replies. */
async function orRefreshAuth() {
  try {
    const auth = await api('/api/openreview/auth');
    const signedIn = !!auth.logged_in;
    el('or-auth-state').textContent = signedIn ? `signed in as ${auth.user}` : 'not signed in';
    el('or-username').parentElement.hidden = signedIn;
    el('or-password').parentElement.hidden = signedIn;
    el('btn-or-login').hidden = signedIn;
    el('btn-or-logout').hidden = !signedIn;
    return signedIn;
  } catch { return false; }
}
el('btn-or-login').addEventListener('click', async () => {
  const username = el('or-username').value.trim();
  const password = el('or-password').value;
  if (!username || !password) { el('or-status').textContent = 'Email and password are required.'; return; }
  el('or-status').textContent = 'Signing in…';
  try {
    await api('/api/openreview/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    el('or-password').value = '';
    el('or-status').textContent = '';
    await orRefreshAuth();
  } catch (error) { el('or-status').textContent = error.message; }
});
el('btn-or-logout').addEventListener('click', async () => {
  await api('/api/openreview/logout', { method: 'POST', body: '{}' });
  el('btn-or-submit').disabled = true;
  await orRefreshAuth();
});
function orRenderPlan(payload) {
  const rows = (payload.items || []).map((item) => item.error
    ? `<article class="rb-project"><div><h3>${esc(item.reviewer_id)}</h3><p>${esc(item.error)}</p></div><span class="rb-pill rb-pill--bad">skipped</span></article>`
    : `<article class="rb-project"><div><h3>${esc(item.reviewer_id)} → ${esc(item.reviewer_label || '')}</h3><p>replyto ${esc(item.replyto)}</p></div><span class="rb-count">${esc(String(item.characters))} chars</span></article>`).join('');
  el('or-plan').innerHTML = `<p class="rb-status">forum <b>${esc(payload.forum)}</b> · invitation <b>${esc(payload.invitation)}</b> · signing as <b>${esc(payload.signature)}</b></p>${rows}`;
}
el('btn-or-preview').addEventListener('click', async () => {
  if (!(await orRefreshAuth())) { el('or-status').textContent = 'Sign in to OpenReview first.'; return; }
  el('or-status').textContent = 'Building the plan…';
  try {
    const payload = await api(`/api/rebuttal/projects/${encodeURIComponent(R.paperId)}/submit-openreview`, {
      method: 'POST', body: '{}',
    });
    orRenderPlan(payload);
    const good = (payload.items || []).filter((item) => !item.error).length;
    el('or-status').textContent = good
      ? `Dry run only — nothing posted. ${good} repl${good === 1 ? 'y' : 'ies'} ready.`
      : 'Nothing postable — see the plan below.';
    el('btn-or-submit').disabled = !good;
    el('btn-or-submit').title = good ? '' : 'preview produced no postable replies';
  } catch (error) { el('or-status').textContent = error.message; el('btn-or-submit').disabled = true; }
});
el('btn-or-submit').addEventListener('click', async () => {
  if (!window.confirm('Post these replies to the PUBLIC OpenReview forum now? This cannot be undone.')) return;
  el('or-status').textContent = 'Posting…';
  try {
    const payload = await api(`/api/rebuttal/projects/${encodeURIComponent(R.paperId)}/submit-openreview`, {
      method: 'POST', body: JSON.stringify({ confirm: true }),
    });
    const ok = (payload.results || []).filter((r) => r.ok).length;
    const bad = (payload.results || []).filter((r) => r.error);
    el('or-status').textContent = `Posted ${ok}/${(payload.results || []).length} replies.`
      + (bad.length ? ` Failed: ${bad.map((r) => `${r.reviewer_id} (${r.error})`).join('; ')}` : '');
    el('btn-or-submit').disabled = true;
    if (ok) toast(`OpenReview: ${ok} replies posted.`);
    loadPaper();
  } catch (error) { el('or-status').textContent = error.message; }
});
el('agent-live').addEventListener('change', (event) => {
  R.agentLive = event.target.checked;
  R.agentLiveTouched = true;
  renderAgentPanel(R.paper || {});
});

Object.keys(STUDIO_POLICY_FIELDS).forEach((id) => {
  el(id).addEventListener('input', () => { R.studioPolicyDirty = true; });
  el(id).addEventListener('change', () => { R.studioPolicyDirty = true; });
});
[
  'policy-platform', 'policy-limit', 'policy-target', 'policy-language',
  'policy-frozen', 'policy-links', 'policy-attachments', 'policy-global',
  'policy-anonymous',
].forEach((id) => {
  el(id).addEventListener('input', () => { R.paperPolicyDirty = true; });
  el(id).addEventListener('change', () => { R.paperPolicyDirty = true; });
});

window.addEventListener('hashchange', readHash);
window.addEventListener('loom:mathjax-ready', refreshRenderedMath);
window.addEventListener('loom:mathjax-error', () => {
  document.querySelectorAll('[data-preview-status]').forEach((node) => {
    node.textContent = 'TeX source shown · scroll linked';
  });
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  loadFleet();
  if (R.view === 'studio') loadStudio();
  if (R.view === 'paper') loadPaper();
});

if (window.__loomMathJaxReady) refreshRenderedMath();
readHash();
loadFleet();
startPolling();
pollAgentPane();
