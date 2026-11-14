/** Tiny DOM helper: text is always set via textContent, never innerHTML. */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs: Record<string, string> | null = null, ...kids: (Node | string | null | undefined)[]
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
export const fmt = (x: number | null | undefined, d = 2) => (x == null ? '—' : x.toFixed(d));
export const clear = (e: Element) => e.replaceChildren();
