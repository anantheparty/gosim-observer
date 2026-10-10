# Sophon receipt：结果 ZIP 之外的只读查询清单

真实 ground-station 后端未公开。下表是候选位置与排查顺序，不代表 receipt 已确认存在于这些入口。
先记录本轮 BATCH、RUN、开始/完成 UTC，用于关联邮件、日志和榜单时间；所有查询针对本队当前 Sophon 运行。

| 优先级 / 位置 | 主会话可做的只读查询 | 查什么 / 证据边界 |
|---|---|---|
| 1. Johnny 的 HTTP 回复 | 在该运行的「查看日志」下载完整 agent.log，或 `survey26 --json results log RUN --full`。 | 找 `sophon_init.credential_present`、`johnny_response.status/body`、`johnny_error`、`johnny_skip`。新包初始化和收尾前各有一次调用，注意对比 `when`。200 的普通确认不等于 flag，也不证明 sky/dive 已通过。只读已有响应，不在评测外重放 contact-johnny。 |
| 2. 评测详情的「平台诊断」 | 展开当前 RUN 的日志区，读「运行/引擎/评分」诊断；上面的 `results log --full` 默认也返回 `diagnostics`。 | 重点看评分完成后的 `kind/status/code/log/finished_at`。这是与 agent.log 独立的数据源，即使 ZIP 没 receipt 也值得查。源码确认入口存在，未确认 Sophon 会把 receipt 写入。 |
| 3. 评测详情原始响应 / 单独 run.json | `survey26 --json results show BATCH --phase extra` 先确认结束状态、运行 ID；再检查已下载的完整 run.json。若 UI 只显示分数，查看正常打开详情页时浏览器 Network 已有响应中的该 RUN 对象。 | 搜索 `receipt`、`sophon`、`flag`、`ground_station` 及 score_summary/score_check（若有）和未知新增字段。CLI show 会整理字段，不能用其输出缺字段来证明后台没有 receipt。只保留所需响应正文，不分享含鉴权头的 HAR。 |
| 4. 之前收到 Johnny 邮件的邮箱/线程 | 在同一收件邮箱搜索本次评测时间之后的 `Johnny`、`Sophon`、`SOPHON{`、`receipt`、`ground station`，检查同线程折叠回复、垃圾邮件与附件。必要时核对队长/实际提交者的既有收件渠道。 | 主会话此前确实收过 Johnny 邮件，因此优先级高；公开仓库没有本轮收件人/邮件正文合同。仅查看，不发信、不触发重发。 |
| 5. Sophon 页面「通关记录」及三榜 | 正常刷新 Sophon 页面，切换 debug、auto、total，查看本队新增单元格、时间和顶部通关记录；可读取页面原有 `sophon_board`、`sophon_totals`、`sophon_finishers` RPC 响应。 | 这些 RPC 已确认只读。`sophon_finishers` 有 text_en/text_zh；可能承载后续文字。榜单的 F1/F2 是显示标签，不是原始 flag。若尚未手动提交就出现 auto 记录，可作为自动结算迹象。 |
| 6. 好友私信列表（低优先级） | 如平台出现新私信提示，只读 `social_counts()` 和 `dm_overview()`，查看发件人、last_at、last_body 摘要。 | 仓库有私信功能，但没有 Sophon 使用它的证据。`dm_thread()` 会更新 read_at，不属于严格只读；本清单不建议调用它。普通 `/notifications` 是组队邀请/申请页，不是通用系统邮箱。 |
| 7. 完成后的延迟结果 | 本轮评分完成时查一次上述入口；若没有回执，可在稍后正常刷新详情、Sophon 页及原邮件线程，并按新鲜下载链接再取一次结果。 | 这是为了排除地面站异步处理/旧下载快照的可能性；没有已知刷新周期或送达时限。不需要新建评测来刷新。 |

公开源码依据：

- `hackathon-survey26/cli/AGENTS.md` §8：Johnny 仅运行内有效。
- `web/src/components/competition/RunLogs.vue`、`web/src/lib/runLogs.ts`：完整 agent.log 与平台 diagnostics 是两个入口。
- `supabase/functions/_shared/observer-portal.ts` 的 agent_log/download_result：日志既可能在存储旁文件，也可能在 ZIP 内。
- `web/src/components/leaderboard/SophonBoards.vue`、`supabase/migrations/20261006000000_sophon_boards.sql`：三个只读榜单 RPC 与通关文字。
- `supabase/migrations/20261005050000_direct_messages.sql`：overview/counts 只读；thread 写已读状态。

建议主会话交回：本轮 RUN/BATCH、完整 agent_log.json（含 diagnostics）、当前 run.json、结果 ZIP；
如收到邮件或新增通关文字，再附正文与 UTC 时间。无需提供 token、凭证、完整邮箱导出或浏览器鉴权头。

离线扫描：

```bash
python3 -B work/sophon_desk/scan_receipts.py work/online/sophon3_XXXX --out work/sophon_desk/validation/sophon3_XXXX_receipts.json
```

## 已备好的三个打包目录

| 行星 | 目录 | 相对木星模板 |
|---|---|---|
| Saturn | `work/packages/o4s_sophon3_saturn/` | 仅 probe_config.json 的 dive_object=saturn |
| Mars | `work/packages/o4s_sophon3_mars/` | 仅 probe_config.json 的 dive_object=mars |
| Venus | `work/packages/o4s_sophon3_venus/` | 仅 probe_config.json 的 dive_object=venus |

每个目录都直接复制 `work/packages/o4s_sophon3/`：9 个文件、包含 requirements.txt、不含 README.md；
8 个文件逐字节相同，配置仅一个键不同。模板未改，未打 ZIP，未重跑仿真。
逐文件 SHA-256 和比较结果：`work/sophon_desk/validation/sophon3_planet_packages.json`。
