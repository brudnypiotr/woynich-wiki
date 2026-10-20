// The sidebar: status line, AI-credit usage, the list of discussions, which entry is highlighted.
import {$, esc} from './ui.js';
import {api} from './api.js';

export async function status() {try {const s = await api('/api/status'); $('#st').textContent = `${s.sources} sources · ${s.pages} pages · ${s.model}${s.busy ? ' · working…' : ''}${s.queued ? ` · ${s.queued} queued` : ''}`;
  $('#dot').classList.toggle('busy', s.busy)} catch (e) {$('#st').textContent = 'not connected'; $('#dot').classList.add('busy')}}

const fmt = n => n == null ? '?' : Number(n).toLocaleString(undefined, {maximumFractionDigits: n < 100 ? 1 : 0});
export async function usage(refresh) {const sub = $('#u-sub'); if (refresh) sub.textContent = 'checking usage…';
  try {const u = await api('/api/usage' + (refresh ? '?refresh=1' : '')); const r = new Date(new Date(u.reset).getTime() - 864e5);  // last day of the cycle, as GitHub shows it
    const when = `resets in ${u.days_left} days (${u.business_days_left} working) · cycle ends ${r.toLocaleDateString(undefined, {day: 'numeric', month: 'short', timeZone: 'UTC'})}`;
    $('#u-unit').textContent = u.unit || 'AI credits';
    const used = u.unlimited ? null : (u.remaining_pct != null ? 100 - u.remaining_pct : (u.entitlement ? 100 * u.used / u.entitlement : null));
    $('#u-pct').textContent = u.unlimited ? 'unlimited' : used == null ? '–' : Math.round(used) + '% used';
    const f = $('#u-fill'); f.style.width = (used == null ? 0 : Math.min(100, Math.max(2, used))) + '%'; f.className = used >= 90 ? 'bad' : used >= 70 ? 'warn' : '';
    sub.innerHTML = (u.entitlement != null && !u.unlimited ? `${fmt(u.used)} of ${fmt(u.entitlement)} used<br>` : '') + when
      + `<br>this knowledge base: ${fmt(u.kb_month)} this month` + (u.error && u.entitlement == null ? `<br><span title="${esc(u.error)}">quota not available from GitHub</span>` : '');
    $('#usage').title = `${u.plan ? ('Plan: ' + u.plan + '. ') : ''}Read from GitHub at ${new Date(u.checked_at).toLocaleTimeString()}${u.since_check ? `, plus ${fmt(u.since_check)} used by this knowledge base since then` : ''}; GitHub is asked again every 5 minutes (usage in your IDE or CLI shows up then). Click to read it now.`}
  catch (e) {sub.textContent = 'usage not available'}}

export async function loadSessions() {const l = await api('/api/sessions').catch(() => []);
  $('#sl').innerHTML = l.length ? l.map(s => `<a data-id="${s.id}" title="${esc(s.topic)} · ${s.turns} questions"><span>${esc(s.topic)}</span><button class="del" data-del="${s.id}" title="Delete discussion">×</button></a>`).join('') : '<div class="none">No discussions yet.</div>'; mark()}

// highlight the current view in the sidebar ("new", "add", "settings", "wiki" or "s=<id>")
export function mark(v) {v = v || (location.hash.slice(1).split('/')[0] || 'new'); const sid = (v.match(/^s=(\w+)/) || [])[1];
  document.querySelectorAll('#navp button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  document.querySelectorAll('#sl a').forEach(a => a.classList.toggle('on', a.dataset.id === sid))}

// under the status line: the app's version and commit; a click opens About (diagnostics)
async function appVersion() {try {const v = await api('/api/about');
  $('#ver').textContent = `v${v.version}${v.commit ? ' · ' + v.commit : ''}${v.dirty ? ' · local changes' : ''}`} catch (e) {}}

// onNew: "New discussion" while already on it (the hash does not change); onDelete: the × next to a discussion
export function initShell({onNew, onDelete}) {
  $('#sl').onclick = e => {const d = e.target.closest('[data-del]'); if (d) {e.preventDefault(); e.stopPropagation(); return onDelete(d.dataset.del)}
    const a = e.target.closest('a'); if (a) location.hash = 's=' + a.dataset.id};
  $('#navp').onclick = e => {const b = e.target.closest('button'); if (!b) return; if (b.dataset.v === 'new' && !location.hash.slice(1)) return onNew(); location.hash = b.dataset.v === 'new' ? '' : b.dataset.v};
  $('#usage').onclick = () => usage(true);
  setInterval(status, 5000); status(); appVersion();
  usage(); setInterval(() => usage(), 60000);
  loadSessions()}
