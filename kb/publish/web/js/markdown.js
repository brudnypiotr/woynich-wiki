// Markdown of answers and thoughts, with citations shown as muted footnotes.
import {esc} from './ui.js';

const CITEGRP = /\(([^()]*?(?:\[\[|:\d[\d,\-–]*@[0-9a-f]{6,}|\b[A-Z][A-Z0-9]+-\d+#)[^()]*)\)/g; // "(…source…)": a footnote, shown muted
// "repo/dir/File.cs:78-94@75f338ff8f" → a small "File.cs:78–94" label, the full reference on hover;
// FitNesse pages are all content.txt, so they are named by their folder
function citeHtml(g) {return g.split(/;\s*/).map(c => {const m = c.match(/^(?:(.*)\/)?([^\/\s]+):([\d,\-–]+)@([0-9a-f]{6,})$/); if (!m) return c;
  const dir = (m[1] || '').split('/'), name = /^(content\.txt|index\.\w+)$/.test(m[2]) && dir.length ? dir[dir.length - 1] : m[2],
    r = m[3].replace(/-/g, '–').split(','), lines = r.length > 2 ? r.slice(0, 2).join(', ') + ' +' + (r.length - 2) : r.join(', ');
  return `<span class="cref" title="${c}">${name}:${lines}</span>`}).join('; ')}
// labels alone need no brackets (a lone "(" would wrap away from them)
export function inl(t) {return esc(t).replace(CITEGRP, (m, g) => {const h = citeHtml(g), bare = !h.replace(/<span class="cref"[^>]*>[^<]*<\/span>/g, '').replace(/[;\s]/g, '');
    return `<span class="cg">${bare ? h : '(' + h + ')'}</span>`}).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<i>$2</i>')
  .replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g, (m, a, l) => `<a class="wl" href="#wiki/w:${encodeURIComponent(a.trim())}" title="Open in the wiki">${l || a.trim()}</a>`)}
const BLOCK = /^(```|#{1,4}\s|\s*\||\s*>|\s*([-*]|\d+\.)\s)/;
export function mdl(src) {const L = String(src || '').replace(/\r/g, '').split('\n'); let o = '', i = 0, m;
  while (i < L.length) {const l = L[i];
    if (/^```/.test(l)) {const c = []; i++; while (i < L.length && !/^```/.test(L[i])) c.push(L[i++]); i++; o += `<pre><code>${esc(c.join('\n'))}</code></pre>`; continue}
    if (m = l.match(/^(#{1,4})\s+(.*)/)) {const n = Math.min(m[1].length + 2, 5); o += `<h${n}>${inl(m[2])}</h${n}>`; i++; continue}
    if (/^\s*\|/.test(l)) {let r = []; while (i < L.length && /^\s*\|/.test(L[i])) r.push(L[i++]); r = r.filter(x => !/^\s*\|[\s:|-]+\|?\s*$/.test(x));
      o += '<div class="tbl"><table>' + r.map((x, k) => '<tr>' + x.trim().replace(/^\||\|$/g, '').split('|').map(c => k ? `<td>${inl(c.trim())}</td>` : `<th>${inl(c.trim())}</th>`).join('') + '</tr>').join('') + '</table></div>'; continue}
    if (/^\s*>/.test(l)) {const q = []; while (i < L.length && /^\s*>/.test(L[i])) q.push(L[i++].replace(/^\s*> ?/, '')); const c = q[0].match(/^\[!(\w+)\]\s*(.*)/);
      o += c ? `<div class="callout"><b>${c[1] === 'contradiction' ? '⚖️ Contradiction' : esc(c[1])}:</b> ${inl([c[2], ...q.slice(1)].join(' '))}</div>` : `<blockquote>${inl(q.join(' '))}</blockquote>`; continue}
    if (/^\s*([-*]|\d+\.)\s/.test(l)) {const ol = /^\s*\d+\./.test(l), it = []; while (i < L.length && /^\s*([-*]|\d+\.)\s/.test(L[i])) it.push(L[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''));
      o += `<${ol ? 'ol' : 'ul'}>${it.map(x => `<li>${inl(x)}</li>`).join('')}</${ol ? 'ol' : 'ul'}>`; continue}
    if (!l.trim()) {i++; continue}
    const p = [l]; i++; while (i < L.length && L[i].trim() && !BLOCK.test(L[i])) p.push(L[i++]); o += `<p>${inl(p.join('\n')).replace(/\n/g, '<br>')}</p>`}
  return o}
