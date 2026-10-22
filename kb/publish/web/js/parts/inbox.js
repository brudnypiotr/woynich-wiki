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

// opts.team: also edit the team's inbox (folder, link, contact; saved in the branding, carried by branding.zip and
// knowledge packs); Settings has it, About shows the state only.
export function mountInbox(el, opts = {}) {
  const draw = s => {
    const team = opts.team ? `<div class="f"><label>Shared OneDrive folder</label><input data-k="folder" list="ib-found" value="${esc(s.name || '')}" placeholder="e.g. Wiki Inbox">
        <datalist id="ib-found">${(s.found || []).map(n => `<option value="${esc(n)}">`).join('')}</datalist></div>
      <div class="f"><label>Share link</label><input data-k="share_url" value="${esc(s.share_url || '')}" placeholder="https://…sharepoint.com/…"></div>
      <div class="f"><label>Author's e-mail</label><input data-k="contact" value="${esc(s.contact || '')}" placeholder="for Teams and e-mail when the inbox is not there"></div>
      <p class="d">The same for the whole team: saved in the branding, so <code>branding.zip</code> and knowledge packs bring it to everyone.
        ${s.onedrive.length ? 'OneDrive on this computer: ' + s.onedrive.map(esc).join(', ') : 'No OneDrive found on this computer.'}</p>` : '';
    el.innerHTML = `<div class="kv"><span>Inbox</span><b>${!s.configured ? 'not set up' : s.connected ? '✓ ' + esc(s.folder) : `not on this computer yet (OneDrive folder “${esc(s.name)}”)`}</b></div>
      ${team}
      <div class="f"><label>Your e-mail</label><input data-k="user" value="${esc(s.user_set || '')}" placeholder="${esc(s.user_detected)} (detected)"></div>
      ${s.configured && !s.connected && s.share_url ? `<p class="d">Add the shared folder to your OneDrive once: open the link, choose <b>Add shortcut to My files</b>. Then feedback and usage go to the author by themselves.</p>` : ''}
      <label class="d"><input type="checkbox" data-k="share_usage" ${s.share_usage ? 'checked' : ''}> Share usage with the app's author, to see how the app is used and where it fails</label>
      <p class="d">${esc(USAGE_NOTE)}</p>
      <div class="btns"><button class="pri" data-i="save">Save</button>${s.connected || !s.share_url ? '' : '<button class="ghost" data-i="connect">Open the shared folder</button>'}<button class="ghost" data-i="check">Check again</button><span class="note"></span></div>`};
  const load = () => api('/api/inbox').then(draw).catch(e => el.innerHTML = `<p class="errmsg">${esc(e.message)}</p>`);
  const val = k => {const i = el.querySelector(`[data-k=${k}]`); return i ? (i.type === 'checkbox' ? i.checked : i.value.trim()) : undefined};
  el.onclick = async e => {const a = (e.target.closest('[data-i]') || {}).dataset?.i, n = () => el.querySelector('.note');
    if (a === 'connect') connectShare((t, ok) => note(n(), t, ok));
    if (a === 'check') load();
    if (a === 'save') {const body = {share_usage: val('share_usage'), user: val('user')};
      if (opts.team) body.inbox = {folder: val('folder'), share_url: val('share_url'), contact: val('contact')};
      try {draw(await post('/api/inbox', body)); note(n(), 'Saved.')} catch (err) {note(n(), err.message, false)}}};
  load()}
