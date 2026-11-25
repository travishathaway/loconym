import { statSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';

// The demo uses 'fetch' mode (the page downloads the whole database), so it needs no cross-origin isolation and runs
// on plain static hosting such as GitHub Pages. The client still bundles its range-mode code (sqlite-wasm-http).

// sqlite-wasm-http starts its workers with `new Worker(new URL('./x.js', import.meta.url))`, i.e. as *classic*
// workers, but those files are ES modules with imports. Vite's dev server serves them as-is, so the browser
// rejects them ("Worker bootstrap failed"). Ask for module workers explicitly.
const moduleWorkers: Plugin = {
  name: 'sqlite-wasm-http-module-workers',
  enforce: 'pre',
  transform(code, id) {
    if (!/sqlite-wasm-http[\\/].*dist[\\/]index\.js/.test(id)) return null;
    return code.replace(/new Worker\(new URL\('(\.\/[\w-]+\.js)', import\.meta\.url\)\)/g,
      "new Worker(new URL('$1', import.meta.url), { type: 'module' })");
  },
};

// Size of the database, shown on the "load" button. null when it hasn't been built (`pixi run demo-data`).
function dbMegabytes(): number | null {
  try {
    return Math.round(statSync(new URL('./public/data/berlin.sqlite', import.meta.url)).size / 1e6);
  } catch {
    return null;
  }
}

export default defineConfig({
  plugins: [moduleWorkers],
  base: './', // served from /logator/demo/ on GitHub Pages
  define: { __DB_MB__: JSON.stringify(dbMegabytes()) },
  // sqlite-wasm and its HTTP VFS load their own wasm/workers via import.meta.url; keep them out of dep pre-bundling
  optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm', 'sqlite-wasm-http', '@thath/logator'] },
  worker: { format: 'es' },
  build: { target: 'es2022' },
});
