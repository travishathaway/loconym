import { describe, expect, it } from 'vitest';
import { decodeHousenumbers, decodeLeaf, decodePostings } from '../src/format.js';
import { normalizeTokens } from '../src/normalize.js';
import { cellKey } from '../src/tiles.js';
import { deepClose, golden } from './helpers.js';

const g = golden('monaco');
const hex = (h: string) => Uint8Array.from(h.match(/../g) ?? [], (b) => parseInt(b, 16));

describe('python parity (golden vectors)', () => {
  it('normalizer', () => {
    for (const [input, tokens] of g.normalizer) expect(normalizeTokens(input), JSON.stringify(input)).toEqual(tokens);
  });

  it('cell keys', () => {
    for (const [x, y, z, key] of g.cell_keys) expect(cellKey(x, y, z)).toBe(key);
  });

  it('cell leaves', () => {
    expect(g.leaves.length).toBeGreaterThan(0);
    for (const l of g.leaves) {
      const c = decodeLeaf(hex(l.hex), l.box);
      const e = l.decoded;
      const got = {
        admin: c.admin.map((a) => [a.id, a.polys]),
        streets: c.streets.map((s) => [s.id, s.pts]),
        addrs: c.addrs.map((a) => [a.streetId, a.housenumber, a.lon, a.lat]),
        interps: c.interps.map((i) => [i.streetId, i.step, i.first, i.last, i.pts]),
      };
      expect(deepClose(got, e, '$', 1e-12)).toEqual([]);
    }
  });

  it('housenumber blobs', () => {
    for (const h of g.housenumbers) {
      const d = decodeHousenumbers(hex(h.hex));
      const got = {
        addrs: d.addrs.map((a) => [a.housenumber, a.lon, a.lat]),
        interps: d.interps.map((i) => [i.step, i.first, i.last, i.pts]),
      };
      expect(deepClose(got, h.decoded, '$', 1e-12)).toEqual([]);
    }
  });

  it('postings', () => {
    expect(decodePostings(hex(g.postings.hex))).toEqual(g.postings.ids);
  });
});
