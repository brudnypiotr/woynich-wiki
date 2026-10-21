// Shared bits of the page: config from the server, DOM helpers, icons, the top bar.
export const CFG = JSON.parse(document.getElementById('kb-config').textContent);
export const ACCESS = CFG.access, MARK = CFG.mark;
export const $ = s => document.querySelector(s);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
export const ic = (d, w = 1.8) => `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
export const I = {menu: 'M4 6h16M4 12h16M4 18h16', clip: 'm21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7', code: 'm8 8-4 4 4 4M16 8l4 4-4 4',
  send: 'M12 19V5m0 0-6 6m6-6 6 6', save: 'M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6', ext: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6', file: 'M6 3h8l5 5v13H6zM14 3v5h5',
  up: 'M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2', redo: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5', trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3'};
export const topbar = (title, acts = '') => `<div class="top"><button class="icon menu" data-act="menu" title="Menu">${ic(I.menu)}</button><div class="ttl">${title}</div>${acts}</div>`;
// a short status line next to buttons: green and fading, or red and staying
export const msg = (id, t, ok = true) => note($('#' + id), t, ok);
export const note = (e, t, ok = true) => {e.className = (ok ? 'okmsg' : 'errmsg') + ' note'; e.textContent = t; if (ok) setTimeout(() => {if (e.textContent === t) e.textContent = ''}, 4000)};
// a spinner with a short text, shown at once while a view waits for the server
export const loader = (t = 'Loading…') => `<div class="loading"><i></i><span>${t}</span></div>`;
