"""Optional pre-filtering with osmium-tool, which keeps builder memory bounded on large inputs.

pyosmium's node-location cache stores *every* node of the file it reads. Running the builder on a country-size
extract would therefore index ~all nodes twice. `osmium tags-filter` instead writes two much smaller files that
contain only what the builder reads (plus the nodes/members they reference):

  boundaries.pbf   administrative boundary relations   -> pass 1 (area assembly)
  features.pbf     highways, housenumbers, interpolation -> pass 2
"""
import shutil
import subprocess
from pathlib import Path

BOUNDARY_EXPR = ["r/boundary=administrative"]
FEATURE_EXPR = ["w/highway", "w/addr:interpolation", "nwr/addr:housenumber"]


def available() -> bool:
    return shutil.which("osmium") is not None


def prefilter(pbf: str, workdir: str | Path, log=print) -> tuple[str, str]:
    if not available():
        raise RuntimeError("osmium-tool ('osmium' binary) not found; install it or use --no-prefilter")
    out = Path(workdir)
    out.mkdir(parents=True, exist_ok=True)
    bounds, feats = str(out / "boundaries.pbf"), str(out / "features.pbf")
    for dst, expr in ((bounds, BOUNDARY_EXPR), (feats, FEATURE_EXPR)):
        log(f"prefilter: osmium tags-filter {' '.join(expr)}")
        subprocess.run(["osmium", "tags-filter", pbf, *expr, "-o", dst, "--overwrite", "--no-progress"], check=True)
        log(f"  -> {Path(dst).name} {Path(dst).stat().st_size / 2**20:.0f} MiB")
    return bounds, feats
