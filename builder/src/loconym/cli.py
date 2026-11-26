import argparse
import sys

from .build import build


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="loconym")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Build a database from an .osm.pbf")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--language", default="en")
    b.add_argument("--city-level", type=int, default=8, help="admin_level streets are grouped under")
    b.add_argument("--search", choices=["none", "full"], default="full")
    b.add_argument("--max-leaf-bytes", type=int, default=16384)
    b.add_argument("--keep-scratch", action="store_true")
    b.add_argument("--prefilter", choices=["auto", "always", "never"], default="auto",
                   help="pre-filter the input with osmium-tool (auto: only for inputs > 400 MiB)")
    b.add_argument("--node-index", choices=["auto", "memory", "disk"], default="auto",
                   help="where node locations are cached (auto: disk for inputs > 400 MiB)")
    b.add_argument("--poi", action=argparse.BooleanOptionalAction, default=True,
                   help="index named points of interest (museums, parks, stations, shops...)")
    a = p.parse_args(argv)
    build(a.input, a.output, language=a.language, city_level=a.city_level, search=a.search == "full",
          max_leaf_bytes=a.max_leaf_bytes, keep_scratch=a.keep_scratch,
          prefilter_mode=a.prefilter, node_index=a.node_index, poi=a.poi, log=lambda m: print(m, file=sys.stderr))
