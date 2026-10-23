// Sources: every ingested source with its quality assessment (the model's scores and what the ingest produced).
// Choose sources (one, several, everything shown) and assess them again: with the model (AI credits per source), or
// only measure again (free; the model's judgement is kept). Useful after changing the criteria or the prompt: an
// assessment made with an older prompt is marked. Read-only for the wiki: nothing is filtered or skipped by it.
import {$, esc, topbar, loader} from './ui.js';
import {api} from './api.js';
import {mark} from './shell.js';

const CRIT = [['relevance', 'rel', 'Relevance'], ['novelty', 'nov', 'Novelty'], ['specificity', 'spe', 'Specificity'],
  ['reliability', 'rlb', 'Reliability'], ['text_quality', 'txt', 'Text quality']];
const FILTERS = [['all', 'All'], ['core', 'Core'], ['useful', 'Useful'], ['marginal', 'Marginal'], ['noise', 'Noise'],
  ['none', 'No judgement'], ['old', 'Older prompt']];
const SEL = new Set(), OPEN = new Set();
let D = null, FILTER = 'all', FIND = '', SORT = ['assessed', -1], POLL = null, LAST = null;  // LAST: for shift-click ranges

export async function openSources() {mark('sources');
  $('#main').innerHTML = topbar('Sources') + `<div class="scroll"><div class="col wider" id="srcv">${loader('Reading the sources…')}</div></div>`;
  await load()}

async function load() {clearTimeout(POLL);
  try {D = await api('/api/sources/quality')} catch (e) {const v = $('#srcv'); if (v) v.innerHTML = `<p class="err">${esc(e.message)}</p>`; return}
  const ids = new Set(D.sources.map(s => s.id)); [...SEL].forEach(i => ids.has(i) || SEL.delete(i));
  render();
  if (running()) POLL = setTimeout(() => {if ($('#srcv')) load()}, 2000)}

const running = () => D && D.run && ['queued', 'running'].includes(D.run.state);
const m = s => (s.assessment || {}).model_assessment || {};
const sig = s => (s.assessment || {}).signals || {};
const current = s => {const a = s.assessment; return a && a.prompt ? D.prompts[a.mode === 'ingest' ? 'ingest' : 'backfill'] : null};
const old = s => {const a = s.assessment; return !!(a && a.prompt && a.prompt !== current(s))};

function shown() {
  const f = FIND.toLowerCase();
  const keep = s => (FILTER === 'all' || (FILTER === 'none' ? !m(s).verdict : FILTER === 'old' ? old(s) : m(s).verdict === FILTER))
    && (!f || (s.title + ' ' + s.ref).toLowerCase().includes(f));
  const [k, dir] = SORT, order = ['core', 'useful', 'marginal', 'noise'];
  const val = s => k === 'title' ? s.title.toLowerCase() : k === 'verdict' ? (order.indexOf(m(s).verdict) + 1 || 9)
    : k === 'cit' ? (sig(s).citations_per_10k_chars ?? -1) : k === 'pages' ? (sig(s).pages_citing ?? -1)
    : k === 'assessed' ? ((s.assessment || {}).assessed || '') : ((m(s)[k] || {}).score ?? -1);
  return D.sources.filter(keep).sort((a, b) => {const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * dir})}

function render() {const v = $('#srcv'); if (!v || !D) return;
  const list = shown(), n = D.sources.length, judged = D.sources.filter(s => m(s).verdict).length;
  const count = k => k === 'all' ? n : D.sources.filter(s => k === 'none' ? !m(s).verdict : k === 'old' ? old(s) : m(s).verdict === k).length;
  const allOn = list.length && list.every(s => SEL.has(s.id));
  const th = (k, label, title = '') => `<th data-sort="${k}" title="${esc(title)}" class="${SORT[0] === k ? (SORT[1] > 0 ? 'asc' : 'desc') : ''}">${label}</th>`;
  v.innerHTML = `<div class="pagehead"><div class="kicker">Sources</div><h2>Quality of the sources</h2>
    <p>${n} sources in the wiki, ${judged} judged by the model. Scores 1–5 are the model's judgement; citations and pages are measured. Nothing is filtered by them: they are here so you can see how they behave.</p></div>
    ${runHTML()}
    <div class="qbar"><div class="flt">${FILTERS.map(([k, l]) => `<button data-f="${k}" class="${FILTER === k ? 'on' : ''}">${l} <small>${count(k)}</small></button>`).join('')}</div>
      <input id="qfind" placeholder="Find a source…" value="${esc(FIND)}"></div>
    <div class="selbar${SEL.size ? ' on' : ''}"><b>${SEL.size ? SEL.size + ' selected' : 'Select sources (Shift for a range)'}</b>
      <button class="pri" data-a="model" ${!SEL.size || running() ? 'disabled' : ''} title="The model reads each source again in a read-only session (AI credits per source)">Assess with the model</button>
      <button class="ghost" data-a="measure" ${!SEL.size || running() ? 'disabled' : ''} title="Count citations and pages again; no AI credits; the model's judgement is kept">Measure again</button>
      ${SEL.size ? '<button class="ghost" data-a="clear">Clear</button>' : ''}
      <small>Prompt now: ${esc(D.prompts.backfill)}${D.prompts.ingest !== D.prompts.backfill ? ` (at ingest: ${esc(D.prompts.ingest)})` : ''}</small></div>
    ${list.length ? `<div class="srcs"><table><thead><tr><th class="ck"><input type="checkbox" data-all ${allOn ? 'checked' : ''} title="Select everything shown"></th>
      ${th('title', 'Source')}${th('verdict', 'Verdict')}${CRIT.map(([k, a, l]) => th(k, a, l)).join('')}${th('cit', 'cit/10k', 'Citations of the source per 10,000 characters (measured)')}${th('pages', 'pages', 'Wiki pages citing the source (measured)')}${th('assessed', 'Assessed')}</tr></thead>
      <tbody>${list.map(row).join('')}</tbody></table></div>` : '<p class="empty">No source matches.</p>'}`}

function row(s) {const a = s.assessment, j = m(s), g = sig(s), on = SEL.has(s.id);
  const when = a ? `${esc((a.assessed || '').slice(0, 10))} <small>${a.mode === 'backfill' ? 'again' : 'at ingest'}</small>${old(s) ? ' <span class="oldp" title="Judged with an older prompt">older prompt</span>' : ''}` : '<small>never</small>';
  const main = `<tr class="${on ? 'sel' : ''}" data-row="${s.id}"><td class="ck"><input type="checkbox" data-id="${s.id}" ${on ? 'checked' : ''}></td>
    <td class="tt"><a href="#wiki/p:sources/${esc(s.slug)}.md" title="Open the source page">${esc(s.title)}</a><small>${esc(s.ref)}</small></td>
    <td>${j.verdict ? `<span class="vd ${j.verdict}">${j.verdict}</span>` : '<small>–</small>'}</td>
    ${CRIT.map(([k]) => `<td class="n" title="${esc((j[k] || {}).why || '')}">${(j[k] || {}).score ?? ''}</td>`).join('')}
    <td class="n">${g.citations_per_10k_chars ?? ''}</td><td class="n">${g.pages_citing ?? ''}</td><td class="wh">${when}</td></tr>`;
  if (!OPEN.has(s.id)) return main;
  const why = j.verdict ? `${j.summary ? `<p>${esc(j.summary)}</p>` : ''}<ul>${CRIT.map(([k, , l]) => `<li><b>${l} ${(j[k] || {}).score ?? '?'}</b> ${esc((j[k] || {}).why || '')}</li>`).join('')}</ul>`
    : `<p>${j.invalid ? 'The model\'s answer could not be read: ' + esc(j.invalid) : a && a.reply_end ? 'The model answered, but without a readable assessment.' : 'No judgement by the model yet.'}</p>${a && a.reply_end ? `<pre class="reply">${esc(a.reply_end)}</pre>` : ''}`;
  const notes = ['pages_needing_ocr', 'slides_without_text', 'hidden_slides', 'cut_sheets'].filter(k => g[k]).map(k => `${k.replace(/_/g, ' ')}: ${g[k].join(', ')}`);
  return main + `<tr class="why"><td></td><td colspan="10">${why}<p class="meas">Measured: ${g.citations ?? '?'} citations on ${g.pages_citing ?? '?'} pages, ${(g.chars ?? 0).toLocaleString()} characters${notes.length ? '; ' + esc(notes.join('; ')) : ''}.${a && a.model ? ` Model: ${esc(a.model)}.` : ''}${a && a.prompt ? ` Prompt ${esc(a.prompt)}.` : ''}</p></td></tr>`}

function runHTML() {const r = D.run; if (!r) return '';
  const live = running(), last = (r.log || []).slice(-1)[0], pct = r.total ? Math.round(100 * r.done / r.total) : 0;
  const head = live ? `${r.model ? 'Assessing with the model' : 'Measuring again'}: ${r.done} of ${r.total}`
    : {done: `Done: ${r.done} of ${r.total} ${r.model ? 'assessed' : 'measured'}`, cancelled: `Stopped after ${r.done} of ${r.total}`, error: 'The assessment failed'}[r.state] || r.state;
  return `<div class="job run ${r.state}"><div class="hd"><div class="nm"><b>${esc(head)}</b><small>${esc(r.error || (last ? last.detail : 'starting…'))}</small></div>
    ${live ? '<button class="ghost" data-a="cancel">Cancel</button>' : '<button class="ghost" data-a="dismiss">Close</button>'}</div>
    <div class="bar"><i style="width:${pct}%"></i></div></div>`}

async function act(a) {
  if (a === 'clear') {SEL.clear(); return render()}
  if (a === 'dismiss') {D.run = null; return render()}
  if (a === 'cancel') {await api('/api/sources/assess/cancel', {method: 'POST'}).catch(e => alert(e.message)); return load()}
  const ids = [...SEL];
  if (a === 'model' && !confirm(`The model reads ${ids.length} source${ids.length === 1 ? '' : 's'} again, one session each: this uses AI credits for every source. Continue?`)) return;
  try {D.run = await api('/api/sources/assess', {method: 'POST', body: JSON.stringify({ids, model: a === 'model'})})} catch (e) {return alert(e.message)}
  render(); load()}

document.addEventListener('click', e => {const v = $('#srcv'); if (!v || !v.contains(e.target)) return;
  const b = e.target.closest('[data-a]'); if (b) return act(b.dataset.a);
  const f = e.target.closest('[data-f]'); if (f) {FILTER = f.dataset.f; return render()}
  const h = e.target.closest('th[data-sort]'); if (h) {const k = h.dataset.sort; SORT = [k, SORT[0] === k ? -SORT[1] : (k === 'title' || k === 'verdict' ? 1 : -1)]; return render()}
  if (e.target.matches('input[data-all]')) {shown().forEach(s => e.target.checked ? SEL.add(s.id) : SEL.delete(s.id)); return render()}
  if (e.target.matches('input[data-id]')) {const id = e.target.dataset.id, ids = shown().map(s => s.id), on = e.target.checked;
    const span = e.shiftKey && LAST && ids.includes(LAST) ? ids.slice(Math.min(ids.indexOf(LAST), ids.indexOf(id)), Math.max(ids.indexOf(LAST), ids.indexOf(id)) + 1) : [id];
    span.forEach(i => on ? SEL.add(i) : SEL.delete(i)); LAST = id; return render()}
  if (e.target.closest('a')) return;
  const r = e.target.closest('tr[data-row]'); if (r) {const id = r.dataset.row; OPEN.has(id) ? OPEN.delete(id) : OPEN.add(id); render()}});
document.addEventListener('input', e => {if (e.target.id !== 'qfind') return; FIND = e.target.value;
  const pos = e.target.selectionStart; render(); const q = $('#qfind'); q.focus(); q.setSelectionRange(pos, pos)});
