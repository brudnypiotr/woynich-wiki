// GitHub Copilot: sign in (copilot login), or a GitHub token; check the sign-in; account and quota details.
import {esc, note} from '../ui.js';
import {api, post} from '../api.js';
import {runCheck, checkState, checkLine, onCheck} from './checks.js';
import {secretRow, bindSecrets, secretItem} from './secret.js';

const SECRET_NAME = 'copilot-github-token';

// C: settings state (GET /api/settings). Returns {ok()}: whether the sign-in check passed.
export function mountCopilot(el, C) {
  let secrets = C.secrets;
  el.innerHTML = `<div class="btns" style="margin-top:0"><button class="ghost" data-a="check">Check sign-in</button><button class="ghost" data-a="login">Sign in with GitHub…</button><span class="note"></span></div>
    <div class="cstat"></div><div class="acc"></div>
    <details class="alt"><summary>No browser sign-in possible? Use a GitHub token</summary><div class="tok"></div></details>`;
  const n = el.querySelector('.note'), stat = () => {el.querySelector('.cstat').innerHTML = checkLine(checkState('copilot'))};
  const tok = () => {const x = secretItem(secrets, SECRET_NAME); el.querySelector('.tok').innerHTML = secretRow(x); if (x.set) el.querySelector('details.alt').open = true};
  tok(); stat();
  const off = onCheck(w => {if (!el.isConnected) return off(); if (w === 'copilot') stat()});
  bindSecrets(el.querySelector('.tok'), st => {secrets = st; tok(); runCheck('copilot')});
  el.querySelector('[data-a=login]').onclick = async () => {try {const r = await post('/api/settings/login'); note(n, r.message, r.ok)} catch (e) {note(n, e.message, false)}};
  el.querySelector('[data-a=check]').onclick = async () => {const b = el.querySelector('[data-a=check]'); b.disabled = true; runCheck('copilot');
    try {const a = await api('/api/settings/account'); const au = a.auth || {}, q = a.quota || {};
      const ok = au.is_authenticated ?? au.isAuthenticated, who = au.login || au.user || '';
      el.querySelector('.acc').innerHTML = `<div class="kv"><span>Signed in</span><b class="${ok ? 'okmsg' : 'errmsg'}" style="font-size:14px">${au.error ? esc(au.error) : (ok ? 'yes' + (who ? ' as ' + esc(who) : '') : 'no')}</b>
        ${au.auth_type || au.authType ? `<span>Method</span><span style="color:var(--ink)">${esc(au.auth_type || au.authType)}</span>` : ''}
        ${a.token_from_store ? '<span>Token</span><span style="color:var(--ink)">GitHub token (stored above)</span>' : ''}
        ${q.error ? `<span>Quota</span><span class="errmsg">${esc(q.error)}</span>` : Object.entries(q).map(([k, v]) => `<span>${esc(k.replace(/_/g, ' '))}</span><div>${v.entitlement ? `${v.used ?? '?'} of ${v.entitlement} used` : 'unlimited'}${v.resets ? ` · resets ${esc(String(v.resets).slice(0, 10))}` : ''}${v.remaining_pct != null && v.entitlement ? `<div class="meter"><i style="width:${Math.max(0, Math.min(100, 100 - v.remaining_pct))}%"></i></div>` : ''}</div>`).join('')}</div>`}
    catch (e) {note(n, e.message, false)} finally {b.disabled = false}};
  runCheck('copilot');
  return {ok: () => (checkState('copilot') || {}).ok === true}}
