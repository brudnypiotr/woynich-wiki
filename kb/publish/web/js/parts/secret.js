// One key or token in the secret store (Windows Credential Manager): set / not set, paste a value, save, remove.
// The browser never learns the value, only whether it is set.
import {esc} from '../ui.js';
import {post} from '../api.js';

export function secretRow(x, extra = '') {
  return `<div class="sec-row" data-n="${esc(x.name)}"><div class="nm"><b>${esc(x.label)} <span class="badge ${x.set ? 'done' : 'off'}">${x.set ? 'Set' : x.set === null ? '?' : 'Not set'}</span></b><code>${esc(x.name)}</code><small>${x.helpHtml || esc(x.help)}</small>${extra}</div>
     <input type="password" placeholder="${x.set ? 'Paste a new value to replace' : 'Paste the value'}" autocomplete="off"><div class="b"><button class="ghost" data-a="set">Save</button>${x.set ? '<button class="ghost" data-a="del">Remove</button>' : ''}</div></div>`}

// clicks on Save / Remove inside el; onState(newSecretsState, name) after every change
export function bindSecrets(el, onState) {
  el.addEventListener('click', async e => {const b = e.target.closest('.sec-row button[data-a]'); if (!b) return; const row = b.closest('.sec-row'), n = row.dataset.n, v = row.querySelector('input').value;
    try {if (b.dataset.a === 'del') {if (!confirm('Remove ' + n + ' from Windows Credential Manager?')) return; onState(await post('/api/secrets/' + n + '/delete'), n)}
      else {if (!v.trim()) return row.querySelector('input').focus(); onState(await post('/api/secrets/' + n, {value: v}), n)}}
    catch (err) {alert(err.message)}})}

export const secretItem = (st, name) => (st.items || []).find(x => x.name === name) || {name, label: name, help: '', set: null};
