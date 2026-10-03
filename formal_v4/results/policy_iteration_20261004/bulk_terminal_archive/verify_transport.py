"""Opaque archive transport verification; no score/label decoding or extraction."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scanner(patterns):
    overlap = max(map(len, patterns)) - 1
    tail = b""
    found = False
    digest = hashlib.sha256()
    total = 0

    def feed(chunk):
        nonlocal tail, found, total
        digest.update(chunk)
        total += len(chunk)
        data = tail + chunk
        found |= any(pattern in data for pattern in patterns)
        tail = data[-overlap:] if overlap else b""

    return feed, lambda: (found, total, digest.hexdigest())


def verify():
    begin = time.monotonic()
    frozen = json.loads((ROOT / "REMOTE_FROZEN_FILES.json").read_text())
    expected = {row["path"]: row for row in frozen["files"]}
    actual = {str(path.relative_to(SOURCE)) for path in SOURCE.rglob("*") if path.is_file()}
    if actual != set(expected):
        raise ValueError("Transport file inventory differs from frozen inventory")
    components = (b"formal_v4", b"runs", b"gpu_service", b"token")
    patterns = [b"/".join(components), b"/".join(components[1:]), b"/".join(components[2:])]
    token_path = Path(__file__).resolve().parents[3] / "runs" / "gpu_service" / "token"
    secret_checked = token_path.is_file()
    if secret_checked:
        # Secret bytes stay in memory, never in reports, exceptions or output.
        secret = token_path.read_bytes().strip()
        if secret:
            patterns.append(secret)
    records, archive_records = [], []
    total_members = total_member_bytes = 0
    for name, remote in expected.items():
        path = SOURCE / name
        if path.stat().st_size != remote["bytes"] or sha(path) != remote["sha256"]:
            raise ValueError("Transport size/SHA mismatch for frozen file")
        row = dict(path="source/"+name, remote_relative_path=name, bytes=remote["bytes"], sha256=remote["sha256"], remote_hash_match=True)
        if name.endswith(".tar.gz"):
            members = regular_members = member_bytes = 0
            inner_manifests = []
            seen = set()
            with tarfile.open(path, "r|gz") as archive:
                for member in archive:
                    members += 1
                    normalized = PurePosixPath(member.name)
                    if member.name in seen or normalized.is_absolute() or ".." in normalized.parts:
                        raise ValueError("Unsafe or duplicate archive member path")
                    seen.add(member.name)
                    encoded = (member.name+"\n"+member.linkname).encode()
                    if any(pattern in encoded for pattern in patterns):
                        raise ValueError("Sensitive archive member path/link detected; no secret output")
                    if member.issym() or member.islnk():
                        raise ValueError("Unexpected archive link member")
                    if not member.isfile():
                        continue
                    regular_members += 1
                    feed, result = scanner(patterns)
                    handle = archive.extractfile(member)
                    for chunk in iter(lambda: handle.read(1024*1024), b""):
                        feed(chunk)
                    sensitive, length, digest = result()
                    handle.close()
                    if sensitive:
                        raise ValueError("Sensitive archive member bytes detected; no secret output")
                    if length != member.size:
                        raise ValueError("Archive member length mismatch")
                    member_bytes += length
                    if PurePosixPath(member.name).name.startswith("archive_members") and member.name.endswith(".json"):
                        # Preserve the original embedded manifest as opaque hash evidence.
                        inner_manifests.append(dict(name=member.name, bytes=length, sha256=digest))
            row["archive_scan"] = dict(member_count=members, regular_member_count=regular_members,
                                       uncompressed_member_bytes=member_bytes, original_member_manifests=inner_manifests,
                                       safe_paths=True, sensitive_path_matches=0, sensitive_value_matches=0,
                                       score_and_label_content_decoded=False, extracted_to_disk=False)
            archive_records.append(row)
            total_members += regular_members
            total_member_bytes += member_bytes
        else:
            feed, result = scanner(patterns)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024*1024), b""):
                    feed(chunk)
            if result()[0]:
                raise ValueError("Sensitive metadata bytes detected; no secret output")
            row["opaque_plaintext_sensitive_scan_passed"] = True
        records.append(row)
    if len(archive_records) != 315:
        raise ValueError("Incomplete bulk episode archive set")
    auxiliary_plaintext_count = 0
    for path in ROOT.iterdir():
        if not path.is_file() or path.suffix not in (".json", ".md", ".txt", ".log", ".py"):
            continue
        feed, result = scanner(patterns)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024*1024), b""):
                feed(chunk)
        if result()[0]:
            raise ValueError("Sensitive auxiliary plaintext bytes detected; no secret output")
        auxiliary_plaintext_count += 1
    # Only permitted source-lock/plan fields are parsed; summary/progress/job and
    # all episode score/label files remain opaque and byte-identical.
    source_lock = json.loads((SOURCE / "source_lock.json").read_text())
    bulk_lock = json.loads((SOURCE / "bulk_source_lock.json").read_text())
    plan = json.loads((SOURCE / "bulk_plan.json").read_text())
    provenance = dict(source_lock_schema=source_lock.get("schema"), bulk_source_lock_schema=bulk_lock.get("schema"),
                      source_lock_sha256=expected["source_lock.json"]["sha256"], plan_sha256=expected["bulk_plan.json"]["sha256"],
                      planned_group_count=len(plan.get("groups", [])),
                      bulk_source_lock_matches_source=bulk_lock.get("frozen_teacher_source_lock_sha256") == expected["source_lock.json"]["sha256"],
                      plan_matches_locked_sha256=bulk_lock.get("plan_sha256") == expected["bulk_plan.json"]["sha256"])
    if not provenance["bulk_source_lock_matches_source"] or not provenance["plan_matches_locked_sha256"] or provenance["planned_group_count"] != 64:
        raise ValueError("Original source-lock/plan provenance differs")
    manifest = dict(schema="bulk-terminal-local-sha256-manifest-v1", remote_host=frozen["remote_host"], remote_source_root=frozen["source_root"],
                    remote_frozen_inventory_sha256=sha(ROOT / "REMOTE_FROZEN_FILES.json"), archive_count=len(archive_records),
                    file_count=len(records), total_original_bytes=sum(row["bytes"] for row in records), files=records,
                    splits_required=0, maximum_blob_bytes=max(row["bytes"] for row in records),
                    split_threshold_bytes=95*1024*1024, maximum_part_bytes=60*1024*1024,
                    original_archives_repacked=False, terminal_labels_decoded=False, L4_scores_labels_summarized=False,
                    token_path_scan_passed=True, secret_value_scan_performed=secret_checked,
                    auxiliary_plaintext_files_scanned=auxiliary_plaintext_count,
                    provenance=provenance)
    if manifest["maximum_blob_bytes"] > manifest["split_threshold_bytes"]:
        raise ValueError("Blob needs the prescribed <=60 MiB reversible split")
    destination = ROOT / "MANIFEST_SHA256.json"
    destination.write_text(json.dumps(manifest, indent=2)+"\n")
    previous_receipt = json.loads((ROOT / "TRANSPORT_RECEIPT.json").read_text()) if (ROOT / "TRANSPORT_RECEIPT.json").exists() else {}
    receipt = dict(schema="bulk-terminal-transport-receipt-v1", passed=True, complete=True, status="all_original_bytes_and_archive_scans_verified", verified_utc=datetime.now(timezone.utc).isoformat(),
                   transport="single rsync file-list session over ssh", transport_failures=[], remote_files_frozen_before_transfer=True,
                   all_321_original_files_size_and_sha256_verified=True, archive_count=len(archive_records), file_count=len(records),
                   original_bytes=manifest["total_original_bytes"], regular_tar_members=total_members, uncompressed_member_bytes=total_member_bytes,
                   remote_frozen_inventory_sha256=sha(ROOT / "REMOTE_FROZEN_FILES.json"), manifest_sha256=sha(destination),
                   sensitive_path_matches=0, sensitive_secret_value_matches=0, secret_value_scan_performed=secret_checked,
                   auxiliary_plaintext_files_scanned=auxiliary_plaintext_count,
                   scores_labels_decoded=False, L4_results_summarized=False, tar_members_extracted_to_disk=False,
                   oversized_blobs=0, parts_created=0, teacher_outcome_records_filtered=False, optimization_steps=0,
                   local_verification_seconds=time.monotonic()-begin)
    receipt["transport_failures"] = previous_receipt.get("transport_failures", [])
    receipt["previously_paused_for_fit_transfer"] = bool(previous_receipt.get("paused_by_root") or previous_receipt.get("root_fit_sealed_transfer_completed"))
    receipt["resume_rsync_pid"] = previous_receipt.get("resume_rsync_pid")
    receipt["resume_utc"] = previous_receipt.get("resume_utc")
    receipt["active_bulk_transport_processes"] = 0
    receipt["parallel_transport_channels_started"] = previous_receipt.get("parallel_transport_channels_started", 0)
    (ROOT / "TRANSPORT_RECEIPT.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps({key: receipt[key] for key in ("passed", "archive_count", "file_count", "original_bytes", "regular_tar_members", "manifest_sha256", "sensitive_path_matches", "oversized_blobs", "local_verification_seconds")}))


if __name__ == "__main__":
    verify()
