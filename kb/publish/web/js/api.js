// The local API: every call carries the session token printed by `kb serve`.
import {ACCESS} from './ui.js';

const H = {'X-KB-Token': ACCESS};
export const api = (p, o = {}) => fetch(p, {...o, headers: {...H, ...(o.headers || {})}})
  .then(async r => {const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.status); return j});
export const post = (path, body) => api(path, {method: 'POST', body: JSON.stringify(body || {})});
