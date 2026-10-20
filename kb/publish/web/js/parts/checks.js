// Credential checks (no AI credits): GitHub Copilot sign-in and one Jira request. Results are shared by all parts.
import {esc} from '../ui.js';
import {api} from '../api.js';

const CHK = {};             // what → {running} | {ok: true|false|null, detail}
const listeners = new Set();

export const checkState = what => CHK[what];
export function onCheck(fn) {listeners.add(fn); return () => listeners.delete(fn)}

export async function runCheck(what) {CHK[what] = {running: true}; listeners.forEach(f => f(what));
  try {Object.assign(CHK, await api('/api/settings/check?what=' + what))} catch (e) {CHK[what] = {ok: false, detail: e.message}}
  listeners.forEach(f => f(what)); return CHK[what]}

// one line: "testing…", "✓ signed in as …", "✗ …" or "– not configured"
export function checkLine(v) {if (!v) return '';
  return v.running ? '<small class="sub chk">testing…</small>' : `<small class="chk ${v.ok === true ? 'okmsg' : v.ok === false ? 'errmsg' : 'sub'}">${v.ok === true ? '✓' : v.ok === false ? '✗' : '–'} ${esc(v.detail)}</small>`}
