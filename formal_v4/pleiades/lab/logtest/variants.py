#!/usr/bin/env python3
"""Deterministic, offline log-format robustness corpus (stdlib only).

Run: python work/logtest/variants.py
     python work/logtest/variants.py --variants original names_tone clock_styles

The original c31 parser is the supplied *schedule* oracle, not a simulator.
Unresolved alternatives remain separate from confirmed faults. Synthetic
variants render changes to the oracle state after each original issued block;
they never use a later block's state. Names/tone edits preserve the raw log.
Each truth file contains final labels, streaming checkpoints and provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # Never write into the read-only oracle package.
HERE = Path(__file__).resolve().parent
OFFSETS = {"A1": -4, "B1": 2, "C1": -10, "D1": -9}
VARIANTS = {
    "original": "Unmodified source control; same oracle labels as all variants.",
    "names_tone": "Lossless speaker/name and conversational filler changes.",
    "canonical": "Control for state-based rewrites: familiar date/time, status and flat-window syntax.",
    "clock_styles": "Canonical replay with AM/PM, h/min, compact, English, Japanese and Chinese clocks.",
    "timezone_dates": "Fixed offsets +1/-10/-13/+5:30/+9; ISO, English month and Chinese dates; explicit interval endpoints.",
    "equipment_aliases": "Canonical replay with new fault-device and non-fault calibration names and explicit semantics.",
    "status_rewrites": "Familiar dates/clocks/windows; new withdrawn/gossip/correction/postponement/rain wording only.",
    "status_relative": "Withdrawn/superseded/held-back wording, correction/postponement relationships, calibration-relative times, weekday dates.",
    "cipher_words": "ROT13 and Caesar +7/+19, explicit per-line keys; English time numbers and month names.",
    "mixed": "Combined multilingual clocks, zones, dates, devices, encoding, relative times and revised statuses.",
    "engineering_table": "New Chinese engineering/calibration task types in a rolling plan table with dates, clocks, status and class in separate columns.",
    "bullet_workorders": "New Chinese task types in multiline work-order lists; date/clock/status/impact must be assembled across lines.",
}
HEADER = re.compile(r"^#### issued ([^\n]+)\n", re.M)


def epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp needs an explicit UTC offset: {value}")
    return dt.timestamp()


def utc(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def local(t, off):
    return datetime.fromtimestamp(t, timezone(timedelta(hours=off)))


def entries(path):
    text = Path(path).read_text(encoding="utf-8")
    matches = list(HEADER.finditer(text))
    if not matches or text[:matches[0].start()].strip():
        raise ValueError(f"Invalid issued-block log: {path}")
    result = []
    for i, match in enumerate(matches):
        issued = match.group(1).strip()
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append((issued, text[match.end():stop].rstrip("\n")))
        epoch(issued)
    if any(epoch(a[0]) > epoch(b[0]) for a, b in zip(result, result[1:])):
        raise ValueError(f"Issued timestamps are not ordered: {path}")
    return result


def load_reader(spec):
    """Load /absolute/or/relative/file.py:Class or importable.module:Class."""
    name, sep, cls = spec.rpartition(":")
    if not sep:
        name, cls = spec, "GuiderLog"
    path = Path(name)
    if path.exists():
        path = path.resolve()
        sys.path.insert(0, str(path.parent))
        module_name = "_evalreader_" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
        spec_obj = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec_obj)
        sys.modules[module_name] = module
        spec_obj.loader.exec_module(module)
    else:
        module = importlib.import_module(name)
    return getattr(module, cls)


def state(reader):
    return {
        "faults_utc": [utc(c["t"]) for c in reader.due()],
        "alternatives_utc": [utc(c["t"]) for c in reader.probes()],
        "flats_utc": [[utc(a), utc(b)] for a, b in sorted(reader.flats)],
        "rumours_utc": sorted(utc(c["t"]) for c in reader.cands.values()
                             if c["st"] == "unsure" and not c["void"]),
        "cancelled_utc": sorted(utc(c["t"]) for c in reader.cands.values() if c["void"]),
    }


def extract(card, source, oracle):
    raw = entries(source)
    reader = oracle(utc_offset_hours=OFFSETS[card])
    checkpoints, changes, prev, prev_flats = [], [], {}, set()
    source_lines = []
    module = sys.modules[oracle.__module__]
    for issued, text in raw:
        source_lines.extend(line.strip() for line in text.splitlines() if line.strip())
        reader.read(text, epoch(issued))
        snap = state(reader)
        checkpoints.append({"issued_utc": issued, **snap})
        changed = []
        for key, c in sorted(reader.cands.items()):
            signature = (c["st"], c["void"])
            if prev.get(key) != signature:
                full_source = next((s for s in reversed(source_lines) if c["src"] and s.startswith(c["src"])), c["src"])
                supersedes = []
                rain_base = None
                if c["st"] == "alt" and not c["void"]:
                    prepared = module.prep(full_source)
                    pairs = module.date_time_pairs(prepared)
                    if module.RAIN.search(prepared) and pairs:
                        mo, da, hh, mi, _ = pairs[0]
                        rain_base = reader._utc(mo, da, hh, mi, reader._tz(prepared), epoch(issued))
                if not c["void"] and c["st"] == "official":
                    prepared = module.prep(full_source)
                    pairs = module.date_time_pairs(prepared)
                    if module.POSTPONE.search(prepared) and not module.RAIN.search(prepared):
                        old_pairs = pairs[:1]
                    elif module.CORR.search(prepared):
                        old_pairs = pairs[:-1]
                    else:
                        old_pairs = []
                    for mo, da, hh, mi, _ in old_pairs:
                        old = reader._utc(mo, da, hh, mi, reader._tz(prepared), epoch(issued))
                        old_c = reader.cands.get(reader._key(old)) if old is not None else None
                        if old_c and old_c["void"] and old != c["t"]:
                            supersedes.append({"t": old, "reason": old_c["void"]})
                changed.append({"t": c["t"], "status": c["st"], "void": c["void"],
                                "source": full_source, "previous": prev.get(key), "supersedes": supersedes})
                changed[-1]["rain_base_epoch"] = rain_base
            prev[key] = signature
        new_flats = [{"start": a, "end": b, "night": list(reader.flats[(a, b)])}
                     for a, b in sorted(set(reader.flats) - prev_flats)]
        prev_flats = set(reader.flats)
        changes.append({"candidates": changed, "flats": new_flats})
    if reader.unparsed or reader.rel_flat or reader.rel_other:
        raise ValueError(f"Oracle cannot fully resolve {card}: unparsed={len(reader.unparsed)}, "
                         f"pending={len(reader.rel_flat) + len(reader.rel_other)}")
    return raw, changes, {**checkpoints[-1], "checkpoints": checkpoints,
                         "source_changes": changes}


EN_SMALL = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty"}


def en(n):
    if n < 20:
        return EN_SMALL[n]
    return EN_TENS[n // 10 * 10] + ("-" + EN_SMALL[n % 10] if n % 10 else "")


def cn(n):
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    return (digits[n // 10] if n >= 20 else "") + "十" + (digits[n % 10] if n % 10 else "")


def clock(dt, style):
    h, m = dt.hour, dt.minute
    h12 = h % 12 or 12
    if style == 0:
        return f"{h12}:{m:02d} {'AM' if h < 12 else 'PM'}"
    if style == 1:
        return f"{h:02d}h{m:02d}"
    if style == 2:
        return f"{h:02d}{m:02d} hours"
    if style == 3:
        suffix = "a.m." if h < 12 else "p.m."
        words = {0: f"{en(h12)} o'clock", 15: f"quarter past {en(h12)}",
                 30: f"half past {en(h12)}", 45: f"quarter to {en(h12 % 12 + 1)}"}
        # Avoid the AM/PM and calendar-date ambiguity around noon/midnight.
        if m == 45 and h12 == 11:
            return "quarter to noon" if h < 12 else "quarter to midnight at the end of this date"
        return words.get(m, f"{en(h12)} {en(m)}") + " " + suffix
    if style == 4:
        return ("午前" if h < 12 else "午後") + f"{h % 12}時" + ("半" if m == 30 else f"{m}分")
    if style == 5:
        period = "凌晨" if h < 6 else "上午" if h < 12 else "下午" if h < 18 else "晚上"
        if h == 12:
            period = "中午"
        return period + cn(h12 if h else 0) + "点" + {0: "整", 15: "一刻", 30: "半", 45: "三刻"}.get(m, cn(m) + "分")
    return dt.strftime("%H:%M")


def stamp(t, off, style=6):
    dt = local(t, off)
    return f"{dt.month}/{dt.day} {clock(dt, style)}"


def names_tone(text):
    for a, b in (("祥子", "林岚"), ("立希", "周航"), ("【灯】", "【小陈】"),
                 ("灯记", "小陈记"), ("灯搞", "小陈搞"), ("灯，", "小陈，"),
                 ("灯刚", "小陈刚"), ("工程组通知", "设备值班组通知"),
                 ("再念一遍", "交接时重申"), ("（第 3 杯咖啡了）", "（保温杯放值班台了）"),
                 ("（车停在 B2 区 17 号）", "（工具箱在东门）"),
                 ("（有事打分机 214）", "（交接本放桌面了）")):
        text = text.replace(a, b)
    return text


def background(text, oracle_module):
    """Keep original unrelated weather/terrain/chatter and scope its cipher key."""
    keep = []
    for line in text.splitlines():
        prepared = oracle_module.prep(line)
        if not (oracle_module.GUIDER.search(prepared) or oracle_module.FLAT.search(prepared)):
            keep.append(line)
    return ("【版面说明】以下原天气/日常栏沿用其自己的暗号约定；后面的设备排程栏单独说明，不套用天气栏的英文移位规则。\n"
            + "\n".join(keep) + "\n【设备排程栏开始】本栏英语默认明文；只有带逐句加密标签时才解码。\n")


FAULT_DEVICES = ("autoguider", "CCD controller", "dome encoder", "fiber positioner")
CALIBRATIONS = ("dome flats", "arc lamp 定标", "bias frames", "twilight flats")
ZONES = ((1, "巴黎表，固定 UTC+1"), (-10, "夏威夷表，UTC-10"),
         (-13, "船上实验钟，固定 UTC-13"), (5.5, "印度表，UTC+05:30"), (9, "东京表，UTC+9"))


def rotate(text, shift):
    def letter(ch):
        start = ord("A") if "A" <= ch <= "Z" else ord("a") if "a" <= ch <= "z" else None
        return chr(start + (ord(ch) - start + shift) % 26) if start is not None else ch
    return "".join(map(letter, text))


def encoded(text, i):
    shift = (13, 7, 19)[i % 3]
    marker = "ROT13（英文字母转十三格）" if shift == 13 else f"Caesar +{shift}（仅字母加 {shift}，阅读时减 {shift}）"
    return f"【通信转录】以下一句使用 {marker}：{rotate(text, shift)}"


def device(t, varied):
    return FAULT_DEVICES[int(t // 900) % len(FAULT_DEVICES)] if varied else "导星相机"


def date_relative(t, issued, off):
    dt, origin = local(t, off), local(epoch(issued), off)
    days = (dt.date() - origin.date()).days
    short = {-2: "前天", -1: "昨天", 0: "今天", 1: "明天", 2: "后天"}
    day = short.get(days, f"交接当天之后第 {days} 天" if days >= 0 else f"交接当天之前第 {-days} 天")
    return f"{day}（星期{'一二三四五六日'[dt.weekday()]}）{dt:%H:%M}"


def fancy_stamp(t, off, i):
    zone, label = ZONES[i % len(ZONES)]
    dt = local(t, zone)
    style = i % 4
    if style == 0:
        return dt.isoformat(timespec="seconds")
    if style == 1:
        return f"{dt:%b} {dt.day}, {dt.year} at {dt:%H:%M}（{label}）"
    if style == 2:
        return f"{dt.day} {dt:%B} {dt.year} {dt:%H:%M}（{label}）"
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt:%H:%M}（{label}）"


def word_stamp(t, off):
    dt = local(t, off)
    # Full year makes the Dec/Jan boundary unambiguous; only time numbers are spelled out.
    return f"{dt:%B} {en(dt.day)}, {dt.year}, {clock(dt, 3)} local time"


NEW_FAULT_TASKS = ("光纤定位器校准", "快门更换", "CCD 控制器重启", "穹顶编码器调零")
NEW_CALIBRATION_TASKS = ("穹顶平场", "弧灯定标", "暗场采集", "读出偏置测量")


def structured(changes, issued, off, variant, block_index):
    """New operation vocabulary; identical time/status changes, new document shape."""
    lines = [f"工程组滚动排程，第 {block_index + 1} 期修订。发布时刻：{issued}。",
             f"全页日期、表盘均使用本站固定 UTC{off:+d}；日期按日历日，不按观测夜归并。",
             "本页只更新列出的工单；此前未列出的有效排程继续保留。",
             "业务字典：光纤定位器校准、快门更换、CCD 控制器重启、穹顶编码器调零属于工程干预。",
             "工程干预在已批准的开始时刻造成仪器故障：首小时效率乘 0.3，随后乘 0.005，持续到 report 报修恢复。",
             "业务字典：穹顶平场、弧灯定标、暗场采集、读出偏置测量属于采集校准；它们只在规定窗口内产生废片，属于非故障，不能报修。",
             "撤回归档、口头草案、待核验候选都不是已批准的开工通知。区间含起点、不含终点。"]
    records = []
    for i, w in enumerate(changes["flats"]):
        records.append({"category": "采集校准", "name": NEW_CALIBRATION_TASKS[(block_index + i) % 4],
                        "status": "已批准", "start": w["start"], "end": w["end"],
                        "note": "该窗口的帧作废；不构成仪器故障，禁止报修。"})
    for c in changes["candidates"]:
        name = NEW_FAULT_TASKS[int(c["t"] // 900) % 4]
        if c["void"]:
            status = "撤回归档"
            reason = {"wrong": "抄表错误", "postponed": "已顺延，旧时刻作废", "cancel": "工程组撤销"}.get(c["void"], "已作废")
            note = f"{reason}；本行时间只作历史留档，不安排开工，不得报修。"
        elif c["status"] == "official":
            status, note = "已批准", "准时开工，触发仪器故障并按规程报修。"
            if c["supersedes"]:
                old = local(c["supersedes"][0]["t"], off)
                note += f" 本行替换抄在 {old:%Y-%m-%d %H:%M} 的旧时刻，旧票作废。"
        elif c["status"] == "alt":
            status = "待核验候选"
            if c["rain_base_epoch"] is not None:
                base = local(c["rain_base_epoch"], off)
                delayed = local(c["rain_base_epoch"] + 86400, off)
                note = f"天气条件未定：无雨才用 {base:%Y-%m-%d %H:%M}，该夜降雨则用 {delayed:%Y-%m-%d %H:%M}；只选其一，先核验实际开工。"
            else:
                note = "跨日相对排程折算出的备选钟点，尚未列入确认故障；到点先核验是否实际开工。"
        else:
            status, note = "口头草案", "只是转述，未获工程组签字；本行时间不作为开工依据，不得报修。"
        records.append({"category": "工程干预", "name": name, "status": status,
                        "start": c["t"], "end": None, "note": note})

    if variant == "engineering_table":
        lines += ["| 工单号 | 业务类别 | 作业项目 | 当前状态 | 开始日期 | 开始表盘 | 结束日期 | 结束表盘 | 执行说明 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(records):
        prefix = "C" if r["category"] == "采集校准" else "E"
        ticket = prefix + hashlib.sha256(str(r["start"]).encode()).hexdigest()[:8].upper()
        start = local(r["start"], off)
        end = local(r["end"], off) if r["end"] is not None else None
        if variant == "engineering_table":
            cells = [ticket, r["category"], r["name"], r["status"], f"{start:%Y-%m-%d}", f"{start:%H:%M}",
                     f"{end:%Y-%m-%d}" if end else "报修恢复为止", f"{end:%H:%M}" if end else "不自动恢复", r["note"]]
            lines.append("| " + " | ".join(cells) + " |")
        else:
            lines += [f"- 工单 {ticket} · {r['name']}",
                      f"  类别：{r['category']}；执行许可：{r['status']}。",
                      f"  开始日期：{start.year}年{start.month}月{start.day}日；星期{'一二三四五六日'[start.weekday()]}。",
                      f"  开始表盘：{clock(start, (block_index + i) % 2)}。"]
            if end:
                lines += [f"  结束日期：{end.year}年{end.month}月{end.day}日。",
                          f"  结束表盘：{clock(end, (block_index + i) % 2)}。"]
            lines.append("  处置说明：" + r["note"])
    if not records:
        lines.append("本期没有新增或撤回条目，继续按前期有效工单执行。")
    return "\n".join(lines)


def synthetic(changes, issued, off, variant, block_index, oracle_module):
    if variant in ("engineering_table", "bullet_workorders"):
        return structured(changes, issued, off, variant, block_index)
    varied = variant in ("equipment_aliases", "mixed")
    relative = variant in ("status_relative", "mixed")
    statuses = relative or variant == "status_rewrites"
    lines = [f"【值班说明】本站本地时间固定 UTC{off:+d}；未另标时区的时刻均按本站时间。",
             "【交接约定】夜晚日期指当日中午起的二十四小时；夜内零点到上午十一点属于次日。区间含起点、不含终点。",
             "【设备规程】工程作业从通知时刻触发仪器故障：前一小时效率乘 0.3，随后乘 0.005，直到 report 报修才恢复。",
             "【设备规程】校准作业只使对应区间的数据作废，不触发仪器故障，报修算误报。",
             "【日常留言】工具箱放在东门；隔壁台站的天气和停机通知不适用于本站。"]
    if varied:
        lines += ["【设备字典】故障类工程作业设备：autoguider、CCD controller、dome encoder、fiber positioner；都遵循上述报修规程。",
                  "【设备字典】非故障校准类型：dome flats、arc lamp 定标、bias frames、twilight flats；全部仅作废数据。"]
    if variant in ("timezone_dates", "mixed"):
        lines.append("【时钟约定】本页所有地名只是表盘标签，严格使用给出的固定 UTC 偏移，不另加夏令时。")
    if relative:
        lines.append(f"【日期锚点】本次交接的本站日期是 {local(epoch(issued), off):%Y-%m-%d}；今天/明天/后天均相对此日期，时间在早晨也照日历计。")

    def at(t, i):
        if variant == "clock_styles":
            return stamp(t, off, (block_index + i) % 6)
        if variant == "timezone_dates":
            return fancy_stamp(t, off, block_index + i)
        if variant == "cipher_words":
            return word_stamp(t, off)
        if relative and (variant == "status_relative" or i % 3 == 0):
            return date_relative(t, issued, off)
        if variant == "mixed":
            return fancy_stamp(t, off, block_index + i) if i % 3 == 1 else stamp(t, off, (block_index + i) % 6)
        return stamp(t, off)

    # Canonical/clock/equipment variants keep the original night-window grammar,
    # allowing effects of clock syntax and vocabulary to be measured separately.
    if variant in ("canonical", "clock_styles", "equipment_aliases", "status_rewrites"):
        groups = {}
        for w in changes["flats"]:
            groups.setdefault(tuple(w["night"]), []).append(w)
        for i, (night, windows) in enumerate(sorted(groups.items())):
            style = (block_index + i) % 6 if variant == "clock_styles" else 6
            ranges = "、".join(clock(local(w["start"], off), style) + "到" + clock(local(w["end"], off), style) for w in windows)
            operation = CALIBRATIONS[(block_index + i) % 4] if varied else "平场灯与镜盖测试"
            lines.append(f"【林岚】{night[1]}/{night[2]} 当晚有 {operation}：{ranges}。这些区间数据作废，但不是故障，不要报修。")
    else:
        for i, w in enumerate(changes["flats"]):
            ticket = f"C{block_index + 1:03d}-{i + 1:02d}"
            operation = CALIBRATIONS[(block_index + i) % 4] if varied else "平场灯/镜盖测试"
            if variant == "cipher_words" or (variant == "mixed" and i % 5 == 4):
                activity = operation if varied else "flat-lamp tests"
                lines.append(encoded(f"Calibration ticket {ticket}: {activity} run from {word_stamp(w['start'], off)} until {word_stamp(w['end'], off)}. Frames in that interval are void; this is not a fault. Do not report it.", i + block_index))
            else:
                lines.append(f"【林岚】校准票 {ticket}，{operation}：从 {at(w['start'], i)} 到 {at(w['end'], i)}。数据作废，但不是故障，禁止报修。")

    repeated_alt_sources = set()
    for i, c in enumerate(changes["candidates"]):
        equipment, when = device(c["t"], varied), at(c["t"], i)
        if c["status"] == "alt" and not c["void"]:
            # Preserve the actual conditional/cross-day relationship, rather than
            # inventing a rain outcome. All prior reference jobs are still present.
            source = c["source"]
            if source not in repeated_alt_sources:
                if statuses:
                    source = oracle_module.prep(source)
                    if c["rain_base_epoch"] is not None:
                        base = c["rain_base_epoch"]
                        source = (f"【林岚】有条件的工程票：{equipment} 暂列 {at(base, i)}；晴天才兑现，"
                                  f"如果该晚降雨，原档自动失效，改用 {at(base + 86400, i)}。天气结果未定，这两档只待核验，切勿当作两个确定故障。")
                    else:
                        source = source.replace("比前面", "相较先前").replace("比上述", "相较先前").replace("按钟点算", "比较当地表盘读数").replace("同一時間", "表盘读数照旧")
                lines.append(source)
                repeated_alt_sources.add(c["source"])
            continue
        if variant == "cipher_words" or (variant == "mixed" and i % 4 == 3 and not c["supersedes"]):
            action = ("The engineering booking is withdrawn; do not report a fault for it." if c["void"] else
                      "Official engineering work begins at this instant. Report the fault then." if c["status"] == "official" else
                      "Unconfirmed break-room gossip only. Do not turn this into an official booking.")
            name = equipment if varied else "Guider camera"
            lines.append(encoded(f"{name}, {word_stamp(c['t'], off)}: {action}", block_index + i))
            continue
        if c["void"]:
            status = "该工程票已作废，排班表划掉这一档，不执行，也不能报修" if statuses else "取消这次作业，不执行，不要报修"
            lines.append(f"【周航】{equipment} {when}：{status}。")
        elif c["status"] == "unsure":
            status = "只是茶水间转述，值班长未签字，排班表上没有这一项，不能报修" if statuses else "传言而已，未确认，先别当真"
            lines.append(f"【小陈】{equipment} {when}，{status}。")
        else:
            relations = c.get("supersedes", [])
            if statuses and relations:
                old = relations[0]
                delta = int((c["t"] - old["t"]) / 60)
                if old["reason"] == "postponed" and delta > 0:
                    lines.append(f"【周航】{equipment} 原票写 {at(old['t'], i)}，这档划掉；工班往后挪 {delta} 分钟再开工，以挪后的时刻触发故障并报修。")
                else:
                    lines.append(f"【周航】{equipment} 的抄表记录 {at(old['t'], i)} 不予采信；签字版唯一生效时刻为 {when}，届时作业并报修。")
            elif relative:
                preceding = [(j, w) for j, w in enumerate(changes["flats"])
                             if 0 <= c["t"] - w["end"] <= 4 * 3600]
                if preceding and i % 2 == 0:
                    j, w = max(preceding, key=lambda pair: pair[1]["end"])
                    minutes = int((c["t"] - w["end"]) / 60)
                    lines.append(f"【周航】{equipment} 的签字工程票：等上文校准票 C{block_index + 1:03d}-{j + 1:02d} 收尾后再过 {minutes} 分钟即开工，届时触发故障并报修。校准区间自身不报修。")
                else:
                    lines.append(f"【周航】签字排班生效：{equipment} {when} 开始作业，到点报修。")
            else:
                lines.append(f"【周航】设备组正式确认：{equipment} {when} 开始作业，到点报修。")
    if not changes["flats"] and not changes["candidates"]:
        lines.append("【林岚】本条无排程变更，沿用先前有效记录。")
    return "\n".join(lines)


def generate(args):
    oracle_path = args.oracle.resolve()
    oracle = load_reader(str(oracle_path) + ":GuiderLog")
    extracted = {card: extract(card, args.source / f"{card}.log.txt", oracle) for card in OFFSETS}
    module = sys.modules[oracle.__module__]
    backgrounds = {card: [background(text, module) for _, text in raw]
                   for card, (raw, _, _) in extracted.items()}
    for variant in args.variants:
        out = args.output / variant
        out.mkdir(parents=True, exist_ok=True)
        for card, (raw, changes, truth) in extracted.items():
            rendered = []
            control = oracle(utc_offset_hours=OFFSETS[card]) if variant in ("original", "names_tone", "canonical") else None
            for index, ((issued, text), change) in enumerate(zip(raw, changes)):
                body = text if variant == "original" else names_tone(text) if variant == "names_tone" else backgrounds[card][index] + synthetic(change, issued, OFFSETS[card], variant, index, module)
                if control is not None:
                    control.read(body, epoch(issued))
                    for key, value in state(control).items():
                        if value != truth["checkpoints"][index][key]:
                            raise ValueError(f"Semantic replay check failed: {variant}/{card} block {index}, {key}")
                rendered.append(f"#### issued {issued}\n{body}\n")
            content = "".join(rendered)
            (out / f"{card}.log.txt").write_text(content, encoding="utf-8")
            source = args.source / f"{card}.log.txt"
            labels = {
                "schema_version": 1, "card": card, "variant": variant,
                "description": VARIANTS[variant], "utc_offset_hours": OFFSETS[card],
                "truth_kind": "c31 schedule semantics; alternatives are not verified physical faults",
                "source_path": str(source.resolve()),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "oracle_path": str(oracle_path),
                "oracle_sha256": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
                "log_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "entry_count": len(raw), **truth,
            }
            (out / f"{card}.truth.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{variant}: 4 cards written to {out}")
    manifest = {
        "schema_version": 1,
        "variants": {v: VARIANTS[v] for v in VARIANTS
                     if all((args.output / v / f"{card}.truth.json").exists() for card in OFFSETS)},
        "cards": {card: {"entries": len(raw), "faults": len(truth["faults_utc"]),
                          "alternatives": len(truth["alternatives_utc"]), "flats": len(truth["flats_utc"])}
                  for card, (raw, _, truth) in extracted.items()},
        "controls_validated_in_this_run": [v for v in args.variants if v in ("original", "names_tone", "canonical")],
        "limitations": [
            "Synthetic format stress tests, not sampled hidden cards and not a prediction of hidden-card scores.",
            "Fault truth is c31 due(); alternatives are unresolved schedule candidates, not simulator-confirmed faults.",
            "Relative-to-another-day notices that c31 labels alt retain that oracle classification, even if their natural wording sounds official.",
            "Large variants reconstruct schedule-state changes, removing duplicate restatements; background weather/terrain/chatter is retained.",
            "Unresolved original conditional/relative clauses are retained in several variants; status variants rewrite their wording.",
            "Confirmed-start precision counts unmatched alternatives as errors; candidate_fp excludes labelled alternatives and alternatives_as_due reports the distinction.",
        ],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "v6")
    parser.add_argument("--oracle", type=Path, default=HERE.parent / "pkgs/c31/guider_log.py")
    parser.add_argument("--output", type=Path, default=HERE / "variants")
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
