// What the model did for an answer: thoughts and reads, live while it works and folded under the answer.
import {esc} from './ui.js';
import {inl} from './markdown.js';

// isOpen(k): whether thought k was opened by the reader (live view only: it is redrawn every second)
function stepHtml(e, k, live, isOpen) {const t = String(e.text || '');
  if (e.kind === 'thinking') {const x = t.replace(/\n{2,}/g, '\n'), full = live && isOpen && isOpen(k) ? ' full' : '';
    return `<li><b>💭</b><i class="th${full}"${live ? ` data-k="${k}"` : ''}>${inl(x)}</i><small>${e.s}s</small></li>`}
  if (e.kind === 'intent') return `<li><b>→</b><span>${esc(t)}</span><small>${e.s}s</small></li>`;
  const m = t.match(/^(\S+)\s*(.*)$/) || [, t, ''], tool = m[1], arg = m[2];
  const verb = {view: 'Read', glob: 'Find', grep: 'Search', rg: 'Search'}[tool] || tool;
  const full = arg.replace(/^.*?[\\/]instance[\\/]/, '').replace(/\\/g, '/'),  // long code paths: the tail of each, full paths on hover
    short = full.split(/,\s*/).map(x => {const p = x.split('/'); return p.length > 4 ? '…/' + p.slice(-3).join('/') : x}).join(', ');
  return `<li><b>${verb === 'Read' ? '📄' : '🔎'}</b><span>${esc(verb)} <code title="${esc(full)}">${esc(short)}</code></span><small>${e.s}s</small></li>`}

export function traceHtml(ev, live, label, isOpen) {if (!ev || !ev.length) return ''; const th = ev.filter(e => e.kind === 'thinking').length, rd = ev.length - th;
  return `<details class="trace"${live ? ' open' : ''}><summary>${label || `Thought${th > 1 ? ' ' + th + '×' : ''} and read ${rd} item${rd === 1 ? '' : 's'}`} ▾</summary><ol>${ev.map((e, k) => stepHtml(e, k, live, isOpen)).join('')}</ol></details>`}

// only thoughts that are really cut off (measured, not guessed from their length) get the hand cursor and expand
export function markMore(root) {(root || document).querySelectorAll('.trace li i.th').forEach(i => i.classList.toggle('more', i.classList.contains('full') || i.scrollHeight > i.clientHeight + 1))}

// onToggle(k, open): a live thought was opened or closed
export function initTrace(onToggle) {
  document.addEventListener('toggle', e => {if (e.target.classList && e.target.classList.contains('trace')) markMore(e.target)}, true);
  addEventListener('resize', () => markMore());
  document.addEventListener('click', e => {const el = e.target.closest('.trace li i.th'); if (!el || !el.classList.contains('more')) return;
    el.classList.toggle('full'); if (el.dataset.k != null) onToggle(+el.dataset.k, el.classList.contains('full'))})}
