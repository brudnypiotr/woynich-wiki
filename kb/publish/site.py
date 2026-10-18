"""Static dashboard: one self-contained HTML file (instance/site/index.html), opens from disk, no server, no internet.

Shows: counts, sources, topics, discrepancies, glossary, model usage (tokens / cost / time), recent questions,
verification report and log. Every wiki page is embedded and readable with client-side search.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from kb.core import config
from kb.knowledge import catalog


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def collect_data() -> dict:
    inst = catalog.instance()
    wiki = inst / "wiki"
    pages = {str(p.relative_to(wiki)).replace("\\", "/"): p.read_text(encoding="utf-8")
             for p in sorted(wiki.rglob("*.md"))} if wiki.exists() else {}
    srcs = catalog.all_sources()
    claims = {}
    for r in srcs:
        cj = inst / "raw" / r["id"] / "claims.json"
        if cj.exists():
            d = json.loads(cj.read_text(encoding="utf-8"))
            claims[r["id"]] = {"verified": len(d.get("verified", [])), "rejected": len(d.get("rejected", []))}
    usage = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "seconds": 0.0, "errors": 0})
    for e in _jsonl(inst / "catalog" / "metering.jsonl"):
        u = usage[e.get("stage") or e.get("task") or "other"]
        u["calls"] += 1
        u["tokens_in"] += e.get("tokens_in") or 0
        u["tokens_out"] += e.get("tokens_out") or 0
        u["cost"] += e.get("cost") or 0
        u["seconds"] += e.get("duration_s") or 0
        u["errors"] += 0 if e.get("ok", True) else 1
    gl = wiki / "glossary.json"
    topics = []
    for f in sorted((wiki / "topics").glob("*.json")) if (wiki / "topics").exists() else []:
        t = json.loads(f.read_text(encoding="utf-8"))
        topics.append({"slug": t["slug"], "title": t["title"], "claims": len(t.get("claims", [])), "conflicts": t.get("conflicts", [])})
    vr = inst / "reports" / "verify.json"
    return {
        "sources": [{"id": r["id"], "title": r["title"], "kind": r["kind"], "status": r["status"], "collected": r["collected_at"][:10],
                     "via": ", ".join(r.get("found_via") or []), **claims.get(r["id"], {"verified": 0, "rejected": 0})} for r in srcs],
        "topics": topics,
        "glossary": json.loads(gl.read_text(encoding="utf-8")) if gl.exists() else {},
        "usage": dict(usage),
        "queries": _jsonl(inst / "catalog" / "queries.jsonl")[-30:][::-1],
        "verify": json.loads(vr.read_text(encoding="utf-8")) if vr.exists() else None,
        "pages": pages,
        "generated": catalog.now(),
        "name": ((config.load("profile").get("instance") or {}).get("title") or inst.name),
    }


def build() -> Path:
    data = collect_data()
    out = catalog.instance() / "site" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out.write_text(TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(data["name"])), encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knowledge base dashboard</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#14152f;--mute:#5b6075;--line:#e3e6ef;--acc:#2969f2;--vio:#764bff;--ok:#1a8f5a;--warn:#c27a00;--bad:#c23b3b}
@media (prefers-color-scheme:dark){:root{--bg:#0d0f24;--card:#14152f;--ink:#e9ebf5;--mute:#9aa0bb;--line:#262949;--acc:#6b9bff;--vio:#a58bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header small{color:var(--mute)}
nav{display:flex;gap:4px;flex-wrap:wrap;padding:8px 24px;border-bottom:1px solid var(--line)}
nav button{border:0;background:none;color:var(--mute);padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit}
nav button.on{background:var(--acc);color:#fff}
main{padding:20px 24px;max-width:1200px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card b{display:block;font-size:24px}.card span{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:20px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}th{color:var(--mute);font-weight:600}
a{color:var(--acc);cursor:pointer;text-decoration:none}a:hover{text-decoration:underline}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:var(--line)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
input[type=search]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font:inherit;margin-bottom:14px}
.page{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 22px}
.page blockquote{margin:2px 0 8px 18px;color:var(--mute);border-left:3px solid var(--line);padding-left:10px}
.page code{background:var(--line);padding:0 4px;border-radius:4px}
.hit{padding:10px 0;border-bottom:1px solid var(--line)}.hit small{color:var(--mute)}
h2{font-size:16px;margin:4px 0 10px}
</style></head><body>
<header><h1>__TITLE__</h1><small id="gen"></small></header>
<nav id="nav"></nav><main id="main"></main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('#gen').textContent='generated '+D.generated;
function md(src,base){ // minimal Markdown: headings, lists, quotes, tables, links, bold, code
  src=src.replace(/^---[\s\S]*?\n---\n/,'');
  const lines=src.split('\n');let out='',inList=false,inTable=false;
  const inline=t=>esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,(m,a,h)=>`<a data-href="${h}">${a}</a>`);
  for(const l of lines){
    if(/^\|/.test(l)){if(/^\|[-| ]+\|$/.test(l))continue;if(!inTable){out+='<table>';inTable=true}
      out+='<tr>'+l.slice(1,-1).split('|').map(c=>'<td>'+inline(c.trim())+'</td>').join('')+'</tr>';continue}
    if(inTable){out+='</table>';inTable=false}
    let m;
    if(m=l.match(/^(#{1,3}) (.*)/)){out+=`<h${m[1].length+1}>${inline(m[2])}</h${m[1].length+1}>`;continue}
    if(m=l.match(/^\s*> ?(.*)/)){out+='<blockquote>'+inline(m[1])+'</blockquote>';continue}
    if(m=l.match(/^\s*- (.*)/)){if(!inList){out+='<ul>';inList=true}out+='<li>'+inline(m[1])+'</li>';continue}
    if(inList&&!l.trim()){out+='</ul>';inList=false;continue}
    if(l.trim())out+='<p>'+inline(l)+'</p>';
  }
  return out+(inList?'</ul>':'')+(inTable?'</table>':'');
}
function resolve(base,h){const parts=(base.split('/').slice(0,-1)).concat(h.split('/'));const st=[];
  for(const p of parts){if(p==='..')st.pop();else if(p!=='.'&&p)st.push(p)}return st.join('/')}
function openPage(path){if(!D.pages[path]){return}
  $('#main').innerHTML=`<p><a onclick="history.back()">← back</a> · <small>${esc(path)}</small></p><div class="page">${md(D.pages[path])}</div>`;
  $('#main').querySelectorAll('a[data-href]').forEach(a=>a.onclick=()=>{const t=resolve(path,a.dataset.href);if(D.pages[t]){location.hash='p:'+t}});
}
const sum=(o,k)=>Object.values(o).reduce((a,u)=>a+(u[k]||0),0);
const T={
 Overview(){const v=D.verify, conf=D.topics.reduce((a,t)=>a+t.conflicts.length,0), facts=D.sources.reduce((a,s)=>a+s.verified,0), rej=D.sources.reduce((a,s)=>a+s.rejected,0);
  return `<div class="cards">
   <div class="card"><b>${D.sources.length}</b><span>sources</span></div>
   <div class="card"><b>${facts}</b><span>verified facts (${rej} rejected)</span></div>
   <div class="card"><b>${D.topics.length}</b><span>topics</span></div>
   <div class="card"><b class="${conf?'warn':''}">${conf}</b><span>discrepancies ⚖️</span></div>
   <div class="card"><b>${Object.keys(D.glossary).length}</b><span>glossary terms</span></div>
   <div class="card"><b>${(sum(D.usage,'tokens_in')+sum(D.usage,'tokens_out')).toLocaleString()}</b><span>model tokens · ${sum(D.usage,'calls')} calls</span></div>
   <div class="card"><b class="${v&&v.problems.length?'bad':'ok'}">${v?v.ok+'/'+v.facts:'–'}</b><span>citations verified</span></div>
   <div class="card"><b>${D.queries.length}</b><span>recent questions</span></div></div>
   <h2>Start here</h2><p>${['index.md','discrepancies.md','glossary.md','hot.md'].filter(p=>D.pages[p]).map(p=>`<a href="#p:${p}">${p}</a>`).join(' · ')}</p>`},
 Sources(){return `<table><tr><th>Title</th><th>Kind</th><th>Status</th><th>Facts</th><th>Rejected</th><th>Collected</th><th>Found via</th></tr>`+
  D.sources.map(s=>`<tr><td><a href="#p:sources/${s.id}.md">${esc(s.title)}</a></td><td><span class="tag">${s.kind}</span></td><td>${s.status}</td><td>${s.verified}</td><td class="${s.rejected?'warn':''}">${s.rejected}</td><td>${s.collected}</td><td>${esc(s.via)}</td></tr>`).join('')+'</table>'},
 Topics(){return `<table><tr><th>Topic</th><th>Facts</th><th>Discrepancies</th></tr>`+D.topics.map(t=>`<tr><td><a href="#p:topics/${t.slug}.md">${esc(t.title)}</a></td><td>${t.claims}</td><td class="${t.conflicts.length?'warn':''}">${t.conflicts.length?'⚖️ '+t.conflicts.length:''}</td></tr>`).join('')+'</table>'},
 Discrepancies(){const rows=D.topics.flatMap(t=>t.conflicts.map(c=>`<tr><td><a href="#p:topics/${t.slug}.md">${esc(t.title)}</a></td><td>⚖️ ${esc(c.explanation)}</td></tr>`));
  return rows.length?`<table><tr><th>Topic</th><th>What disagrees</th></tr>${rows.join('')}</table>`:'<p>No discrepancies found yet.</p>'},
 Glossary(){return `<table><tr><th>Term</th><th>Meaning</th><th>Defined in</th></tr>`+Object.entries(D.glossary).map(([k,e])=>`<tr><td><b>${esc(k)}</b></td><td>${esc(e.expansion)}</td><td>${e.cites.slice(0,3).map(c=>`<a href="#p:sources/${c.source_id}.md">${esc((D.sources.find(s=>s.id===c.source_id)||{}).title||c.source_id)}</a> · ${esc(c.locator)}`).join('<br>')}</td></tr>`).join('')+'</table>'},
 Usage(){const rows=Object.entries(D.usage);return `<p>Every model call is metered (tokens, time, cost when prices are set in config/models.yaml).</p><table><tr><th>Stage</th><th>Calls</th><th>Tokens in</th><th>Tokens out</th><th>Cost</th><th>Time (s)</th><th>Errors</th></tr>`+
  rows.map(([k,u])=>`<tr><td>${esc(k)}</td><td>${u.calls}</td><td>${u.tokens_in.toLocaleString()}</td><td>${u.tokens_out.toLocaleString()}</td><td>${u.cost?u.cost.toFixed(4):'–'}</td><td>${u.seconds.toFixed(1)}</td><td class="${u.errors?'bad':''}">${u.errors}</td></tr>`).join('')+'</table>'},
 Questions(){return D.queries.length?`<table><tr><th>When</th><th>Question</th><th>Answered</th><th>Time (s)</th></tr>`+D.queries.map(q=>`<tr><td>${esc(q.at.slice(0,16))}</td><td>${esc(q.question)}</td><td class="${q.not_found?'warn':'ok'}">${q.not_found?'not found':q.sentences+' sentences'}</td><td>${q.seconds}</td></tr>`).join('')+'</table>':'<p>No questions yet. Ask with <code>kb ask "…"</code> or <code>/kb-ask</code> in Copilot CLI.</p>'},
 Verify(){const v=D.verify;if(!v)return '<p>Run <code>kb verify</code>.</p>';
  return `<p>${v.pages} pages · ${v.facts} cited facts · <b class="${v.problems.length?'bad':'ok'}">${v.ok} verified</b> · ${v.problems.length} problems</p>`+(v.problems.length?`<table><tr><th>Page</th><th>Line</th><th>Issue</th></tr>${v.problems.map(p=>`<tr><td><a href="#p:${p.page}">${esc(p.page)}</a></td><td>${p.line}</td><td>${esc(p.issue)}</td></tr>`).join('')}</table>`:'')},
 Search(){setTimeout(()=>{const i=$('#q');i.focus();i.oninput=()=>{const w=i.value.toLowerCase().split(/\s+/).filter(x=>x.length>1);
   const res=w.length?Object.entries(D.pages).map(([p,t])=>{const l=t.toLowerCase();return [p,t,w.reduce((a,x)=>a+(l.split(x).length-1),0)]}).filter(r=>r[2]).sort((a,b)=>b[2]-a[2]).slice(0,30):[];
   $('#res').innerHTML=res.map(([p,t,n])=>{const k=t.toLowerCase().indexOf(w[0]);return `<div class="hit"><a href="#p:${p}">${esc((t.match(/^# (.*)$/m)||[,p])[1])}</a> <small>${esc(p)} · ${n} hits</small><br><small>${esc(t.slice(Math.max(0,k-80),k+160))}</small></div>`}).join('')||'<p><small>No matches.</small></p>'}},0);
  return '<input type="search" id="q" placeholder="Search all wiki pages…"><div id="res"></div>'},
 Log(){return D.pages['log.md']?`<div class="page">${md(D.pages['log.md'])}</div>`:'<p>No log yet.</p>'}
};
$('#nav').innerHTML=Object.keys(T).map(k=>`<button data-t="${k}">${k}</button>`).join('');
$('#nav').onclick=e=>{if(e.target.dataset.t)location.hash=e.target.dataset.t};
function route(){const h=decodeURIComponent(location.hash.slice(1))||'Overview';
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===h));
  if(h.startsWith('p:'))return openPage(h.slice(2));$('#main').innerHTML=(T[h]||T.Overview)()}
window.onhashchange=route;route();
</script></body></html>
"""
