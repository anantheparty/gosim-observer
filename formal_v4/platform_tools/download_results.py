#!/usr/bin/env python3
"""Download our own per-card result ZIPs of platform evaluations. Read-only (no quota is used).

Same requests as the website's "download result" button: observer-portal action `download_result`
(run_id) returns a short-lived signed URL; the ZIP is fetched from it. Each card's ZIP is stored as-is
and extracted next to it.

Output: <out>/<batch-id>/
          evaluation.json                       batch metadata (phase, version title, scores, timestamps)
          <card-slug>.zip                       original result ZIP (SHA-256 in manifest.json)
          <card-slug>/...                       extracted members
          manifest.json                         per-card ZIP + member SHA-256, score_report totals

  GOSIM_EMAIL=... GOSIM_PASSWORD=... python3 download_results.py --latest 1
  python3 download_results.py --batch caf453f6            # full id or unique prefix (>= 4 chars)
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gosim_platform import Client, sha256_bytes, to_bjt, utc_stamp  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "platform_results"


def safe_extract(zbytes: bytes, dest: Path) -> dict:
    members = {}
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f"corrupt member {bad}")
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = PurePosixPath(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise SystemExit(f"unsafe member name {info.filename!r}")
            data = z.read(info)
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            members[info.filename] = {"bytes": len(data), "sha256": sha256_bytes(data)}
    return members


def score_summary(dest: Path) -> dict | None:
    for path in sorted(dest.rglob("score_report.json")):
        try:
            rep = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out = {"file": str(path.relative_to(dest))}
        for key in ("total", "components", "counts", "termination", "accounted_wallclock_seconds", "scenario"):
            if key in rep:
                out[key] = rep[key]
        return out
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch", nargs="+", help="evaluation (batch) ids or unique prefixes")
    g.add_argument("--latest", type=int, help="the N most recent evaluations of the team")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="re-download cards that already have a ZIP")
    args = ap.parse_args(argv)

    c = Client()
    c.login()
    data = c.portal("list")
    batches = data.get("batches") or []
    phase_slug = {p["phase_id"]: (p.get("phases") or {}).get("slug") for p in data.get("phases") or []}
    titles = {r["id"]: p.get("title") for p in data.get("projects") or [] for r in p.get("observer_revisions") or []}
    if args.latest:
        chosen = batches[:args.latest]
    else:
        chosen = []
        for prefix in args.batch:
            hits = [b for b in batches if b["id"].startswith(prefix.lower())]
            if len(hits) != 1:
                raise SystemExit(f"{prefix}: {len(hits)} matching evaluations")
            chosen.append(hits[0])
    names = c.scenario_names([r["scenario_id"] for b in chosen for r in b.get("observer_runs") or []])

    for b in chosen:
        bdir = args.out / b["id"]
        bdir.mkdir(parents=True, exist_ok=True)
        meta = {"evaluation_id": b["id"], "phase": phase_slug.get(b["phase_id"], b["phase_id"]), "status": b["status"],
                "score_mean": b.get("score"), "revision_id": b.get("revision_id"), "version_title": titles.get(b.get("revision_id")),
                "created_at": b.get("created_at"), "created_bjt": to_bjt(b.get("created_at")), "finished_at": b.get("finished_at"),
                "quota_refunded": bool(b.get("quota_refunded")), "model_disabled": bool(b.get("model_disabled")),
                "runs": [{"run_id": r["id"], "card": (names.get(r["scenario_id"]) or {}).get("slug"), "status": r["status"],
                          "score": r.get("score"), "error": r.get("error") or "", "started_at": r.get("started_at"),
                          "finished_at": r.get("finished_at"), "decisions_digest": r.get("decisions_digest"),
                          "score_summary": r.get("score_summary")} for r in b.get("observer_runs") or []]}
        (bdir / "evaluation.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest_path = bdir / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"evaluation_id": b["id"], "cards": {}}
        for run in sorted(b.get("observer_runs") or [], key=lambda r: (names.get(r["scenario_id"]) or {}).get("slug", "")):
            slug = (names.get(run["scenario_id"]) or {}).get("slug") or run["id"]
            zpath = bdir / f"{slug}.zip"
            if not run.get("result_path"):
                print(f"{b['id'][:8]} {slug}: no result yet ({run['status']})")
                continue
            if zpath.exists() and not args.force:
                print(f"{b['id'][:8]} {slug}: already downloaded")
                continue
            url = (c.portal("download_result", run_id=run["id"]) or {}).get("url")
            if not url:
                print(f"{b['id'][:8]} {slug}: no download URL", file=sys.stderr)
                continue
            zbytes = c.get_url(url)
            zpath.write_bytes(zbytes)
            members = safe_extract(zbytes, bdir / slug)
            manifest["cards"][slug] = {"run_id": run["id"], "platform_score": run.get("score"), "zip": zpath.name,
                                       "zip_bytes": len(zbytes), "zip_sha256": sha256_bytes(zbytes),
                                       "download_host": url.split("/")[2], "downloaded_at_utc": utc_stamp(),
                                       "members": members, "score_report": score_summary(bdir / slug)}
            rep = manifest["cards"][slug]["score_report"] or {}
            print(f"{b['id'][:8]} {slug}: {len(zbytes)} bytes sha256 {sha256_bytes(zbytes)[:16]}… members={len(members)} "
                  f"platform={run.get('score')} report_total={rep.get('total')}")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
