// Jira the assistant may read: URL, e-mail (Cloud), token, with where to create the token; test the connection.
import {esc, note} from '../ui.js';
import {post} from '../api.js';
import {runCheck, checkState, checkLine, onCheck} from './checks.js';
import {secretRow, bindSecrets, secretItem} from './secret.js';

const SECRET_NAME = 'jira-token';
const isCloud = url => /\.atlassian\.net/i.test(url || '');
const howTo = url => isCloud(url)
  ? `<b>Jira Cloud</b>: open <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener">id.atlassian.com → Security → API tokens</a>, click <i>Create API token</i>, give it a name (e.g. “knowledge base”), copy it and paste it below. The e-mail above is your Atlassian account.`
  : `<b>Jira Data Center / Server</b>: in Jira click your avatar → <i>Profile</i> → <i>Personal Access Tokens</i> → <i>Create token</i>, copy it and paste it below. Leave the e-mail empty.`;

// C: settings state. Returns {save()}: saves URL and e-mail (true when saved).
export function mountJira(el, C) {
  let secrets = C.secrets; const p = C.profile;
  el.innerHTML = `<div class="grid2"><div class="f"><label>Jira URL</label><input data-k="url" value="${esc(p.jira_base_url)}" placeholder="https://yourcompany.atlassian.net"></div>
     <div class="f"><label>Jira e-mail</label><input data-k="email" value="${esc(p.jira_email)}" placeholder="Jira Cloud only"><small>Leave empty for Jira Data Center.</small></div></div>
    <div class="btns"><button class="pri" data-a="save">Save and test</button><span class="note"></span></div>
    <div class="jstat"></div><p class="howto d"></p><div class="tok"></div>`;
  const $k = k => el.querySelector(`[data-k=${k}]`), n = el.querySelector('.note');
  const stat = () => {el.querySelector('.jstat').innerHTML = checkLine(checkState('jira'))};
  const tok = () => {el.querySelector('.tok').innerHTML = secretRow({...secretItem(secrets, SECRET_NAME), help: 'Stored in Windows Credential Manager, for your user only.'})};
  const help = () => {el.querySelector('.howto').innerHTML = howTo($k('url').value)};
  tok(); stat(); help();
  $k('url').oninput = help;
  const off = onCheck(w => {if (!el.isConnected) return off(); if (w === 'jira') stat()});
  bindSecrets(el.querySelector('.tok'), st => {secrets = st; tok(); if ($k('url').value.trim()) runCheck('jira')});
  const save = async () => {try {const r = await post('/api/settings', {profile: {jira_base_url: $k('url').value, jira_email: $k('email').value}});
      note(n, 'Saved.'); if (r.profile.jira_base_url) runCheck('jira'); return true}
    catch (e) {note(n, e.message, false); return false}};
  el.querySelector('[data-a=save]').onclick = save;
  if (p.jira_base_url) runCheck('jira');
  return {save, ok: () => (checkState('jira') || {}).ok === true}}
