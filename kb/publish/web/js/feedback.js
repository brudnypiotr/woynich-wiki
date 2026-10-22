// Feedback: a bubble in the bottom right corner. The user writes what happened (screenshots with Ctrl+V), Luna asks a
// few short questions (at most two rounds) and writes a report, then a zip goes to the Desktop for the user to send.
// After a few days of use a small note above the bubble invites feedback (again two weeks later, or never).
import {esc} from './ui.js';
import {post} from './api.js';

const DAY = 864e5, LS = 'kb.feedback';
const store = {get() {try {return JSON.parse(localStorage.getItem(LS)) || {}} catch (e) {return {}}},
  set(v) {try {localStorage.setItem(LS, JSON.stringify({...store.get(), ...v}))} catch (e) {}}};

let S;  // {text, messages, shots, report, done, busy, result}
const fresh = () => ({text: '', messages: [], shots: [], report: null, done: false, busy: false, result: null, error: null});

export function initFeedback() {
  document.body.insertAdjacentHTML('beforeend', `<button class="fb-bubble" title="Send feedback" aria-label="Send feedback">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/></svg></button>
    <div class="fb-nudge" hidden><b>How is it going?</b><span>Something annoying, missing or great? Tell us in a minute.</span>
      <div><button class="pri" data-n="open">Give feedback</button><button class="ghost" data-n="later">Later</button><button class="ghost" data-n="never">Don't ask again</button></div></div>
    <section class="fb-panel" hidden aria-label="Feedback"><header><b>Feedback</b><button class="icon" data-f="close" title="Close">×</button></header><div class="fb-body"></div></section>`);
  S = fresh();
  document.querySelector('.fb-bubble').onclick = () => toggle();
  document.querySelector('[data-f=close]').onclick = () => toggle(false);
  document.querySelector('.fb-nudge').onclick = e => {const a = (e.target.closest('button') || {}).dataset?.n; if (!a) return;
    document.querySelector('.fb-nudge').hidden = true;
    if (a === 'open') toggle(true); else if (a === 'never') store.set({never: true}); else store.set({next: Date.now() + 14 * DAY})};
  nudge()}

// days on which the app was opened; the note shows after 3 such days, then every 2 weeks, unless "never"
function nudge() {const st = store.get(), today = new Date().toISOString().slice(0, 10);
  const days = [...new Set([...(st.days || []), today])].slice(-30); store.set({days});
  if (st.never || days.length < 3 || Date.now() < (st.next || 0)) return;
  setTimeout(() => {if (document.querySelector('.fb-panel').hidden) {document.querySelector('.fb-nudge').hidden = false; store.set({next: Date.now() + 14 * DAY})}}, 20000)}

function toggle(open) {const p = document.querySelector('.fb-panel'); p.hidden = open === undefined ? !p.hidden : !open;
  document.querySelector('.fb-nudge').hidden = true; if (!p.hidden) draw()}

function draw() {const b = document.querySelector('.fb-body');
  if (S.result) {b.innerHTML = `<p><b>Saved on your Desktop:</b><br><code>${esc(S.result.path.split(/[\\/]/).pop())}</code></p>
      <p class="d">Send this file to the app's author in Teams (or e-mail). It holds your discussions and the wiki: company content, keep it inside the company.</p>
      <div class="btns"><button class="pri" data-f="reveal">Show in folder</button><button class="ghost" data-f="copy">Copy message for Teams</button><button class="ghost" data-f="new">New feedback</button></div><p class="fb-note"></p>`;
    return bind(b)}
  const chat = S.messages.map(m => `<div class="fb-msg ${m.role}">${esc(m.text)}</div>`).join('');
  const shots = S.shots.map((u, i) => `<span class="fb-shot"><img src="${u}" alt=""><button data-del="${i}" title="Remove">×</button></span>`).join('');
  const rep = S.report ? `<div class="fb-report"><b>${esc(S.report.title || 'Feedback')}</b><small>${esc(S.report.kind || '')}${S.report.where ? ' · ' + esc(S.report.where) : ''}</small>
      ${S.report.what_happened ? `<p>${esc(S.report.what_happened)}</p>` : ''}</div>` : '';
  const intro = !S.messages.length ? `<p class="d">What happened, what is missing, what would help? Paste screenshots with Ctrl+V. Luna asks a couple of quick questions, then prepares a file for you to send.</p>` : '';
  const input = S.done ? '' : `<textarea rows="${S.messages.length ? 2 : 4}" placeholder="${S.messages.length ? 'Your answer…' : 'Describe it in your own words…'}"></textarea>
      <div class="btns"><button class="pri" data-f="send"${S.busy ? ' disabled' : ''}>${S.messages.length ? 'Answer' : 'Send'}</button>
      ${S.messages.length ? `<button class="ghost" data-f="finish"${S.busy ? ' disabled' : ''}>That's all</button>` : ''}</div>`;
  const pack = S.done || S.error ? `<p class="d">The file will contain: this report and conversation, screenshots, diagnostics (no keys or passwords), the app log, your discussions and the wiki as it is now.</p>
      <div class="btns"><button class="pri" data-f="package"${S.busy ? ' disabled' : ''}>Create feedback file</button></div>` : '';
  b.innerHTML = intro + `<div class="fb-chat">${chat}${S.busy ? '<div class="fb-msg assistant fb-typing">Luna is thinking…</div>' : ''}</div>` + rep
    + (S.error ? `<p class="errmsg">${esc(S.error)} You can still create the file with your own words.</p>` : '')
    + (shots ? `<div class="fb-shots">${shots}</div>` : '') + input + pack + '<p class="fb-note"></p>';
  bind(b); const t = b.querySelector('textarea'); if (t) {t.value = S.draft || ''; t.oninput = () => S.draft = t.value; t.focus()}
  b.scrollTop = b.scrollHeight}

async function ask(finish) {if (S.busy) return;
  const t = document.querySelector('.fb-body textarea'), v = (t && t.value.trim()) || '';
  if (!v && !finish) return t && t.focus();
  if (v) {S.messages.push({role: 'user', text: v}); if (!S.text) S.text = v}
  if (finish) S.messages.push({role: 'user', text: "That's all I can tell."});
  S.draft = ''; S.busy = true; S.error = null; draw();
  try {const r = await post('/api/feedback/chat', {messages: S.messages});
    if (r.message) S.messages.push({role: 'assistant', text: r.message});
    S.report = r.report || S.report; S.done = r.done}
  catch (e) {S.error = 'Luna is not available (' + e.message + ').'}
  finally {S.busy = false; draw()}}

function bind(b) {
  b.onclick = async e => {const a = (e.target.closest('[data-f],[data-del]') || {}).dataset || {};
    if (a.del !== undefined) {S.shots.splice(+a.del, 1); return draw()}
    if (a.f === 'send') return ask(false);
    if (a.f === 'finish') return ask(true);
    if (a.f === 'new') {S = fresh(); return draw()}
    const note = t => {const n = b.querySelector('.fb-note'); if (n) n.textContent = t};
    if (a.f === 'package') {S.busy = true; draw(); note('Collecting diagnostics, the log, discussions and the wiki…');
      try {S.result = await post('/api/feedback/package', {text: S.text, report: S.report, messages: S.messages, screenshots: S.shots});
        store.set({next: Date.now() + 30 * DAY})}
      catch (err) {S.error = err.message} finally {S.busy = false; draw()}}
    if (a.f === 'reveal') {try {await post('/api/feedback/reveal', {path: S.result.path})} catch (err) {note(err.message)}}
    if (a.f === 'copy') {const t = `Feedback for Wiki: ${(S.report && S.report.title) || S.text.slice(0, 80)}. File attached: ${S.result.path.split(/[\\/]/).pop()}`;
      try {await navigator.clipboard.writeText(t); note('Copied: paste it in Teams and attach the file.')} catch (err) {note(t)}}};
  // Enter sends, Shift+Enter is a new line (as in the chat)
  b.onkeydown = e => {if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.target.tagName === 'TEXTAREA') {e.preventDefault(); ask(false)}};
  b.onpaste = e => {const items = [...(e.clipboardData || {}).items || []].filter(i => i.type.startsWith('image/'));
    if (!items.length) return; e.preventDefault();
    items.forEach(i => {const r = new FileReader(); r.onload = () => {if (S.shots.length < 6) {S.shots.push(r.result); S.draft = (b.querySelector('textarea') || {}).value || S.draft; draw()}}; r.readAsDataURL(i.getAsFile())})}}
