/* Auto Rebuttal Factory - path-imported, file-backed reviewer responses. */
'use strict';

const R = {
  view: 'fleet',
  id: '',
  data: null,
  projects: [],
  busy: false,
  timer: null,
  dirtyResponses: new Set(),
  policyDirty: false,
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

function show(view) {
  R.view = view;
  el('view-fleet').hidden = view !== 'fleet';
  el('view-project').hidden = view !== 'project';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function setButton(id, ok, why = '') {
  const button = el(id);
  button.disabled = !ok;
  button.title = ok ? '' : why;
}

function openFleet() {
  R.id = '';
  R.data = null;
  R.dirtyResponses.clear();
  R.policyDirty = false;
  history.replaceState(null, '', '#');
  show('fleet');
  loadFleet();
}

function openProject(id) {
  R.id = id;
  R.data = null;
  R.dirtyResponses.clear();
  R.policyDirty = false;
  history.replaceState(null, '', `#project/${encodeURIComponent(id)}`);
  show('project');
  loadProject();
}

function readHash() {
  const [kind, id] = location.hash.replace(/^#/, '').split('/');
  if (kind === 'project' && id) openProject(decodeURIComponent(id));
  else openFleet();
}

async function loadFleet() {
  let payload;
  try { payload = await api('/api/rebuttal/projects'); }
  catch (error) { toast(error.message, true); return; }
  R.projects = payload.projects || [];
  const ready = R.projects.filter((item) => item.ready).length;
  const spent = R.projects.reduce((sum, item) => sum + Number(item.cost_usd || 0), 0);
  el('stat-projects').innerHTML = `<b>${R.projects.length}</b> ${R.projects.length === 1 ? 'project' : 'projects'}`;
  el('stat-ready').innerHTML = `<b>${ready}</b> ready`;
  el('stat-cost').innerHTML = `<b>$${spent.toFixed(2)}</b> spent`;
  if (R.view !== 'fleet') return;

  const host = el('project-list');
  if (!R.projects.length) {
    host.innerHTML = '<div class="rb-card">No rebuttal projects yet. Import a package path above.</div>';
    return;
  }
  host.innerHTML = R.projects.map((project) => {
    const badge = project.active_job
      ? `<span class="rb-pill rb-pill--live">${esc(project.active_job)} running</span>`
      : project.ready
        ? '<span class="rb-pill rb-pill--ready">ready</span>'
        : project.error
          ? '<span class="rb-pill rb-pill--bad">blocked</span>'
          : `<span class="rb-pill">${esc(project.stage || 'intake')}</span>`;
    return `<article class="rb-project" data-project="${esc(project.id)}">
      <div>
        <h3>${esc(project.title || project.id)}</h3>
        <p>${esc(project.source_path || '')}</p>
      </div>
      <span class="rb-count">${esc(plural(Number(project.reviewers || 0), 'reviewer'))}</span>
      <span class="rb-count">${esc(plural(Number(project.responses || 0), 'response'))}</span>
      ${badge}
    </article>`;
  }).join('');
  host.querySelectorAll('[data-project]').forEach((node) => {
    node.addEventListener('click', () => openProject(node.dataset.project));
  });
}

async function importPackage() {
  const path = el('import-path').value.trim();
  if (!path) {
    el('import-status').textContent = 'An absolute server directory path is required.';
    return;
  }
  el('import-status').textContent = 'Scanning package…';
  setButton('btn-import', false, 'importing');
  try {
    const payload = await api('/api/rebuttal/projects', {
      method: 'POST',
      body: JSON.stringify({
        path,
        title: el('import-title').value.trim(),
        policy: {
          character_limit: Number(el('import-limit').value || 10000),
          manuscript_frozen: el('import-frozen').checked,
          allow_links: el('import-links').checked,
          allow_global_response: el('import-global').checked,
        },
      }),
    });
    el('import-status').textContent = '';
    openProject(payload.project.id);
  } catch (error) {
    el('import-status').textContent = error.message;
    toast(error.message, true);
  } finally {
    setButton('btn-import', true);
  }
}

const STAGES = [
  ['intake', 'Package intake'],
  ['concerns_ready', 'Concern matrix'],
  ['responses_ready', 'Draft responses'],
  ['validated', 'Policy validated'],
  ['approved', 'Human approved'],
];

function renderPipeline(project) {
  const index = STAGES.findIndex(([id]) => id === project.stage);
  el('pipeline').innerHTML = STAGES.map(([id, label], position) => {
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
  const host = el('manifest');
  host.innerHTML = `<div class="rb-file-list">${shown.map((item) => `
    <div class="rb-file">
      <b>${esc(item.kind)}</b>
      <span>${esc(item.relative_path)}</span>
      <em>${(Number(item.size || 0) / 1024).toFixed(1)} kB</em>
    </div>`).join('')}</div>
    ${materials.length > 18 ? `<p class="rb-status">+ ${materials.length - 18} additional material files</p>` : ''}
    ${(manifest.warnings || []).map((warning) => `<p class="rb-warning">${esc(warning)}</p>`).join('')}`;
}

function renderPolicy(project) {
  if (R.policyDirty) return;
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

function policyFromForm() {
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
      <header>
        <h3>${esc(reviewer.label || reviewer.id)}</h3>
        <p>${esc(reviewer.summary || '')}</p>
      </header>
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
  const textarea = section.querySelector('textarea');
  const counter = section.querySelector('.rb-char');
  const count = textarea.value.length;
  counter.textContent = `${count.toLocaleString()} / ${Number(project.policy.character_limit || 10000).toLocaleString()}`;
  counter.className = `rb-char ${responseCountClass(count, project.policy || {})}`;
}

function createResponseSection(reviewerId, project) {
  const section = document.createElement('article');
  section.className = 'rb-response';
  section.dataset.reviewer = reviewerId;
  section.innerHTML = `<header>
      <h3>${esc(reviewerId)}</h3>
      <span class="rb-char"></span>
    </header>
    <textarea spellcheck="true" aria-label="Response to ${esc(reviewerId)}"></textarea>
    <footer>
      <span class="rb-status">Markdown source · saved on disk</span>
      <button type="button" class="rb-btn" data-save>Save response</button>
    </footer>`;
  const textarea = section.querySelector('textarea');
  textarea.addEventListener('input', () => {
    R.dirtyResponses.add(reviewerId);
    section.classList.add('is-dirty');
    updateResponseCounter(section, R.data || project);
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

function renderActions(project) {
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
    active
      ? `${active} is running`
      : (project.stage === 'approved' ? 'already human-approved' : 'validation must pass first'),
  );
  setButton('btn-policy-save', !active, active ? `${active} is running` : '');
  el('action-status').textContent = active
    ? `${active} running — this page polls automatically`
    : (project.error || '');
}

function renderProject(payload) {
  const project = payload.project || {};
  R.data = project;
  el('project-stage').textContent = project.stage || 'intake';
  el('project-title').textContent = project.title || project.id;
  el('project-path').textContent = project.source_path || '';
  el('project-meta').textContent = [
    `${(project.reviewers || []).length} reviewer(s)`,
    `${Object.keys(project.responses || {}).length} response(s)`,
    `$${Number(project.cost_usd || 0).toFixed(2)} spent`,
    project.updated_at ? `updated ${shortTime(project.updated_at)}` : '',
  ].filter(Boolean).join(' · ');
  el('output-path').textContent = `Output: ${project.output_path || ''}`;
  renderPipeline(project);
  renderManifest(project);
  renderPolicy(project);
  renderConcerns(project);
  renderResponses(project);
  renderValidation(project);
  renderActions(project);
  const logs = project.logs || [];
  const log = el('activity-log');
  const pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent = logs.length ? logs.join('\n') : '(no activity yet)';
  if (pinned || project.active_job) log.scrollTop = log.scrollHeight;
}

async function loadProject() {
  if (!R.id) return;
  try {
    const payload = await api(`/api/rebuttal/projects/${encodeURIComponent(R.id)}`);
    if (R.id === payload.project.id) renderProject(payload);
  } catch (error) {
    toast(error.message, true);
  }
}

async function act(action, body = {}) {
  if (R.busy || !R.id) return null;
  R.busy = true;
  try {
    return await api(`/api/rebuttal/projects/${encodeURIComponent(R.id)}/${action}`, {
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

async function savePolicy() {
  const payload = await act('policy', { policy: policyFromForm() });
  if (!payload) return;
  R.policyDirty = false;
  renderProject(payload);
  toast('Venue policy saved.');
}

async function saveResponse(reviewerId) {
  const section = [...document.querySelectorAll('.rb-response')]
    .find((node) => node.dataset.reviewer === reviewerId);
  if (!section) return;
  const payload = await act('save-response', {
    reviewer_id: reviewerId,
    body: section.querySelector('textarea').value,
  });
  if (!payload) return;
  R.dirtyResponses.delete(reviewerId);
  renderProject(payload);
  toast(`Saved response to ${reviewerId}.`);
}

async function runAction(action) {
  const payload = await act(action);
  if (payload && payload.project) renderProject(payload);
  else loadProject();
}

async function forgetProject() {
  if (!R.id || !window.confirm('Forget this project? Source files and rebuttal-output will be preserved.')) return;
  try {
    await api(`/api/rebuttal/projects/${encodeURIComponent(R.id)}`, { method: 'DELETE' });
    toast('Project forgotten; on-disk output was preserved.');
    openFleet();
  } catch (error) {
    toast(error.message, true);
  }
}

function startPolling() {
  if (R.timer) clearInterval(R.timer);
  R.timer = setInterval(() => {
    if (document.hidden) return;
    loadFleet();
    if (R.view === 'project') loadProject();
  }, 4000);
}

el('btn-import').addEventListener('click', importPackage);
el('btn-refresh').addEventListener('click', () => {
  loadFleet();
  if (R.view === 'project') loadProject();
});
el('btn-back').addEventListener('click', openFleet);
el('btn-rescan').addEventListener('click', () => runAction('rescan'));
el('btn-analyze').addEventListener('click', () => runAction('analyze'));
el('btn-draft').addEventListener('click', () => runAction('draft'));
el('btn-validate').addEventListener('click', () => runAction('validate'));
el('btn-approve').addEventListener('click', async () => {
  if (!window.confirm('Mark this validated response package as human-approved?')) return;
  await runAction('approve');
});
el('btn-policy-save').addEventListener('click', savePolicy);
el('btn-forget').addEventListener('click', forgetProject);

[
  'policy-platform', 'policy-limit', 'policy-target', 'policy-language',
  'policy-frozen', 'policy-links', 'policy-attachments', 'policy-global',
  'policy-anonymous',
].forEach((id) => {
  el(id).addEventListener('input', () => { R.policyDirty = true; });
  el(id).addEventListener('change', () => { R.policyDirty = true; });
});

window.addEventListener('hashchange', readHash);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    loadFleet();
    if (R.view === 'project') loadProject();
  }
});

readHash();
loadFleet();
startPolling();
