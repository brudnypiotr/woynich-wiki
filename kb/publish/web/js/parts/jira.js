// Jira the assistant may read: URL, e-mail (Cloud), token, with a button to the page that creates the token;
// one "Save and test" at the bottom saves all of it and tests the connection.
import {esc, ic, note} from '../ui.js';
import {post} from '../api.js';
import {runCheck, checkState, checkLine, onCheck} from './checks.js';
import {secretRow, bindSecrets, secretItem} from './secret.js';

const SECRET_NAME = 'jira-token';
const EXT = 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6';
// no URL yet counts as Cloud (*.atlassian.net, an API token), so the setup shows the token button from the start
const isCloud = url => !url || /\.atlassian\.net/i.test(url);
// where the token is created: Atlassian account (Cloud) or the Jira profile (Data Center / Server)
const tokenPage = url => isCloud(url) ? 'https://id.atlassian.com/manage-profile/security/api-tokens'
  : /^https?:\/\/\S+/.test(url || '') ? url.replace(/\/+$/, '') + '/secure/ViewProfile.jspa?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens' : '';
const howTo = url => isCloud(url)
  ? `<b>Jira Cloud</b>: open the page below, click <i>Create API token</i>, give it a name (e.g. “knowledge base”), copy it and paste it into <i>Jira token</i>. The e-mail above is your Atlassian account.`
  : `<b>Jira Data Center / Server</b>: open the page below (or your avatar → <i>Profile</i> → <i>Personal Access Tokens</i>), click <i>Create token</i>, copy it and paste it into <i>Jira token</i>. Leave the e-mail empty.`;

// C: settings state. Returns {save(), ok()}: save stores URL, e-mail and a pasted token, then tests (true when saved).
export function mountJira(el, C) {
  let secrets = C.secrets; const p = C.profile;
  el.innerHTML = `<div class="grid2"><div class="f"><label>Jira URL</label><input data-k="url" value="${esc(p.jira_base_url)}" placeholder="https://yourcompany.atlassian.net"></div>
     <div class="f"><label>Jira e-mail</label><input data-k="email" value="${esc(p.jira_email)}" placeholder="Jira Cloud only"><small>Leave empty for Jira Data Center.</small></div></div>
    <div class="tokhelp"><p class="howto d"></p><a class="bigbtn" target="_blank" rel="noopener"></a></div>
    <div class="tok"></div>
    <div class="btns jfoot"><button class="pri" data-a="save">Save and test</button><span class="note"></span><span class="jstat"></span></div>`;
  const $k = k => el.querySelector(`[data-k=${k}]`), n = el.querySelector('.note');
  const stat = () => {el.querySelector('.jstat').innerHTML = checkLine(checkState('jira'))};
  const tok = () => {el.querySelector('.tok').innerHTML = secretRow({...secretItem(secrets, SECRET_NAME), help: 'Stored in Windows Credential Manager, for your user only.'})};
  const help = () => {const url = $k('url').value.trim(), page = tokenPage(url), b = el.querySelector('.bigbtn');
    el.querySelector('.howto').innerHTML = howTo(url);
    b.hidden = !page; b.href = page || '#';
    b.innerHTML = `${ic(EXT, 2)}<span>${isCloud(url) ? 'Create a Jira API token' : 'Open Personal Access Tokens'}</span><small>${esc(page.replace(/^https?:\/\//, '').split('?')[0])}</small>`};
  tok(); stat(); help();
  $k('url').oninput = help;
  const off = onCheck(w => {if (!el.isConnected) return off(); if (w === 'jira') stat()});
  bindSecrets(el.querySelector('.tok'), st => {secrets = st; tok(); if ($k('url').value.trim()) runCheck('jira')});
  const save = async () => {try {const r = await post('/api/settings', {profile: {jira_base_url: $k('url').value, jira_email: $k('email').value}});
      const pasted = el.querySelector('.tok input').value.trim();
      if (pasted) {secrets = await post('/api/secrets/' + SECRET_NAME, {value: pasted}); tok()}
      note(n, 'Saved.'); if (r.profile.jira_base_url) runCheck('jira'); return true}
    catch (e) {note(n, e.message, false); return false}};
  el.querySelector('[data-a=save]').onclick = save;
  if (p.jira_base_url) runCheck('jira');
  return {save, ok: () => (checkState('jira') || {}).ok === true}}
