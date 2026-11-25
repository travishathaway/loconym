export type Box = [number, number, number, number]; // minLon, minLat, maxLon, maxLat

export function tileBounds(x: number, y: number, z: number): Box {
  const n = 2 ** z;
  const lat = (yy: number) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * yy) / n))) * 180) / Math.PI;
  return [(x / n) * 360 - 180, lat(y + 1), ((x + 1) / n) * 360 - 180, lat(y)];
}

export function lonlatTile(lon: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const x = Math.trunc(((lon + 180) / 360) * n);
  const y = Math.trunc(((1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2) * n);
  return [Math.min(Math.max(x, 0), n - 1), Math.min(Math.max(y, 0), n - 1)];
}

/** (1 << 2z) | morton(x, y), computed with arithmetic because keys exceed 32 bits. */
export function cellKey(x: number, y: number, z: number): number {
  let k = 0;
  for (let i = 0; i < z; i++) {
    k += ((x >> i) & 1) * 2 ** (2 * i) + ((y >> i) & 1) * 2 ** (2 * i + 1);
  }
  return 2 ** (2 * z) + k;
}
