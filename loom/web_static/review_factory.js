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
    const rated = p.rating != null;
    const grade = !rated ? 'none' : (p.rating >= 7 ? 'good' : (p.rating >= 5 ? 'mid' : 'bad'));
    const verdict = (p.headline || '').split('·').map((s) => s.trim())
      .find((s) => /^(accept|reject|borderline|weak)/i.test(s)) || '';
    return `<article class="rf-studio rv-project" data-id="${esc(p.id)}">
      <div class="rf-studio__head rv-head" data-open="${esc(p.id)}" tabindex="0" role="button"
           title="${esc(p.source_path)}" aria-label="Toggle reports for ${esc(p.title)}">
        <div class="rv-score rv-score--${grade}">${rated ? esc(p.rating) : '·'}<small>/10</small></div>
        <div class="rv-title-wrap">
          <div class="rf-studio__name">${esc(p.title)}</div>
          <div class="rv-meta">
            <span class="rf-pill">${esc(String(p.venue || '').toUpperCase())}</span>
            ${verdict ? `<span class="rv-verdict rv-verdict--${grade}">${esc(verdict)}</span>` : ''}
            ${p.reviewed_at ? `<span class="rv-when">reviewed ${esc(p.reviewed_at.slice(0, 16).replace('T', ' '))}</span>` : '<span class="rv-when">not reviewed yet</span>'}
          </div>
          ${p.error ? `<div class="rf-studio__meta" style="color:var(--rf-bad)">${esc(p.error)}</div>` : ''}
        </div>
        <div class="rf-section__actions">
          ${p.status === 'running' ? statusPill(p) : ''}
          <button type="button" class="rf-btn rf-btn--sm" data-run="${esc(p.id)}"
                  ${p.status === 'running' ? 'disabled title="already reviewing"' : ''}>
            ${rated ? 'Review again' : 'Run review'}</button>
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

function runRow(id, run, isLatest) {
  const scores = run.scores || {};
  const chips = ['rating', 'confidence']
    .filter((k) => scores[k] != null)
    .map((k) => `<span class="rf-pill">${esc(k)} ${esc(scores[k])}</span>`).join(' ');
  const base = `/api/review/projects/${encodeURIComponent(id)}/runs/${encodeURIComponent(run.run)}`;
  return `<div class="rv-run">
    <span class="rv-run__stamp">${esc(run.run.slice(0, 16).replace('T', ' '))}${isLatest ? ' · latest' : ''}</span>
    ${chips}
    <span class="rv-run__spacer"></span>
    <a class="rf-btn rf-btn--sm" href="${base}/review.md?dl=1">⬇ review.md</a>
    <a class="rf-btn rf-btn--sm rf-btn--ghost" href="${base}/panel.json?dl=1">⬇ panel.json</a>
  </div>`;
}

function openreviewBox(id, state) {
  const src = String(state.source_url || '');
  if (!/openreview\.net/.test(src)) return '';
  const done = state.openreview_review || null;
  return `<div class="rv-or" data-or="${esc(id)}">
    <div class="rf-section__head" style="margin:14px 0 6px">
      <h3 style="margin:0">Fill the OpenReview form</h3>
      <span class="rf-hint" data-or-auth>…</span>
    </div>
    ${done ? `<p class="rf-hint">Already submitted ${esc(String(done.at || '').slice(0, 16))} as ${esc(done.signature || '')} (note ${esc(done.note_id || '')}).</p>` : ''}
    <p class="rf-hint">Maps the panel report onto the venue's Official_Review fields (summary, strengths &amp; weaknesses, questions, rating, confidence). You must be an assigned reviewer; nothing posts without the confirm.</p>
    <div class="rf-section__actions" style="justify-content:flex-start; gap:8px">
      <button type="button" class="rf-btn rf-btn--sm" data-or-preview="${esc(id)}">Preview form</button>
      <button type="button" class="rf-btn rf-btn--sm rf-btn--danger" data-or-submit="${esc(id)}" disabled
              title="preview first">Confirm — submit review</button>
    </div>
    <p class="rf-hint" data-or-status></p>
    <div data-or-plan></div>
  </div>`;
}

async function orAuthLabel(node) {
  try {
    const auth = await api('/api/openreview/auth');
    node.textContent = auth.logged_in
      ? `signed in as ${auth.user}`
      : 'not signed in — use the Rebuttal Factory sign-in once, it is shared';
    return !!auth.logged_in;
  } catch { node.textContent = 'auth check failed'; return false; }
}

function wireOpenreviewBox(id) {
  const box = document.querySelector(`.rv-or[data-or="${CSS.escape(id)}"]`);
  if (!box) return;
  const status = box.querySelector('[data-or-status]');
  const plan = box.querySelector('[data-or-plan]');
  const submitBtn = box.querySelector('[data-or-submit]');
  orAuthLabel(box.querySelector('[data-or-auth]'));
  box.querySelector('[data-or-preview]').addEventListener('click', async () => {
    status.textContent = 'Reading the venue form…';
    try {
      const d = await api(`/api/review/projects/${id}/submit-openreview`, { method: 'POST', body: '{}' });
      plan.innerHTML = `
        <p class="rf-hint">forum <b>${esc(d.forum)}</b> · invitation <b>${esc(d.invitation)}</b> · signing as <b>${esc(d.signature)}</b></p>
        ${(d.fields || []).map((f) => `<div class="rv-run"><span class="rf-pill">${esc(f.field)}</span>
          <span class="rv-run__stamp">${esc(String(f.chars))} chars</span>
          <span class="rv-field-preview">${esc(f.preview)}</span></div>`).join('')}`;
      status.textContent = 'Dry run only — nothing posted yet.';
      submitBtn.disabled = false;
      submitBtn.title = '';
    } catch (err) { status.textContent = err.message; submitBtn.disabled = true; }
  });
  submitBtn.addEventListener('click', async () => {
    if (!confirm('Submit this review to the PUBLIC OpenReview forum now? This cannot be undone.')) return;
    status.textContent = 'Submitting…';
    try {
      const d = await api(`/api/review/projects/${id}/submit-openreview`, {
        method: 'POST', body: JSON.stringify({ confirm: true }),
      });
      status.textContent = `Submitted — note ${d.note_id || '(id unknown)'}.`;
      submitBtn.disabled = true;
      toast('Official review submitted to OpenReview.');
      S.fp = '';
      fillDetail(id);
    } catch (err) { status.textContent = err.message; }
  });
}

async function fillDetail(id) {
  const node = document.querySelector(`.rv-detail[data-detail="${CSS.escape(id)}"]`);
  if (!node || !S.open.has(id)) return;
  let d;
  try { d = await api(`/api/review/projects/${id}`); }
  catch (err) { node.innerHTML = `<p class="rf-hint">${esc(err.message)}</p>`; return; }
  const state = d.state || {};
  const latest = state.latest_review;
  const runs = d.runs || [];
  if (!latest && !runs.length) {
    node.innerHTML = '<p class="rf-hint" style="margin-top:10px">No report yet — run the review.</p>';
    return;
  }
  const scores = (latest && latest.scores) || {};
  const chips = Object.entries(scores)
    .map(([k, v]) => `<span class="rf-pill">${esc(k)} ${esc(v)}</span>`).join(' ');
  const latestRun = latest ? Path_name(latest.path) : '';
  node.innerHTML = `
    <div class="rv-scores">${chips}</div>
    ${reviewerCards(latest || {})}
    <div class="rv-runs">${runs.map((r) => runRow(id, r, r.run === latestRun)).join('')}</div>
    ${openreviewBox(id, state)}
    <pre class="rv-review-text" data-md>loading review…</pre>`;
  wireOpenreviewBox(id);
  try {
    const res = await fetch(`/api/review/projects/${id}/runs/${encodeURIComponent(latestRun || (runs[0] || {}).run || '')}/review.md`);
    const md = res.ok ? await res.text() : '';
    const pre = node.querySelector('[data-md]');
    if (pre) {
      if (md) pre.textContent = md.slice(0, 120000);
      else pre.remove();
    }
  } catch { const pre = node.querySelector('[data-md]'); if (pre) pre.remove(); }
}

function Path_name(p) {
  const parts = String(p || '').split('/');
  return parts[parts.length - 1] || '';
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
