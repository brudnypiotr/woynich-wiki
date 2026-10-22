// The inbox: a OneDrive folder the app's author shares (set in the branding). Feedback files and usage records go there
// by themselves once the user has added it to their OneDrive. In Settings and About.
import {esc, note} from '../ui.js';
import {api, post} from '../api.js';

export const USAGE_NOTE = 'What is shared: when you ask (with the question text), which model, tokens, AI credits, time and errors, '
  + 'app starts and the app version, with your work e-mail. Answers, sources and wiki pages are not shared.';

// "Message in Teams" and e-mail links to the app's author, with the text filled in
export const contactLinks = (to, text) => to ? `<a class="ghost" target="_blank" rel="noopener" href="https://teams.microsoft.com/l/chat/0/0?users=${encodeURIComponent(to)}&message=${encodeURIComponent(text)}">Message in Teams</a>
  <a class="ghost" href="mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(text.slice(0, 120))}&body=${encodeURIComponent(text)}">E-mail</a>` : '';

// say(text, ok): where to show the outcome
export async function connectShare(say) {try {await post('/api/inbox/open-share', {}); say('Opened in the browser: choose “Add shortcut to My files”, wait a minute for OneDrive, then check again.', true)}
  catch (e) {say(e.message, false)}}

export function mountInbox(el) {
  const draw = s => {
    if (!s.configured) {el.innerHTML = `<p class="d">Not set up: the branding has no inbox. Feedback files stay on your Desktop.</p>`; return}
    el.innerHTML = `<div class="kv"><span>Inbox</span><b>${s.connected ? '✓ ' + esc(s.folder) : `not on this computer yet (OneDrive folder “${esc(s.name)}”)`}</b>
        <span>You</span><b>${esc(s.user)}</b>${s.contact ? `<span>Author</span><b>${esc(s.contact)}</b>` : ''}</div>
      ${s.connected ? '' : `<p class="d">Add the shared folder to your OneDrive once: open the link, choose <b>Add shortcut to My files</b>. Then feedback and usage go to the author by themselves.</p>`}
      <label class="d"><input type="checkbox" data-i="usage" ${s.share_usage ? 'checked' : ''}> Share usage with the app's author, to see how the app is used and where it fails</label>
      <p class="d">${esc(USAGE_NOTE)}</p>
      <div class="btns">${s.connected || !s.share_url ? '' : '<button class="pri" data-i="connect">Open the shared folder</button>'}<button class="ghost" data-i="check">Check again</button><span class="note"></span></div>`};
  const load = () => api('/api/inbox').then(draw).catch(e => el.innerHTML = `<p class="errmsg">${esc(e.message)}</p>`);
  el.onclick = async e => {const a = (e.target.closest('[data-i]') || {}).dataset?.i, n = el.querySelector('.note');
    if (a === 'connect') connectShare((t, ok) => note(n, t, ok));
    if (a === 'check') load()};
  el.onchange = async e => {if (e.target.dataset.i !== 'usage') return;
    try {draw(await post('/api/inbox', {share_usage: e.target.checked}))} catch (err) {note(el.querySelector('.note'), err.message, false)}};
  load()}
