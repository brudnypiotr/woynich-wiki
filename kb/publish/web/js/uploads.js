// Add sources: upload files, follow each through the ingest steps, cancel or remove.
import {$, esc, ic, I, topbar} from './ui.js';
import {api} from './api.js';
import {mark} from './shell.js';

let STEPS = ['saved', 'extracted', 'writing', 'checking', 'verify', 'done'];  // the server sends its own list with every job
const STEP_LABEL = {saved: 'Saved', extracted: 'Text extracted', writing: 'Writing wiki', checking: 'Checking', verify: 'Citations verified', done: 'Done'};

export function openAdd() {mark('add');
  $('#main').innerHTML = topbar('Add sources') + `<div class="scroll"><div class="col wide">
   <div class="pagehead"><div class="kicker">Add sources</div><h2>Feed the knowledge base</h2>
   <p>Each file is kept unchanged. The model reads it, writes or updates the wiki pages, then every citation and link is checked and the change is committed.</p></div>
   <div class="drop" id="drop"><div class="up">${ic(I.up)}</div><b>Drop files here</b><span>or click to choose from your computer</span>
     <div class="types"><em>PDF</em><em>Word</em><em>E-mail .eml</em><em>Teams .vtt</em><em>Jira .jira.json</em><em>Text &amp; code</em></div>
     <input type="file" id="file" multiple hidden></div>
   <div class="how"><div><b><i>1</i>Saved</b>Original stored as-is, text extracted.</div><div><b><i>2</i>Written</b>The model updates topic, entity and source pages.</div><div><b><i>3</i>Checked</b>Citations verified, everything committed. Cancel any time.</div></div>
   <h3 class="sec">Recent uploads</h3><div id="jobs"><p class="empty">Nothing uploaded in this session yet.</p></div></div></div>`;
  const d = $('#drop'), f = $('#file'); d.onclick = e => {if (e.target !== f) f.click()}; f.onchange = () => {upload([...f.files]); f.value = ''};
  d.ondragover = e => {e.preventDefault(); d.classList.add('over')}; d.ondragleave = () => d.classList.remove('over');
  d.ondrop = e => {e.preventDefault(); d.classList.remove('over'); upload([...e.dataTransfer.files])};
  $('#jobs').onclick = e => {const b = e.target.closest('button[data-act]'); if (!b) return;
    if (b.dataset.act === 'cancel') cancelJob(b.dataset.job, b.dataset.rm === '1'); else if (b.dataset.act === 'remove') removeSrc(b.dataset.job, b.dataset.src)};
  api('/api/jobs').then(js => js.reverse().forEach(j => showJob(j)))}

async function upload(files) {for (const file of files) {const j = await api('/api/upload', {method: 'POST', headers: {'X-Filename': encodeURIComponent(file.name)}, body: file})
  .catch(e => ({id: 'x' + Math.random().toString(16).slice(2), error: e.message, filename: file.name, state: 'error', log: []})); showJob(j)}}

function showJob(j) {const box = $('#jobs'); if (!box) return; box.querySelector('.empty')?.remove();
  let el = document.getElementById('job-' + j.id); if (!el) {el = document.createElement('div'); el.className = 'job'; el.id = 'job-' + j.id; box.prepend(el)}
  const open = el.querySelector('details')?.open, pre = el.querySelector('pre'), top = pre ? pre.scrollTop : 0,
    atEnd = pre ? pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4 : false; if (j.steps) STEPS = j.steps; const at = STEPS.indexOf(j.step), bad = j.state === 'error' || j.state === 'cancelled';
  const last = (j.log || []).slice(-1)[0];
  const btn = (label, act, extra) => `<button class="ghost" data-act="${act}" data-job="${j.id}" ${extra}>${label}</button>`;
  el.innerHTML = `<div class="hd"><span class="fi">${ic(I.file)}</span><div class="nm"><b>${esc(j.filename)}</b><small>${j.bytes ? (j.bytes > 1e6 ? (j.bytes / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(j.bytes / 1024)) + ' KB') : ''}</small></div>
    <span class="badge ${j.state}">${j.state === 'queued' ? (j.ahead ? `Queued · ${j.ahead} ahead` : 'Starting…') : ({running: 'Working…', done: 'Done', error: 'Failed', cancelled: 'Cancelled'}[j.state] || esc(j.state))}</span></div>
   <ol class="stepper">${STEPS.map((s, i) => `<li class="${bad && i === Math.max(at, 0) ? 'err' : (i < at || j.state === 'done' ? 'done' : (i === at ? 'now' : ''))}">${STEP_LABEL[s] || s}</li>`).join('')}</ol>
   ${j.error ? `<p class="det err">${esc(j.error)}</p>` : (j.state === 'queued' ? `<p class="det">Waiting: files are ingested one by one (the model reads each one and updates the wiki).${j.ahead ? ` ${j.ahead} before this one.` : ''}</p>` : (last ? `<p class="det">${esc(last.detail)}</p>` : ''))}
   <div class="acts">${j.state === 'queued' ? btn('Remove from queue', 'cancel', 'data-rm="0"') : j.state === 'running' ? btn('Cancel', 'cancel', 'data-rm="0"') + btn('Cancel and remove file', 'cancel', 'data-rm="1"') :
     (j.source_id && !j.removed ? btn('Remove from knowledge base', 'remove', `data-src="${j.source_id}"`) : (j.removed ? '<span class="empty">removed</span>' : ''))}</div>
   ${(j.log || []).length ? `<details${open ? ' open' : ''}><summary>Details</summary><pre>${(j.log || []).map(l => `${l.at} ${l.step}: ${esc(l.detail)}`).join('\n')}</pre></details>` : ''}`;
  const np = el.querySelector('pre'); if (np && pre) np.scrollTop = atEnd ? np.scrollHeight : top;  // keep the reader's place in the log
  if (j.state === 'running' || j.state === 'queued') setTimeout(() => {if (document.getElementById('job-' + j.id)) api('/api/jobs/' + j.id).then(showJob).catch(() => {})}, j.state === 'queued' ? 4000 : 1500)}

async function cancelJob(id, rm) {if (rm && !confirm('Stop and delete this file from the knowledge base?')) return;
  await api('/api/jobs/' + id + '/cancel', {method: 'POST', body: JSON.stringify({remove: rm})}).catch(e => alert(e.message))}
async function removeSrc(jid, sid) {if (!confirm('Delete this source and its pages from the knowledge base? (one commit, can be undone with Git)')) return;
  try {await api('/api/sources/' + sid + '/remove', {method: 'POST'}); api('/api/jobs/' + jid).then(showJob)} catch (e) {alert(e.message)}}
