import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { CapabilityError, Logator } from '../src/index.js';
import { deepClose, golden, hasFixture, startRangeServer, type RangeServer } from './helpers.js';

let server: RangeServer;
beforeAll(async () => {
  server = await startRangeServer();
});
afterAll(async () => {
  await server.close();
});

const DBS = ['monaco', 'bremen'].filter(hasFixture);

describe.each(DBS)('%s', (name) => {
  const g = golden(name);
  for (const mode of ['fetch', 'range'] as const) {
    describe(mode, () => {
      let gator: Logator;
      beforeAll(async () => {
        gator = await Logator.open({ url: server.url(`${name}.sqlite`), mode });
      });
      afterAll(async () => {
        await gator.close();
      });

      // the range driver is much slower in Node, so it checks a deterministic subset
      const every = mode === 'range' ? 12 : 1;

      it('meta', () => {
        expect(gator.meta.format_version).toMatch(/^0\./);
        expect(gator.capabilities).toContain('search');
      });

      it('reverse matches the python reference', async () => {
        const cases = g.reverse.filter((_: unknown, i: number) => i % every === 0);
        const bad: string[] = [];
        for (const c of cases) {
          const r = await gator.reverse({ lon: c.lon, lat: c.lat, zoom: c.zoom });
          const errs = deepClose(r, c.expected);
          if (errs.length) bad.push(`(${c.lon},${c.lat},z${c.zoom}) ${errs[0]}`);
        }
        expect(bad.slice(0, 5)).toEqual([]);
      });

      it('search matches the python reference', async () => {
        const cases = g.search.filter((_: unknown, i: number) => i % every === 0);
        const bad: string[] = [];
        for (const c of cases) {
          const r = await gator.search(c.args);
          const errs = deepClose(r, c.expected, '$', 1e-9);
          if (errs.length) bad.push(`${JSON.stringify(c.args)} ${errs[0]}`);
        }
        expect(bad.slice(0, 5)).toEqual([]);
      });
    });
  }
});

describe('range mode traffic', () => {
  it.skipIf(!hasFixture('bremen'))('reads a small fraction of the file per query', async () => {
    server.reset();
    const gator = await Logator.open({ url: server.url('bremen.sqlite'), mode: 'range' });
    const afterOpen = { ...server.stats };
    const g = golden('bremen');
    const probes = g.reverse.slice(0, 20);
    for (const c of probes) await gator.reverse({ lon: c.lon, lat: c.lat });
    const s = g.search.slice(0, 10);
    for (const c of s) await gator.search(c.args);
    await gator.close();
    const fileSize = 3928064;
    console.log(`bremen range: open=${afterOpen.bytes} B/${afterOpen.ranges} req, total=${server.stats.bytes} B / ${server.stats.ranges} range requests for 30 queries (file ${fileSize} B)`);
    expect(server.stats.bytes).toBeLessThan(fileSize * 0.6);
    expect(server.stats.ranges).toBeGreaterThan(0);
  });
});

describe('capabilities', () => {
  it('rejects unsupported format', async () => {
    await expect(Logator.open({ url: server.url('does-not-exist.sqlite'), mode: 'fetch' })).rejects.toThrow();
  });
  it('CapabilityError is exported', () => {
    expect(new CapabilityError('x')).toBeInstanceOf(Error);
  });
});
