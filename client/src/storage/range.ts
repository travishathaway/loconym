import { createSQLiteHTTPPool } from 'sqlite-wasm-http';
import type { Db, OpenOptions } from './types.js';

/** Query a remote file lazily with HTTP range requests (runs SQLite in a worker). */
export async function openRange(url: string, opts: OpenOptions['range'] = {}): Promise<Db> {
  if (typeof SharedArrayBuffer === 'undefined') {
    throw new Error(
      "mode 'range' needs SharedArrayBuffer: serve the page with 'Cross-Origin-Opener-Policy: same-origin' and " +
        "'Cross-Origin-Embedder-Policy: require-corp' (cross-origin isolation), or use mode 'fetch'.",
    );
  }
  const pool = await createSQLiteHTTPPool({
    workers: 1,
    httpOptions: {
      maxPageSize: opts.maxPageSize ?? 4096,
      cacheSize: opts.cacheSizeKiB ?? 4096,
      timeout: opts.timeoutMs ?? 20000,
    },
  } as never);
  await pool.open(new URL(url, globalThis.location?.href ?? undefined).href);
  return {
    async all(sql, bind) {
      const rows = await pool.exec(sql, bind as never, { rowMode: 'array' });
      // the pool returns one message per row: { row, columnNames }
      return (rows as unknown as { row?: unknown[] }[]).filter((r) => r.row).map((r) => r.row as unknown[]);
    },
    async close() {
      await pool.close();
    },
  };
}
