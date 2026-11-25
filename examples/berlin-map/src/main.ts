import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import type { Logator, SearchResult } from '@thath/logator';

declare const __DB_MB__: number | null;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const searchEl = $('search');
const qInput = $<HTMLInputElement>('q');
const listEl = $<HTMLUListElement>('suggestions');
const loaderEl = $('loader');
const loadBtn = $<HTMLButtonElement>('load');
const statusEl = $('status');
const detailsEl = $('details');
const detailsTitle = $('details-title');
const detailsRows = $('details-rows');

// Berlin (west, south, east, north). The view can't leave a slightly padded box around it.
const BERLIN: [number, number, number, number] = [13.088, 52.338, 13.761, 52.675];
const PAD = 0.15;

// MapLibre needs WebGL. Without it the map stays blank, but search and the details popover still work.
let map: maplibregl.Map | null = null;
try {
  map = new maplibregl.Map({
    container: 'map',
    style: 'https://tiles.openfreemap.org/styles/bright',
    bounds: BERLIN,
    fitBoundsOptions: { padding: 20 },
    maxBounds: [BERLIN[0] - PAD, BERLIN[1] - PAD / 2, BERLIN[2] + PAD, BERLIN[3] + PAD / 2],
    minZoom: 8.5,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
} catch (e) {
  console.warn('logator demo: no map (WebGL unavailable?)', e);
  $('map').classList.add('no-map');
  $('map').textContent = 'The map needs WebGL, which this browser has turned off. Search still works.';
}
const marker = new maplibregl.Marker({ color: '#70853C' });

let gator: Logator | null = null;
let loading: Promise<void> | null = null;
let items: SearchResult[] = [];
let active = -1;
let searchSeq = 0;
let pickSeq = 0;
let timer: number | undefined;

if (__DB_MB__) loadBtn.textContent = `Load the Berlin database (${__DB_MB__} MB)`;

/** Download and open the database once, on the first click or focus. */
function load(): Promise<void> {
  loading ??= (async () => {
    loadBtn.disabled = true;
    statusEl.textContent = 'Downloading…';
    const t0 = performance.now();
    try {
      // loaded on demand: the client and SQLite wasm stay out of the page until the user asks for the demo
      const { Logator } = await import('@thath/logator');
      gator = await Logator.open({ url: new URL('data/berlin.sqlite', document.baseURI).href, mode: 'fetch' });
    } catch (e) {
      statusEl.textContent = `Couldn't open the database: ${(e as Error).message}`;
      loadBtn.disabled = false;
      loading = null;
      return;
    }
    loaderEl.hidden = true;
    qInput.focus();
    console.info(`logator: Berlin database ready in ${Math.round(performance.now() - t0)} ms`);
    if (qInput.value.trim()) void runSearch();
  })();
  return loading;
}

loadBtn.addEventListener('click', () => void load());
qInput.addEventListener('focus', () => void load());

function setOpen(open: boolean) {
  listEl.hidden = !open;
  searchEl.setAttribute('aria-expanded', String(open));
}

function setActive(i: number) {
  active = i;
  [...listEl.children].forEach((li, j) => li.classList.toggle('active', j === i));
  const li = listEl.children[i] as HTMLElement | undefined;
  if (li) qInput.setAttribute('aria-activedescendant', li.id);
  else qInput.removeAttribute('aria-activedescendant');
}

function render(results: SearchResult[]) {
  items = results;
  active = -1;
  listEl.replaceChildren();
  results.forEach((r, i) => {
    const li = document.createElement('li');
    li.id = `opt-${i}`;
    li.setAttribute('role', 'option');
    li.textContent = r.display_name;
    if (r.interpolated) {
      const s = document.createElement('small');
      s.textContent = 'interpolated house number';
      li.append(s);
    }
    // mousedown (not click) so the input doesn't lose focus and close the list first
    li.addEventListener('mousedown', (ev) => {
      ev.preventDefault();
      void pick(r);
    });
    listEl.append(li);
  });
  setOpen(results.length > 0);
}

async function runSearch() {
  const q = qInput.value.trim();
  if (!gator || q.length < 2) return render([]);
  const seq = ++searchSeq;
  const results = await gator.search({ q, limit: 6 });
  if (seq === searchSeq) render(results);
}

qInput.addEventListener('input', () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(runSearch, 200);
});

qInput.addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    if (!items.length) return;
    ev.preventDefault();
    setOpen(true);
    const step = ev.key === 'ArrowDown' ? 1 : -1;
    setActive((active + step + items.length) % items.length);
  } else if (ev.key === 'Enter') {
    const r = items[active >= 0 ? active : 0];
    if (r) void pick(r);
  } else if (ev.key === 'Escape') {
    setOpen(false);
  }
});
qInput.addEventListener('blur', () => setOpen(false));

function showDetails(title: string, rows: [string, string][]) {
  detailsTitle.textContent = title;
  detailsRows.replaceChildren();
  for (const [k, v] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = k.replace(/_/g, ' ');
    const dd = document.createElement('dd');
    dd.textContent = v;
    detailsRows.append(dt, dd);
  }
  detailsEl.hidden = false;
}

async function pick(r: SearchResult) {
  setOpen(false);
  qInput.value = r.display_name;
  qInput.blur();
  if (map) {
    marker.setLngLat([r.lon, r.lat]).addTo(map);
    map.flyTo({ center: [r.lon, r.lat], zoom: r.housenumber ? 17 : 15, duration: 1200 });
  }

  const coords: [string, string][] = [['coordinates', `${r.lat.toFixed(6)}, ${r.lon.toFixed(6)}`]];
  const note: [string, string][] = r.interpolated ? [['note', 'house number interpolated along the street']] : [];
  showDetails(r.display_name, [...note, ...coords]);

  // Search returns the street and city; reverse geocoding the point adds suburb, district, postcode and so on.
  const seq = ++pickSeq;
  const rev = await gator?.reverse({ lat: r.lat, lon: r.lon });
  if (!rev || seq !== pickSeq || detailsEl.hidden) return;
  // The nearest address may be on another street or have another number, so keep the picked result's own.
  const { house_number: _h, road: _r, ...area } = rev.address;
  const own: [string, string][] = [
    ...(r.housenumber ? ([['house_number', r.housenumber]] as [string, string][]) : []),
    ['road', r.name],
  ];
  showDetails(r.display_name, [...own, ...Object.entries(area), ...note, ...coords]);
}

$('close').addEventListener('click', () => {
  detailsEl.hidden = true;
  pickSeq++;
  marker.remove();
});
