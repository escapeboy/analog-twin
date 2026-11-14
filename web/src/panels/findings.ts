// D3 Findings card: sentences generated server-side from docs/metrics.json; each one carries its metric keys as a tooltip.
import { http } from '../api';
import { clear, h } from '../dom';

interface Source { key: string; value: unknown }
interface Sentence { id: string; text: string; sources?: Source[] }
interface Findings { generated_utc?: string; sentences: Sentence[] }

const brief = (v: unknown) => { const s = typeof v === 'string' ? v : JSON.stringify(v); return s.length > 60 ? s.slice(0, 58) + '…' : s; };

export function initFindings(root: HTMLElement) {
  let loaded = false;
  let busy = false;
  async function show() {
    if (loaded || busy) return;
    busy = true;
    clear(root);
    root.append(h('p', { class: 'muted' }, 'Loading findings…'));
    try {
      const f = await http<Findings>('/api/findings');
      clear(root);
      root.append(h('p', { class: 'muted tight' }, 'Every sentence is filled from computed metrics; the (i) shows which values it uses.'));
      for (const s of f.sentences ?? []) {
        const tip = (s.sources ?? []).map((x) => `${x.key} = ${brief(x.value)}`).join('\n');
        const info = h('span', { class: 'finding-i', tabindex: '0', title: tip, 'aria-label': `Metrics used: ${tip}` }, 'i');
        root.append(h('p', { class: 'finding' }, s.text, ' ', info));
      }
      loaded = true;
    } catch (e) {
      clear(root);
      root.append(h('p', { class: 'err', role: 'alert' }, `Findings unavailable (${e instanceof Error ? e.message : e})`));
    }
    busy = false;
  }
  return { show };
}
