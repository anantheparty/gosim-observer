# GOSIM survey26 platform: API access notes (read-only)

Checked 2026-10-05 01:20–01:40 BJT (2026-10-04 17:20–17:40 UTC), about 1.5 h after the online phase opened.
Every request was a read. No upload, preparation, confirmation, evaluation, withdrawal, final-version choice,
key claim or settings change was made, and no daily quota was used.

## 1. How the site talks to its backend

- The site at `https://create.gosim.org/survey26/platform/` is a static Vue app (source:
  `gosimfoundation/hackathon-survey26`, `web/`; shallow clone in `/home/shu/kamico/observer/hackathon-survey26`,
  HEAD `d293dea`, 2026-10-05 02:18 +0900). Everything stateful is one Supabase project:
  - URL: `https://vdiemcofukuxglqsmlyz.supabase.co`
  - anon (publishable) key: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZkaWVtY29mdWt1eGdscXNtbHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg5NTU3OTcsImV4cCI6MjEwNDUzMTc5N30.qMbZ_C3iKq70SdGDYQPPUD0LMBst-xBspZ-zj_gn75w`
    It is embedded in the live bundle `assets/supabase-C2tePZWH.js` and matches `SKILL.md`, `sac_submit.py` and `fetch_scenario.py`.
- Network from this host: `create.gosim.org` works both directly and through the proxy. `*.supabase.co` works
  **only through the proxy** `http://127.0.0.1:7890`; the direct connection is reset.
- Backend surfaces:
  - GoTrue: `/auth/v1/token`.
  - PostgREST: `/rest/v1/<table>` and `/rest/v1/rpc/<fn>`.
  - Storage: `/storage/v1/object/...`.
  - Edge function `/functions/v1/observer-portal`. This is the competition workspace. Each POST body is
    `{"action": ..., ...}` and the response is `{"data": ...}` or `{"error": "<code>"}`.
- The official CLI `survey26` (`cli/survey26.py`, gateway `supabase/functions/_shared/cli-gateway.ts`) needs a
  personal `s26_` token, which can only be created on the profile page. That is a settings change, so it was
  not done. The gateway sends the same RPC and portal requests listed below, so a password-grant JWT is enough.

## 2. Authentication

```
POST {URL}/auth/v1/token?grant_type=password
  headers: apikey: <anon>, Content-Type: application/json
  body:    {"email": "...", "password": "..."}
-> {access_token (JWT, 3600 s), refresh_token, expires_at, user}
```

Every later request sends `apikey: <anon>` and `Authorization: Bearer <access_token>`.
To refresh, call `POST /auth/v1/token?grant_type=refresh_token` with `{"refresh_token": ...}`.
The tools read `GOSIM_EMAIL` and `GOSIM_PASSWORD` from the environment and never write them anywhere.

Identity used:
- user `7afaf76f-63f4-4173-8f78-439d9ed3bbe6`
- team **Pleiades** `b9b69b29-6f59-4ced-9024-2036a36db3ee`

## 3. Read-only endpoints used

| Purpose | Request |
|---|---|
| Account/team | `POST /rest/v1/rpc/me {}` |
| Site mode | `POST /rest/v1/rpc/current_competition {}` → `{mode:"competition", phase_id:<online>, practice_phase_id:<practice-projects>}` |
| Phases | `GET /rest/v1/phases?select=id,slug,starts_at,ends_at,is_active,leaderboard_mode,counts_for_final,observer_settings:observer_phase_settings(projects_enabled,daily_batches,sealed,repeat_runs)&order=sort_order` |
| Workspace (versions, evaluations, quota, final) | `POST /functions/v1/observer-portal {"action":"list"}` → `phases, projects[].observer_revisions[], batches[].observer_runs[]` (purpose `formal`, latest 50), `quota, final_versions` (plus team env/model fields; the tools do not store these) |
| Quota only | `rpc/observer_evaluation_quota {}`; organizer reset notice: `rpc/observer_quota_reset_notice {}` |
| Final version | `rpc/observer_final_versions {}` |
| Boards | `rpc/observer_card_board {"p_phase":<uuid>,"p_scenario_slug":null\|"v4-a",...,"p_limit":1000}` (overall rows carry `card_scores`; card tabs carry components) |
| Scenario names/meta | `GET /rest/v1/scenarios?select=id,slug,name,n_nights,n_slots,global_wallclock_seconds,weather_public,start_date&...` (`select=*` is denied; per-column grants) |
| Card files | `POST /storage/v1/object/list/scenarios {"prefix":"v4-a/public","limit":1000,"offset":0,"sortBy":{"column":"name","order":"asc"}}`, then `GET /storage/v1/object/scenarios/v4-a/public/targets.csv` |
| Result ZIP of one card | portal `{"action":"download_result","run_id":...}` → `{url}` (signed, 120 s) → GET |
| Logs | portal `{"action":"agent_log","run_id":...,"full":true}`, `{"action":"diagnostics","revision_id"\|"run_id":...}` |
| Announcements | `GET /rest/v1/announcements?select=*&is_published=eq.true&order=created_at.desc` |

Phase IDs:
- `online`: `049d6029-343d-4d16-80d5-94b56b350301`, 2026-10-04T16:00:00Z → 2026-10-07T15:59:59Z
- `practice-projects`: `249c223b-2ec8-4f0a-924e-7af3c4e3eb44`

Card scenario IDs:

| Card | Scenario ID |
|---|---|
| v4-a | `30d456db-7677-4bb6-8c83-3db513614c93` |
| v4-b | `297bf82f-54f3-49d6-bc27-04dcc65a8c79` |
| v4-c | `6fb9c640-de50-409c-8eef-b1ac40542d27` |
| v4-d | `5dd4610e-cfa3-42f3-a0a0-e7be0f65e489` |

## 4. Tools (`formal_v4/platform_tools/`, standard library only)

| Script | What it does |
|---|---|
| `gosim_platform.py` | Client: login, proxy, an allowlist of read-only RPCs/portal actions/tables. Write actions raise `PermissionError` before any request is sent. Optional `GOSIM_SESSION_FILE` (0600) caches the session. |
| `fetch_formal_cards.py` | Downloads released files of `v4-a..d` into `formal_cards/<A..D>/<a..d>/{config,public}/` plus a deterministic `taskcard-<id>.zip`. Writes `formal_cards/download_manifest.json` (per-file SHA-256, server sizes/eTags, card statistics). |
| `platform_status.py [--card-details]` | Writes `platform_snapshots/status_<UTC>.json`: phases, quota, final version, versions, evaluation history, online/practice boards (and card tabs). |
| `download_results.py --latest N \| --batch ID…` | Our per-card result ZIPs → `platform_results/<eval-id>/{<card>.zip,<card>/…,evaluation.json,manifest.json}` |

Usage: `export GOSIM_EMAIL=... GOSIM_PASSWORD=...` (proxy defaults to `http://127.0.0.1:7890`; `GOSIM_PROXY=none` disables it), then
`python3 formal_v4/platform_tools/platform_status.py`.

## 5. Findings

### (a) Formal cards A–D (released 2026-10-04 16:00 UTC; files uploaded 2026-10-02 05:36–05:53 UTC)

Each card releases 7 files: `config/v4_fiber_config.json`, `config/v4_score_config.json`, `public/footprint.csv`,
`public/targets.csv`, `public/v4_night_calendar.csv`, `public/taskcard.{en,zh}.md`.
- `truth/` is empty and `v4_scenario.json` is not released.
- Weather, forecasts and events are hidden (`weather_public=false`).
- Wall clock 900 s, contract `v4-score-v1`.

| Card | Site | Season (nights / slots) | Targets | Σ science_weight | Required (Σw) | Fibres (cell deg²) | f0·T0 | Footprint | Stress |
|---|---|---|---|---|---|---|---|---|---|
| A "First light" | VISTA/Paranal −24.62 | 2026-10-01→2027-01-31 (123 / 3777) | 30,000 | 27,300 | 1,500 (1356.9) | 16, 4×4 (0.4) | 450 | 3 regions, 6000 deg², 23 RA bands | none stated |
| B "Crowded field" | Cape Town −33.92 | 2027-06-01→11-30 (183 / 6745) | 50,000 | 45,500 | 2,500 (2237.9) | 25, 5×5 (0.064) | **800** (0.8×1000) | 2 regions, 8000 deg², 22 bands | none stated |
| C "Northern sky" | Mauna Kea +19.82 | 2026-12-01→2027-03-31 (121 / 4743) | 30,000 | 27,300 | 1,500 (1373.4) | 9, 3×3 (0.7) | 450 | 4 regions, 4000 deg², 16 bands | none stated |
| D "The long year" | Nemo −45.00 (fictional) | 2027-01-01→12-31 (365 / 11536) | 30,000 | 27,300 | 1,500 (1365.4) | 100, 10×10 (0.06) | 450 | 3 regions, 6000 deg², 24 bands | **data loss** (`state_resync`, once) |

- All cards have class mix BGS 24% / ELG 34% / LRG 20% / QSO 14% / Star 8%.
- Scoring is the same as in practice except B's zero points:
  - program multipliers 1.20/1.12/1.06
  - required penalty 50 at factor ≥ 0.5
  - uniformity weight 200
  - report reward +100, false-report penalty −150 after 2 free reports, at most 32 consecutive reports
- The rules call δ/D/H "extreme: less observable time and more disruptions".
- In the v4 engine (`challenge/v4_weather_simulator.py`), stress mode always also draws a hidden, never-announced fixed
  pointing offset (|alt|, |az| < configured max < 0.1 rad). D therefore very likely also has a pointing offset. This
  is inferred from the engine source; the card does not state it.

Archive SHA-256 values. The site zips in the browser (fflate), so its archive hash is not stable. These are
deterministic re-packs; the per-file hashes are in `formal_cards/download_manifest.json`.

| Archive | SHA-256 |
|---|---|
| A `taskcard-a.zip` | `5d299ffdb6dccac7e4bef07b2baaa2f488081f15dbfbaa6d3a5674d8c86116f6` |
| B `taskcard-b.zip` | `a5c32cb86449e880c7527b2fa706d4e232ab9d1f9028b5b640958624789a032a` |
| C `taskcard-c.zip` | `592abb512527c431d56acbae3af2edd675a7a88eccbf1f8660758731b8a14ed6` |
| D `taskcard-d.zip` | `df2aa463765ce3ad54f62745c8fb1a14775e37e042e56dfd06d345b337589bf5` |

targets.csv SHA-256:

| Card | SHA-256 |
|---|---|
| A | `05dc5357fad3b12e3ede1d7aeb7eb59ec5f9b666980ba0cbc409f74c3697f736` |
| B | `ab8089a285fcf4890dc1cf82ea50ae6fa5b8e60da6c68a44473967910298dccb` |
| C | `d33d443675f3f6621d41902822c6fc8ceb450a1453593a7781e68db8d6cfa416` |
| D | `656e63f7ea6f5dafb382eb96287bd511f792a690d43bcbfab39ef93907cce89c` |

### (b) Our evaluation history (all practice-projects; **no online evaluation yet**)

| Eval | Created (BJT) | Version | Mean | α | β | γ | δ |
|---|---|---|---:|---:|---:|---:|---:|
| `caf453f6` | 10-04 17:51 | Observer Sparse Exact | **6928.064035** | 7576.505584 | 6608.586653 | 7225.119085 | 6302.044818 |
| `4bf103c3` | 10-03 19:10 | Observer Request Cache | 6735.0925025 | 7248.868252 | 6517.864140 | 6750.550861 | 6423.086757 |
| `d2ef6bae` | 10-03 18:41 | Observer Verified Portfolio | 6714.98391975 | 7279.188726 | 6571.727518 | 6585.932678 | 6423.086757 |
| `2459f58c` | 10-03 07:38 | Observer Request GPU | 6280.45111625 | 5891.789130 | 6138.150947 | 6668.777631 | 6423.086757 |
| `be003ca0` | 10-03 06:58 | Observer Phase GPU | 6532.68247925 | 7289.494481 | 6602.149692 | 7033.080199 | 5206.005545 |
| `8b1bf93d` | 10-03 05:06 | Observer Search CD2 | 6198.39046425 | 7094.664204 | 6333.107019 | 6547.568316 | 4818.222318 |

All six are `scored`.

The "Observer Sparse Exact" evaluation (`caf453f6-df1d-4e37-a6d7-65cc8712bced`):
- Version `1286e001-00e0-4783-bbcc-50dc4626affd`, status `approved`. Source fingerprint `965657690a2a…`;
  the uploaded ZIP's SHA-256 is `5b00e6a3…`.
- Created 09:51:37Z (18:51 JST) and finished 10:02:30Z.
- All four cards ended `survey_complete` and made no egress calls.

| Card | Required missing | Requests completed | Invalidated observations | CPU charged / 900 s | Speed factor |
|---|---:|---|---:|---:|---:|
| α | 4 | 2/2 | 0 | 490.0 | 1.05 |
| β | 11 | 2/2 | 0 | 557.9 | 1.04 |
| γ | 2 | 2/2 | 308 | 493.9 | 1.09 |
| δ | 7 | 1/2 | 266 | 379.7 | 1.04 |

The four result ZIPs (8 members each, including `egress.json`) are in
`platform_results/caf453f6-df1d-4e37-a6d7-65cc8712bced/`:

| Card | ZIP SHA-256 |
|---|---|
| α | `d5f687a388107d80b207b8a126e58e90bbdf32a6a563cc8ec2542d8e6d74a7e5` |
| β | `fc6e310f8f6de7aa209b06f3f0dd62321da3258611f91ef738b1d05037025e2b` |
| γ | `457dd6a98410a552a3c8b46f16d9c72a4bd8697d303402916e1e0daccb844eff` |
| δ | `890aef1e42966029c629969e0a91aa02ec5c816afcf0e558dff7bae10492f1df` |

Each `score_report.json` total equals the platform score.

Other versions:

| Version | Status |
|---|---|
| Observer Compatible GPU `b1ce7f29` | reviewable, never confirmed |
| Observer Geometry Phase `f675939b` | reviewable, never confirmed |
| Observer CD2 IP check `d1158cf7` | reviewable, never confirmed |
| Observer API GPU `cf4dbae3` | failed preparation |
| Observer Search `7f750af9` | failed preparation |

### (c) Leaderboards (snapshot 2026-10-04 17:33:45Z, `platform_snapshots/status_20261004T173345Z.json`)

**Online (A–D)**:
- 25 teams; Pleiades is not ranked yet.
- Score is the mean of the 4 cards from one evaluation.
- Board median 25606.9; 10th place 26037.2.

| # | Team | Mean | A | B | C | D |
|---|---|---:|---:|---:|---:|---:|
| 1 | AstroNJU | 30431.89 | 24435.32 | 39887.22 | 24918.55 | 32486.49 |
| 2 | 测试队伍 | 29939.53 | 23711.41 | 37952.01 | 25767.14 | 32327.56 |
| 3 | 只会一点 | 29288.79 | 23144.04 | 37159.74 | 25232.19 | 31619.19 |
| 4 | CCB | 29133.85 | 23303.57 | 36220.77 | 24557.02 | 32454.04 |
| 5 | 两个半鸿蒙 | 28846.12 | 22056.02 | 38650.79 | 24579.13 | 30098.52 |

Card maxima:

| Card | Max | Team | Median |
|---|---:|---|---:|
| A | 24435 | AstroNJU | 18471 |
| B | 39887 | AstroNJU | 34859 |
| C | 25767 | 测试队伍 | 18221 |
| D | 32905 | Argelander | 31454 |

On D, the top teams observe all 30,000 targets, with 2–3 required missing and +200…300 reports.

On B, 7 of 25 runs ended `global_wallclock_expired` and 1 ended `agent_error`.
- The leader's B run (AstroNJU, 39887) also expired, but with 0 required missing.
- 6 teams were left with 110–751 required missing, a penalty of −5,500 to −37,550.
- That made B negative for 4 teams, including the strong practice teams Argelander −18815, DeepSky −13342 and muin −928.

Termination counts on the other cards:
- A: 1 expired, 1 `agent_error`.
- C: 4 expired, 1 `agent_error`.
- D: 1 expired.

Leaders' request rewards reach 400–600 per card.

**Practice board (α–δ)**:
- 66 teams; **Pleiades #6, 6928.064** (card ranks α5/β7/γ4/δ8).
- Leaders: 豆包 7664.32, CCB 7580.71, AstroNJU 7572.10, Argelander 7206.53, muin 7022.15.

### (d) Quota (live values from `observer_evaluation_quota`)

- **Online: 40 evaluations per UTC day. Used 0, remaining 40.**
- Practice-projects has its own separate 40/day (used 0).
- Version preparations: 40/day, shared, 0 used.
- At most **4 evaluations in flight** per team; a 3× self-check set counts as one and uses 3.
- Next reset **2026-10-05 00:00 UTC = 08:00 BJT (09:00 JST)**, then daily. The phase ends 2026-10-07 15:59:59 UTC.
- The count starts at the later of UTC midnight and the latest organizer reset. The latest reset was
  2026-10-04 10:12:44 UTC on online and practice-projects, which is why the 09:51Z practice run no longer counts.
- Platform failures are refunded (`quota_refunded`). Failures caused by the program (build failure, crash,
  protocol error) count.
- The older "4/day formal" text is superseded; the pinned announcement of 2026-10-04 17:18Z says 40/40/4.

Current rules (rules page and announcement), relevant to strategy:
- **Timing is normalized CPU time.** The budget is 900 s of the agent's own CPU per card. Time waiting on the
  network or a model is free. The real-time cap is 30 min. Each request carries `wallclock.remaining_seconds`
  and `speed_factor`.
- During evaluation the program can reach any public host on ports 443/80. Egress is logged; optional platform
  routes `cn`/`overseas` are available.
- The four cards run concurrently and typically take 10–20 min.
- The hidden final runs each of E–H 3 times concurrently and averages them.
- The final version can be chosen until the deadline. None is chosen now, so the default is the version of the
  best online evaluation.

### (e) Submission flow via API (documented from source and the official CLI; **none of these were executed**)

All calls carry `apikey: <anon>` and `Authorization: Bearer <JWT>`. Portal means `POST /functions/v1/observer-portal`.

1. **Reserve upload**: portal `{"action":"upload","purpose":"source"}` → `{id, path:"<team>/<id>/source.zip", token}`.
2. **Put ZIP** (≤ 50 MB): `PUT /storage/v1/object/upload/sign/observer-staging/<path>?token=<token>`.
   - Headers: `x-upsert: false`, `Content-Type: multipart/form-data`.
   - Form fields: `cacheControl=3600`, plus a file part (name `""`, filename `x.zip`, `Content-Type: application/zip`).
3. **Create version**: portal `{"action":"submit_zip","title":"<≤100>","upload_id":"<id>"}` → `{revision_id[, warning:"no_manifest"]}`.
   - Uses 1 of the 40 daily preparations.
   - Errors: `upload_not_finished` (retry), `zip_has_no_code`, `preparation_daily_limit`, `preparation_limit` (3 already queued or preparing).
   - Repository variant: `{"action":"submit_repository","title","url","branch"?,"subdir"?}`.
4. **Wait for preparation and public test.** Poll portal `list` (≥ 15 s interval).
   - The revision status goes `queued → preparing → reviewable` (requires `public_test.passed=true`, `manifest`, `adapter_files`, `approval_digest`), or ends `failed` with `error`.
   - Logs: `diagnostics {revision_id}` and `agent_log {run_id: public_test.run_id}`.
   - The "interface check" runs automatically and uses no quota.
5. **Confirm the version**: portal `{"action":"approve","revision_id","digest":<approval_digest>}`, which calls RPC `observer_approve_revision`.
   - Uses no quota.
   - Errors: `stale_approval`, `revision_not_ready`, `revision_withdrawn`.
6. **Start an evaluation**: portal `{"action":"evaluate","phase_id":"049d6029-343d-4d16-80d5-94b56b350301","revision_id", "confirm_repeat":true?, "no_model":true?}` → `{batch_id}`. This calls RPC `observer_create_batch` and uses 1 of today's 40.
   - `confirm_repeat` is required if the version already has a non-refunded evaluation in this phase.
   - Errors: `daily_limit`, `batch_already_active` (4 in flight), `revision_not_approved`, `revision_already_evaluated`, `phase_closed`.
   - Self-check: `POST /rest/v1/rpc/observer_create_repeat_batches {"p_phase","p_revision","p_confirm_repeat":true}` uses 3.
7. **Track**: poll portal `list`.
   - Batch status: `queued/running/scored/failed/cancelled`.
   - Each card's run has `status`, `score`, `result_path`, `score_summary`.
   - Then `download_result` / `agent_log` per run.
8. **Final version**: portal `{"action":"set_final_version","phase_id":<online>,"revision_id":<id or null>}`, until 2026-10-07T15:59:59Z.
   Other actions: `withdraw {revision_id}`, `evidence {revision_id, notes, code_url}`.

**Shortcut** (not executed): "Observer Sparse Exact" `1286e001-00e0-4783-bbcc-50dc4626affd` is already `approved`
and has no online evaluation. A first online evaluation of it is therefore step 6 alone, without `confirm_repeat`.
Versions are not tied to a phase.

Risk noted from the data:
- The practice runs charged 380–558 CPU seconds of 900 on 38-night, 10k-target cards.
- A–D have 121–365 nights and 30k–50k targets.
- On B, CPU exhaustion (`global_wallclock_expired`) has already turned several strong teams' scores negative
  through required penalties.
