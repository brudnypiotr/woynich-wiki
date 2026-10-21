// Project branding from a colleague's branding.zip (logo, header background, icon, the knowledge base title):
// in Settings and as the first step of the first-run setup. The page reloads after an import to show the logo.
import {esc, note} from '../ui.js';
import {api} from '../api.js';

// opts.reload: where to go after an import (the setup continues with its next step)
export function mountBranding(el, C, opts = {}) {
  el.innerHTML = `<div class="kv bfiles"></div>
    <div class="drop" tabindex="0"><b>Drop branding.zip here</b><span>or</span><label class="pri" style="cursor:pointer">Choose file…<input type="file" accept=".zip" hidden></label></div>
    <div class="btns"><span class="note"></span></div>`;
  const n = el.querySelector('.note'), drop = el.querySelector('.drop'), input = el.querySelector('input[type=file]');
  const show = b => {el.querySelector('.bfiles').innerHTML = Object.entries(b.files).map(([k, v]) =>
    `<span>${k}</span><b>${v ? esc(v.split(/[\\/]/).slice(-3).join('/')) : 'none'}</b>`).join('')
    + `<span>title</span><b>${esc((C.profile || {}).title || 'not set')}</b>`};
  api('/api/branding').then(show).catch(() => {});
  const send = async f => {if (!f) return; if (!/\.zip$/i.test(f.name)) return note(n, 'Choose the branding .zip file.', false);
    note(n, 'Importing…');
    try {const r = await api('/api/branding', {method: 'POST', body: f});
      note(n, `Imported ${[...r.imported, ...(r.title ? [`title “${r.title}”`] : [])].join(', ')}. Reloading…`);
      setTimeout(() => {if (opts.reload) opts.reload(); else location.reload()}, 1200)}
    catch (e) {note(n, e.message, false)} finally {input.value = ''}};
  input.onchange = () => send(input.files[0]);
  drop.ondragover = e => {e.preventDefault(); drop.classList.add('over')};
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => {e.preventDefault(); drop.classList.remove('over'); send(e.dataTransfer.files[0])};
  return {save: async () => true}}
