// Code repositories the assistant may read (never change), and how the parts of the system fit together.
import {esc, note} from '../ui.js';
import {post} from '../api.js';

const ROLES = ['frontend (UI)', 'backend server', 'API / services', 'database (schema, procedures)', 'rules / configuration', 'batch / integration', 'shared library', 'tests', 'infrastructure / deployment'];

// C: settings state. Returns {save()} (true when saved).
export function mountRepos(el, C) {
  let RP = C.profile.code_repos.map(r => ({...r}));
  el.innerHTML = `<datalist id="rolelist">${ROLES.map(x => `<option value="${x}">`).join('')}</datalist>
    <div class="rlist"></div>
    <div class="btns" style="margin-top:6px"><button class="ghost" data-a="add">+ Add repository</button></div>
    <div class="f" style="margin-top:16px"><label>How the parts fit together</label>
     <textarea data-k="arch" rows="5" placeholder="e.g. Three tiers: the Angular frontend (inv-web) calls the Java server (inv-server) over REST; the server keeps orders and rules in Oracle (schema and stored procedures in inv-db). Rule parameters come from XML in inv-rules, loaded by the server at start.">${esc(C.profile.architecture)}</textarea>
     <small>Plain words are enough: tiers, who calls whom, where data lives, which repository holds what.</small></div>
    <div class="btns"><button class="pri" data-a="save">Save repositories</button><span class="note"></span></div>`;
  const list = el.querySelector('.rlist'), n = el.querySelector('.note');
  const rstate = r => r.exists === undefined ? '' : (r.exists ? `<span class="st ok">✓ ${esc(r.branch || '?')}@${esc(r.commit || '?')}${r.dirty ? ' · local changes' : ''}</span>` : '<span class="st bad">⚠ folder not found</span>');
  const render = () => {list.innerHTML = RP.length ? RP.map((r, i) => `<div class="repo" data-i="${i}">
     <div class="f"><label>Name</label><input data-k="name" value="${esc(r.name || '')}" placeholder="inv-server"></div>
     <div class="f"><label>Role</label><input data-k="role" list="rolelist" value="${esc(r.role || '')}" placeholder="backend server"></div>
     <button class="icon x" data-del="${i}" title="Remove from the list (the folder stays)">×</button>
     <div class="f wide"><label>Folder</label><input data-k="path" value="${esc(r.path || '')}" placeholder="C:\\Users\\you\\DEV\\inv-server"></div>${rstate(r)}
     <div class="f wide"><label>What it contains, where to look</label><textarea data-k="description" rows="2" placeholder="Java server: rule engine (package rules/), order services, REST API for the frontend.">${esc(r.description || '')}</textarea></div></div>`).join('') : '<p class="empty">No repositories yet.</p>'};
  render();
  list.oninput = e => {const box = e.target.closest('.repo'), k = e.target.dataset.k; if (box && k) {RP[+box.dataset.i][k] = e.target.value; RP[+box.dataset.i].exists = undefined}};
  list.onclick = e => {const d = e.target.closest('[data-del]'); if (d) {RP.splice(+d.dataset.del, 1); render()}};
  el.querySelector('[data-a=add]').onclick = () => {RP.push({name: '', role: '', path: '', description: ''}); render(); list.querySelector('.repo:last-child input').focus()};
  const save = async () => {try {const r = await post('/api/settings', {repos: {list: RP, architecture: el.querySelector('[data-k=arch]').value}});
      RP = r.profile.code_repos.map(x => ({...x})); render(); const bad = RP.filter(x => !x.exists).length;
      note(n, bad ? `Saved; ${bad} folder${bad > 1 ? 's' : ''} not found on this computer.` : 'Saved. The next question uses them.', !bad); return true}
    catch (e) {note(n, e.message, false); return false}};
  el.querySelector('[data-a=save]').onclick = save;
  return {save}}
