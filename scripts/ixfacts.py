"""List displayed inline-XBRL facts in a filing.

For each fact: concept, period, dimensions, displayed text, scale and row label.
"""

import functools
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

IX = "{http://www.xbrl.org/2013/inlineXBRL}"
XBRLI = "{http://www.xbrl.org/2003/instance}"
XHTML = "{http://www.w3.org/1999/xhtml}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"


def tx(e):
    return re.sub(r"\s+", " ", "".join(e.itertext())).strip()


def _period(period, tag):
    return (period.findtext(f"{XBRLI}{tag}") or "").strip() or None


@functools.lru_cache(4)
def load(path):
    root = ET.parse(path).getroot()
    ctx = {}
    for c in root.iter(f"{XBRLI}context"):
        p = c.find(f"{XBRLI}period")
        dims = tuple(
            sorted(
                (m.get("dimension"), (m.text or "").strip())
                for m in c.iter(f"{XBRLDI}explicitMember")
            )
        )
        ctx[c.get("id")] = (
            _period(p, "startDate"),
            _period(p, "endDate") or _period(p, "instant"),
            dims,
        )
    parents = {ch: pa for pa in root.iter() for ch in pa}
    hidden = {e for h in root.iter(f"{IX}hidden") for e in h.iter()}
    return root, ctx, parents, hidden


def label(el, parents):
    n = el
    while n is not None and n.tag != f"{XHTML}tr":
        n = parents.get(n)
    if n is None:
        return ""
    for cell in n:
        t = tx(cell)
        if t and not re.fullmatch(r"[\s$()\d,.%—–-]*", t):
            return t[:90]
    return ""


def facts(path, concept_re, end=None, dims_re=None, limit=40):
    root, ctx, parents, hidden = load(path)
    out = []
    seen = set()
    for el in root.iter(f"{IX}nonFraction"):
        if el in hidden or not re.search(concept_re, el.get("name", "")):
            continue
        s, e, d = ctx.get(el.get("contextRef"), (None, None, ()))
        if end and e != end:
            continue
        ds = ";".join(f"{a.split(':')[-1]}={b.split(':')[-1]}" for a, b in d)
        if dims_re is not None and not re.search(dims_re, ds):
            continue
        key = (el.get("name"), s, e, ds)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            dict(
                concept=el.get("name"),
                start=s,
                end=e,
                dims=ds,
                shown=tx(el),
                scale=el.get("scale", "0"),
                sign=el.get("sign"),
                label=label(el, parents),
            )
        )
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    proj = Path(sys.argv[1])
    ticker = sys.argv[2]
    concept = sys.argv[3]
    dims = sys.argv[4] if len(sys.argv) > 4 else None
    m = [json.loads(line) for line in open(proj / "data/manifest.jsonl")]
    r = max((x for x in m if x["ticker"] == ticker), key=lambda x: x["report_date"])
    for f in facts(str(proj / r["local_path"]), concept, None, dims):
        print(f)
