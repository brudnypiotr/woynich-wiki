// Add sources: upload files or whole folders, follow each file through the ingest steps, cancel or remove.
// A dropped folder is read recursively; before anything is sent the user sees what goes in (as a tree, per folder) and
// what is skipped (types without an extractor, hidden and temporary files); every file and folder has a checkbox
// (all checked) to leave some out. Then each chosen file is uploaded with its path
// in the folder; the jobs of one folder show as a tree with counts per folder, and each file opens to its full card.
import {$, esc, ic, I, topbar} from './ui.js';
import {api} from './api.js';
import {mark} from './shell.js';

let STEPS = ['saved', 'extracted', 'writing', 'checking', 'verify', 'done'];  // the server sends its own list with every job
const STEP_LABEL = {saved: 'Saved', extracted: 'Text extracted', writing: 'Writing wiki', checking: 'Checking', verify: 'Citations verified', done: 'Done'};
const FOLDER = 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z';
const JOBS = new Map();          // id → job, as the server last reported it
const OPEN = new Set();          // expanded file cards (job ids) and folders ("batch/path")
const CLOSED = new Set();        // folders the user closed (open by default)
let TYPES = null, POLL = null;

export function openAdd() {mark('add');
  $('#main').innerHTML = topbar('Add sources') + `<div class="scroll"><div class="col wide">
   <div class="pagehead"><div class="kicker">Add sources</div><h2>Feed the knowledge base</h2>
   <p>Each file is kept unchanged. The model reads it, writes or updates the wiki pages, then every citation and link is checked and the change is committed.</p></div>
   <div class="drop" id="drop"><div class="up">${ic(I.up)}</div><b>Drop files or a whole folder here</b>
     <span>or <a href="#" data-pick="file">choose files</a> · <a href="#" data-pick="dir">choose a folder</a> (subfolders included)</span>
     <div class="types"><em>PDF</em><em>Word</em><em>Excel</em><em>PowerPoint</em><em>E-mail .eml</em><em>Teams .vtt</em><em>Jira .jira.json</em><em>XML / XSD</em><em>Images</em><em>Text &amp; code</em></div>
     <input type="file" id="file" multiple hidden><input type="file" id="dir" webkitdirectory multiple hidden></div>
   <div id="preview"></div>
   <div class="how"><div><b><i>1</i>Saved</b>Original stored as-is, text extracted.</div><div><b><i>2</i>Written</b>The model updates topic, entity and source pages.</div><div><b><i>3</i>Checked</b>Citations verified, everything committed. Cancel any time.</div></div>
   <h3 class="sec">Recent uploads</h3><div id="jobs"><p class="empty">Nothing uploaded in this session yet.</p></div></div></div>`;
  const d = $('#drop');
  d.onclick = e => {const p = e.target.closest('[data-pick]'); if (e.target.tagName === 'INPUT') return; e.preventDefault(); $(p && p.dataset.pick === 'dir' ? '#dir' : '#file').click()};
  $('#file').onchange = e => {pick([...e.target.files].map(f => ({file: f, path: f.name}))); e.target.value = ''};
  $('#dir').onchange = e => {pick([...e.target.files].map(f => ({file: f, path: f.webkitRelativePath || f.name}))); e.target.value = ''};
  d.ondragover = e => {e.preventDefault(); d.classList.add('over')}; d.ondragleave = () => d.classList.remove('over');
  d.ondrop = async e => {e.preventDefault(); d.classList.remove('over'); pick(await dropped(e.dataTransfer))};
  $('#jobs').onclick = onJobsClick;
  api('/api/upload/types').then(t => TYPES = t.extensions).catch(() => {});
  refresh()}

// ------------------------------------------------------------------ reading what was dropped

// Files and folders from a drop, with their path inside the dropped folder ("Specs/2024/a.pdf").
async function dropped(dt) {
  const entries = [...(dt.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dt.files].map(f => ({file: f, path: f.name}));
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {const file = await new Promise((ok, no) => entry.file(ok, no)); out.push({file, path: prefix + entry.name}); return}
    const reader = entry.createReader();
    for (;;) {  // readEntries returns at most ~100 entries per call: read until it returns none
      const batch = await new Promise((ok, no) => reader.readEntries(ok, no));
      if (!batch.length) break;
      for (const child of batch) await walk(child, prefix + entry.name + '/');
    }};
  for (const e of entries) await walk(e, '');
  return out}

function skipWhy(path, file) {const name = path.split('/').pop(), low = name.toLowerCase();
  if (path.split('/').some(p => p.startsWith('.'))) return 'hidden';
  if (/^(thumbs\.db|desktop\.ini)$/i.test(name) || name.startsWith('~$')) return 'system or temporary file';
  if (!file.size) return 'empty';
  if (TYPES && !TYPES.some(t => low.endsWith(t))) return 'no reader for this type';
  return null}

// ------------------------------------------------------------------ the preview before upload

let PENDING = null;

function pick(items) {
  if (!items.length) return;
  const take = [], skip = [];
  for (const it of items) {const why = skipWhy(it.path, it.file); (why ? skip : take).push({...it, why})}
  if (items.length === 1 && take.length === 1 && !take[0].path.includes('/')) return upload(take);  // one file: as before
  take.sort((a, b) => treeOrder(a.path, b.path));  // ingested top to bottom, as the tree shows them
  PENDING = {take, skip, off: new Set()};  // off: paths the user unchecked
  const {node: tree, name: top} = unwrap(build(take.map(t => ({path: t.path, bytes: t.file.size}))));
  $('#preview').innerHTML = `<div class="set pv"><h3><span id="pvn"></span>${top ? ` from <b>${esc(top)}</b>` : ''} <small id="pvmb"></small></h3>
    <p class="d">The model reads each file in its own session: every file costs AI credits and takes about a minute. The folders stay visible below and the model uses their names as context. Uncheck the files or folders to leave out${take.length > 1 ? ' (<a href="#" data-pv="all">all</a> · <a href="#" data-pv="none">none</a>)' : ''}.</p>
    ${take.length ? `<div class="tree">${treeHTML(tree, {preview: true}, top ? top + '/' : '')}</div>` : ''}
    ${skip.length ? `<details class="skipped"><summary>${skip.length} skipped</summary><ul>${skip.slice(0, 200).map(s => `<li><code>${esc(s.path)}</code> · ${esc(s.why)}</li>`).join('')}</ul></details>` : ''}
    <div class="btns">${take.length ? '<button class="pri" data-pv="go"></button>' : ''}<button class="ghost" data-pv="cancel">Cancel</button></div></div>`;
  $('#preview').onchange = e => {const c = e.target; if (!c.matches('input.pick')) return;
    const paths = c.dataset.p ? [c.dataset.p] : take.map(t => t.path).filter(p => p.startsWith(c.dataset.pd));  // a folder: all inside
    paths.forEach(p => c.checked ? PENDING.off.delete(p) : PENDING.off.add(p)); syncPreview()};
  $('#preview').onclick = e => {const a = (e.target.closest('[data-pv]') || {}).dataset?.pv; if (!a) return; e.preventDefault();
    if (a === 'all' || a === 'none') {PENDING.off = new Set(a === 'none' ? take.map(t => t.path) : []); return syncPreview()}
    const p = PENDING; PENDING = null; $('#preview').innerHTML = ''; if (a === 'go') upload(p.take.filter(t => !p.off.has(t.path)))};
  syncPreview()}

// checkboxes, counts and the button after a change: a folder is checked, unchecked or partly checked (indeterminate)
function syncPreview() {const {take, off} = PENDING, on = take.filter(t => !off.has(t.path));
  const n = on.length, size = on.reduce((k, t) => k + t.file.size, 0), all = take.length;
  $('#pvn').textContent = n === all ? `${all} file${all === 1 ? '' : 's'} to add` : `${n} of ${all} files to add`;
  $('#pvmb').textContent = mb(size);
  const go = $('#preview [data-pv="go"]');
  if (go) {go.textContent = n ? `Add ${n} file${n === 1 ? '' : 's'}` : 'Nothing chosen'; go.disabled = !n}
  document.querySelectorAll('#preview input.pick').forEach(c => {
    if (c.dataset.p) {c.checked = !off.has(c.dataset.p); c.closest('li').classList.toggle('off', !c.checked); return}
    const inside = take.filter(t => t.path.startsWith(c.dataset.pd)), k = inside.filter(t => !off.has(t.path)).length;
    c.checked = k === inside.length; c.indeterminate = k > 0 && k < inside.length;
    c.closest('li').classList.toggle('off', !k);
    const sm = c.parentElement.querySelector('small');
    if (sm) sm.textContent = `${k === inside.length ? '' : k + ' of '}${inside.length} file${inside.length === 1 ? '' : 's'} · ${mb(inside.filter(t => !off.has(t.path)).reduce((m, t) => m + t.file.size, 0) || 0)}`})}

async function upload(items) {
  const batch = items.length > 1 || items.some(i => i.path.includes('/')) ? Math.random().toString(36).slice(2, 10) : '';
  for (const {file, path} of items) {
    const j = await api('/api/upload', {method: 'POST', body: file,
      headers: {'X-Filename': encodeURIComponent(file.name), 'X-Path': encodeURIComponent(path), ...(batch ? {'X-Batch': batch} : {})}})
      .catch(e => ({id: 'x' + Math.random().toString(16).slice(2), error: e.message, filename: file.name, path, batch, state: 'error', log: [], seq: 1e9}));
    JOBS.set(j.id, j); render()}
  refresh()}

// ------------------------------------------------------------------ jobs: one card per single file, a tree per folder

async function refresh() {clearTimeout(POLL);
  try {(await api('/api/jobs')).forEach(j => JOBS.set(j.id, j))} catch (e) {}
  render();
  if ([...JOBS.values()].some(j => j.state === 'queued' || j.state === 'running')) POLL = setTimeout(() => {if ($('#jobs')) refresh()}, 2000)}

function render() {const box = $('#jobs'); if (!box) return;
  const all = [...JOBS.values()].sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));
  if (!all.length) return;
  const keepScroll = [...box.querySelectorAll('pre[data-job]')].map(p => [p.dataset.job, p.scrollTop, p.scrollTop + p.clientHeight >= p.scrollHeight - 4]);
  const seen = new Set(), blocks = [];
  for (const j of all) {
    if (!j.batch) {blocks.push(card(j)); continue}
    if (seen.has(j.batch)) continue; seen.add(j.batch);
    blocks.push(batchHTML(j.batch, all.filter(x => x.batch === j.batch)))}
  box.innerHTML = blocks.join('');
  for (const [id, top, end] of keepScroll) {const p = box.querySelector(`pre[data-job="${id}"]`); if (p) p.scrollTop = end ? p.scrollHeight : top}}

const count = js => ({total: js.length, done: js.filter(j => j.state === 'done').length, bad: js.filter(j => j.state === 'error' || j.state === 'cancelled').length,
  live: js.filter(j => j.state === 'queued' || j.state === 'running').length});

function batchHTML(batch, js) {
  const c = count(js), {node: tree, name: top} = unwrap(build(js.map(j => ({path: j.path || j.filename, job: j}))));
  const title = top || `${js.length} files`;
  return `<div class="batch"><div class="hd"><span class="fi">${ic(FOLDER)}</span><div class="nm"><b>${esc(title)}</b>
      <small>${c.done} of ${c.total} done${c.bad ? ` · ${c.bad} failed or cancelled` : ''}${c.live ? ` · ${c.live} to go` : ''}</small></div>
      ${c.live ? `<button class="ghost" data-act="cancel-batch" data-batch="${esc(batch)}">Cancel the rest</button>` : ''}</div>
    <div class="bar"><i style="width:${Math.round(100 * (c.done + c.bad) / c.total)}%"></i></div>
    <div class="tree">${treeHTML(tree, {batch}, top ? top + '/' : '')}</div></div>`}

// the order of the tree: at each level folders first, then files, each by name
function treeOrder(a, b) {const x = a.split('/'), y = b.split('/');
  for (let i = 0; ; i++) {const xf = i === x.length - 1, yf = i === y.length - 1;
    if (xf !== yf) return xf ? 1 : -1;
    const c = x[i].localeCompare(y[i]); if (c || xf) return c}}

// path list → nested {dirs: {name: node}, files: [item]}
function build(items) {const root = {dirs: {}, files: []};
  for (const it of items) {const parts = it.path.split('/'); let n = root;
    for (const p of parts.slice(0, -1)) n = n.dirs[p] ||= {dirs: {}, files: []};
    n.files.push({...it, name: parts[parts.length - 1]})}
  return root}

// a single top folder holding everything: show its contents, its name goes in the heading
function unwrap(root) {const names = Object.keys(root.dirs);
  return !root.files.length && names.length === 1 ? {node: root.dirs[names[0]], name: names[0]} : {node: root, name: null}}

function all(node) {return [...node.files, ...Object.values(node.dirs).flatMap(all)]}

function treeHTML(node, opts, prefix = '') {
  const dirs = Object.entries(node.dirs).sort(([a], [b]) => a.localeCompare(b));
  const files = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
  return `<ul>${dirs.map(([name, sub]) => {const key = (opts.batch || 'pv') + '/' + prefix + name, items = all(sub);
      const sum = opts.preview ? `${items.length} file${items.length === 1 ? '' : 's'} · ${mb(items.reduce((n, i) => n + i.bytes, 0))}`
        : (c => `${c.done}/${c.total} done${c.bad ? ` · ${c.bad} failed` : ''}${c.live ? ` · ${c.live} to go` : ''}`)(count(items.map(i => i.job)));
      const st = opts.preview ? '' : (c => c.bad ? 'bad' : c.live ? 'live' : 'ok')(count(items.map(i => i.job)));
      const box = opts.preview ? `<input type="checkbox" class="pick" checked data-pd="${esc(prefix + name + '/')}" title="Add this folder">` : '';
      return `<li class="dir"><details${CLOSED.has(key) ? '' : ' open'} data-dir="${esc(key)}"><summary>${box}${ic(FOLDER)}<b>${esc(name)}</b><small class="${st}">${sum}</small></summary>
        ${treeHTML(sub, opts, prefix + name + '/')}</details></li>`}).join('')}
    ${files.map(f => opts.preview ? `<li class="file"><input type="checkbox" class="pick" checked data-p="${esc(f.path)}" title="Add this file">${ic(I.file)}<span>${esc(f.name)}</span><small>${mb(f.bytes)}</small></li>`
      : `<li class="file"><div class="row" data-open="${f.job.id}">${ic(I.file)}<span>${esc(f.name)}</span>${badge(f.job)}${verdict(f.job)}<small class="det1">${esc(line(f.job))}</small></div>
         ${OPEN.has(f.job.id) ? card(f.job) : ''}</li>`).join('')}</ul>`}

const mb = n => n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
const badge = j => `<span class="badge ${j.state}">${j.state === 'queued' ? (j.ahead ? `Queued · ${j.ahead} ahead` : 'Starting…') : ({running: 'Working…', done: 'Done', error: 'Failed', cancelled: 'Cancelled'}[j.state] || esc(j.state))}</span>`;
// the source's quality after its ingest (read-only): the model's verdict and scores, and what the ingest produced
const CRIT = [['relevance', 'Relevance'], ['novelty', 'Novelty'], ['specificity', 'Specificity'], ['reliability', 'Reliability'], ['text_quality', 'Text quality']];
const qa = j => ((j.result || {}).assessment || {});
const verdict = j => {const m = qa(j).model_assessment || {}; return m.verdict ? `<span class="vd ${m.verdict}" title="${esc(m.summary || '')}">${m.verdict}</span>` : ''};
function quality(j) {const a = qa(j), m = a.model_assessment, s = a.signals;
  if (!m || !s) return '';
  const scores = m.missing ? '<p class="det">The model gave no assessment for this source.</p>'
    : `<div class="scores">${CRIT.map(([k, label]) => {const c = m[k] || {}; return `<span title="${esc(c.why || '')}"><b>${c.score ?? '?'}</b>${label}</span>`}).join('')}</div>`;
  return `<div class="qa"><div class="qh"><b>Source quality</b>${verdict(j)}<small>the model's judgement, recorded only; it changes nothing</small></div>
    ${m.summary ? `<p class="det">${esc(m.summary)}</p>` : ''}${scores}
    <p class="det">Measured: ${s.citations} citations (${s.citations_per_10k_chars} per 10,000 characters) on ${s.pages_citing} pages; ${s.pages_created} pages created, ${s.pages_updated} updated.</p></div>`}

const line = j => j.error || (j.state === 'queued' ? '' : ((j.log || []).slice(-1)[0] || {}).detail || '');

function card(j) {if (j.steps) STEPS = j.steps; const at = STEPS.indexOf(j.step), bad = j.state === 'error' || j.state === 'cancelled';
  const last = (j.log || []).slice(-1)[0];
  const btn = (label, act, extra) => `<button class="ghost" data-act="${act}" data-job="${j.id}" ${extra}>${label}</button>`;
  return `<div class="job" id="job-${j.id}"><div class="hd"><span class="fi">${ic(I.file)}</span><div class="nm"><b>${esc(j.filename)}</b><small>${j.bytes ? mb(j.bytes) : ''}${j.path && j.path.includes('/') ? ' · ' + esc(j.path) : ''}</small></div>
    ${badge(j)}</div>
   <ol class="stepper">${STEPS.map((s, i) => `<li class="${bad && i === Math.max(at, 0) ? 'err' : (i < at || j.state === 'done' ? 'done' : (i === at ? 'now' : ''))}">${STEP_LABEL[s] || s}</li>`).join('')}</ol>
   ${j.error ? `<p class="det err">${esc(j.error)}</p>` : (j.state === 'queued' ? `<p class="det">Waiting: files are ingested one by one (the model reads each one and updates the wiki).${j.ahead ? ` ${j.ahead} before this one.` : ''}</p>` : (last ? `<p class="det">${esc(last.detail)}</p>` : ''))}
   ${j.state === 'done' ? quality(j) : ''}
   <div class="acts">${j.state === 'queued' ? btn('Remove from queue', 'cancel', 'data-rm="0"') : j.state === 'running' ? btn('Cancel', 'cancel', 'data-rm="0"') + btn('Cancel and remove file', 'cancel', 'data-rm="1"') :
     (j.source_id && !j.removed ? btn('Remove from knowledge base', 'remove', `data-src="${j.source_id}"`) : (j.removed ? '<span class="empty">removed</span>' : ''))}</div>
   ${(j.log || []).length ? `<details${OPEN.has('log/' + j.id) ? ' open' : ''} data-log="${j.id}"><summary>Details</summary><pre data-job="${j.id}">${(j.log || []).map(l => `${l.at} ${l.step}: ${esc(l.detail)}`).join('\n')}</pre></details>` : ''}</div>`}

async function onJobsClick(e) {
  const b = e.target.closest('button[data-act]');
  if (b) {const a = b.dataset.act;
    if (a === 'cancel') return cancelJob(b.dataset.job, b.dataset.rm === '1');
    if (a === 'remove') return removeSrc(b.dataset.job, b.dataset.src);
    if (a === 'cancel-batch') return cancelBatch(b.dataset.batch)}
  const row = e.target.closest('[data-open]');
  if (row) {const id = row.dataset.open; OPEN.has(id) ? OPEN.delete(id) : OPEN.add(id); return render()}
  const sum = e.target.closest('summary'); if (!sum) return;
  const det = sum.parentElement;
  setTimeout(() => {  // after the browser toggled it
    if (det.dataset.dir) det.open ? CLOSED.delete(det.dataset.dir) : CLOSED.add(det.dataset.dir);
    if (det.dataset.log) det.open ? OPEN.add('log/' + det.dataset.log) : OPEN.delete('log/' + det.dataset.log)})}

async function cancelJob(id, rm) {if (rm && !confirm('Stop and delete this file from the knowledge base?')) return;
  await api('/api/jobs/' + id + '/cancel', {method: 'POST', body: JSON.stringify({remove: rm})}).catch(e => alert(e.message)); refresh()}
async function cancelBatch(batch) {const left = [...JOBS.values()].filter(j => j.batch === batch && (j.state === 'queued' || j.state === 'running'));
  if (!confirm(`Stop the ${left.length} file${left.length === 1 ? '' : 's'} not ingested yet? Files already done stay in the knowledge base.`)) return;
  for (const j of left) await api('/api/jobs/' + j.id + '/cancel', {method: 'POST', body: JSON.stringify({remove: false})}).catch(() => {});
  refresh()}
async function removeSrc(jid, sid) {if (!confirm('Delete this source and its pages from the knowledge base? (one commit, can be undone with Git)')) return;
  try {await api('/api/sources/' + sid + '/remove', {method: 'POST'}); refresh()} catch (e) {alert(e.message)}}
