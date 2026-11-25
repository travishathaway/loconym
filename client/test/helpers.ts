import { createServer, type Server } from 'node:http';
import { readFileSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { AddressInfo } from 'node:net';

export const GOLDEN_DIR = resolve(__dirname, '../../fixtures/golden');
export const golden = (name: string) => JSON.parse(readFileSync(join(GOLDEN_DIR, `${name}.golden.json`), 'utf8'));
export const hasFixture = (name: string) => existsSync(join(GOLDEN_DIR, `${name}.sqlite`)) && existsSync(join(GOLDEN_DIR, `${name}.golden.json`));

/** Deep-compare with a numeric tolerance (floats from different libm implementations differ by ulps). */
export function deepClose(a: unknown, b: unknown, path = '$', tol = 1e-9, errors: string[] = []): string[] {
  if (typeof a === 'number' && typeof b === 'number') {
    if (Math.abs(a - b) > tol && !(path.endsWith('distance_m') && Math.abs(a - b) <= 0.11)) errors.push(`${path}: ${a} != ${b}`);
  } else if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) errors.push(`${path}: length ${a.length} != ${b.length}`);
    else a.forEach((x, i) => deepClose(x, b[i], `${path}[${i}]`, tol, errors));
  } else if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a as object).sort();
    const kb = Object.keys(b as object).sort();
    if (ka.join() !== kb.join()) errors.push(`${path}: keys ${ka} != ${kb}`);
    else for (const k of ka) deepClose((a as never)[k], (b as never)[k], `${path}.${k}`, tol, errors);
  } else if (a !== b) errors.push(`${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
  return errors;
}

export interface RangeServer {
  url: (file: string) => string;
  stats: { requests: number; bytes: number; ranges: number };
  reset(): void;
  close(): Promise<void>;
}

/** Static file server with HTTP Range support that records traffic. */
export async function startRangeServer(dir = GOLDEN_DIR): Promise<RangeServer> {
  const stats = { requests: 0, bytes: 0, ranges: 0 };
  const server: Server = createServer((req, res) => {
    const file = join(dir, decodeURIComponent((req.url ?? '/').split('?')[0]));
    if (!file.startsWith(dir) || !existsSync(file)) {
      res.writeHead(404).end();
      return;
    }
    const size = statSync(file).size;
    const data = readFileSync(file);
    stats.requests++;
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? '');
    const headers = { 'Accept-Ranges': 'bytes', 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Content-Range, Content-Length, Accept-Ranges' };
    if (req.method === 'HEAD') {
      res.writeHead(200, { ...headers, 'Content-Length': size }).end();
      return;
    }
    if (m) {
      const start = m[1] ? Number(m[1]) : size - Number(m[2]);
      const end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
      stats.ranges++;
      stats.bytes += end - start + 1;
      res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
      res.end(data.subarray(start, end + 1));
    } else {
      stats.bytes += size;
      res.writeHead(200, { ...headers, 'Content-Length': size }).end(data);
    }
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const port = (server.address() as AddressInfo).port;
  return {
    url: (f) => `http://127.0.0.1:${port}/${f}`,
    stats,
    reset: () => Object.assign(stats, { requests: 0, bytes: 0, ranges: 0 }),
    close: () => new Promise((r) => server.close(() => r())),
  };
}
