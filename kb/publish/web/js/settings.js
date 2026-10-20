// Settings: models, GitHub Copilot sign-in, keys and tokens, Jira and title, code repositories.
import {$, esc, topbar, msg} from './ui.js';
import {api, post} from './api.js';
import {mark, status} from './shell.js';

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
   <section class="set"><h3>GitHub Copilot account</h3><p class="d">The models run through your GitHub Copilot subscription.</p>
    <div class="btns" style="margin-top:0"><button class="ghost" id="acheck">Check sign-in</button><button class="ghost" id="alogin">Sign in with GitHub…</button><span id="amsg"></span></div><div id="acc"></div></section>
   <section class="set"><h3>Keys and tokens</h3><p class="d">Stored for your Windows user only. This page can tell whether a key is set, never what it is.</p>
    <div class="btns" style="margin:0 0 6px"><button class="ghost" id="ctest">Test connections</button><span class="sub" style="margin:0;font-size:12px">GitHub Copilot sign-in and one Jira request; no AI credits used</span></div><div id="cres" class="kv" style="margin:4px 0 12px"></div>
    <div id="secs"></div>
    <div class="sec-row"><div class="nm"><b>Another key</b><small>Name: lowercase letters, digits, dashes.</small></div><input id="nk-name" placeholder="name, e.g. confluence-token"><div class="b"></div>
     <div></div><input id="nk-val" type="password" placeholder="value" autocomplete="off"><div class="b"><button class="ghost" id="nk-add">Add</button></div></div></section>
   <section class="set"><h3>Knowledge base</h3><p class="d">Name shown in the sidebar, and the Jira the assistant may read.</p>
    <div class="grid2"><div class="f" style="grid-column:1/-1"><label for="ptitle">Title</label><input id="ptitle" value="${esc(p.title)}"></div>
     <div class="f"><label for="pjira">Jira URL</label><input id="pjira" value="${esc(p.jira_base_url)}" placeholder="https://jira.example.com"><small>Token: <b>Jira token</b> under Keys and tokens.</small></div>
     <div class="f"><label for="pmail">Jira e-mail</label><input id="pmail" value="${esc(p.jira_email)}" placeholder="Jira Cloud only"><small>Leave empty for Jira Data Center.</small></div></div>
    <div class="btns"><button class="pri" id="psave">Save</button><span id="pmsg"></span></div></section>
   <section class="set"><h3>Code repositories</h3><p class="d">Local clones the assistant may read (never change). The role and description tell
    it which tier holds what; the name is used in citations (<code>name/path:line@commit</code>).</p>
    <datalist id="rolelist">${['frontend (UI)','backend server','API / services','database (schema, procedures)','rules / configuration','batch / integration','shared library','tests','infrastructure / deployment'].map(x=>`<option value="${x}">`).join('')}</datalist>
    <div id="repos"></div>
    <div class="btns" style="margin-top:6px"><button class="ghost" id="radd">+ Add repository</button></div>
    <div class="f" style="margin-top:16px"><label for="arch">How the parts fit together</label>
     <textarea id="arch" rows="5" placeholder="e.g. Three tiers: the Angular frontend (inv-web) calls the Java server (inv-server) over REST; the server keeps orders and rules in Oracle (schema and stored procedures in inv-db). Rule parameters come from XML in inv-rules, loaded by the server at start.">${esc(p.architecture)}</textarea>
     <small>Plain words are enough: tiers, who calls whom, where data lives, which repository holds what.</small></div>
    <div class="btns"><button class="pri" id="rsave">Save repositories</button><span id="rmsg"></span></div></section>`;
  $('#msave').onclick=async()=>{try{const r=await post('/api/settings',{model:{override:$('#ov').value,tiers:{basic:$('#t-basic').value,standard:$('#t-standard').value,premium:$('#t-premium').value},timeout_s:Math.round(+$('#tmo').value*60)}});
    $('#effm').textContent=r.model.effective;$('.eff .badge').textContent=SRC[r.model.source];msg('mmsg','Saved. The next question or ingest uses '+r.model.effective+'.');status()}catch(e){msg('mmsg',e.message,false)}};
  $('#mload').onclick=async()=>{const b=$('#mload');b.disabled=true;msg('mmsg','Asking GitHub Copilot… (a few seconds)');
    try{const l=await api('/api/settings/models');$('#mlist').innerHTML='<option value="auto"></option>'+l.map(x=>`<option value="${esc(x.id)}">${esc(x.name||'')}${x.policy&&x.policy!=='enabled'?' ('+esc(x.policy)+')':''}</option>`).join('');
      msg('mmsg',l.length+' models available: click a model field to pick one.')}catch(e){msg('mmsg',e.message,false)}finally{b.disabled=false}};
  $('#acheck').onclick=async()=>{const b=$('#acheck');b.disabled=true;msg('amsg','Checking…');
    try{const a=await api('/api/settings/account');$('#amsg').textContent='';const au=a.auth||{},q=a.quota||{};
      const ok=au.is_authenticated??au.isAuthenticated,who=au.login||au.user||'';
      $('#acc').innerHTML=`<div class="kv"><span>Signed in</span><b class="${ok?'okmsg':'errmsg'}" style="font-size:14px">${au.error?esc(au.error):(ok?'yes'+(who?' as '+esc(who):''):'no')}</b>
        ${au.auth_type||au.authType?`<span>Method</span><span style="color:var(--ink)">${esc(au.auth_type||au.authType)}</span>`:''}
        ${a.token_from_store?'<span>Token</span><span style="color:var(--ink)">GitHub token from Keys and tokens</span>':''}
        ${q.error?`<span>Quota</span><span class="errmsg">${esc(q.error)}</span>`:Object.entries(q).map(([k,v])=>`<span>${esc(k.replace(/_/g,' '))}</span><div>${v.entitlement?`${v.used??'?'} of ${v.entitlement} used`:'unlimited'}${v.resets?` · resets ${esc(String(v.resets).slice(0,10))}`:''}${v.remaining_pct!=null&&v.entitlement?`<div class="meter"><i style="width:${Math.max(0,Math.min(100,100-v.remaining_pct))}%"></i></div>`:''}</div>`).join('')}</div>`}
    catch(e){msg('amsg',e.message,false)}finally{b.disabled=false}};
  $('#ctest').onclick=()=>{runCheck('copilot');runCheck('jira')};
  $('#alogin').onclick=async()=>{try{const r=await post('/api/settings/login');msg('amsg',r.message,r.ok)}catch(e){msg('amsg',e.message,false)}};
  const CHK={},SVC={'jira-token':'jira','copilot-github-token':'copilot'},LBL={copilot:'GitHub Copilot',jira:'Jira'};let LASTSEC=C.secrets;
  const chkLine=name=>{const v=CHK[SVC[name]];if(!SVC[name]||!v)return '';
    return v.running?'<small class="sub chk">testing…</small>':`<small class="chk ${v.ok===true?'okmsg':v.ok===false?'errmsg':'sub'}">${v.ok===true?'✓':v.ok===false?'✗':'–'} ${esc(v.detail)}</small>`};
  const showChecks=()=>{$('#cres').innerHTML=Object.entries(CHK).map(([k,v])=>`<span>${LBL[k]||k}</span><b class="${v.running?'sub':v.ok===true?'okmsg':v.ok===false?'errmsg':'sub'}" style="font-size:14px;margin:0">${v.running?'testing…':(v.ok===true?'✓ ':v.ok===false?'✗ ':'– ')+esc(v.detail)}</b>`).join('');secs(LASTSEC)};
  const runCheck=async what=>{CHK[what]={running:true};showChecks();
    try{const r=await api('/api/settings/check?what='+what);Object.assign(CHK,r)}catch(e){CHK[what]={ok:false,detail:e.message}}showChecks()};
  const secs=st=>{LASTSEC=st;$('#secs').innerHTML=(st.error?`<p class="errmsg">Secret store not available: ${esc(st.error)}</p>`:'')+st.items.map(x=>`<div class="sec-row" data-n="${esc(x.name)}"><div class="nm"><b>${esc(x.label)} <span class="badge ${x.set?'done':'off'}">${x.set?'Set':x.set===null?'?':'Not set'}</span></b><code>${esc(x.name)}</code><small>${esc(x.help)}</small>${chkLine(x.name)}</div>
     <input type="password" placeholder="${x.set?'Paste a new value to replace':'Paste the value'}" autocomplete="off"><div class="b"><button class="ghost" data-a="set">Save</button>${x.set?'<button class="ghost" data-a="del">Remove</button>':''}</div></div>`).join('')};
  secs(C.secrets);
  $('#secs').onclick=async e=>{const b=e.target.closest('button');if(!b)return;const row=b.closest('.sec-row'),n=row.dataset.n,v=row.querySelector('input').value;
    try{if(b.dataset.a==='del'){if(!confirm('Remove '+n+' from Windows Credential Manager?'))return;secs(await post('/api/secrets/'+n+'/delete'))}
      else{if(!v.trim())return row.querySelector('input').focus();secs(await post('/api/secrets/'+n,{value:v}))}
      if(SVC[n])runCheck(SVC[n])}catch(err){alert(err.message)}};
  $('#nk-add').onclick=async()=>{const n=$('#nk-name').value.trim(),v=$('#nk-val').value;if(!n||!v)return;
    try{secs(await post('/api/secrets/'+encodeURIComponent(n),{value:v}));$('#nk-name').value=$('#nk-val').value=''}catch(e){alert(e.message)}};
  let RP=p.code_repos.map(r=>({...r}));
  const rstate=r=>r.exists===undefined?'':(r.exists?`<span class="st ok">✓ ${esc(r.branch||'?')}@${esc(r.commit||'?')}${r.dirty?' · local changes':''}</span>`:'<span class="st bad">⚠ folder not found</span>');
  const rrender=()=>{$('#repos').innerHTML=RP.length?RP.map((r,i)=>`<div class="repo" data-i="${i}">
     <div class="f"><label>Name</label><input data-k="name" value="${esc(r.name||'')}" placeholder="inv-server"></div>
     <div class="f"><label>Role</label><input data-k="role" list="rolelist" value="${esc(r.role||'')}" placeholder="backend server"></div>
     <button class="icon x" data-del="${i}" title="Remove from the list (the folder stays)">×</button>
     <div class="f wide"><label>Folder</label><input data-k="path" value="${esc(r.path||'')}" placeholder="C:\\Users\\you\\DEV\\inv-server"></div>${rstate(r)}
     <div class="f wide"><label>What it contains, where to look</label><textarea data-k="description" rows="2" placeholder="Java server: rule engine (package rules/), order services, REST API for the frontend.">${esc(r.description||'')}</textarea></div></div>`).join(''):'<p class="empty">No repositories yet.</p>'};
  rrender();
  $('#repos').oninput=e=>{const box=e.target.closest('.repo'),k=e.target.dataset.k;if(box&&k){RP[+box.dataset.i][k]=e.target.value;RP[+box.dataset.i].exists=undefined}};
  $('#repos').onclick=e=>{const d=e.target.closest('[data-del]');if(d){RP.splice(+d.dataset.del,1);rrender()}};
  $('#radd').onclick=()=>{RP.push({name:'',role:'',path:'',description:''});rrender();$('#repos .repo:last-child input').focus()};
  $('#rsave').onclick=async()=>{try{const r=await post('/api/settings',{repos:{list:RP,architecture:$('#arch').value}});
    RP=r.profile.code_repos.map(x=>({...x}));rrender();const bad=RP.filter(x=>!x.exists).length;
    msg('rmsg',bad?`Saved; ${bad} folder${bad>1?'s':''} not found on this computer.`:'Saved. The next question uses them.',!bad)}catch(e){msg('rmsg',e.message,false)}};
  $('#psave').onclick=async()=>{try{const r=await post('/api/settings',{profile:{title:$('#ptitle').value,jira_base_url:$('#pjira').value,jira_email:$('#pmail').value}});
    document.querySelector('aside header h1').textContent=r.profile.title;msg('pmsg','Saved.');
    if(r.profile.jira_base_url)runCheck('jira')}catch(e){msg('pmsg',e.message,false)}};
  runCheck('copilot');if(p.jira_base_url)runCheck('jira')}  // test what is configured as soon as Settings opens
