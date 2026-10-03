"""Read only released request records in frozen strong-native public messages.

Never opens terminal labels, teacher archives, bulk datasets or truth files.
"""
from pathlib import Path
import hashlib
import itertools
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "formal_v4/results/policy_iteration_20261004/natural_control"


def main():
    output = {}
    for card in ("L1", "L2", "L3", "L4"):
        path = BASE / card / "rank_0064/control/messages.jsonl"
        requests = []
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("record_type") == "observation_request":
                requests.append(row)
        pairs = []
        for left, right in itertools.combinations(requests, 2):
            overlap = max(left["issued_at_utc"], right["issued_at_utc"]) < min(left["deadline_utc"], right["deadline_utc"])
            pairs.append(dict(request_ids=[left["request_id"], right["request_id"]],
                              window_overlap=overlap,
                              shared_target_count=len(set(left["target_ids"]) & set(right["target_ids"]))))
        output[card] = dict(source=str(path.relative_to(ROOT)),
                           source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           request_count=len(requests),
                           requests=[dict(request_id=r["request_id"], issued_at_utc=r["issued_at_utc"],
                                          deadline_utc=r["deadline_utc"], target_count=len(r["target_ids"]),
                                          quorum=r["minimum_completed"], reward=r["completion_reward"])
                                     for r in requests],
                           pairs=pairs, any_joint_window=any(p["window_overlap"] for p in pairs))
    (HERE / "public_request_windows.json").write_text(json.dumps(output, indent=2, sort_keys=True)+"\n")
    print(json.dumps({card: dict(requests=row["request_count"], joint_window=row["any_joint_window"])
                      for card, row in output.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
