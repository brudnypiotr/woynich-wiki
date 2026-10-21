// About: the app's version, updates, a diagnostics report to copy or download for support (no keys, no content), the changelog.
import {$, esc, topbar, note} from './ui.js';
import {api} from './api.js';
import {mark} from './shell.js';
import {entry, notice, run} from './update.js';

export async function openAbout() {mark('about');
  $('#main').innerHTML = topbar('About') + `<div class="scroll"><div class="col wide" id="about"><p class="empty">Loading…</p></div></div>`;
  let v; try {v = await api('/api/about')} catch (e) {$('#about').innerHTML = `<p class="errmsg">${esc(e.message)}</p>`; return}
  $('#about').innerHTML = `<div class="pagehead"><div class="kicker">About</div><h2>woynich-wiki ${esc(v.version)}</h2>
    <p>Project knowledge base with a paper trail.</p></div>
    <section class="set"><h3>This copy</h3><div class="kv">
      <span>Version</span><b>${esc(v.version)}</b>
      <span>Commit</span><b>${esc(v.commit || 'unknown (no git)')}${v.date ? ' · ' + esc(v.date) : ''}${v.branch ? ' · ' + esc(v.branch) : ''}</b>
      <span>Local changes</span><b>${v.dirty ? 'yes' : 'no'}</b></div></section>
    <section class="set" id="updates"><h3>Updates</h3><p class="d">New versions come from the official repository. Update keeps your
      knowledge base, settings and keys; the app restarts by itself. If a new version misbehaves, Roll back returns to the previous one.</p>
      <div class="kv" id="u-state"><span>Status</span><b>checking…</b></div><ul class="chg" id="u-list"></ul>
      <div class="btns"><button class="pri" data-a="update" hidden>Update now</button><button class="ghost" data-a="check">Check now</button>
        <button class="ghost" data-a="rollback">Roll back to previous</button><span class="note"></span></div></section>
    <section class="set"><h3>Diagnostics</h3>
      <p class="d">Versions, paths, the model, counts, which keys are set (never their values), a GitHub Copilot and Jira check
      (no AI credits) and the last errors. No content of sources or pages. Send it when something does not work.</p>
      <div class="btns"><button class="pri" data-a="run">Collect diagnostics</button><button class="ghost" data-a="copy" hidden>Copy</button>
        <button class="ghost" data-a="save" hidden>Download</button><span class="note"></span></div><pre hidden></pre></section>
    <section class="set"><h3>Changelog</h3><p class="d">What changed in each version, from the history of this copy.</p>
      <label class="d"><input type="checkbox" id="chg-all"> Show all changes (also documentation, tests and internal work)</label>
      <div id="chg"><p class="empty">Loading…</p></div></section>`;
  const root = $('#about'), pre = root.querySelector('pre'), n = root.querySelector('.note'), btn = a => root.querySelector(`[data-a=${a}]`);
  let text = '';
  btn('run').onclick = async () => {btn('run').disabled = true; note(n, 'Collecting… (checks GitHub Copilot and Jira, a few seconds)');
    try {text = JSON.stringify(await api('/api/diagnostics'), null, 2); pre.textContent = text; pre.hidden = btn('copy').hidden = btn('save').hidden = false; note(n, 'Ready.')}
    catch (e) {note(n, e.message, false)} finally {btn('run').disabled = false}};
  btn('copy').onclick = async () => {try {await navigator.clipboard.writeText(text); note(n, 'Copied to the clipboard.')} catch (e) {note(n, 'Copy failed: select the text and copy it.', false)}};
  btn('save').onclick = () => {const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
    a.download = `woynich-wiki-diagnostics-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href)}
  updates(); changelog()}

async function updates(refresh) {const sec = $('#updates'), n = sec.querySelector('.note'), btn = a => sec.querySelector(`[data-a=${a}]`);
  const say = (t, ok = true) => {n.className = (ok ? 'okmsg' : 'errmsg') + ' note'; n.textContent = t};
  const u = await notice(refresh);
  const st = !u ? 'not available' : u.error ? `cannot check: ${u.error}` : u.available
    ? `version ${u.latest_version || u.latest} is available (${u.behind} change${u.behind > 1 ? 's' : ''})` : 'this is the newest version';
  $('#u-state').innerHTML = `<span>Status</span><b>${esc(st)}</b>` + (u && u.checked_at ? `<span>Checked</span><b>${new Date(u.checked_at * 1000).toLocaleString()}</b>` : '');
  $('#u-list').innerHTML = u && u.available ? u.incoming.map(entry).join('') : '';
  btn('update').hidden = !(u && u.available);
  btn('check').onclick = async () => {say('Checking…'); await updates(true); say('')};
  const go = what => async () => {sec.querySelectorAll('button').forEach(b => b.disabled = true);
    try {await run(what, say)} catch (e) {say(e.message, false)} finally {sec.querySelectorAll('button').forEach(b => b.disabled = false)}};
  btn('update').onclick = go('apply');
  btn('rollback').onclick = () => confirm('Go back to the version before the last update?') && go('rollback')()}

async function changelog() {let groups; try {groups = await api('/api/changelog')} catch (e) {$('#chg').innerHTML = `<p class="errmsg">${esc(e.message)}</p>`; return}
  const draw = () => {const all = $('#chg-all').checked;
    const html = groups.map(g => [g, g.entries.filter(e => all || e.kind !== 'Other')]).filter(([, es]) => es.length)
      .map(([g, es], i) => `<details class="ver"${i === 0 ? ' open' : ''}><summary>${esc(g.version)}<small>${esc(g.date)} · ${es.length} change${es.length > 1 ? 's' : ''}</small></summary>
        <ul class="chg">${es.map(entry).join('')}</ul></details>`).join('');
    $('#chg').innerHTML = html || '<p class="empty">No history in this copy (run setup.cmd again).</p>'};
  $('#chg-all').onchange = draw; draw()}
