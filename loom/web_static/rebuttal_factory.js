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
  writeHash(`paper/${encodeURIComponent(id)}`);
  show('paper');
  loadPaper();
}

function readHash() {
  const [kind, id] = location.hash.replace(/^#/, '').split('/');
  if (kind === 'studio' && id) openStudio(decodeURIComponent(id));
  else if (kind === 'paper' && id) openPaper(decodeURIComponent(id));
  else openFleet();
}

function projectBadge(project) {
  if (project.active_job) {
    return `<span class="rb-pill rb-pill--live">${esc(project.active_job)} running</span>`;
  }
  if (project.ready) return '<span class="rb-pill rb-pill--ready">ready</span>';
  if (project.error) return '<span class="rb-pill rb-pill--bad">blocked</span>';
  return `<span class="rb-pill">${esc(project.stage || 'intake')}</span>`;
}

function paperRow(project, studioId = '') {
  return `<article class="rb-project" data-paper="${esc(project.id)}" data-studio="${esc(studioId)}">
    <div>
      <h3>${esc(project.title || project.id)}</h3>
      <p>${esc(project.source_path || '')}</p>
    </div>
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

  const host = el('studio-list');
  if (!R.studios.length && !orphanProjects.length) {
    host.innerHTML = '<div class="rb-card">No Conference Studios yet. Start one above.</div>';
    return;
  }
  const studios = R.studios.map((studio) => {
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
  const legacy = orphanProjects.length
    ? `<div class="rb-section-head"><div><h2>Legacy flat imports</h2><p>Assign new papers through a Conference Studio.</p></div></div>
       ${orphanProjects.map((project) => paperRow(project)).join('')}`
    : '';
  host.innerHTML = studios + legacy;
  host.querySelectorAll('[data-studio]:not([data-paper])').forEach((node) => {
    node.addEventListener('click', () => openStudio(node.dataset.studio));
  });
  host.querySelectorAll('[data-paper]').forEach((node) => {
    node.addEventListener('click', () => openPaper(node.dataset.paper, node.dataset.studio));
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
  el('studio-policy-markdown').innerHTML = renderMarkdown(studio.policy_markdown || '');
  el('studio-strategy-markdown').innerHTML = renderMarkdown(studio.strategy_markdown || '');
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
    el('paper-import-status').textContent = 'An absolute Paper materials path is required.';
    return;
  }
  setButton('btn-add-paper', false, 'importing');
  el('paper-import-status').textContent = 'Scanning Paper package…';
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
    toast('Paper imported. Review analysis and rebuttal drafting started automatically.');
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
  ['validated', 'Policy validated'],
  ['approved', 'Human approved'],
];

function renderPaperPipeline(project) {
  const index = PAPER_STAGES.findIndex(([id]) => id === project.stage);
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
    <textarea spellcheck="true" aria-label="Response to ${esc(reviewerId)}"></textarea>
    <footer><span class="rb-status">Markdown source · saved on disk</span>
      <button type="button" class="rb-btn" data-save>Save response</button></footer>`;
  const textarea = section.querySelector('textarea');
  textarea.addEventListener('input', () => {
    R.dirtyResponses.add(reviewerId);
    section.classList.add('is-dirty');
    updateResponseCounter(section, R.paper || project);
    section.querySelector('[data-save]').disabled = false;
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
      section.querySelector('textarea').value = responses[reviewerId].body || '';
      section.classList.remove('is-dirty');
      section.querySelector('[data-save]').disabled = true;
    }
    updateResponseCounter(section, project);
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

function renderPaperActions(project) {
  const active = String(project.active_job || '');
  const manifestReady = Boolean((project.manifest || {}).ready);
  const reviewers = project.reviewers || [];
  const responseCount = Object.keys(project.responses || {}).length;
  setButton('btn-rescan', !active, active ? `${active} is running` : '');
  setButton('btn-analyze', !active && manifestReady, active ? `${active} is running` : 'package needs paper and review PDFs');
  setButton('btn-draft', !active && reviewers.length > 0, active ? `${active} is running` : 'analyze reviews first');
  setButton('btn-validate', !active && responseCount === reviewers.length && responseCount > 0, active ? `${active} is running` : 'draft every reviewer response first');
  setButton(
    'btn-approve',
    !active && Boolean((project.validation || {}).ready) && project.stage !== 'approved',
    active ? `${active} is running` : (project.stage === 'approved' ? 'already human-approved' : 'validation must pass first'),
  );
  setButton('btn-policy-save', !active, active ? `${active} is running` : '');
  el('action-status').textContent = active
    ? `${active} running — this page polls automatically`
    : (project.error || '');
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
  renderPaperPipeline(project);
  renderManifest(project);
  renderPaperPolicy(project);
  renderConcerns(project);
  renderResponses(project);
  renderValidation(project);
  renderPaperActions(project);
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
el('btn-analyze').addEventListener('click', () => runPaperAction('analyze'));
el('btn-draft').addEventListener('click', () => runPaperAction('draft'));
el('btn-validate').addEventListener('click', () => runPaperAction('validate'));
el('btn-approve').addEventListener('click', async () => {
  if (!window.confirm('Mark this validated response package as human-approved?')) return;
  await runPaperAction('approve');
});
el('btn-policy-save').addEventListener('click', savePaperPolicy);
el('btn-forget').addEventListener('click', forgetPaper);

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
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  loadFleet();
  if (R.view === 'studio') loadStudio();
  if (R.view === 'paper') loadPaper();
});

readHash();
loadFleet();
startPolling();
