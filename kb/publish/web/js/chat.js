// Discussions: the chat view, asking a question, the live view of the answer, attachments.
import {$, esc, ic, I, MARK, topbar} from './ui.js';
import {api} from './api.js';
import {mdl} from './markdown.js';
import {traceHtml, markMore, initTrace} from './trace.js';
import {loadSessions, mark} from './shell.js';

let S = null;       // the open discussion ({id, topic, turns}), null on "New discussion"
let BUSY = false;   // a question is being answered (one at a time)
// the question being answered lives in PEND, not only in the DOM: leaving the chat and coming back shows it again
let PEND = null;
let IM = [];        // screenshots attached to the next question
// follow new content only while the reader is at the bottom; scrolling up to read stops it, scrolling back down resumes it
let AT_END = true;

export const currentId = () => S && S.id;
export const isBusy = () => BUSY;

export async function delSession(id) {if (!confirm('Delete this discussion? Wiki pages saved from it stay.')) return;
  try {await api('/api/sessions/' + id + '/delete', {method: 'POST'})} catch (e) {return alert(e.message)}
  if (S && S.id === id) {S = null; if (location.hash.slice(1)) location.hash = ''; else openChat(null)} loadSessions()}

export function openChat(s, keep) {S = s; mark(s ? 's=' + s.id : 'new'); const top = keep && $('#scroll') ? $('#scroll').scrollTop : 0; if (!keep) AT_END = true;
  $('#main').innerHTML = topbar(s ? esc(s.topic) : 'New discussion', s ? `<button class="ghost" id="save" title="Save this discussion as a wiki page">${ic(I.save)}<span>Save as wiki page</span></button><button class="icon" id="delc" title="Delete this discussion">${ic(I.trash)}</button>` : '') +
   `<div class="scroll" id="scroll"><div class="col" id="turns"></div></div>
   <div class="cwrap"><div class="composer"><div class="imgs" id="imgs"></div>
     <textarea id="q" rows="1" placeholder="Ask anything about the knowledge base…"></textarea>
     <div class="tools"><button class="icon" id="att" title="Attach a screenshot (or paste one with Ctrl+V)">${ic(I.clip)}</button><input type="file" id="img" accept="image/*" multiple hidden>
       <button class="pill" id="code" aria-pressed="false" title="Also read the code repositories">${ic(I.code)}Code</button><span class="sp"></span>
       <button class="send" id="ask" title="Send (Enter)" disabled>${ic(I.send, 2.2)}</button></div></div>
     <p class="hint">Answers use only the knowledge base and cite their sources. Shift+Enter for a new line.</p></div>`;
  renderTurns(); if (keep && !AT_END) $('#scroll').scrollTop = top; watchScroll();
  if (s) $('#delc').onclick = () => delSession(S.id);
  if (s) $('#save').onclick = async () => {const b = $('#save'); b.disabled = true; try {const r = await api('/api/sessions/' + S.id + '/save', {method: 'POST'}); b.innerHTML = ic('M5 12l5 5 9-10', 2) + '<span>Saved</span>'; b.title = r.saved}
    catch (e) {alert(e.message); b.disabled = false}};
  const q = $('#q'), ask = $('#ask'), fit = () => {q.style.height = 'auto'; q.style.height = q.scrollHeight + 'px'; ask.disabled = BUSY ? !pendHere() : !q.value.trim()};
  q.oninput = fit; q.onkeydown = e => {if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {e.preventDefault(); if (!BUSY) go()}};
  $('#code').onclick = e => {const b = e.currentTarget; b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') !== 'true')};
  $('#att').onclick = () => $('#img').click(); $('#img').onchange = () => {addImgs([...$('#img').files]); $('#img').value = ''};
  q.onpaste = e => {const fs = [...((e.clipboardData || {}).files || [])]; if (fs.length) {e.preventDefault(); addImgs(fs)}};
  ask.onclick = go; IM = []; showImgs(); busyUi(BUSY); q.focus()}

function addImgs(fs) {for (const f of fs) {if (!f.type.startsWith('image/')) continue; const r = new FileReader(); r.onload = () => {IM.push({name: f.name || 'screenshot.png', data: r.result}); showImgs()}; r.readAsDataURL(f)}}
function showImgs() {const el = $('#imgs'); if (!el) return; el.innerHTML = IM.map((x, k) => `<span><img src="${x.data}" alt="">${esc(x.name)}<b data-rm="${k}" title="Remove">×</b></span>`).join('')}
function userMsg(q, imgs) {return `<div class="msg user"><div class="bubble">${esc(q)}</div>${imgs && imgs.length ? `<div class="att">📎 ${imgs.map(esc).join(', ')}</div>` : ''}</div>`}
function checkHtml(c) {if (!c) return ''; const b = c.broken || [];
  if (b.length) return `<span class="badc" title="${esc(b.join('\n'))}" onclick="alert(this.title)">⚠ ${b.length} citation${b.length > 1 ? 's' : ''} not found</span>`;
  return c.ok ? `<span class="okc" title="Every link and page/time reference was found in the wiki and its sources">✓ ${c.ok} citation${c.ok > 1 ? 's' : ''} checked</span>` : ''}
function botMsg(t) {const md = t.markdown || (t.sentences || []).map(s => s.text).join(' ');
  const pr = t.pages_read || [], meta = [t.stopped ? '⏹ stopped' : '', t.session === 'continued' ? 'same session' : t.session === 'resumed' ? 'session resumed' : '', t.seconds ? `${t.seconds} s` : '', t.credits != null ? `${Number(t.credits).toFixed(2)} AI credits` : '', t.tools_used && t.tools_used.length ? `tools: ${t.tools_used.map(esc).join(', ')}` : ''].filter(Boolean);
  return `<div class="msg bot">${MARK}<div class="body">${traceHtml(t.trace, false)}<div class="md ${t.not_found ? 'nf' : ''}">${t.not_found && !md.trim() ? '<p>No answer found in the knowledge base. Try other words, or add a source that covers it.</p>' : mdl(md)}</div>
   <div class="meta">${checkHtml(t.check)}${meta.map(x => `<span>${x}</span>`).join('')}${pr.length ? `<details><summary>${pr.length} page${pr.length > 1 ? 's' : ''} read ▾</summary><div>${pr.map(p => `<a class="wl" href="#wiki/w:${encodeURIComponent(String(p).replace(/^.*\//, '').replace(/\.md$/, ''))}">${esc(String(p).replace(/^.*\//, '').replace(/\.md$/, ''))}</a>`).join(' ')}</div></details>` : ''}</div></div></div>`}

const scrollEnd = force => {const s = $('#scroll'); if (!s) return; if (force) AT_END = true; if (AT_END) s.scrollTop = s.scrollHeight};
function watchScroll() {const s = $('#scroll'); if (s) s.onscroll = () => {AT_END = s.scrollTop + s.clientHeight >= s.scrollHeight - 60}}

const pendHere = () => !!PEND && (PEND.sid ? !!S && S.id === PEND.sid : !S);
const liveTrace = () => traceHtml(PEND.ev, true, 'Working… ' + PEND.ev.length + ' step' + (PEND.ev.length > 1 ? 's' : ''), k => PEND.open.has(k));
const pendHtml = () => userMsg(PEND.q, PEND.imgs) + `<div class="msg bot" id="pending">${MARK}<div class="body"><div class="typing"><i></i><i></i><i></i> <span id="pnow">${esc(PEND.now)}</span></div><div id="ptrace">${liveTrace()}</div></div></div>`;

function renderTurns() {const el = $('#turns'), p = pendHere(), sc = $('#scroll'), top = sc ? sc.scrollTop : 0;
  if (!p && (!S || !S.turns.length)) {el.className = 'hero'; el.innerHTML = `${MARK}<h2>${S ? esc(S.topic) : 'What would you like to know?'}</h2>
    <p>Ask a question. The assistant reads the wiki (and the code, Jira or your screenshots when useful) and cites every source it uses.</p>
    <div class="chips">${['What are the main topics in the wiki?', 'Which sources contradict each other?', 'Summarise the most recent source'].map(x => `<button>${x}</button>`).join('')}</div>`;
    el.querySelectorAll('.chips button').forEach(b => b.onclick = () => {$('#q').value = b.textContent; $('#q').oninput(); go()}); return}
  el.className = 'col'; el.innerHTML = (S ? S.turns.map(t => userMsg(t.question, t.images) + botMsg(t)).join('') : '') + (p ? pendHtml() : ''); markMore(el);
  if (AT_END) scrollEnd(); else if (sc) sc.scrollTop = top}  // a reader scrolled up keeps their place when the answer lands

async function stopAnswer() {if (!BUSY || !pendHere() || !PEND.sid) return; const p = $('#pnow'); if (p) p.textContent = 'Stopping…';
  try {await api('/api/sessions/' + PEND.sid + '/stop', {method: 'POST'})} catch (e) {if (p) p.textContent = e.message}}
function busyUi(on) {const b = $('#ask'); if (!b) return; const mine = on && pendHere(); b.disabled = on && !mine; b.classList.toggle('stop', mine);
  b.title = mine ? 'Stop (Esc)' : on ? 'Another discussion is still being answered' : 'Send (Enter)';
  b.innerHTML = mine ? '<svg class="i" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg>' : ic(I.send, 2.2);
  if (!on) $('#q').oninput()}

async function go() {if (BUSY) {if (pendHere()) stopAnswer(); return} const q = $('#q').value.trim(); if (!q) return;
  const code = $('#code').getAttribute('aria-pressed') === 'true', imgs = IM; IM = []; showImgs(); $('#q').value = ''; $('#q').style.height = 'auto';
  BUSY = true; PEND = {sid: S ? S.id : null, q, imgs: imgs.map(x => x.name), now: `Reading the wiki${code ? ' and the code' : ''}…`, ev: [], open: new Set()}; busyUi(true);
  const el = $('#turns'); if (el.className === 'hero') {el.className = 'col'; el.innerHTML = ''}
  el.insertAdjacentHTML('beforeend', pendHtml()); scrollEnd(true);
  let live = true, started = false, since = 0, seen = '';
  const tick = async () => {if (!live) return; if (!PEND.sid) return setTimeout(tick, 700);
    // the last event is fetched again: a streamed thought keeps growing on the server after we first saw it
    const from = started ? Math.max(0, since - 1) : 0;
    try {const r = await api(`/api/sessions/${PEND.sid}/progress?since=${from}`); if (!live) return;
      if (r.running && !started) {started = true; PEND.ev = []}
      if (started && r.events.length) {PEND.ev = PEND.ev.slice(0, from).concat(r.events); since = r.total; const l = PEND.ev[PEND.ev.length - 1];
        const key = since + ':' + String(l.text).length; if (key === seen) throw 0; seen = key;  // nothing new: no redraw
        PEND.now = l.kind === 'thinking' ? 'Thinking…' : l.kind === 'intent' ? l.text : 'Reading ' + String(l.text).replace(/^\S+\s*/, '').replace(/^.*[\\/]/, '') + '…';
        const pt = $('#ptrace'); if (pt) {pt.innerHTML = liveTrace(); markMore(pt); $('#pnow').textContent = PEND.now; scrollEnd()}}}
    catch (e) {} if (live) setTimeout(tick, 800)};
  tick();
  try {let sess = S;
    if (!sess) {sess = await api('/api/sessions', {method: 'POST', body: JSON.stringify({topic: q.replace(/\s+/g, ' ').slice(0, 80)})}); PEND.sid = sess.id;
      if (!S && $('#turns')) {S = sess; history.replaceState(null, '', '#s=' + S.id); $('.top .ttl').textContent = S.topic} loadSessions()}  // still on this view: it becomes the discussion
    const t = await api('/api/sessions/' + sess.id + '/ask', {method: 'POST', body: JSON.stringify({question: q, images: imgs, focus: code ? 'code' : 'wiki'})});
    sess.turns.push(t); live = false; BUSY = false; PEND = null;
    if (S && S.id === sess.id && $('#turns')) {if (S !== sess) S.turns.push(t); if (!$('#save')) openChat(S, true); else renderTurns()} loadSessions()}  // reopened meanwhile: S is a fresh copy
  catch (e) {const p = pendHere() && $('#pending'); if (p) {p.querySelector('.body').innerHTML = `<p class="err">${esc(e.message)}</p>`; if ($('#q') && !$('#q').value) {$('#q').value = q; $('#q').oninput()}}}
  finally {live = false; BUSY = false; PEND = null; busyUi(false); if ($('#q')) $('#q').focus()}}

export function initChat() {
  initTrace((k, open) => {if (PEND) PEND.open[open ? 'add' : 'delete'](k)});
  document.addEventListener('keydown', e => {if (e.key === 'Escape' && BUSY) stopAnswer()});
  document.addEventListener('click', e => {const b = e.target.closest('#imgs [data-rm]'); if (b) {IM.splice(+b.dataset.rm, 1); showImgs()}})}
