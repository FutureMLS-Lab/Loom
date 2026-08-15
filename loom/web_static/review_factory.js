/* Review Factory - standalone reviewer-panel projects.
 *
 * Same origin as Loom, so auth and static assets apply unchanged. The page
 * is a thin client over /api/review/*: register a directory, run the panel,
 * read the reports. State lives on the server; this file only paints it.
 */

'use strict';

const S = {
  projects: [],
  open: new Set(),     // project ids whose report panel is expanded
  fp: '',              // last-rendered data, so unchanged polls skip the DOM
  busy: false,
};

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

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status}`);
  return body || {};
}

function statusPill(p) {
  if (p.status === 'running') return '<span class="rf-pill rf-pill--live">reviewing</span>';
  if (p.status === 'error') return '<span class="rf-pill rf-pill--stuck">failed</span>';
  if (p.rating != null) return `<span class="rf-pill rf-pill--done">rated ${esc(p.rating)}/10</span>`;
  return '<span class="rf-pill">not reviewed</span>';
}

function reviewerCards(latest) {
  const reviewers = (latest && latest.reviewers) || [];
  if (!reviewers.length) return '';
  const deciding = String((latest && latest.deciding_model) || '');
  return `<div class="rv-reviewers">${reviewers.map((r) => {
    const model = String(r.model || '');
    const scores = r.scores || {};
    return `<div class="rv-reviewer ${model === deciding ? 'is-deciding' : ''}">
      <b>${esc(model)}</b>
      <div class="rv-rating">${esc(scores.rating != null ? scores.rating : '–')}/10</div>
      <div>${esc(String(r.recommendation || scores.recommendation || ''))}</div>
      ${model === deciding ? '<span class="rf-pill rf-pill--stuck">lowest · final</span>' : ''}
    </div>`;
  }).join('')}</div>`;
}

async function loadProjects() {
  let d;
  try { d = await api('/api/review/projects'); }
  catch (err) {
    if (!S.fp) el('project-list').innerHTML =
      `<div class="rf-empty">Could not reach Loom: ${esc(err.message)}</div>`;
    return;
  }
  S.projects = d.projects || [];
  const running = S.projects.filter((p) => p.status === 'running').length;
  el('stat-projects').innerHTML = `<b>${S.projects.length}</b> projects`;
  const live = el('stat-running');
  live.hidden = !running;
  live.innerHTML = `<b>${running}</b> running`;
  el('projects-status').textContent = running ? 'panel running — a few minutes…' : '';

  const fp = JSON.stringify([S.projects, [...S.open]]);
  if (fp === S.fp) return;
  S.fp = fp;
  renderProjects();
}

function renderProjects() {
  const host = el('project-list');
  if (!S.projects.length) {
    host.innerHTML = '<div class="rf-empty">No review projects yet. Add a directory above.</div>';
    return;
  }
  host.innerHTML = S.projects.map((p) => {
    const opened = S.open.has(p.id);
    return `<article class="rf-studio rv-project" data-id="${esc(p.id)}">
      <div class="rf-studio__head" data-open="${esc(p.id)}" tabindex="0" role="button"
           aria-label="Toggle reports for ${esc(p.title)}">
        <div>
          <div class="rf-studio__name">${esc(p.title)}</div>
          <div class="rf-studio__meta">${esc(p.source_path)} · ${esc(String(p.venue || '').toUpperCase())}${p.reviewed_at ? ` · reviewed ${esc(p.reviewed_at.slice(0, 16).replace('T', ' '))}` : ''}</div>
          ${p.headline ? `<div class="rf-studio__meta">${esc(p.headline)}</div>` : ''}
          ${p.error ? `<div class="rf-studio__meta" style="color:var(--rf-bad)">${esc(p.error)}</div>` : ''}
        </div>
        <div class="rf-section__actions">
          ${statusPill(p)}
          <button type="button" class="rf-btn rf-btn--sm" data-run="${esc(p.id)}"
                  ${p.status === 'running' ? 'disabled title="already reviewing"' : ''}>
            ${p.rating != null ? 'Review again' : 'Run review'}</button>
          <button type="button" class="rf-btn rf-btn--sm rf-btn--ghost" data-del="${esc(p.id)}"
                  title="Unregister; files and reports stay on disk">×</button>
        </div>
      </div>
      <div class="rv-detail" data-detail="${esc(p.id)}" ${opened ? '' : 'hidden'}></div>
    </article>`;
  }).join('');

  host.querySelectorAll('[data-open]').forEach((node) => {
    const toggle = async () => {
      const id = node.dataset.open;
      if (S.open.has(id)) S.open.delete(id); else S.open.add(id);
      S.fp = '';
      await fillDetail(id);
      renderOpenStates();
    };
    node.addEventListener('click', (ev) => {
      if (ev.target.closest('button')) return;  // buttons act, not toggle
      toggle();
    });
    node.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); }
    });
  });
  host.querySelectorAll('[data-run]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (S.busy) return;
      S.busy = true;
      try {
        await api(`/api/review/projects/${btn.dataset.run}/run`, { method: 'POST', body: '{}' });
        toast('Panel started — three reviewers, a few minutes.');
      } catch (err) { toast(`Run failed: ${err.message}`, true); }
      finally { S.busy = false; }
      loadProjects();
    });
  });
  host.querySelectorAll('[data-del]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Unregister this review project? Files and reports stay on disk.')) return;
      try {
        await api(`/api/review/projects/${btn.dataset.del}`, { method: 'DELETE' });
        S.open.delete(btn.dataset.del);
        toast('Project unregistered.');
      } catch (err) { toast(err.message, true); }
      S.fp = '';
      loadProjects();
    });
  });
  S.projects.forEach((p) => { if (S.open.has(p.id)) fillDetail(p.id); });
}

function renderOpenStates() {
  document.querySelectorAll('.rv-detail').forEach((node) => {
    node.hidden = !S.open.has(node.dataset.detail);
  });
}

async function fillDetail(id) {
  const node = document.querySelector(`.rv-detail[data-detail="${CSS.escape(id)}"]`);
  if (!node || !S.open.has(id)) return;
  let d;
  try { d = await api(`/api/review/projects/${id}`); }
  catch (err) { node.innerHTML = `<p class="rf-hint">${esc(err.message)}</p>`; return; }
  const latest = (d.state || {}).latest_review;
  if (!latest) {
    node.innerHTML = '<p class="rf-hint" style="margin-top:10px">No report yet — run the review.</p>';
    return;
  }
  const scores = latest.scores || {};
  const chips = Object.entries(scores)
    .map(([k, v]) => `<span class="rf-pill">${esc(k)} ${esc(v)}</span>`).join(' ');
  let text = '';
  try {
    const md = latest.reviewers && latest.reviewers.length
      ? latest.reviewers.map((r) => `# ${r.model}\n\n${r.review || ''}`).join('\n\n---\n\n')
      : '';
    text = md;
  } catch { /* keep empty */ }
  node.innerHTML = `
    <div class="rv-scores">${chips}</div>
    ${reviewerCards(latest)}
    ${text ? `<pre class="rv-review-text">${esc(text.slice(0, 60000))}</pre>` : ''}`;
}

el('btn-create').addEventListener('click', async () => {
  const path = el('new-path').value.trim();
  const status = el('create-status');
  if (!path) { status.textContent = 'A directory path is required.'; return; }
  const isUrl = /^https?:\/\//i.test(path);
  status.textContent = isUrl ? 'Fetching the paper…' : 'Registering…';
  try {
    await api('/api/review/projects', {
      method: 'POST',
      body: JSON.stringify(
        isUrl
          ? { url: path, venue: el('new-venue').value }
          : { path, venue: el('new-venue').value },
      ),
    });
    el('new-path').value = '';
    status.textContent = '';
    toast('Project added.');
  } catch (err) { status.textContent = err.message; }
  S.fp = '';
  loadProjects();
});
el('new-path').addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') { ev.preventDefault(); el('btn-create').click(); }
});

loadProjects();
setInterval(() => { if (!document.hidden) loadProjects(); }, 6000);
