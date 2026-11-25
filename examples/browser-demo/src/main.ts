import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Logator, type ReverseResult, type SearchResult } from '@thath/logator';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const dbSel = $<HTMLSelectElement>('db');
const modeSel = $<HTMLSelectElement>('mode');
const qInput = $<HTMLInputElement>('q');
const resultsEl = $<HTMLUListElement>('results');
const detailEl = $('detail');
const statusEl = $('status');

const map = L.map('map').setView([52.5, 9.5], 6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  crossOrigin: true, // tiles must be CORS-fetched on a cross-origin-isolated page (COEP: require-corp)
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);
const marker = L.circleMarker([0, 0], { radius: 8, color: '#1a7f64', weight: 3, fillOpacity: 0.3 });
let coverage: L.Rectangle | null = null;
let gator: Logator | null = null;
let searchSeq = 0;

function setStatus(msg: string) {
  statusEl.textContent = msg;
}

function showDetail(title: string, rows: [string, string][]) {
  detailEl.hidden = false;
  detailEl.replaceChildren();
  const h = document.createElement('h2');
  h.textContent = title;
  const dl = document.createElement('dl');
  for (const [k, v] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = k;
    const dd = document.createElement('dd');
    dd.textContent = v;
    dl.append(dt, dd);
  }
  detailEl.append(h, dl);
}

function show(lat: number, lon: number, zoom?: number) {
  marker.setLatLng([lat, lon]).addTo(map);
  if (zoom) map.flyTo([lat, lon], zoom, { duration: 0.6 });
}

async function open() {
  qInput.disabled = true;
  resultsEl.replaceChildren();
  detailEl.hidden = true;
  setStatus('Opening database…');
  await gator?.close();
  gator = null;
  const t0 = performance.now();
  try {
    const url = new URL(`data/${dbSel.value}.sqlite`, document.baseURI).href;
    gator = await Logator.open({ url, mode: modeSel.value as 'range' | 'fetch' });
  } catch (e) {
    setStatus(`Failed to open database: ${(e as Error).message}. Run "pixi run demo-data" first.`);
    return;
  }
  const [w, s, e, n] = gator.meta.bbox.split(',').map(Number);
  coverage?.remove();
  coverage = L.rectangle([[s, w], [n, e]], { color: '#1a7f64', weight: 1, fill: false, dashArray: '4' }).addTo(map);
  map.fitBounds(coverage.getBounds());
  qInput.disabled = false;
  qInput.placeholder = dbSel.value === 'berlin' ? 'Search an address, e.g. Unter den Linden 77, Berlin' : 'Search an address, e.g. Avenue Princesse Grace';
  setStatus(`Ready in ${Math.round(performance.now() - t0)} ms · ${gator.meta.source} · built ${gator.meta.created_utc.slice(0, 10)}`);
}

map.on('click', async (ev: L.LeafletMouseEvent) => {
  if (!gator) return;
  const t0 = performance.now();
  const r: ReverseResult | null = await gator.reverse({ lat: ev.latlng.lat, lon: ev.latlng.lng, zoom: 18 });
  const ms = Math.round(performance.now() - t0);
  if (!r) {
    setStatus(`No data at this point (${ms} ms). Click inside the dashed area.`);
    return;
  }
  show(r.lat, r.lon);
  showDetail(r.display_name || '(no address)', [
    ['match', r.kind === 'addr' ? 'address' : r.kind === 'street' ? 'nearest street' : 'area only'],
    ...(r.distance_m != null ? ([['distance', `${r.distance_m} m`]] as [string, string][]) : []),
    ...Object.entries(r.address),
  ]);
  setStatus(`Reverse geocoded in ${ms} ms`);
});

function renderResults(items: SearchResult[]) {
  resultsEl.replaceChildren();
  for (const r of items) {
    const li = document.createElement('li');
    li.textContent = r.display_name;
    if (r.interpolated) {
      const s = document.createElement('small');
      s.textContent = 'interpolated house number';
      li.append(s);
    }
    li.addEventListener('click', () => {
      show(r.lat, r.lon, r.housenumber ? 18 : 16);
      showDetail(r.display_name, [['lat', r.lat.toFixed(6)], ['lon', r.lon.toFixed(6)], ['street id', String(r.street_id)]]);
    });
    resultsEl.append(li);
  }
}

let timer: number | undefined;
qInput.addEventListener('input', () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(async () => {
    const q = qInput.value.trim();
    if (!gator || q.length < 2) return renderResults([]);
    const seq = ++searchSeq;
    const t0 = performance.now();
    const items = await gator.search({ q, limit: 6 });
    if (seq !== searchSeq) return;
    renderResults(items);
    setStatus(`${items.length} result${items.length === 1 ? '' : 's'} in ${Math.round(performance.now() - t0)} ms`);
  }, 200);
});
qInput.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') (resultsEl.firstElementChild as HTMLElement | null)?.click();
});

dbSel.addEventListener('change', open);
modeSel.addEventListener('change', open);
void open();
