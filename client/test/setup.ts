// sqlite-wasm-http runs SQLite in a worker; Node needs a Worker implementation.
import Worker from '@mmomtchev/web-worker';

(globalThis as { Worker?: unknown }).Worker ??= Worker;
