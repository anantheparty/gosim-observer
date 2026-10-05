#!/usr/bin/env python3
"""Download the released public files of the formal (online) task cards A-D. Read-only.

Mirrors the website's "download task card" button (web/src/lib/taskCardSource.ts): list
scenarios/<slug>/{config,public,truth} in Storage (the bucket policy only lists released files),
download each file, and pack them as cards/<id>/<folder>/<file> into taskcard-<id>.zip.
The website builds that ZIP in the browser, so the archive hash depends on the packer and timestamps;
the per-file SHA-256 values (and the server's object listing) are the stable identity.
This script writes the ZIP with fixed timestamps so its hash is reproducible for identical files.

Output (default --out formal_v4/formal_cards):
  <out>/<A..D>/<a..d>/{config,public}/...   extracted files (archive layout)
  <out>/<A..D>/taskcard-<id>.zip            deterministic archive of the same files
  <out>/download_manifest.json              file sizes, SHA-256, server metadata, card statistics

  GOSIM_EMAIL=... GOSIM_PASSWORD=... python3 fetch_formal_cards.py [--cards a b c d] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gosim_platform import Client, sha256_bytes, utc_stamp  # noqa: E402

FOLDERS = ("config", "public", "truth")
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "formal_cards"


def card_stats(files: dict[str, bytes]) -> dict:
    stats: dict = {}
    if "public/targets.csv" in files:
        rows = list(csv.DictReader(io.StringIO(files["public/targets.csv"].decode("utf-8"))))
        req = [r for r in rows if str(r.get("required", "")).strip().lower() in ("true", "1", "yes")]
        classes: dict = {}
        for r in rows:
            classes[r.get("target_class")] = classes.get(r.get("target_class"), 0) + 1
        ras = [float(r["ra_deg"]) for r in rows]
        decs = [float(r["dec_deg"]) for r in rows]
        stats["targets"] = {
            "count": len(rows),
            "science_weight_sum": round(sum(float(r["science_weight"]) for r in rows), 6),
            "required_count": len(req),
            "required_science_weight_sum": round(sum(float(r["science_weight"]) for r in req), 6),
            "classes": dict(sorted(classes.items(), key=lambda kv: str(kv[0]))),
            "feature_flux_min": min(float(r["feature_flux"]) for r in rows),
            "feature_flux_max": max(float(r["feature_flux"]) for r in rows),
            "ra_range_deg": [min(ras), max(ras)],
            "dec_range_deg": [min(decs), max(decs)],
            "nonempty_10deg_ra_bands": len({int(ra // 10) for ra in ras}),
        }
    if "public/v4_night_calendar.csv" in files:
        nights = list(csv.DictReader(io.StringIO(files["public/v4_night_calendar.csv"].decode("utf-8"))))
        stats["calendar"] = {
            "nights": len(nights),
            "first_night": nights[0]["night_date"] if nights else None,
            "last_night": nights[-1]["night_date"] if nights else None,
            "observing_seconds_total": sum(int(n["night_seconds"]) for n in nights),
            "slot_count_total": sum(int(n["slot_count"]) for n in nights),
        }
    if "public/footprint.csv" in files:
        fp = list(csv.DictReader(io.StringIO(files["public/footprint.csv"].decode("utf-8"))))
        stats["footprint"] = {"vertices": len(fp), "components": len({r["component_id"] for r in fp})}
    if "config/v4_fiber_config.json" in files:
        fc = json.loads(files["config/v4_fiber_config.json"])
        stats["fiber_config"] = fc
    if "config/v4_score_config.json" in files:
        stats["score_config"] = json.loads(files["config/v4_score_config.json"])
    if "config/v4_scenario.json" in files:
        stats["scenario_config"] = json.loads(files["config/v4_scenario.json"])
    return stats


def deterministic_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, entries[name])
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", nargs="+", default=list("abcd"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    c = Client()
    ident = c.login()
    manifest = {"schema": "gosim-formal-card-download-v1", "downloaded_at_utc": utc_stamp(), "account_user_id": ident["user_id"],
                "source": "Supabase Storage bucket 'scenarios' (same requests as the website task-card download)", "cards": {}}
    for cid in args.cards:
        slug = f"v4-{cid}"
        listing, files = {}, {}
        for folder in FOLDERS:
            for item in c.storage_list("scenarios", f"{slug}/{folder}"):
                if not (item.get("id") or item.get("metadata")):
                    continue  # sub-folder placeholder
                key = f"{folder}/{item['name']}"
                listing[key] = {"server_size": (item.get("metadata") or {}).get("size"), "server_etag": (item.get("metadata") or {}).get("eTag"),
                                "server_updated_at": item.get("updated_at"), "server_mimetype": (item.get("metadata") or {}).get("mimetype")}
                files[key] = c.storage_download("scenarios", f"{slug}/{key}")
        if not files:
            print(f"{slug}: no released files (card not public yet?)", file=sys.stderr)
            manifest["cards"][cid.upper()] = {"slug": slug, "released": False}
            continue
        card_dir = args.out / cid.upper()
        entries = {}
        for key, data in files.items():
            target = card_dir / cid / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries[f"{cid}/{key}"] = data
            size_ok = listing[key]["server_size"] in (None, len(data))
            if not size_ok:
                raise SystemExit(f"{slug}/{key}: size mismatch {len(data)} vs listing {listing[key]['server_size']}")
        zbytes = deterministic_zip(entries)
        zpath = card_dir / f"taskcard-{cid}.zip"
        zpath.write_bytes(zbytes)
        manifest["cards"][cid.upper()] = {
            "slug": slug, "released": True,
            "archive": {"path": str(zpath.relative_to(args.out)), "bytes": len(zbytes), "sha256": sha256_bytes(zbytes),
                        "members": sorted(entries), "note": "deterministic re-pack (fixed 1980-01-01 timestamps, sorted, deflate-6) of the website ZIP layout"},
            "files": {key: dict(listing[key], bytes=len(data), sha256=sha256_bytes(data)) for key, data in sorted(files.items())},
            "stats": card_stats(files),
        }
        t = manifest["cards"][cid.upper()]["stats"].get("targets", {})
        cal = manifest["cards"][cid.upper()]["stats"].get("calendar", {})
        fib = (manifest["cards"][cid.upper()]["stats"].get("fiber_config") or {}).get("field", {})
        print(f"{cid.upper()} {slug}: {len(files)} files, zip sha256 {sha256_bytes(zbytes)[:16]}…  targets={t.get('count')} "
              f"sum_w={t.get('science_weight_sum')} required={t.get('required_count')} nights={cal.get('nights')} fibers={fib.get('n_fibers')}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "download_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'download_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
