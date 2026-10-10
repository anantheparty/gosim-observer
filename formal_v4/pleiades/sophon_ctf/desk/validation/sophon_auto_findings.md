# Sophon 自动化榜：认证证据与剩余实验

更新至 2026-10-07 08:40 UTC。本文不含任何凭证值、请求头、完整请求 URL 或服务端原始动态
正文。

## 已验证事实

| 运行 | 调用时机 | 凭证存在性 | 请求 | 结果 |
|---|---|---|---|---|
| `b9ea806e…` | initialize 处理期间 | O 有，S 无 | old status query O；desk Bearer O | 均 `404 closed` |
| `bad776d9…` | 首个 decision_request，engine.begin 之后 | O 有，S 无 | desk Bearer O、status query O、无认证 desk/status、desk query O、desk Bearer O + site | 六项均 `404 closed` |
| `60eb961f…` | 首个 decision_request，engine.begin 之后 | O 有，S 无 | `/desk/flag`：body、query、Bearer、body+Bearer、body+site、Bearer+site | 六项均 `404 closed`；无 solve |
| `9d5bdb27…` | 首个 decision_request，engine.begin 之后 | O 有，S 无 | 正确 112 字符句子到旧 `/answer`：body O、Bearer O、body+Bearer O | 三项均 HTTP 401；无 flag/key/code/solve |

这里 O 表示当前运行自己的 `OBSERVER_RUN_TOKEN`，S 表示 `SOPHON_RUN_TOKEN`。所有运行都只记
变量是否存在；没有读取、打印、哈希或落盘凭证值。两个新运行均正常 `survey_complete`，agent
无异常，因此 `closed` 不是客户端崩溃或提前 finish 的副作用。

延迟运行排除了旧探针的 initialize/begin 竞态；无认证对照与各种 O 载体逐字得到相同 29-byte
拒绝对象，支持 Sophon 私有函数在认证格式之前或认证失败时统一门控。它不能证明私有 handler
不存在，也不能把 `closed` 精确归因到哪一条私有分支。

## 公开代码边界

- `private.sophon_g_solves` 以 `(board, team_id, no)` 唯一，board 只有 `debug/auto`；auto 计分在
  总分中乘 2，auto 行可带 `run_id`。这强烈支持“运行身份提交”解释，但表结构没有发布写入合同。
- 网页 debug 提交使用登录用户会话与 `x-sophon-site: 1`；私有 `sophon` Edge handler 没有进入
  公开仓库。扩展扫描 377 个可达提交、3129 个源码 blob，仍未找到 auto 认证或 S token 签发实现。
- public test 使用独立 PT 卡和 preview run，不是 Sophon 真卡的短版；公开 builder 不启用 Sophon
  调度。因此旧记忆中“准备阶段 public test 有 S token”不能从公开构建路径得到支持。
- 07:38 UTC 另行只读检查了 GitHub 最新公开 HEAD `0c001ed`；相对本地 `373d94f` 只有 4 个
  文档/前端失败提示提交，diff 中没有 Sophon handler、token 注入或 auto 合同变化。
- agent finish 后最多有 30 秒收尾，随后容器关闭、结果上传，最后数据库才 scored。auto 请求应在
  决策期执行，不能等本次 run 的 receipt；当前两轮新实验均在第一个决策执行，处于有效窗口。

## 当前结论

新版 auto 不能通过当前 O capability 的原样 body/query/Bearer 形式进入；S capability 又没有注入。
所以 10 月 5 日早期运行可联系 Johnny、后续运行全部关闭的差异，最符合平台侧 S token 注入或
私有服务门控在阶段重开后改变。继续加工 O token、猜额外头或枚举未知端点没有公开合同支持。

旧 `/answer` 的 401 与新版 desk 的 404 `closed` 不同，证明观察到了不同的拒绝响应。由于原始
401 正文没有保存、日志把未知错误归为 `other`，这不足以确定处理器进入了哪一个分支，亦不能
把专用 S capability 缺失认定为唯一阻断点。O 的三种已测运输方式未成功；S 没有注入，故缺少
按原合同提交的阳性对照。

复核补充（2026-10-07）：本地 `desk_calls.jsonl` L264 中，登录用户身份请求 `/desk/status`
也得到同样的 `404 {"ok":false,"error":"closed"}`；相邻根 desk 请求仍可读取 debug 状态。
这进一步说明 `closed` 不是“整个 Sophon 服务关闭”的充分证据。该子路径本身没有公开合同，
不能据此断定运行身份有效，也不能倒推出一个新认证办法。当前准确结论是“已测 auto 入口未
成功，准确写入合同仍未知”。不再启动运行包或重交已知旗标。

已知 21 个 debug 真码的批量包保持 `enabled=false`。即使用户允许批量重交，也必须先由一个真实
响应和公开榜单证明某个认证模式写入 `board=auto`；HTTP 200 或旧 solver 记录本身不够。

## 已完成的旧契约实验

公开根入口仍逐字发布 `POST /answer {sentence, token}`，旧表
`private.sophon_solves(team_id, run_id, key)` 也仍存在。包 `o4s_sophon4_oldanswer` 只提交已经解出的
Johnny/Sakurai 112 字符句子，使用当次 S（若存在）或 O 的有界原样 body/Bearer 形式。三种 O
形式均 401，无签发内容；旧单题系统仍有鉴权入口，但 No.4 桥接假设没有得到成功证据。这个
实验也不能替代新版 auto board 的明确归榜证据。

No.4 的独立 auto 时序候选见 `no4_auto_fresh_plan.md`。它同样保持禁用，只有在 auto 认证被真实
证明后才可运行。
