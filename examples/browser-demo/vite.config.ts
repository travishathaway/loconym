import { defineConfig, type Plugin } from 'vite';

// 'range' mode runs SQLite in workers that share memory (SharedArrayBuffer), which browsers only allow on
// cross-origin-isolated pages. Any host serving a range-mode app must send these two headers.
const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
};

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

export default defineConfig({
  plugins: [moduleWorkers],
  server: { headers: isolation },
  preview: { headers: isolation },
  base: './',
  // sqlite-wasm and its HTTP VFS load their own wasm/workers via import.meta.url; keep them out of dep pre-bundling
  optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm', 'sqlite-wasm-http', '@thath/logator'] },
  worker: { format: 'es' },
  build: { target: 'es2022' },
});
