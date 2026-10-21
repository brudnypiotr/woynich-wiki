// Knowledge pack: start from a colleague's finished knowledge base (first-run setup, Settings), or export this one
// (Settings). Importing replaces the wiki and sources; the previous ones stay in the instance's Git history.
import {esc, note, ACCESS} from '../ui.js';

const upload = (file, onProgress) => new Promise((ok, fail) => {  // XHR: fetch cannot report upload progress
  const x = new XMLHttpRequest(); x.open('POST', '/api/pack/import'); x.setRequestHeader('X-KB-Token', ACCESS);
  x.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total);
  x.onload = () => {let j = {}; try {j = JSON.parse(x.responseText)} catch (e) {}
    x.status < 300 ? ok(j) : fail(new Error(j.error || x.status))};
  x.onerror = () => fail(new Error('the app did not answer')); x.send(file)});

// opts.after(result): what to do after an import (default: reload); opts.exportable: show the export button
export function mountPack(el, C, opts = {}) {
  el.innerHTML = `<div class="drop" tabindex="0"><b>Drop a knowledge pack (.kbpack.zip) here</b><span>or</span>
      <label class="pri" style="cursor:pointer">Choose file…<input type="file" accept=".zip" hidden></label></div>
    ${opts.exportable ? `<div class="btns"><a class="ghost" href="/api/pack/export?t=${ACCESS}" data-a="export">Export this knowledge base…</a>
      <small class="d">One file with the wiki, every source and the project branding, for colleagues to start from.
      It holds company content: share it only through Teams or SharePoint, never GitHub.</small></div>` : ''}
    <div class="btns"><span class="note"></span></div>`;
  const n = el.querySelector('.note'), drop = el.querySelector('.drop'), input = el.querySelector('input[type=file]');
  const exp = el.querySelector('[data-a=export]');
  if (exp) exp.onclick = () => note(n, 'Preparing the pack… the download starts when it is ready (large originals take a while).');
  const send = async f => {if (!f) return; if (!/\.zip$/i.test(f.name)) return note(n, 'Choose the .kbpack.zip file.', false);
    if (opts.confirm !== false && !confirm(`Replace this knowledge base's wiki and sources with ${f.name}?\nThe current knowledge base is saved first (local/backups); your settings and discussions stay.`)) return;
    drop.classList.add('busy');
    try {const r = await upload(f, p => note(n, p < 1 ? `Uploading ${Math.round(p * 100)}%…` : 'Unpacking and indexing…'));
      note(n, `Imported “${r.title}”: ${r.sources} sources, ${r.pages} pages.${r.backup ? ' The previous knowledge base is saved in local/backups.' : ''} Reloading…`);
      setTimeout(() => opts.after ? opts.after(r) : location.reload(), r.backup ? 3500 : 1200)}
    catch (e) {note(n, e.message, false)} finally {drop.classList.remove('busy'); input.value = ''}};
  input.onchange = () => send(input.files[0]);
  drop.ondragover = e => {e.preventDefault(); drop.classList.add('over')};
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => {e.preventDefault(); drop.classList.remove('over'); send(e.dataTransfer.files[0])};
  return {save: async () => true}}
