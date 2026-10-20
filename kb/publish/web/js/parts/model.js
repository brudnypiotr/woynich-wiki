// The model: one model for every task or one per tier, the agent time limit; the models the Copilot account offers.
// In the first-run setup the recommended model (config/models.yaml: recommended_model) is preselected when the account offers it.
import {esc, note} from '../ui.js';
import {api, post} from '../api.js';
import {status} from '../shell.js';

const SRC = {env: 'set by KB_MODEL', override: 'one model for all tasks', tiers: 'per task tier'};
const TIERS = ['basic', 'standard', 'premium'];

// C: settings state. opts.setup: preselect the recommended model. Returns {save(), ok()}: save is true when saved.
export function mountModel(el, C, opts = {}) {
  const m = C.model, rec = m.recommended;
  const inp = (k, v, ph = '') => `<input data-k="${k}" value="${esc(v)}" placeholder="${esc(ph)}" list="mlist-${k}">`;
  const list = k => `<datalist id="mlist-${k}"><option value="auto"></option></datalist>`;
  el.innerHTML = `<div class="eff"><span class="sub" style="margin:0">Now in use</span><b class="effm">${esc(m.effective)}</b><span class="badge">${SRC[m.source]}</span></div>
    ${m.env ? `<p class="errmsg">The environment variable KB_MODEL=${esc(m.env)} overrides everything below until it is removed.</p>` : ''}
    <div class="grid2"><div class="f" style="grid-column:1/-1"><label>One model for every task</label>${inp('ov', m.override, 'empty = use the tiers below')}${list('ov')}
      <small>Like <code>kb model set</code>. Leave empty to choose per tier.${rec ? ` Recommended: <code>${esc(rec)}</code>.` : ''}</small></div>
     ${TIERS.map(t => `<div class="f"><label>${t[0].toUpperCase() + t.slice(1)} tier</label>${inp(t, m.tiers[t], 'auto')}${list(t)}<small>${Object.entries(m.tasks).filter(x => x[1] === t).map(x => x[0]).join(', ') || 'no tasks'}</small></div>`).join('')}
     <div class="f"><label>Agent time limit (minutes)</label><input data-k="tmo" type="number" min="1" max="240" value="${Math.round(m.timeout_s / 60)}"><small>Per source or question; long documents need more.</small></div></div>
    <div class="btns"><button class="pri" data-a="save">Save model settings</button><button class="ghost" data-a="load">Load available models</button><span class="note"></span></div>`;
  const $k = k => el.querySelector(`[data-k=${k}]`), n = el.querySelector('.note');
  let saved = !!(m.override || m.env);

  const load = async () => {const b = el.querySelector('[data-a=load]'); b.disabled = true; note(n, 'Asking GitHub Copilot… (a few seconds)');
    try {const l = await api('/api/settings/models'), opt = '<option value="auto"></option>' + l.map(x => `<option value="${esc(x.id)}">${esc(x.name || '')}${x.policy && x.policy !== 'enabled' ? ' (' + esc(x.policy) + ')' : ''}</option>`).join('');
      el.querySelectorAll('datalist').forEach(d => {d.innerHTML = opt});
      note(n, l.length + ' models available: click a model field to pick one.'); return l}
    catch (e) {note(n, e.message, false); return null}
    finally {b.disabled = false}};

  const save = async () => {try {const r = await post('/api/settings', {model: {override: $k('ov').value, tiers: Object.fromEntries(TIERS.map(t => [t, $k(t).value])), timeout_s: Math.round(+$k('tmo').value * 60)}});
      el.querySelector('.effm').textContent = r.model.effective; el.querySelector('.eff .badge').textContent = SRC[r.model.source];
      note(n, 'Saved. The next question or ingest uses ' + r.model.effective + '.'); status(); saved = true; return true}
    catch (e) {note(n, e.message, false); return false}};

  el.querySelector('[data-a=save]').onclick = save;
  el.querySelector('[data-a=load]').onclick = load;

  // first-run setup: nothing chosen yet → ask the account and preselect the recommended model if it is offered
  if (opts.setup && rec && !m.override && !m.env) load().then(l => {
    if (!l || $k('ov').value.trim()) return;
    const x = l.find(x => x.id === rec);
    if (x && (!x.policy || x.policy === 'enabled')) {$k('ov').value = rec; note(n, `${rec} preselected (recommended). Save to use it for every task.`)}
    else note(n, `The recommended model ${rec} is ${x ? 'not enabled' : 'not offered'} for this account: pick one from the list or leave “auto”.`, false)});
  return {save, ok: () => saved}}
