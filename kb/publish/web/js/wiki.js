// The wiki dashboard inside the app (an iframe of /dashboard), or in a new tab.
import {$, ic, I, ACCESS, topbar, loader} from './ui.js';
import {mark} from './shell.js';

export function openWiki(sub) {mark('wiki');
  $('#main').innerHTML = topbar('Wiki', `<button class="icon" id="rl" title="Rebuild and reload">${ic(I.redo)}</button><a class="ghost" target="_blank" href="/dashboard?t=${ACCESS}${sub ? '#' + sub : ''}" title="Open in a new tab">${ic(I.ext)}<span>New tab</span></a>`) +
   `<div class="wfwrap"><div class="wfload">${loader('Opening the wiki…')}</div>
    <iframe id="wf" src="/dashboard?t=${ACCESS}&embed=1${sub ? '#' + sub : ''}" title="Wiki"></iframe></div>`;
  const wf = $('#wf'), wl = document.querySelector('.wfload');
  wf.onload = () => wl.hidden = true;
  // Rebuild: read every page again (the view itself reuses the last build while the wiki has not changed)
  $('#rl').onclick = () => {wl.hidden = false; wl.innerHTML = loader('Rebuilding the wiki…'); wf.src = `/dashboard?t=${ACCESS}&embed=1&rebuild=1`}}
