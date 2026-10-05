#!/usr/bin/env python3
"""Read-only snapshot of our team's platform state: phases, daily quota, final version, project
versions, evaluation history (per-card scores) and the online / practice leaderboards.

Same reads as the website's Participate and Leaderboard pages (observer-portal "list", RPCs
current_competition / observer_card_board, table phases). Nothing is created or changed.
Team variables, model settings and provider entries are deliberately not stored.

  GOSIM_EMAIL=... GOSIM_PASSWORD=... python3 platform_status.py [--out DIR] [--top 10] [--quiet] [--card-details]
Writes <out>/status_<UTC>.json (default out: formal_v4/platform_snapshots) and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gosim_platform import Client, to_bjt, utc_stamp  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "platform_snapshots"


def board_view(board: dict, team_id: str) -> dict:
    rows = board.get("rows") or []
    cards = [c["slug"] for c in board.get("cards") or []]
    card_rank = {}
    for slug in cards:
        order = sorted(rows, key=lambda r: -float((r.get("card_scores") or {}).get(slug) or 0.0))
        card_rank[slug] = {r["team_id"]: i + 1 for i, r in enumerate(order)}
    out_rows = []
    for r in rows:
        out_rows.append({
            "rank": r.get("rank"), "team_name": r.get("team_name"), "team_id": r.get("team_id"), "mine": r.get("team_id") == team_id,
            "total_score": r.get("total_score"), "card_scores": r.get("card_scores"),
            "card_ranks": {s: card_rank[s].get(r["team_id"]) for s in cards},
            "evaluations": r.get("submission_count"), "scored_at": r.get("scored_at"), "batch_id": r.get("observer_batch_id"),
            "required_missing_mean": r.get("required_missing"), "targets_observed_mean": r.get("targets_observed"),
            "components_mean": r.get("components"), "final_version": r.get("final_version"),
        })
    mine = [r for r in out_rows if r["mine"]]
    return {"layout": board.get("layout"), "cards": cards, "teams": len(out_rows), "ours": mine[0] if mine else None, "rows": out_rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--card-details", action="store_true", help="also store each card tab of both boards (8 more RPC calls)")
    args = ap.parse_args(argv)

    c = Client()
    ident = c.login()
    me = c.rpc("me") or {}
    team = me.get("team") or {}
    team_id = team.get("id")
    comp = c.rpc("current_competition") or {}
    phases = c.phases()
    data = c.portal("list")
    by_phase = {p["id"]: p for p in phases}
    titles = {r["id"]: p.get("title") for p in data.get("projects") or [] for r in p.get("observer_revisions") or []}
    names = c.scenario_names([r["scenario_id"] for b in data.get("batches") or [] for r in b.get("observer_runs") or []])

    versions = []
    for p in data.get("projects") or []:
        for r in p.get("observer_revisions") or []:
            versions.append({"revision_id": r["id"], "title": p.get("title"), "status": "withdrawn" if r.get("archived_at") else r.get("status"),
                             "source_kind": r.get("source_kind"), "source_digest": r.get("source_digest"),
                             "created_at": r.get("created_at"), "created_bjt": to_bjt(r.get("created_at")),
                             "approved_at": r.get("approved_at"), "public_test": r.get("public_test"), "error": r.get("error") or ""})
    versions.sort(key=lambda v: v["created_at"] or "", reverse=True)

    evaluations = []
    for b in data.get("batches") or []:
        runs = sorted(({"card": (names.get(r["scenario_id"]) or {}).get("slug"), "run_id": r["id"], "status": r["status"],
                        "score": r.get("score"), "termination": (r.get("score_summary") or {}).get("termination_reason"),
                        "error": (r.get("error") or "")[:300], "has_result": bool(r.get("result_path"))}
                       for r in b.get("observer_runs") or []), key=lambda x: x["card"] or "")
        evaluations.append({"evaluation_id": b["id"], "phase": (by_phase.get(b["phase_id"]) or {}).get("slug"),
                            "version_title": titles.get(b.get("revision_id")), "revision_id": b.get("revision_id"),
                            "status": b["status"], "score_mean": b.get("score"), "created_at": b.get("created_at"),
                            "created_bjt": to_bjt(b.get("created_at")), "finished_at": b.get("finished_at"),
                            "quota_refunded": bool(b.get("quota_refunded")), "model_disabled": bool(b.get("model_disabled")),
                            "repeat_group": b.get("repeat_group"), "runs": runs})

    boards = {}
    for slug in ("online", "practice-projects"):
        ph = next((p for p in phases if p["slug"] == slug), None)
        if ph:
            boards[slug] = board_view(c.rpc("observer_card_board", p_phase=ph["id"], p_scenario_slug=None, p_limit=1000) or {}, team_id)
            if args.card_details:
                # Per-card tabs of the same board: each team's best overall evaluation, ranked on that card,
                # with the card's score components (required missing, targets observed, request rewards ...).
                boards[slug]["card_tabs"] = {}
                for card in boards[slug]["cards"]:
                    tab = c.rpc("observer_card_board", p_phase=ph["id"], p_scenario_slug=card, p_limit=1000) or {}
                    boards[slug]["card_tabs"][card] = [
                        {k: r.get(k) for k in ("rank", "team_name", "team_id", "total_score", "termination_reason",
                                               "required_missing", "targets_observed", "components", "observer_batch_id")}
                        for r in tab.get("rows") or []]

    quota = []
    for q in data.get("quota") or []:
        quota.append(dict(q, phase=(by_phase.get(q.get("phase_id")) or {}).get("slug"), resets_bjt=to_bjt(q.get("resets_at"))))
    phase_settings = []
    for s in data.get("phases") or []:
        info = s.get("phases") or {}
        phase_settings.append({k: s.get(k) for k in ("phase_id", "projects_enabled", "daily_batches", "max_active_evaluations", "runtime_seconds",
                                                      "repeat_runs", "sealed", "board_layout", "colocated", "model_call_limit",
                                                      "model_token_limit", "model_concurrency")}
                              | {"slug": info.get("slug"), "starts_at": info.get("starts_at"), "ends_at": info.get("ends_at")})

    snapshot = {
        "schema": "gosim-platform-status-v1", "taken_at_utc": utc_stamp(),
        "account": {"user_id": ident["user_id"], "team_id": team_id, "team_name": team.get("name")},
        "competition": comp, "phases": phases, "phase_settings": phase_settings, "quota": quota,
        "quota_reset_notice": c.rpc("observer_quota_reset_notice"),
        "final_versions": data.get("final_versions"), "versions": versions, "evaluations": evaluations, "boards": boards,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"status_{snapshot['taken_at_utc']}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"team {team.get('name')} ({team_id}); site mode {comp.get('mode')}")
        for q in quota:
            print(f"quota {q['phase']}: {q['remaining']}/{q['daily_batches']} evaluations left (used {q['used']}), "
                  f"preparations {q.get('preparations_remaining')}/{q.get('preparations_daily')}, resets {q['resets_at']} ({q['resets_bjt']})")
        for f in data.get("final_versions") or []:
            print(f"final version ({(by_phase.get(f['phase_id']) or {}).get('slug')}): chosen={f.get('chosen_revision_id')} "
                  f"best={f.get('best_revision_id')} best_score={f.get('best_score')} deadline={f.get('deadline')} locked={f.get('locked')}")
        for e in evaluations:
            cards = " ".join(f"{(r['card'] or '?').replace('v4-practice-', '').replace('v4-', '')}={r['score']}" for r in e["runs"])
            print(f"eval {e['evaluation_id'][:8]} {e['phase']:<17} {e['created_bjt']} {e['status']:<8} mean={e['score_mean']} "
                  f"[{e['version_title']}] {cards}{' (refunded)' if e['quota_refunded'] else ''}")
        for slug, bv in boards.items():
            ours = bv["ours"]
            print(f"board {slug}: {bv['teams']} teams; ours: " + (f"#{ours['rank']} {ours['total_score']:.4f}" if ours else "not ranked"))
            for r in bv["rows"][:args.top]:
                cs = " ".join(f"{k.replace('v4-practice-', '').replace('v4-', '')}={v:.2f}" for k, v in sorted((r["card_scores"] or {}).items()))
                print(f"   #{r['rank']:<3} {r['team_name'][:24]:<24} {r['total_score']:11.4f}  {cs}  evals={r['evaluations']}")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
