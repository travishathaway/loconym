/** Minimal async read-only SQL interface the geocoder needs. */
export interface Db {
  /** Run a statement, return rows as arrays. BLOB columns are Uint8Array. */
  all(sql: string, bind?: (string | number)[]): Promise<unknown[][]>;
  close(): Promise<void>;
}

export interface OpenOptions {
  /** URL of the database file. */
  url: string;
  /**
   * 'range': query the remote file with HTTP range requests (needs a server that supports Range and CORS).
   * 'fetch': download the whole file once and query it from memory (best for small, bundled databases).
   */
  mode?: 'range' | 'fetch';
  /** Override where sqlite3.wasm is loaded from (fetch mode). */
  wasmUrl?: string;
  /** Range mode tuning. */
  range?: { maxPageSize?: number; cacheSizeKiB?: number; timeoutMs?: number };
}
