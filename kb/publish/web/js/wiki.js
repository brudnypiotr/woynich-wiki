// The wiki dashboard inside the app (an iframe of /dashboard), or in a new tab.
import {$, ic, I, ACCESS, topbar} from './ui.js';
import {mark} from './shell.js';

export function openWiki(sub) {mark('wiki');
  $('#main').innerHTML = topbar('Wiki', `<button class="icon" id="rl" title="Rebuild and reload">${ic(I.redo)}</button><a class="ghost" target="_blank" href="/dashboard?t=${ACCESS}${sub ? '#' + sub : ''}" title="Open in a new tab">${ic(I.ext)}<span>New tab</span></a>`) +
   `<iframe id="wf" src="/dashboard?t=${ACCESS}&embed=1${sub ? '#' + sub : ''}" title="Wiki"></iframe>`;
  $('#rl').onclick = () => $('#wf').contentWindow.location.reload()}
