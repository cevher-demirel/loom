#!/usr/bin/env python3
"""Builds the minimal static site (index.html + the local assets it references) into
./dist, so a static host publishes the page and NOTHING else (the repository root also
holds backend source, tests and docs, which should not be served).

    python scripts/build_frontend.py [--out dist]

Fails if the page references a local file that does not exist or uses a root-absolute
path (which would break when hosted under a subpath). This script only writes to its
output folder; it does not deploy anything. Whether a static host uses it is the
owner's decision (see docs/stage30/DEPLOYMENT_AUDIT.md)."""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Standalone public pages that are not linked from index.html but must be published.
EXTRA_PAGES = ["about.html"]


def local_refs(html):
    refs = set()
    for m in re.finditer(r'''url\(\s*["']?([^)"']+)["']?\s*\)''', html):
        refs.add(m.group(1))
    for m in re.finditer(r'''(?:src|href)=["']([^"'#][^"']*)["']''', html):
        refs.add(m.group(1))
    return sorted(r for r in refs if not re.match(r"^(#|https?:|data:|mailto:|tel:|blob:|javascript:|\/\/)", r))


def build(out):
    html = (ROOT / "index.html").read_text()
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(ROOT / "index.html", out / "index.html")
    copied = ["index.html"]
    for ref in local_refs(html):
        if ref.startswith("/"):
            raise SystemExit(f"root-absolute reference breaks subpath hosting: {ref}")
        src = (ROOT / ref.split("?")[0]).resolve()
        if ROOT not in src.parents or not src.is_file():
            raise SystemExit(f"referenced file missing or outside the project: {ref}")
        dst = out / ref.split("?")[0]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(ref)
    for page in EXTRA_PAGES:
        shutil.copy2(ROOT / page, out / page)
        copied.append(page)
    return copied


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    for f in build(a.out):
        print("included:", f)
