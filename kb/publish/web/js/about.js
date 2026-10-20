// About: the app's version, and a diagnostics report to copy or download for support (no keys, no content).
import {$, esc, topbar, note} from './ui.js';
import {api} from './api.js';
import {mark} from './shell.js';

export async function openAbout() {mark('about');
  $('#main').innerHTML = topbar('About') + `<div class="scroll"><div class="col wide" id="about"><p class="empty">Loading…</p></div></div>`;
  let v; try {v = await api('/api/about')} catch (e) {$('#about').innerHTML = `<p class="errmsg">${esc(e.message)}</p>`; return}
  $('#about').innerHTML = `<div class="pagehead"><div class="kicker">About</div><h2>woynich-wiki ${esc(v.version)}</h2>
    <p>Project knowledge base with a paper trail.</p></div>
    <section class="set"><h3>This copy</h3><div class="kv">
      <span>Version</span><b>${esc(v.version)}</b>
      <span>Commit</span><b>${esc(v.commit || 'unknown (no git)')}${v.date ? ' · ' + esc(v.date) : ''}${v.branch ? ' · ' + esc(v.branch) : ''}</b>
      <span>Local changes</span><b>${v.dirty ? 'yes' : 'no'}</b></div></section>
    <section class="set"><h3>Diagnostics</h3>
      <p class="d">Versions, paths, the model, counts, which keys are set (never their values), a GitHub Copilot and Jira check
      (no AI credits) and the last errors. No content of sources or pages. Send it when something does not work.</p>
      <div class="btns"><button class="pri" data-a="run">Collect diagnostics</button><button class="ghost" data-a="copy" hidden>Copy</button>
        <button class="ghost" data-a="save" hidden>Download</button><span class="note"></span></div><pre hidden></pre></section>`;
  const root = $('#about'), pre = root.querySelector('pre'), n = root.querySelector('.note'), btn = a => root.querySelector(`[data-a=${a}]`);
  let text = '';
  btn('run').onclick = async () => {btn('run').disabled = true; note(n, 'Collecting… (checks GitHub Copilot and Jira, a few seconds)');
    try {text = JSON.stringify(await api('/api/diagnostics'), null, 2); pre.textContent = text; pre.hidden = btn('copy').hidden = btn('save').hidden = false; note(n, 'Ready.')}
    catch (e) {note(n, e.message, false)} finally {btn('run').disabled = false}};
  btn('copy').onclick = async () => {try {await navigator.clipboard.writeText(text); note(n, 'Copied to the clipboard.')} catch (e) {note(n, 'Copy failed: select the text and copy it.', false)}};
  btn('save').onclick = () => {const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
    a.download = `woynich-wiki-diagnostics-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href)}}
