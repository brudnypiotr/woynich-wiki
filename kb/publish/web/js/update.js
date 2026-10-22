// Updates: the sidebar notice, the Update / Roll back buttons (About) and the restart that follows.
import {$, esc} from './ui.js';
import {api, post} from './api.js';

export const entry = e => `<li><span class="kind k-${esc(e.kind.toLowerCase())}">${esc({Features: 'feature', Fixes: 'fix'}[e.kind] || e.type)}</span>${esc(e.text)}`
  + `<small>${e.scope ? esc(e.scope) + ' · ' : ''}${esc(e.date)} · ${esc(e.commit)}</small></li>`;

// in the sidebar, above the version: shown only when a newer version is waiting
// a newer version label only when it was bumped; otherwise just the number of changes (a quick fix)
export const newer = u => u.latest_version && u.latest_version !== u.current_version ? 'v' + u.latest_version : '';
export async function notice(refresh) {try {const u = await api('/api/update' + (refresh ? '?refresh=1' : ''));
  const a = $('#upd'); a.hidden = !u.available; if (u.available) a.textContent = u.gone ? `Branch merged · back to ${u.default_channel}`
    : `Update available${newer(u) ? ' · ' + newer(u) : ''} · ${u.behind} change${u.behind > 1 ? 's' : ''}`;
  return u} catch (e) {return null}}

// what: 'apply', 'rollback' or 'switch' (body: {channel}); say: shows progress next to the buttons
export async function run(what, say, body) {
  say({apply: 'Updating… (downloads the new version)', rollback: 'Rolling back…', switch: `Switching to ${body && body.channel}…`}[what]);
  const r = await post('/api/update/' + what, body);
  if (r.updated === false) return say(r.message);
  const notes = (r.notes || []).join('; ');
  if (!r.launcher) return say(`Done (version ${r.version}${notes ? '; ' + notes : ''}). Close the app window and start the app again.`);
  document.body.insertAdjacentHTML('beforeend', `<div class="restarting"><div><b>Restarting the app…</b>
    <p>${r.packages ? 'Installing updated packages, this can take a minute.' : 'This takes a few seconds.'}</p></div></div>`);
  const t0 = Date.now();
  await new Promise(ok => setTimeout(ok, 1500));
  while (Date.now() - t0 < 600000) {try {await api('/api/about'); return location.reload()} catch (e) {await new Promise(ok => setTimeout(ok, 1500))}}
  document.querySelector('.restarting p').textContent = 'The app did not come back. Look at its window for a message.'}
