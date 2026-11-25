import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import type { Db } from './types.js';

/** Download the whole file, open it from memory. Works in browsers and Node. */
export async function openFetch(url: string, wasmUrl?: string): Promise<Db> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`failed to fetch ${url}: ${res.status}`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  const init = sqlite3InitModule as unknown as (cfg: object) => ReturnType<typeof sqlite3InitModule>;
  const sqlite3 = await init({
    print: () => {},
    printErr: () => {},
    ...(wasmUrl ? { locateFile: (f: string) => (f.endsWith('.wasm') ? wasmUrl : f) } : {}),
  });
  const db = new sqlite3.oo1.DB(':memory:', 'c');
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  const rc = sqlite3.capi.sqlite3_deserialize(
    db.pointer!,
    'main',
    p,
    bytes.length,
    bytes.length,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_READONLY,
  );
  if (rc !== 0) throw new Error(`sqlite3_deserialize failed (${rc})`);
  return {
    async all(sql, bind) {
      return db.exec({ sql, bind, rowMode: 'array', returnValue: 'resultRows' }) as unknown[][];
    },
    async close() {
      db.close();
    },
  };
}
