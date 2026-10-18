"""Static dashboard: one self-contained HTML file (instance/site/index.html), opens from disk, no server, no internet.

Shows: counts, sources, topics, discrepancies, glossary, model usage (tokens / cost / time), recent questions,
verification report and log. Every wiki page is embedded and readable with client-side search.
"""
from __future__ import annotations

import base64
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


def _data_uri(p: Path) -> str:
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[p.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _branding() -> str:
    """Optional company branding, kept in the instance (never in the blueprint): instance/branding/logo.(svg|png)
    and background.(jpg|png). Embedded so the dashboard stays a single file that works offline."""
    d = catalog.instance() / "branding"
    find = lambda stem: next((p for ext in (".svg", ".png", ".jpg", ".jpeg") if (p := d / f"{stem}{ext}").exists()), None)
    out = ""
    if (logo := find("logo")):
        out += f'<img src="{_data_uri(logo)}" alt="">'
    if (bg := find("background")):
        out += f'<style>header{{--hdr-bg:url("{_data_uri(bg)}")}}</style>'
    return out


def build() -> Path:
    data = collect_data()
    out = catalog.instance() / "site" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(data["name"])).replace("__LOGO__", _branding())
    out.write_text(page, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knowledge base</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* Palette: navy, blue, violet; Red Hat Display (falls back to Segoe UI offline). */
:root{--navy:#06103d;--navy2:#181a3a;--navy3:#14152f;--blue:#2969f2;--vio:#764bff;--vio-soft:#efeaff;--blue-soft:#e8efff;
  --bg:#f8f8f8;--card:#fff;--ink:#111827;--ink2:#374151;--mute:#6b7280;--line:#e5e7eb;--ok:#1f9d6b;--warn:#b86e0b;--bad:#c23b3b;--r:12px}
@media (prefers-color-scheme:dark){:root{--bg:#0d0f24;--card:#14152f;--ink:#eef0fa;--ink2:#d6dcf7;--mute:#9aa3c7;--line:#262949;--vio-soft:rgba(118,75,255,.18);--blue-soft:rgba(41,105,242,.18)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 'Red Hat Display',system-ui,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased}
header{background:var(--navy2) var(--hdr-bg,none) center/cover;color:#fff;padding:18px 28px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;
  border-bottom:3px solid var(--vio)}
header img{height:30px;width:auto}
header .t{display:flex;flex-direction:column}
header h1{font-size:20px;margin:0;font-weight:800;letter-spacing:-.01em}
header small{color:#b9c1ea;font-size:12px}
header .k{margin-left:auto;font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#b9a6ff}
.wrap{display:grid;grid-template-columns:210px 1fr;min-height:calc(100vh - 70px)}
nav{background:var(--navy3);padding:16px 10px;display:flex;flex-direction:column;gap:2px}
nav button{border:0;background:none;color:#c3c9ea;padding:9px 14px;border-radius:8px;cursor:pointer;font:inherit;font-weight:600;text-align:left;display:flex;justify-content:space-between}
nav button:hover{background:rgba(255,255,255,.06);color:#fff}
nav button.on{background:var(--vio);color:#fff}
nav button .n{font-size:12px;opacity:.75;font-weight:700}
main{padding:26px 30px;max-width:1240px;width:100%}
h2{font-size:22px;margin:0 0 4px;font-weight:800;color:var(--navy);letter-spacing:-.01em}
@media (prefers-color-scheme:dark){h2{color:#fff}}
.kicker{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--vio);margin-bottom:4px}
.sub{color:var(--mute);margin:0 0 18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:0 1px 2px rgba(6,16,61,.05);position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--vio)}
.card.blue::before{background:var(--blue)}.card.warn::before{background:#d98a1b}.card.ok::before{background:var(--ok)}.card.bad::before{background:var(--bad)}
.card b{display:block;font-size:28px;font-weight:800;color:var(--navy);line-height:1.1}
@media (prefers-color-scheme:dark){.card b{color:#fff}}
.card span{color:var(--mute);font-size:13px;font-weight:500}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;margin-bottom:18px}
.panel h3{margin:0 0 8px;font-size:15px;color:var(--navy)}
@media (prefers-color-scheme:dark){.panel h3,.page h3,.page h4{color:#b9a6ff}a{color:#7da6ff}}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin-bottom:22px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}
th{background:var(--navy);color:#fff;font-weight:600;font-size:12px;letter-spacing:.04em;text-transform:uppercase}
tr:last-child td{border-bottom:0}tr:hover td{background:var(--blue-soft)}
a{color:var(--blue);cursor:pointer;text-decoration:none;font-weight:600}a:hover{text-decoration:underline}
.tag{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;background:var(--vio-soft);color:var(--vio)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
input[type=search]{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;margin-bottom:14px;outline:none}
input[type=search]:focus{border-color:var(--vio);box-shadow:0 0 0 3px var(--vio-soft)}
.page{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:22px 26px}
.page h2{font-size:22px}.page h3{color:var(--navy);margin-top:18px}
.page blockquote{margin:2px 0 10px 18px;color:var(--mute);border-left:3px solid var(--vio);padding-left:10px;font-style:italic}
.page code{background:var(--vio-soft);padding:0 5px;border-radius:4px}
.page li{margin:4px 0}
.hit{padding:12px 0;border-bottom:1px solid var(--line)}.hit small{color:var(--mute)}
.conf{border-left:4px solid #d98a1b;background:rgba(217,138,27,.08);padding:10px 14px;border-radius:0 10px 10px 0;margin-bottom:10px}
.links a{display:inline-block;margin:4px 8px 4px 0;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card)}
@media (prefers-color-scheme:dark){.page h3,.page h4,.panel h3{color:#b9a6ff}}
@media (max-width:760px){.wrap{grid-template-columns:1fr}nav{flex-direction:row;flex-wrap:wrap}main{padding:18px 16px}}
</style></head><body>
<header>__LOGO__<div class="t"><h1>__TITLE__</h1><small id="gen"></small></div><span class="k">Knowledge base</span></header>
<div class="wrap"><nav id="nav"></nav><main id="main"></main></div>
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
const head=(k,t,sub)=>`<div class="kicker">${k}</div><h2>${t}</h2><p class="sub">${sub}</p>`;
const sum=(o,k)=>Object.values(o).reduce((a,u)=>a+(u[k]||0),0);
const T={
 Overview(){const v=D.verify, conf=D.topics.reduce((a,t)=>a+t.conflicts.length,0), facts=D.sources.reduce((a,s)=>a+s.verified,0), rej=D.sources.reduce((a,s)=>a+s.rejected,0);
  const recent=(D.pages['hot.md']||'').split('\n').filter(l=>l.startsWith('- ')).slice(0,6);
  return head('Overview','State of the knowledge base','Every fact on these pages links to its exact source; quotes are checked by code.')+`<div class="cards">
   <div class="card blue"><b>${D.sources.length}</b><span>sources</span></div>
   <div class="card"><b>${facts}</b><span>verified facts · ${rej} rejected</span></div>
   <div class="card"><b>${D.topics.length}</b><span>topics</span></div>
   <div class="card ${conf?'warn':'ok'}"><b>${conf}</b><span>discrepancies ⚖️</span></div>
   <div class="card ${v&&v.problems.length?'bad':'ok'}"><b>${v?v.ok+'/'+v.facts:'–'}</b><span>citations verified</span></div>
   <div class="card blue"><b>${Object.keys(D.glossary).length}</b><span>glossary terms</span></div>
   <div class="card"><b>${(sum(D.usage,'tokens_in')+sum(D.usage,'tokens_out')).toLocaleString()}</b><span>model tokens · ${sum(D.usage,'calls')} calls</span></div>
   <div class="card blue"><b>${D.queries.length}</b><span>recent questions</span></div></div>
   <div class="panel"><h3>Start here</h3><div class="links">${[['index.md','Index'],['discrepancies.md','Discrepancies ⚖️'],['glossary.md','Glossary']].filter(p=>D.pages[p[0]]).map(p=>`<a href="#p:${p[0]}">${p[1]}</a>`).join('')}</div></div>
   <div class="panel"><h3>Recent activity</h3>${recent.length?'<ul>'+recent.map(l=>'<li>'+esc(l.slice(2))+'</li>').join('')+'</ul>':'<p class="sub">Nothing yet.</p>'}</div>`},
 Sources(){return head('Sources','Sources','Originals are kept unchanged; each one is a commit in the knowledge base.')+`<table><tr><th>Title</th><th>Kind</th><th>Status</th><th>Facts</th><th>Rejected</th><th>Collected</th><th>Found via</th></tr>`+
  D.sources.map(s=>`<tr><td><a href="#p:sources/${s.id}.md">${esc(s.title)}</a></td><td><span class="tag">${s.kind}</span></td><td>${s.status}</td><td>${s.verified}</td><td class="${s.rejected?'warn':''}">${s.rejected}</td><td>${s.collected}</td><td>${esc(s.via)}</td></tr>`).join('')+'</table>'},
 Topics(){return head('Topics','Topics','Pages built from verified facts across all sources.')+`<table><tr><th>Topic</th><th>Facts</th><th>Discrepancies</th></tr>`+D.topics.map(t=>`<tr><td><a href="#p:topics/${t.slug}.md">${esc(t.title)}</a></td><td>${t.claims}</td><td class="${t.conflicts.length?'warn':''}">${t.conflicts.length?'⚖️ '+t.conflicts.length:''}</td></tr>`).join('')+'</table>'},
 Discrepancies(){const rows=D.topics.flatMap(t=>t.conflicts.map(c=>`<tr><td><a href="#p:topics/${t.slug}.md">${esc(t.title)}</a></td><td>⚖️ ${esc(c.explanation)}</td></tr>`));
  return head('Discrepancies','Discrepancies ⚖️','Sources that disagree. Experts decide which one wins (authority, validity date).')+(rows.length?`<table><tr><th>Topic</th><th>What disagrees</th></tr>${rows.join('')}</table>`:'<p class="sub">No discrepancies found yet.</p>')},
 Glossary(){return head('Glossary','Glossary','Terms and acronyms found in the sources, by rules (not by the model).')+`<table><tr><th>Term</th><th>Meaning</th><th>Defined in</th></tr>`+Object.entries(D.glossary).map(([k,e])=>`<tr><td><b>${esc(k)}</b></td><td>${esc(e.expansion)}</td><td>${e.cites.slice(0,3).map(c=>`<a href="#p:sources/${c.source_id}.md">${esc((D.sources.find(s=>s.id===c.source_id)||{}).title||c.source_id)}</a> · ${esc(c.locator)}`).join('<br>')}</td></tr>`).join('')+'</table>'},
 Usage(){const rows=Object.entries(D.usage);return head('Usage','AI usage','Every model call is metered: tokens, time, and cost when prices are set in config/models.yaml.')+`<table><tr><th>Stage</th><th>Calls</th><th>Tokens in</th><th>Tokens out</th><th>Cost</th><th>Time (s)</th><th>Errors</th></tr>`+
  rows.map(([k,u])=>`<tr><td>${esc(k)}</td><td>${u.calls}</td><td>${u.tokens_in.toLocaleString()}</td><td>${u.tokens_out.toLocaleString()}</td><td>${u.cost?u.cost.toFixed(4):'–'}</td><td>${u.seconds.toFixed(1)}</td><td class="${u.errors?'bad':''}">${u.errors}</td></tr>`).join('')+'</table>'},
 Questions(){return head('Questions','Recent questions','Asked with kb ask or /kb-ask in Copilot CLI.')+(D.queries.length?`<table><tr><th>When</th><th>Question</th><th>Answered</th><th>Time (s)</th></tr>`+D.queries.map(q=>`<tr><td>${esc(q.at.slice(0,16))}</td><td>${esc(q.question)}</td><td class="${q.not_found?'warn':'ok'}">${q.not_found?'not found':q.sentences+' sentences'}</td><td>${q.seconds}</td></tr>`).join('')+'</table>':'<p class="sub">No questions yet.</p>')},
 Verify(){const v=D.verify;if(!v)return head('Verify','Citation check','')+'<p>Run <code>kb verify</code>.</p>';
  return head('Verify','Citation check','Every quote on every page is matched against its source.')+`<p>${v.pages} pages · ${v.facts} cited facts · <b class="${v.problems.length?'bad':'ok'}">${v.ok} verified</b> · ${v.problems.length} problems</p>`+(v.problems.length?`<table><tr><th>Page</th><th>Line</th><th>Issue</th></tr>${v.problems.map(p=>`<tr><td><a href="#p:${p.page}">${esc(p.page)}</a></td><td>${p.line}</td><td>${esc(p.issue)}</td></tr>`).join('')}</table>`:'')},
 Search(){setTimeout(()=>{const i=$('#q');i.focus();i.oninput=()=>{const w=i.value.toLowerCase().split(/\s+/).filter(x=>x.length>1);
   const res=w.length?Object.entries(D.pages).map(([p,t])=>{const l=t.toLowerCase();return [p,t,w.reduce((a,x)=>a+(l.split(x).length-1),0)]}).filter(r=>r[2]).sort((a,b)=>b[2]-a[2]).slice(0,30):[];
   $('#res').innerHTML=res.map(([p,t,n])=>{const k=t.toLowerCase().indexOf(w[0]);return `<div class="hit"><a href="#p:${p}">${esc((t.match(/^# (.*)$/m)||[,p])[1])}</a> <small>${esc(p)} · ${n} hits</small><br><small>${esc(t.slice(Math.max(0,k-80),k+160))}</small></div>`}).join('')||'<p><small>No matches.</small></p>'}},0);
  return head('Search','Search','All wiki pages, in this browser, offline.')+'<input type="search" id="q" placeholder="Search all wiki pages…"><div id="res"></div>'},
 Log(){return head('Log','Change log','Newest first. Every change is also a Git commit.')+(D.pages['log.md']?`<div class="page">${md(D.pages['log.md'])}</div>`:'<p>No log yet.</p>')}
};
const N={Sources:D.sources.length,Topics:D.topics.length,Discrepancies:D.topics.reduce((a,t)=>a+t.conflicts.length,0),Glossary:Object.keys(D.glossary).length,Questions:D.queries.length};
$('#nav').innerHTML=Object.keys(T).map(k=>`<button data-t="${k}">${k}${N[k]?`<span class="n">${N[k]}</span>`:''}</button>`).join('');
$('#nav').onclick=e=>{const b=e.target.closest('button');if(b)location.hash=b.dataset.t};
function route(){const h=decodeURIComponent(location.hash.slice(1))||'Overview';
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===h));
  if(h.startsWith('p:'))return openPage(h.slice(2));$('#main').innerHTML=(T[h]||T.Overview)()}
window.onhashchange=route;route();
</script></body></html>
"""
