// Settings: the parts shared with the first-run setup (model, Copilot, Jira, repositories), other keys, the title.
import {$, esc, topbar, msg} from './ui.js';
import {api, post} from './api.js';
import {mark} from './shell.js';
import {mountModel} from './parts/model.js';
import {mountCopilot} from './parts/copilot.js';
import {mountJira} from './parts/jira.js';
import {mountRepos} from './parts/repos.js';
import {secretRow, bindSecrets} from './parts/secret.js';

export async function openSettings(){mark('settings');
  $('#main').innerHTML=topbar('Settings')+`<div class="scroll"><div class="col wide" id="setc"><p class="empty">Loading…</p></div></div>`;
  let C;try{C=await api('/api/settings')}catch(e){$('#setc').innerHTML=`<p class="errmsg">${esc(e.message)}</p>`;return}
  const p=C.profile;
  $('#setc').innerHTML=`<div class="pagehead"><div class="kicker">Settings</div><h2>Models, sign-in and keys</h2>
    <p>Saved in this knowledge base's own config (<code>instance/config</code>). Keys go to Windows Credential Manager and are never shown again.</p></div>
   <section class="set"><h3>Model</h3><p class="d">Which model writes the wiki and answers questions. Each question or source costs AI credits (shown under answers and in the sidebar).</p><div id="p-model"></div></section>
   <section class="set"><h3>GitHub Copilot account</h3><p class="d">The models run through your GitHub Copilot subscription.</p><div id="p-copilot"></div></section>
   <section class="set"><h3>Jira</h3><p class="d">The Jira the assistant may read (read only).</p><div id="p-jira"></div></section>
   <section class="set"><h3>Code repositories</h3><p class="d">Local clones the assistant may read (never change). The role and description tell
    it which tier holds what; the name is used in citations (<code>name/path:line@commit</code>).</p><div id="p-repos"></div></section>
   <section class="set"><h3>Other keys and tokens</h3><p class="d">Stored for your Windows user only. This page can tell whether a key is set, never what it is.</p>
    <div id="secs"></div>
    <div class="sec-row"><div class="nm"><b>Another key</b><small>Name: lowercase letters, digits, dashes.</small></div><input id="nk-name" placeholder="name, e.g. confluence-token"><div class="b"></div>
     <div></div><input id="nk-val" type="password" placeholder="value" autocomplete="off"><div class="b"><button class="ghost" id="nk-add">Add</button></div></div></section>
   <section class="set"><h3>Branding</h3><p class="d">Company logo, header background and icon, kept out of Git. Got a <code>branding.zip</code>
    from a colleague? Import it here; the desktop shortcut gets the icon too.</p><div class="kv" id="brand-files"></div>
    <div class="btns"><label class="pri" for="brand-zip" style="cursor:pointer">Import branding.zip…</label><input type="file" id="brand-zip" accept=".zip" hidden><span id="bmsg"></span></div></section>
   <section class="set"><h3>Knowledge base</h3><p class="d">Name shown in the sidebar.</p>
    <div class="f"><label for="ptitle">Title</label><input id="ptitle" value="${esc(p.title)}"></div>
    <div class="btns"><button class="pri" id="psave">Save</button><a class="ghost" href="#setup">Run the first-run setup again</a><span id="pmsg"></span></div></section>`;
  mountModel($('#p-model'),C);mountCopilot($('#p-copilot'),C);mountJira($('#p-jira'),C);mountRepos($('#p-repos'),C);
  // keys and tokens other than the ones the parts above own (Copilot token, Jira token)
  const OWNED=new Set(['copilot-github-token','jira-token']);
  const secs=st=>{$('#secs').innerHTML=(st.error?`<p class="errmsg">Secret store not available: ${esc(st.error)}</p>`:'')+(st.items.filter(x=>!OWNED.has(x.name)).map(x=>secretRow(x)).join('')||'<p class="empty">No other keys.</p>')};
  secs(C.secrets);bindSecrets($('#secs'),st=>secs(st));
  $('#nk-add').onclick=async()=>{const n=$('#nk-name').value.trim(),v=$('#nk-val').value;if(!n||!v)return;
    try{secs(await post('/api/secrets/'+encodeURIComponent(n),{value:v}));$('#nk-name').value=$('#nk-val').value=''}catch(e){alert(e.message)}};
  const brand=b=>{$('#brand-files').innerHTML=Object.entries(b.files).map(([k,v])=>`<span>${k}</span><b>${v?esc(v.split(/[\\/]/).slice(-3).join('/')):'none'}</b>`).join('')};
  api('/api/branding').then(brand).catch(()=>{});
  $('#brand-zip').onchange=async e=>{const f=e.target.files[0];if(!f)return;msg('bmsg','Importing…');
    try{const r=await api('/api/branding',{method:'POST',body:f});brand(r);msg('bmsg',`Imported ${r.imported.join(', ')}. Reloading…`);setTimeout(()=>location.reload(),1200)}
    catch(err){msg('bmsg',err.message,false)}finally{e.target.value=''}};
  $('#psave').onclick=async()=>{try{const r=await post('/api/settings',{profile:{title:$('#ptitle').value}});
    document.querySelector('aside header h1').textContent=r.profile.title;msg('pmsg','Saved.')}catch(e){msg('pmsg',e.message,false)}}}
