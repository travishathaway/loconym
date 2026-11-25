/** Varint reader. Numbers only (values stay below 2^53), so no 32-bit bit tricks. */
export class Reader {
  i = 0;
  constructor(readonly b: Uint8Array) {}

  v(): number {
    let n = 0;
    let mul = 1;
    for (;;) {
      const x = this.b[this.i++];
      n += (x & 0x7f) * mul;
      if (!(x & 0x80)) return n;
      mul *= 128;
    }
  }

  /** zigzag-decoded signed varint */
  sv(): number {
    const n = this.v();
    return n % 2 === 0 ? n / 2 : -(n + 1) / 2;
  }

  raw(n: number): Uint8Array {
    const r = this.b.subarray(this.i, this.i + n);
    this.i += n;
    return r;
  }

  more(): boolean {
    return this.i < this.b.length;
  }
}

const utf8 = new TextDecoder();
export const decodeUtf8 = (b: Uint8Array): string => utf8.decode(b);
