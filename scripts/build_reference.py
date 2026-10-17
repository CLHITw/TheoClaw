"""Build the Bible-dictionary data for pastor mode (data/reference/), from public-domain CrossWire modules.

    python scripts/build_reference.py <folder with ISBE.zip, Easton.zip, Smith.zip>

Sources (all public domain, from crosswire.org's SWORD module packages):
- ISBE: International Standard Bible Encyclopedia, 1915 (James Orr, ed.)
- Easton: Easton's Illustrated Bible Dictionary, 1897
- Smith: Smith's Bible Dictionary, 1884

Writes data/reference/<name>.json: headword -> plain text (git-ignored; packed for the server).
The SWORD lexicon formats read here: RawLD (Smith) and zLD (ISBE, Easton, zlib-compressed blocks).
"""

from __future__ import annotations

import html
import json
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference"
MODULES = {"ISBE": "isbe", "Easton": "easton", "Smith": "smith"}


def _key(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").strip()


def read_rawld(files: dict[str, bytes], base: str) -> dict[str, str]:
    idx, dat = files[base + ".idx"], files[base + ".dat"]
    out = {}
    for i in range(0, len(idx) - 5, 6):  # RawLD: 4-byte offset, 2-byte size
        off, size = struct.unpack("<IH", idx[i:i + 6])
        rec = dat[off:off + size]
        key, _, body = rec.partition(b"\n")
        try:
            out[_key(key)] = body.decode("utf-8")
        except UnicodeDecodeError:  # older modules (Smith) are partly Windows-1252
            out[_key(key)] = body.decode("cp1252", "replace")
    return out


def read_zld(files: dict[str, bytes], base: str) -> dict[str, str]:
    idx, dat = files[base + ".idx"], files[base + ".dat"]
    zdx, zdt = files[base + ".zdx"], files[base + ".zdt"]
    blocks: dict[int, bytes] = {}

    def block(n: int) -> bytes:
        if n not in blocks:
            off, size = struct.unpack("<II", zdx[n * 8:n * 8 + 8])
            blocks[n] = zlib.decompress(zdt[off:off + size])
        return blocks[n]

    out = {}
    for i in range(0, len(idx) - 7, 8):
        off, size = struct.unpack("<II", idx[i:i + 8])
        rec = dat[off:off + size]
        nl = rec.find(b"\n")
        if nl < 0 or len(rec) < nl + 9:
            continue
        key = _key(rec[:nl])
        bnum, enum = struct.unpack("<II", rec[nl + 1:nl + 9])
        buf = block(bnum)
        count = struct.unpack("<I", buf[:4])[0]
        if enum >= count:
            continue
        eoff, esize = struct.unpack("<II", buf[4 + enum * 8:12 + enum * 8])
        out[key] = buf[eoff:eoff + esize].rstrip(b"\0").decode("utf-8", "replace")
    return out


def plain(markup: str) -> str:
    text = re.sub(r"<(?:lb|br)\s*/?>|</p>|<p[^>]*>|</div>|<div[^>]*>", "\n", markup, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def main(argv=None) -> None:
    src = Path((argv or sys.argv[1:])[0])
    OUT.mkdir(parents=True, exist_ok=True)
    for name, base in MODULES.items():
        z = zipfile.ZipFile(src / f"{name}.zip")
        files = {Path(n).name: z.read(n) for n in z.namelist() if not n.endswith("/")}
        conf = files[f"{base}.conf"].decode("utf-8", "replace")
        driver = re.search(r"ModDrv=(\w+)", conf).group(1)
        entries = read_zld(files, base) if driver == "zLD" else read_rawld(files, base)
        entries = {k: plain(v) for k, v in entries.items() if k and plain(v)}
        (OUT / f"{base}.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(entries)} entries")
    (OUT / "SOURCES.md").write_text(
        "Public domain, from crosswire.org SWORD modules: International Standard Bible Encyclopedia (1915), "
        "Easton's Bible Dictionary (1897), Smith's Bible Dictionary (1884).\n", encoding="utf-8")


if __name__ == "__main__":
    main()
