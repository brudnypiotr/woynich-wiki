// Settings: the model, then the parts shared with the first-run setup (Copilot, Jira, repositories), other keys, the title.
import {$, esc, topbar, msg} from './ui.js';
import {api, post} from './api.js';
import {mark, status} from './shell.js';
import {mountCopilot} from './parts/copilot.js';
import {mountJira} from './parts/jira.js';
import {mountRepos} from './parts/repos.js';
import {secretRow, bindSecrets} from './parts/secret.js';

export async function openSettings(){mark('settings');
  $('#main').innerHTML=topbar('Settings')+`<div class="scroll"><div class="col wide" id="setc"><p class="empty">Loading…</p></div></div>`;
  let C;try{C=await api('/api/settings')}catch(e){$('#setc').innerHTML=`<p class="errmsg">${esc(e.message)}</p>`;return}
  const m=C.model,p=C.profile,inp=(id,v,ph='',extra='')=>`<input id="${id}" value="${esc(v)}" placeholder="${esc(ph)}" list="mlist" ${extra}>`;
  const SRC={env:'set by KB_MODEL',override:'one model for all tasks',tiers:'per task tier'};
  $('#setc').innerHTML=`<div class="pagehead"><div class="kicker">Settings</div><h2>Models, sign-in and keys</h2>
    <p>Saved in this knowledge base's own config (<code>instance/config</code>). Keys go to Windows Credential Manager and are never shown again.</p></div>
   <datalist id="mlist"><option value="auto"></option></datalist>
   <section class="set"><h3>Model</h3><p class="d">Which model writes the wiki and answers questions. Each question or source costs AI credits (shown under answers and in the sidebar).</p>
    <div class="eff"><span class="sub" style="margin:0">Now in use</span><b id="effm">${esc(m.effective)}</b><span class="badge">${SRC[m.source]}</span></div>
    ${m.env?`<p class="errmsg">The environment variable KB_MODEL=${esc(m.env)} overrides everything below until it is removed.</p>`:''}
    <div class="grid2"><div class="f" style="grid-column:1/-1"><label for="ov">One model for every task</label>${inp('ov',m.override,'empty = use the tiers below')}<small>Like <code>kb model set</code>. Leave empty to choose per tier.</small></div>
     ${['basic','standard','premium'].map(t=>`<div class="f"><label for="t-${t}">${t[0].toUpperCase()+t.slice(1)} tier</label>${inp('t-'+t,m.tiers[t],'auto')}<small>${Object.entries(m.tasks).filter(x=>x[1]===t).map(x=>x[0]).join(', ')||'no tasks'}</small></div>`).join('')}
     <div class="f"><label for="tmo">Agent time limit (minutes)</label><input id="tmo" type="number" min="1" max="240" value="${Math.round(m.timeout_s/60)}"><small>Per source or question; long documents need more.</small></div></div>
    <div class="btns"><button class="pri" id="msave">Save model settings</button><button class="ghost" id="mload">Load available models</button><span id="mmsg"></span></div></section>
   <section class="set"><h3>GitHub Copilot account</h3><p class="d">The models run through your GitHub Copilot subscription.</p><div id="p-copilot"></div></section>
   <section class="set"><h3>Jira</h3><p class="d">The Jira the assistant may read (read only).</p><div id="p-jira"></div></section>
   <section class="set"><h3>Code repositories</h3><p class="d">Local clones the assistant may read (never change). The role and description tell
    it which tier holds what; the name is used in citations (<code>name/path:line@commit</code>).</p><div id="p-repos"></div></section>
   <section class="set"><h3>Other keys and tokens</h3><p class="d">Stored for your Windows user only. This page can tell whether a key is set, never what it is.</p>
    <div id="secs"></div>
    <div class="sec-row"><div class="nm"><b>Another key</b><small>Name: lowercase letters, digits, dashes.</small></div><input id="nk-name" placeholder="name, e.g. confluence-token"><div class="b"></div>
     <div></div><input id="nk-val" type="password" placeholder="value" autocomplete="off"><div class="b"><button class="ghost" id="nk-add">Add</button></div></div></section>
   <section class="set"><h3>Knowledge base</h3><p class="d">Name shown in the sidebar.</p>
    <div class="f"><label for="ptitle">Title</label><input id="ptitle" value="${esc(p.title)}"></div>
    <div class="btns"><button class="pri" id="psave">Save</button><a class="ghost" href="#setup">Run the first-run setup again</a><span id="pmsg"></span></div></section>`;
  mountCopilot($('#p-copilot'),C);mountJira($('#p-jira'),C);mountRepos($('#p-repos'),C);
  $('#msave').onclick=async()=>{try{const r=await post('/api/settings',{model:{override:$('#ov').value,tiers:{basic:$('#t-basic').value,standard:$('#t-standard').value,premium:$('#t-premium').value},timeout_s:Math.round(+$('#tmo').value*60)}});
    $('#effm').textContent=r.model.effective;$('.eff .badge').textContent=SRC[r.model.source];msg('mmsg','Saved. The next question or ingest uses '+r.model.effective+'.');status()}catch(e){msg('mmsg',e.message,false)}};
  $('#mload').onclick=async()=>{const b=$('#mload');b.disabled=true;msg('mmsg','Asking GitHub Copilot… (a few seconds)');
    try{const l=await api('/api/settings/models');$('#mlist').innerHTML='<option value="auto"></option>'+l.map(x=>`<option value="${esc(x.id)}">${esc(x.name||'')}${x.policy&&x.policy!=='enabled'?' ('+esc(x.policy)+')':''}</option>`).join('');
      msg('mmsg',l.length+' models available: click a model field to pick one.')}catch(e){msg('mmsg',e.message,false)}finally{b.disabled=false}};
  // keys and tokens other than the ones the parts above own (Copilot token, Jira token)
  const OWNED=new Set(['copilot-github-token','jira-token']);
  const secs=st=>{$('#secs').innerHTML=(st.error?`<p class="errmsg">Secret store not available: ${esc(st.error)}</p>`:'')+(st.items.filter(x=>!OWNED.has(x.name)).map(x=>secretRow(x)).join('')||'<p class="empty">No other keys.</p>')};
  secs(C.secrets);bindSecrets($('#secs'),st=>secs(st));
  $('#nk-add').onclick=async()=>{const n=$('#nk-name').value.trim(),v=$('#nk-val').value;if(!n||!v)return;
    try{secs(await post('/api/secrets/'+encodeURIComponent(n),{value:v}));$('#nk-name').value=$('#nk-val').value=''}catch(e){alert(e.message)}};
  $('#psave').onclick=async()=>{try{const r=await post('/api/settings',{profile:{title:$('#ptitle').value}});
    document.querySelector('aside header h1').textContent=r.profile.title;msg('pmsg','Saved.')}catch(e){msg('pmsg',e.message,false)}}}
