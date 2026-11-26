import 'bootstrap/dist/css/bootstrap.min.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import maplibregl, { type GeoJSONSource, type GeoJSONSourceSpecification } from 'maplibre-gl';
import { Loconym, type ReverseResult, type SearchResult } from 'loconym';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const dbSel = $<HTMLSelectElement>('db');
const modeSel = $<HTMLSelectElement>('mode');
const qInput = $<HTMLInputElement>('q');
const resultsEl = $('results');
const detailEl = $('detail');
const statusEl = $('status');

const PLACEHOLDER: Record<string, string> = {
  berlin: 'Address, place or category: Unter den Linden 77, museums in Berlin',
  monaco: 'Address, place or category: Avenue Princesse Grace, restaurants in Monaco',
};

// 'range' mode needs a cross-origin-isolated page (see vite.config.ts). Without it, offer only 'fetch'.
if (!self.crossOriginIsolated) {
  modeSel.value = 'fetch';
  modeSel.querySelector<HTMLOptionElement>('option[value="range"]')!.disabled = true;
  modeSel.title = 'HTTP range requests need a cross-origin-isolated page (COOP/COEP headers)';
}

// Every map resource (style, tiles, glyphs, sprites) is fetched with CORS, which COEP 'require-corp' allows.
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/bright',
  center: [9.5, 52.5],
  zoom: 5,
});
map.addControl(new maplibregl.NavigationControl(), 'top-right');
const marker = new maplibregl.Marker({ color: '#70853C' });
const mapReady = new Promise<void>((resolve) => map.once('load', () => resolve()));

let geocoder: Loconym | null = null;
let searchSeq = 0;
let openSeq = 0;

function setStatus(msg: string) {
  statusEl.textContent = msg;
}

function showDetail(title: string, rows: [string, string][]) {
  $('detail-title').textContent = title;
  const dl = $('detail-rows');
  dl.replaceChildren();
  for (const [k, v] of rows) {
    const dt = document.createElement('dt');
    dt.className = 'col-5 fw-normal text-body-secondary text-capitalize';
    dt.textContent = k.replace(/_/g, ' ');
    const dd = document.createElement('dd');
    dd.className = 'col-7 mb-1';
    dd.textContent = v;
    dl.append(dt, dd);
  }
  detailEl.hidden = false;
}

function show(lat: number, lon: number, zoom?: number) {
  marker.setLngLat([lon, lat]).addTo(map);
  if (zoom) map.flyTo({ center: [lon, lat], zoom, duration: 800 });
}

/** Dashed outline of the database's coverage (its bbox). */
async function showCoverage([w, s, e, n]: number[]) {
  await mapReady;
  const data: GeoJSONSourceSpecification['data'] = {
    type: 'Feature',
    properties: {},
    geometry: { type: 'LineString', coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] },
  };
  const src = map.getSource('coverage') as GeoJSONSource | undefined;
  if (src) src.setData(data);
  else {
    map.addSource('coverage', { type: 'geojson', data });
    map.addLayer({
      id: 'coverage',
      type: 'line',
      source: 'coverage',
      paint: { 'line-color': '#5a6415', 'line-width': 1.5, 'line-dasharray': [3, 2] },
    });
  }
  map.fitBounds([w, s, e, n], { padding: 30, duration: 0 });
}

async function open() {
  const seq = ++openSeq;
  qInput.disabled = true;
  qInput.value = '';
  resultsEl.replaceChildren();
  detailEl.hidden = true;
  marker.remove();
  setStatus('Opening database…');
  await geocoder?.close();
  geocoder = null;
  const url = new URL(`data/${dbSel.value}.sqlite`, document.baseURI).href;
  const t0 = performance.now();
  let g: Loconym;
  try {
    g = await Loconym.open({ url, mode: modeSel.value as 'range' | 'fetch' });
  } catch (e) {
    if (seq === openSeq) setStatus(`Failed to open database: ${(e as Error).message}. Run "pixi run example-data" first.`);
    return;
  }
  if (seq !== openSeq) return void g.close(); // the user switched again while this one was opening
  geocoder = g;
  await showCoverage(g.meta.bbox.split(',').map(Number));
  qInput.disabled = false;
  qInput.placeholder = PLACEHOLDER[dbSel.value];
  setStatus(`Ready in ${Math.round(performance.now() - t0)} ms · ${g.meta.source} · built ${g.meta.created_utc.slice(0, 10)}`);
}

map.on('click', async (ev) => {
  if (!geocoder) return;
  const t0 = performance.now();
  const r: ReverseResult | null = await geocoder.reverse({ lat: ev.lngLat.lat, lon: ev.lngLat.lng, zoom: 18, pois: true });
  const ms = Math.round(performance.now() - t0);
  if (!r) {
    setStatus(`No data at this point (${ms} ms). Click inside the dashed area.`);
    return;
  }
  show(r.lat, r.lon);
  showDetail(r.display_name || '(no address)', [
    ['match', r.kind === 'addr' ? 'address' : r.kind === 'poi' ? 'place' : r.kind === 'street' ? 'nearest street' : 'area only'],
    ...(r.distance_m != null ? ([['distance', `${r.distance_m} m`]] as [string, string][]) : []),
    ...Object.entries(r.address),
  ]);
  setStatus(`Reverse geocoded in ${ms} ms`);
});

/** "Supermarket" from `shop=supermarket`. */
const poiType = (r: SearchResult): string => (r.class ?? '').split('=')[1]?.replace(/_/g, ' ') ?? '';
/** "Dammweg 12, Bremen": the POI's address line (street and number, then city). */
const poiAddress = (r: SearchResult): string =>
  [r.street ? (r.housenumber ? `${r.street} ${r.housenumber}` : r.street) : '', r.city ?? ''].filter(Boolean).join(', ');

function renderResults(items: SearchResult[]) {
  resultsEl.replaceChildren();
  for (const r of items) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'list-group-item list-group-item-action px-2 py-1';
    if (r.kind === 'poi') {
      btn.textContent = r.name;
      const where = document.createElement('small');
      where.className = 'd-block text-body-secondary';
      where.textContent = [poiType(r), poiAddress(r)].filter(Boolean).join(' · ');
      btn.append(where);
    } else {
      btn.textContent = r.display_name;
    }
    if (r.interpolated) {
      const s = document.createElement('small');
      s.className = 'd-block text-body-secondary';
      s.textContent = 'interpolated house number';
      btn.append(s);
    }
    btn.addEventListener('click', () => {
      for (const el of resultsEl.children) el.classList.toggle('active', el === btn);
      show(r.lat, r.lon, r.housenumber || r.kind === 'poi' ? 18 : 16);
      showDetail(r.display_name, [
        ['lat', r.lat.toFixed(6)],
        ['lon', r.lon.toFixed(6)],
        ...(r.kind === 'poi'
          ? ([['place', r.name], ['type', poiType(r)], ['address', poiAddress(r)]] as [string, string][])
          : ([['street id', String(r.street_id)]] as [string, string][])),
        ...(r.interpolated ? ([['note', 'house number interpolated']] as [string, string][]) : []),
      ]);
    });
    resultsEl.append(btn);
  }
}

let timer: number | undefined;
qInput.addEventListener('input', () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(async () => {
    const q = qInput.value.trim();
    if (!geocoder || q.length < 2) return renderResults([]);
    const seq = ++searchSeq;
    const t0 = performance.now();
    const items = await geocoder.search({ q, limit: 6 });
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
