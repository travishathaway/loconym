import { decodeHousenumbers, decodeLeaf, decodePostings, isSplit, type Cell, type Pt } from './format.js';
import { normalizeTokens } from './normalize.js';
import { openFetch } from './storage/fetch.js';
import { openRange } from './storage/range.js';
import type { Db, OpenOptions } from './storage/types.js';
import { cellKey, lonlatTile, tileBounds, type Box } from './tiles.js';

const ADDR_RADIUS_M = 40;
const POI_RADIUS_M = 50;
const POI_PARENT = -2; // term.parent for POI postings is POI_PARENT - city
const MAX_ROWS_PER_TOKEN = 200;
const MIN_PREFIX = 3;
const HN_TOKEN = /^[0-9]+[a-zA-Z]?$/;
const INT = /^[0-9]+$/;

const ADMIN_KEYS: Record<number, string> = {
  2: 'country', 3: 'region', 4: 'state', 5: 'state_district', 6: 'county', 7: 'municipality',
  8: 'city', 9: 'city_district', 10: 'suburb', 11: 'neighbourhood',
};

export class CapabilityError extends Error {}

export interface AdminArea { id: number; level: number; name: string; rank: number }
export interface ReverseOptions {
  lat: number;
  lon: number;
  zoom?: number;
  /** Also report a named POI within 50 m (below an exact address, above a street). Needs the `poi` capability. */
  pois?: boolean;
}
export interface PoiInfo { id: number; name: string; class: string }
export interface ReverseResult {
  kind: 'addr' | 'street' | 'poi' | null;
  poi: PoiInfo | null;
  street: string | null;
  housenumber: string | null;
  street_id: number | null;
  /** Containing admin areas, deepest first. */
  admin: AdminArea[];
  lon: number;
  lat: number;
  distance_m: number | null;
  place_rank: number | null;
  /** Nominatim-style address parts (house_number, road, suburb, city, state, country, ...). */
  address: Record<string, string>;
  display_name: string;
}
export interface SearchOptions {
  /** Free-form query, e.g. "Hauptstraße 12, Bremen". */
  q?: string;
  street?: string;
  city?: string;
  limit?: number;
  /** Minimum length for prefix (type-ahead) matching of the last street token. */
  minPrefix?: number;
}
export interface SearchResult {
  /** 'street' hits carry street_id; 'poi' hits carry poi_id, class ("tourism=museum") and rank. */
  kind: 'street' | 'poi';
  street_id?: number;
  poi_id?: number;
  class?: string;
  rank?: number;
  name: string;
  city_id: number;
  city: string | null;
  lat: number;
  lon: number;
  score: number;
  housenumber: string | null;
  interpolated?: boolean;
  display_name: string;
}

const mPerDeg = (lat: number): [number, number] => [111320 * Math.cos((lat * Math.PI) / 180), 110540];

function pip(polygon: Pt[][], x: number, y: number): boolean {
  let inside = false;
  for (const ring of polygon) {
    let j = ring.length - 1;
    for (let i = 0; i < ring.length; i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      j = i;
    }
  }
  return inside;
}

function segDist(px: number, py: number, a: Pt, b: Pt, lat: number): [number, number, number] {
  const [cx, cy] = mPerDeg(lat);
  const ax = a[0] * cx, ay = a[1] * cy, bx = b[0] * cx, by = b[1] * cy;
  px *= cx;
  py *= cy;
  const dx = bx - ax, dy = by - ay;
  const L = dx * dx + dy * dy;
  const t = L === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L));
  const qx = ax + t * dx, qy = ay + t * dy;
  return [Math.hypot(px - qx, py - qy), qx / cx, qy / cy];
}

const splitWs = (s: string): string[] => s.split(/\s+/).filter(Boolean);
const bytes = (v: unknown): Uint8Array => v as Uint8Array;

export class Loconym {
  private constructor(
    private readonly db: Db,
    readonly meta: Record<string, string>,
  ) {
    this.cellZoom = Number(meta.cell_zoom);
    this.rootZoom = Number(meta.root_zoom);
    this.caps = new Set(meta.capabilities.split(','));
  }
  private cellZoom: number;
  private rootZoom: number;
  private caps: Set<string>;

  static async open(opts: OpenOptions): Promise<Loconym> {
    const db = opts.mode === 'fetch' ? await openFetch(opts.url, opts.wasmUrl) : await openRange(opts.url, opts.range);
    try {
      const rows = await db.all('SELECT k, v FROM meta');
      const meta = Object.fromEntries(rows.map(([k, v]) => [String(k), String(v)]));
      if (Number(meta.format_version?.split('.')[0]) !== 0) throw new Error(`unsupported format version ${meta.format_version}`);
      return new Loconym(db, meta);
    } catch (e) {
      await db.close();
      throw e;
    }
  }

  async close(): Promise<void> {
    await this.db.close();
  }

  get capabilities(): string[] {
    return [...this.caps];
  }

  // ---------------------------------------------------------------- cells
  private async row(x: number, y: number, z: number): Promise<Uint8Array | null> {
    const rows = await this.db.all('SELECT data FROM cell WHERE id=?', [cellKey(x, y, z)]);
    return rows.length ? bytes(rows[0][0]) : null;
  }

  private async findCell(lon: number, lat: number): Promise<{ cell: Cell; box: Box } | null> {
    let z = this.cellZoom;
    let [x, y] = lonlatTile(lon, lat, z);
    let blob = await this.row(x, y, z);
    if (blob === null) {
      for (z = this.cellZoom - 1; z >= this.rootZoom; z--) {
        [x, y] = lonlatTile(lon, lat, z);
        blob = await this.row(x, y, z);
        if (blob !== null) break;
      }
      if (blob === null) return null;
    }
    while (isSplit(blob)) {
      z++;
      [x, y] = lonlatTile(lon, lat, z);
      blob = await this.row(x, y, z);
      if (blob === null) return null;
    }
    const box = tileBounds(x, y, z);
    return { cell: decodeLeaf(blob, box), box };
  }

  // ---------------------------------------------------------------- reverse
  async reverse({ lat, lon, zoom = 18, pois = false }: ReverseOptions): Promise<ReverseResult | null> {
    if (!this.caps.has('reverse')) throw new CapabilityError('database built without reverse');
    const withPois = pois && this.caps.has('poi') && zoom >= 17;
    const found = await this.findCell(lon, lat);
    if (!found) return null;
    const { cell, box } = found;
    const chain = cell.admin
      .filter((a) => a.polys === null || a.polys.some((p) => pip(p, lon, lat)))
      .map((a) => a.id);

    let kind: 'addr' | 'street' | 'poi' | null = null;
    let bestSid = 0;
    let bestHn: string | null = null;
    let bestD = 1e18;
    let bestPt: Pt | null = null;
    const [cx, cy] = mPerDeg(lat);

    const scan = (c: Cell): void => {
      if (zoom >= 18) {
        for (const a of c.addrs) {
          const d = Math.hypot((a.lon - lon) * cx, (a.lat - lat) * cy);
          if (d < ADDR_RADIUS_M && (kind !== 'addr' || d < bestD)) {
            kind = 'addr'; bestSid = a.streetId; bestHn = a.housenumber; bestD = d; bestPt = [a.lon, a.lat];
          }
        }
      }
      if (withPois && kind !== 'addr') {
        for (const p of c.pois) {
          const d = Math.hypot((p.lon - lon) * cx, (p.lat - lat) * cy);
          if (d < POI_RADIUS_M && (kind !== 'poi' || d < bestD)) {
            kind = 'poi'; bestSid = p.id; bestHn = null; bestD = d; bestPt = [p.lon, p.lat];
          }
        }
      }
      if (zoom >= 16 && kind !== 'addr' && kind !== 'poi') {
        for (const s of c.streets) {
          for (let i = 0; i + 1 < s.pts.length; i++) {
            const [d, qx, qy] = segDist(lon, lat, s.pts[i], s.pts[i + 1], lat);
            if (d < bestD) {
              kind = 'street'; bestSid = s.id; bestHn = null; bestD = d; bestPt = [qx, qy];
            }
          }
        }
      }
    };

    scan(cell);
    if (kind !== 'addr') {
      const r = kind ? bestD : 500;
      const edges: [number, [number, number]][] = [
        [(lon - box[0]) * cx, [-1, 0]],
        [(box[2] - lon) * cx, [1, 0]],
        [(lat - box[1]) * cy, [0, -1]],
        [(box[3] - lat) * cy, [0, 1]],
      ];
      for (const [e, [ox, oy]] of edges) {
        if (e < r) {
          const n = await this.findCell(lon + (ox * (e + 0.5)) / cx, lat + (oy * (e + 0.5)) / cy);
          if (n) scan(n.cell);
        }
      }
    }

    const [streetRow, poiRow, adminRows] = await Promise.all([
      kind && kind !== 'poi' ? this.db.all('SELECT name FROM street WHERE id=?', [bestSid]) : Promise.resolve([] as unknown[][]),
      kind === 'poi' ? this.db.all('SELECT name,class FROM poi WHERE id=?', [bestSid]) : Promise.resolve([] as unknown[][]),
      Promise.all(chain.map((id) => this.db.all('SELECT id,level,name,rank FROM admin WHERE id=?', [id]))),
    ]);
    const admin: AdminArea[] = adminRows
      .map((r) => r[0])
      .filter(Boolean)
      .map(([id, level, name, rank]) => ({ id: Number(id), level: Number(level), name: String(name), rank: Number(rank) }))
      .sort((a, b) => b.level - a.level);
    const street = streetRow.length ? String(streetRow[0][0]) : null;
    const housenumber = bestHn;
    const poi: PoiInfo | null = poiRow.length ? { id: bestSid, name: String(poiRow[0][0]), class: String(poiRow[0][1]) } : null;

    const address: Record<string, string> = {};
    if (poi) address[poi.class.split('=')[1]] = poi.name;
    if (housenumber) address.house_number = housenumber;
    if (street) address.road = street;
    for (const a of [...admin].reverse()) {
      const key = ADMIN_KEYS[a.level];
      if (key) address[key] = a.name;
    }
    const parts: string[] = [];
    if (poi) parts.push(poi.name);
    if (street) parts.push(housenumber ? `${street} ${housenumber}` : street);
    for (const a of admin) if (!parts.includes(a.name)) parts.push(a.name);

    const pt = bestPt as Pt | null;
    return {
      kind,
      street,
      housenumber,
      street_id: kind && kind !== 'poi' ? bestSid : null,
      poi,
      admin,
      lon: pt ? pt[0] : lon,
      lat: pt ? pt[1] : lat,
      distance_m: kind ? Math.round(bestD * 10) / 10 : null,
      place_rank: kind === 'addr' || kind === 'poi' ? 30 : kind === 'street' ? 26 : admin.length ? admin[0].rank : null,
      address,
      display_name: parts.join(', '),
    };
  }

  // ---------------------------------------------------------------- search
  private async postings(token: string, parent: number, prefix: boolean): Promise<Set<number>> {
    const ids = new Set<number>();
    const rows = prefix
      ? await this.db.all('SELECT postings FROM term WHERE t>=? AND t<? AND parent=? LIMIT ?', [
          token, token.slice(0, -1) + String.fromCharCode(token.charCodeAt(token.length - 1) + 1), parent, MAX_ROWS_PER_TOKEN,
        ])
      : await this.db.all('SELECT postings FROM term WHERE t=? AND parent=?', [token, parent]);
    for (const [b] of rows) for (const id of decodePostings(bytes(b))) ids.add(id);
    return ids;
  }

  private async postingsAnyCity(token: string, prefix: boolean): Promise<Set<number>> {
    const ids = new Set<number>();
    const rows = prefix
      ? await this.db.all('SELECT postings FROM term WHERE t>=? AND t<? AND parent>=0 LIMIT ?', [
          token, token.slice(0, -1) + String.fromCharCode(token.charCodeAt(token.length - 1) + 1), MAX_ROWS_PER_TOKEN,
        ])
      : await this.db.all('SELECT postings FROM term WHERE t=? AND parent>=0 LIMIT ?', [token, MAX_ROWS_PER_TOKEN]);
    for (const [b] of rows) for (const id of decodePostings(bytes(b))) ids.add(id);
    return ids;
  }

  private async postingsAnyPoiCity(token: string, prefix: boolean): Promise<Set<number>> {
    const ids = new Set<number>();
    const rows = prefix
      ? await this.db.all('SELECT postings FROM term WHERE t>=? AND t<? AND parent<=? LIMIT ?', [
          token, token.slice(0, -1) + String.fromCharCode(token.charCodeAt(token.length - 1) + 1), POI_PARENT, MAX_ROWS_PER_TOKEN,
        ])
      : await this.db.all('SELECT postings FROM term WHERE t=? AND parent<=? LIMIT ?', [token, POI_PARENT, MAX_ROWS_PER_TOKEN]);
    for (const [b] of rows) for (const id of decodePostings(bytes(b))) ids.add(id);
    return ids;
  }

  private async cities(text: string): Promise<Set<number>> {
    const toks = normalizeTokens(text);
    const sets = await Promise.all(toks.map((t, i) => this.postings(t, -1, i === toks.length - 1)));
    let ids: Set<number> = sets.length ? sets[0] : new Set();
    for (const s of sets.slice(1)) ids = new Set([...ids].filter((i) => s.has(i)));
    const out = new Set<number>();
    for (const i of ids) {
      const r = await this.db.all('SELECT city FROM admin WHERE id=?', [i]);
      const city = Number(r[0][0]);
      if (city) out.add(city);
    }
    return out;
  }

  async search(opts: SearchOptions | string): Promise<SearchResult[]> {
    if (!this.caps.has('search')) throw new CapabilityError('database built without search');
    const o: SearchOptions = typeof opts === 'string' ? { q: opts } : opts;
    const limit = o.limit ?? 5;
    const minPrefix = o.minPrefix ?? MIN_PREFIX;
    let street = o.street;
    let city = o.city;
    if (o.q !== undefined) {
      const parts = o.q.split(',').map((p) => p.trim());
      city = parts.length > 1 ? parts[parts.length - 1] : undefined;
      street = parts[0];
    }
    const toks = splitWs(street ?? '');
    let number: string | null = null;
    if (toks.length && HN_TOKEN.test(toks[toks.length - 1])) number = toks.pop()!;
    else if (toks.length && HN_TOKEN.test(toks[0])) number = toks.shift()!;
    const stoks = normalizeTokens(toks.join(' '));
    if (!stoks.length) return [];
    const cities = city ? await this.cities(city) : null;
    if (cities && cities.size === 0) return [];

    let cand = null as Set<number> | null;
    for (let i = 0; i < stoks.length; i++) {
      const t = stoks[i];
      const prefix = i === stoks.length - 1 && t.length >= minPrefix;
      let ids = new Set<number>();
      if (cities === null) {
        ids = await this.postingsAnyCity(t, prefix);
      } else {
        for (const c of [...cities].sort((a, b) => a - b)) for (const id of await this.postings(t, c, prefix)) ids.add(id);
      }
      const prev: Set<number> | null = cand;
      cand = prev === null ? ids : new Set([...prev].filter((x) => ids.has(x)));
    }
    const hits: SearchResult[] = [];
    let poiCand = new Set<number>();
    if (number === null && this.caps.has('poi')) {
      for (let i = 0; i < stoks.length; i++) {
        const t = stoks[i];
        const prefix = i === stoks.length - 1 && t.length >= minPrefix;
        let ids = new Set<number>();
        if (cities === null) {
          ids = await this.postingsAnyPoiCity(t, prefix);
        } else {
          for (const c of [...cities].sort((a, b) => a - b)) for (const id of await this.postings(t, POI_PARENT - c, prefix)) ids.add(id);
        }
        poiCand = i === 0 ? ids : new Set([...poiCand].filter((x) => ids.has(x)));
      }
    }
    for (const pid of [...poiCand].sort((a, b) => a - b).slice(0, 50)) {
      const [row] = await this.db.all('SELECT name,class,rank,parent,lat,lon FROM poi WHERE id=?', [pid]);
      const [name, cls, rank, parent, lat, lon] = [String(row[0]), String(row[1]), Number(row[2]), Number(row[3]), Number(row[4]), Number(row[5])];
      const ntoks = normalizeTokens(name);
      const score = 10 * stoks.filter((t) => ntoks.includes(t)).length - Math.abs(ntoks.length - stoks.length);
      hits.push({ kind: 'poi', poi_id: pid, name, class: cls, rank, city_id: parent, city: null, lat: lat / 1e6, lon: lon / 1e6, score, housenumber: null, display_name: '' });
    }
    for (const sid of [...(cand ?? [])].sort((a, b) => a - b).slice(0, 50)) {
      const [row] = await this.db.all('SELECT name,parent,lat,lon FROM street WHERE id=?', [sid]);
      const [name, parent, lat, lon] = [String(row[0]), Number(row[1]), Number(row[2]), Number(row[3])];
      const ntoks = normalizeTokens(name);
      const score = 10 * stoks.filter((t) => ntoks.includes(t)).length - Math.abs(ntoks.length - stoks.length);
      hits.push({ kind: 'street', street_id: sid, name, city_id: parent, city: null, lat: lat / 1e6, lon: lon / 1e6, score, housenumber: null, display_name: '' });
    }
    // equal scores: more prominent POI (lower rank) first, then streets, then id
    const idOf = (h: SearchResult): number => (h.kind === 'poi' ? h.poi_id! : h.street_id!);
    hits.sort(
      (a, b) =>
        b.score - a.score ||
        (a.rank ?? 30) - (b.rank ?? 30) ||
        Number(a.kind === 'street') - Number(b.kind === 'street') ||
        idOf(a) - idOf(b),
    );
    const top = hits.slice(0, limit);
    for (const h of top) {
      if (number && h.kind === 'street') await this.locate(h, number);
      if (h.city_id) {
        const r = await this.db.all('SELECT name FROM admin WHERE id=?', [h.city_id]);
        h.city = r.length ? String(r[0][0]) : null;
      }
      h.display_name = [h.housenumber ? `${h.name} ${h.housenumber}` : h.name, h.city].filter(Boolean).join(', ');
    }
    return top;
  }

  private async locate(hit: SearchResult, number: string): Promise<void> {
    const rows = await this.db.all('SELECT data FROM housenumber WHERE street_id=?', [hit.street_id!]);
    if (!rows.length) return;
    const sn = decodeHousenumbers(bytes(rows[0][0]));
    const exact = new Map<string, [number, number]>();
    for (const a of [...sn.addrs].reverse()) exact.set(a.housenumber.toLowerCase(), [a.lon, a.lat]);
    const hit0 = exact.get(number.toLowerCase());
    if (hit0) {
      [hit.lon, hit.lat] = hit0;
      hit.housenumber = number;
      return;
    }
    if (!INT.test(number)) return;
    const n = Number(number);
    for (const { step, first, last, pts } of sn.interps) {
      const lo = Math.min(first, last), hi = Math.max(first, last);
      if (first !== last && lo <= n && n <= hi && (step === 1 || (n - first) % 2 === 0)) {
        const f = (n - first) / (last - first);
        const segs = pts.slice(1).map((b, i) => {
          const a = pts[i];
          const [cx, cy] = mPerDeg(a[1]);
          return Math.hypot((b[0] - a[0]) * cx, (b[1] - a[1]) * cy);
        });
        const target = f * segs.reduce((s, v) => s + v, 0);
        let acc = 0;
        for (let i = 0; i < segs.length; i++) {
          const L = segs[i];
          if (acc + L >= target && L > 0) {
            const t = (target - acc) / L;
            const a = pts[i], b = pts[i + 1];
            hit.lon = a[0] + t * (b[0] - a[0]);
            hit.lat = a[1] + t * (b[1] - a[1]);
            hit.housenumber = number;
            hit.interpolated = true;
            return;
          }
          acc += L;
        }
      }
    }
  }
}
