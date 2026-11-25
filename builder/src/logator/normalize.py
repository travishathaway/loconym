"""Text normalizer. Spec: docs/format-spec.md section 6. Must stay bit-identical with the TypeScript client."""
import re
import unicodedata

NORMALIZER_VERSION = "1"
_SPLIT = re.compile(r"[^0-9a-z]+")


def normalize_tokens(s: str) -> list[str]:
    s = s.replace("ß", "ss").replace("ẞ", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.category(c).startswith("M")).lower()  # drop all marks (\p{M})
    out = []
    for t in _SPLIT.split(s):
        if not t:
            continue
        if t.endswith("str") and len(t) > 3:
            t += "asse"
        out.append(t)
    return out


def normalize_key(s: str) -> str:
    """Canonical string for grouping names (e.g. street identity)."""
    return " ".join(normalize_tokens(s))
