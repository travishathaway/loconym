import { Reader, decodeUtf8 } from './bytes.js';
import type { Box } from './tiles.js';

export const COORD_QUANTUM = 1e-6;
export const HN_QUANTUM = 1e-7;
export const GEOM_QUANTUM = 1e-6;

export type Pt = [number, number];
export interface Cell {
  /** polys === null: the whole tile lies inside the area. polygon = rings, ring = points */
  admin: { id: number; polys: Pt[][][] | null }[];
  streets: { id: number; pts: Pt[] }[];
  addrs: { streetId: number; housenumber: string; lon: number; lat: number }[];
  interps: { streetId: number; step: number; first: number; last: number; pts: Pt[] }[];
  /** Trailing section (format 0.2); empty for older databases. */
  pois: { id: number; lon: number; lat: number }[];
}
export interface StreetNumbers {
  addrs: { housenumber: string; lon: number; lat: number }[];
  interps: { step: number; first: number; last: number; pts: Pt[] }[];
}

const decCoords = (r: Reader, ox: number, oy: number, q: number): Pt[] => {
  const n = r.v();
  const pts: Pt[] = [];
  let px = 0;
  let py = 0;
  for (let i = 0; i < n; i++) {
    px += r.sv();
    py += r.sv();
    pts.push([ox + px * q, oy + py * q]);
  }
  return pts;
};

export const isSplit = (blob: Uint8Array): boolean => blob[0] === 1;

export function decodeLeaf(blob: Uint8Array, box: Box): Cell {
  const [ox, oy] = box;
  const q = COORD_QUANTUM;
  const r = new Reader(blob);
  if (r.v() !== 0) throw new Error('not a leaf cell');
  const cell: Cell = { admin: [], streets: [], addrs: [], interps: [], pois: [] };
  for (let n = r.v(); n > 0; n--) {
    const id = r.v();
    const flag = r.v();
    if (flag === 0) {
      cell.admin.push({ id, polys: null });
    } else {
      const polys: Pt[][][] = [];
      for (let p = flag - 1; p > 0; p--) {
        const rings: Pt[][] = [];
        for (let k = r.v(); k > 0; k--) rings.push(decCoords(r, ox, oy, q));
        polys.push(rings);
      }
      cell.admin.push({ id, polys });
    }
  }
  for (let n = r.v(); n > 0; n--) cell.streets.push({ id: r.v(), pts: decCoords(r, ox, oy, q) });
  let sid = 0;
  let px = 0;
  let py = 0;
  for (let g = r.v(); g > 0; g--) {
    sid += r.v();
    for (let n = r.v(); n > 0; n--) {
      const housenumber = decodeUtf8(r.raw(r.v()));
      px += r.sv();
      py += r.sv();
      cell.addrs.push({ streetId: sid, housenumber, lon: ox + px * q, lat: oy + py * q });
    }
  }
  for (let n = r.v(); n > 0; n--) {
    const streetId = r.v();
    const step = r.v();
    const first = r.v();
    const last = r.v();
    cell.interps.push({ streetId, step, first, last, pts: decCoords(r, ox, oy, q) });
  }
  if (r.more()) {
    let id = 0;
    px = 0;
    py = 0;
    for (let n = r.v(); n > 0; n--) {
      id += r.v();
      px += r.sv();
      py += r.sv();
      cell.pois.push({ id, lon: ox + px * q, lat: oy + py * q });
    }
  }
  return cell;
}

export function decodeHousenumbers(blob: Uint8Array): StreetNumbers {
  const r = new Reader(blob);
  const sn: StreetNumbers = { addrs: [], interps: [] };
  let plat = 0;
  let plon = 0;
  for (let n = r.v(); n > 0; n--) {
    const housenumber = decodeUtf8(r.raw(r.v()));
    plat += r.sv();
    plon += r.sv();
    sn.addrs.push({ housenumber, lon: plon * HN_QUANTUM, lat: plat * HN_QUANTUM });
  }
  for (let n = r.v(); n > 0; n--) {
    const step = r.v();
    const first = r.v();
    const last = r.v();
    sn.interps.push({ step, first, last, pts: decCoords(r, 0, 0, GEOM_QUANTUM) });
  }
  return sn;
}

export function decodePostings(blob: Uint8Array): number[] {
  const r = new Reader(blob);
  const out: number[] = [];
  let acc = 0;
  while (r.more()) {
    acc += r.v();
    out.push(acc);
  }
  return out;
}

/** Plain varints in stored order (ranked category lists); `limit` stops early. */
export function decodeIdList(blob: Uint8Array, limit?: number): number[] {
  const r = new Reader(blob);
  const out: number[] = [];
  while (r.more() && (limit === undefined || out.length < limit)) out.push(r.v());
  return out;
}
