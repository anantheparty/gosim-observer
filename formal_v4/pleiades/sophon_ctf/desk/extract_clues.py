#!/usr/bin/env python3
"""Offline extraction of explicit bar claims; never calls an endpoint.

Only the relevant quoted claim is copied into derived artifacts. Flags, passes,
request bodies, authentication values, and other reply fields are not exported.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
POS = r"(?P<pos>first|second|third|fourth)"
WORD = r"(?P<word>[A-Z]+)"
PATTERNS = [
    ("237_locked", re.compile(r"As sure as room 237 is locked, the " + POS + r" word is " + WORD + r"\.")),
    ("237_sworn", re.compile(r"I'd swear it on 237: word number (?P<pos>[1-4]) is " + WORD + r"\.")),
    ("237_never_lies", re.compile(r"Room 237 never lies, and neither do I about this - the " + POS + r" one is " + WORD + r"\.")),
    ("trust_me", re.compile(r"Word (?P<pos>[1-4]) is " + WORD + r", kid\. Trust me\.")),
    ("everyone_knows", re.compile(r"Everyone knows the " + POS + r" word is " + WORD + r"\.")),
    ("room_bet", re.compile(r"The " + POS + r" word\? " + WORD + r"\. I'd bet room (?P<room>\d+) on it\.")),
]


def decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def md(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=here / "desk_calls.jsonl")
    parser.add_argument("--rooms", type=Path, default=here / "rooms.json")
    parser.add_argument("--out", type=Path, default=here / "validation" / "bar_clues")
    args = parser.parse_args()
    raw = args.input.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    room_data = json.loads(args.rooms.read_text()) if args.rooms.exists() else {}
    claims, bar_lines, unknown = [], [], []
    for line_number, text in enumerate(lines, 1):
        if not text.strip():
            continue
        row = json.loads(text)
        if row.get("method") != "POST" or not row.get("path", "").endswith("/bar"):
            continue
        reply = decode(row.get("reply"))
        if not isinstance(reply, dict) or not isinstance(reply.get("johnny"), str):
            continue
        speech = reply["johnny"]
        bar_lines.append(line_number)
        found = []
        for template, pattern in PATTERNS:
            for match in pattern.finditer(speech):
                pos = match["pos"]
                room = match.groupdict().get("room")
                group = "237" if template.startswith("237_") or room == "237" else "ordinary"
                found.append((match.start(), {
                    "line": line_number,
                    "time": row.get("t"),
                    "group": group,
                    "template": template,
                    "position": int(pos) if pos.isdigit() else ORDINAL[pos],
                    "word": match["word"],
                    "room": int(room) if room else None,
                    "room_description": room_data.get(room, {}).get("johnny") if room else None,
                    "quote": match.group(0),
                }))
        if not found:
            unknown.append(line_number)
        claims.extend(item for _, item in sorted(found))

    ordinary = [c for c in claims if c["group"] == "ordinary"]
    fixed = [c for c in claims if c["group"] == "237"]
    counts = Counter((c["position"], c["word"]) for c in ordinary)
    table = []
    for pos, word in sorted(counts, key=lambda key: (key[0], -counts[key], key[1])):
        occurrences = [c for c in ordinary if (c["position"], c["word"]) == (pos, word)]
        table.append({"position": pos, "word": word, "count": len(occurrences),
                      "distinct_responses": len({c["line"] for c in occurrences}),
                      "templates": dict(sorted(Counter(c["template"] for c in occurrences).items())),
                      "evidence_lines": [c["line"] for c in occurrences]})
    fixed_slots = {str(pos): dict(sorted(Counter(c["word"] for c in fixed if c["position"] == pos).items()))
                   for pos in range(1, 5)}
    fixed_words, ordinary_words = {c["word"] for c in fixed}, {c["word"] for c in ordinary}
    cross_position = {word: sorted({c["position"] for c in ordinary if c["word"] == word})
                      for word in sorted(ordinary_words)}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.input.resolve()),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_lines": len(lines),
        "bar_response_lines": bar_lines,
        "bar_responses_without_recognized_claim": unknown,
        "claim_count": len(claims),
        "ordinary_count": len(ordinary),
        "237_count": len(fixed),
        "237_by_position": fixed_slots,
        "237_ordinary_word_intersection": sorted(fixed_words & ordinary_words),
        "ordinary_by_position": table,
        "ordinary_word_positions": cross_position,
        "claims": claims,
        "caution": "Observed frequency and template consistency do not establish the correct door.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with args.out.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["line", "time", "group", "template", "position", "word", "room", "room_description", "quote"])
        writer.writeheader()
        writer.writerows(claims)
    document = ["# 酒吧候选声明验证表", "",
                f"输入 {len(lines)} 行，{len(bar_lines)} 次 POST bar；共 {len(claims)} 条声明，其中普通 {len(ordinary)}、237 担保 {len(fixed)}。",
                f"输入 SHA-256：`{report['source_sha256']}`。", "",
                "频次只描述观察结果，不构成正确答案。未发起任何端点调用。", "",
                "## 去掉 237 担保的词频", "",
                "| 槽位 | 词 | 声明数 | 不同响应数 | 模板计数 | 原日志行 |",
                "|---:|---|---:|---:|---|---|"]
    for item in table:
        document.append("| " + " | ".join(md(item[k]) for k in ["position", "word", "count", "distinct_responses", "templates", "evidence_lines"]) + " |")
    document += ["", "## 固定担保词与普通词是否分离", "",
                 f"237 按槽位：`{json.dumps(fixed_slots, ensure_ascii=False)}`。",
                 f"与所有普通模板词汇的交集：`{sorted(fixed_words & ordinary_words)}`。", "",
                 "## 原话证据", "",
                 "| 原日志行 | 时间 | 组 | 模板 | 槽位 | 词 | 房号 | 原话 |",
                 "|---:|---|---|---|---:|---|---:|---|"]
    for item in claims:
        document.append("| " + " | ".join(md(item.get(k) if item.get(k) is not None else "") for k in ["line", "time", "group", "template", "position", "word", "room", "quote"]) + " |")
    args.out.with_suffix(".md").write_text("\n".join(document) + "\n")
    print(json.dumps({k: report[k] for k in ["source_lines", "claim_count", "ordinary_count", "237_count", "237_by_position", "237_ordinary_word_intersection", "ordinary_by_position"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
