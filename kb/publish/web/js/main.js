// Entry point: wires the sidebar and the views to the URL hash.
// #s=<id> discussion · #add · #settings · #setup[/<step>] · #about · #wiki[/<dashboard hash>] · (empty) new discussion
import {$} from './ui.js';
import {api} from './api.js';
import {initShell} from './shell.js';
import {openChat, currentId, delSession, initChat} from './chat.js';
import {openAdd} from './uploads.js';
import {openWiki} from './wiki.js';
import {openSettings} from './settings.js';
import {openSetup, needsSetup} from './setup.js';
import {openAbout} from './about.js';
import {initFeedback} from './feedback.js';

async function route() {document.body.classList.remove('side'); const h = location.hash.slice(1), m = h.match(/^s=([0-9a-f]{12})$/);
  if (m) {if (currentId() === m[1] && $('#turns')) return; try {openChat(await api('/api/sessions/' + m[1]))} catch (e) {location.hash = ''}}
  else if (h === 'add') openAdd(); else if (h === 'settings') openSettings(); else if (h === 'setup' || h.startsWith('setup/')) openSetup(+h.split('/')[1] || 0); else if (h === 'about') openAbout();
  else if (h === 'wiki' || h.startsWith('wiki/')) openWiki(h.slice(5)); else openChat(null)}

document.addEventListener('click', e => {  // the menu on narrow screens
  if (e.target.closest('[data-act="menu"]')) document.body.classList.add('side');
  else if (e.target.closest('.scrim')) document.body.classList.remove('side')});
initShell({onNew: () => openChat(null), onDelete: delSession});
initChat();
initFeedback();
window.onhashchange = route;
if (!location.hash.startsWith('#setup') && await needsSetup()) location.hash = 'setup'; else route();
