// First-run setup: one screen per part (the same parts as Settings), then the app.
// Shown when the instance has no setup.done_at yet; Settings → "Run the first-run setup again" opens it any time.
import {$, esc, topbar} from './ui.js';
import {api, post} from './api.js';
import {mark} from './shell.js';
import {mountCopilot} from './parts/copilot.js';
import {mountModel} from './parts/model.js';
import {mountJira} from './parts/jira.js';
import {mountRepos} from './parts/repos.js';

const STEPS = [
  {key: 'copilot', title: 'Sign in to GitHub Copilot', text: 'The assistant runs on your GitHub Copilot subscription. Sign in once in the browser; if that is not possible, store a GitHub token with Copilot access.', mount: mountCopilot},
  {key: 'model', title: 'Choose the model', text: 'The model that writes the wiki and answers questions. The recommended one is preselected when your Copilot account offers it; each source or question costs AI credits. You can change it later in Settings.', mount: (el, C) => mountModel(el, C, {setup: true})},
  {key: 'jira', title: 'Connect Jira', optional: true, text: 'Optional. With Jira the assistant can read tickets you paste into a question (read only). You can add it later in Settings.', mount: mountJira},
  {key: 'repos', title: 'Add code repositories', optional: true, text: 'Optional. Local clones the assistant may read (never change), so answers can point to the exact line of code. You can add them later in Settings.', mount: mountRepos},
];

export async function openSetup(at = 0) {mark('setup');
  $('#main').innerHTML = topbar('Setup') + `<div class="scroll"><div class="col wide" id="setup"><p class="empty">Loading…</p></div></div>`;
  let C; try {C = await api('/api/settings')} catch (e) {$('#setup').innerHTML = `<p class="errmsg">${esc(e.message)}</p>`; return}
  const s = STEPS[at], last = at === STEPS.length - 1;
  $('#setup').innerHTML = `<ol class="stepper">${STEPS.map((x, i) => `<li class="${i < at ? 'done' : i === at ? 'now' : ''}">${esc(x.title)}</li>`).join('')}</ol>
    <div class="pagehead"><div class="kicker">First-run setup · step ${at + 1} of ${STEPS.length}</div><h2>${esc(s.title)}</h2><p>${esc(s.text)}</p></div>
    <section class="set" id="part"></section>
    <div class="btns wiz">${at ? '<button class="ghost" data-a="back">Back</button>' : ''}<span class="sp"></span>
      <button class="ghost" data-a="skip">${s.optional ? 'Skip' : 'Continue anyway'}</button>
      <button class="pri" data-a="next">${last ? 'Save and finish' : 'Save and continue'}</button></div><p class="d wmsg"></p>`;
  const part = s.mount($('#part'), C);
  const go = async save => {
    if (save && part.save && !(await part.save())) return;  // the part shows what went wrong
    if (save && s.key === 'copilot' && !part.ok()) {$('.wmsg').textContent = 'Not signed in yet: press “Sign in with GitHub…”, finish the steps there, then “Check sign-in”. Or continue anyway and do it later in Settings.'; return}
    if (!last) return openSetup(at + 1);
    await post('/api/setup/done'); location.hash = ''};
  $('.wiz').onclick = e => {const a = (e.target.closest('button') || {}).dataset?.a;
    if (a === 'back') openSetup(at - 1); else if (a === 'skip') go(false); else if (a === 'next') go(true)}}

// on start: an instance that was never set up opens the setup first
export async function needsSetup() {try {return !(await api('/api/setup')).done} catch (e) {return false}}
