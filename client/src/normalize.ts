/** Text normalizer. Spec: docs/format-spec.md section 6; must match builder/src/logator/normalize.py. */
export const NORMALIZER_VERSION = '1';

export function normalizeTokens(input: string): string[] {
  const s = input
    .replaceAll('ß', 'ss')
    .replaceAll('ẞ', 'ss')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase();
  const out: string[] = [];
  for (let t of s.split(/[^0-9a-z]+/)) {
    if (!t) continue;
    if (t.endsWith('str') && t.length > 3) t += 'asse';
    out.push(t);
  }
  return out;
}
