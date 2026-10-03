# 2026-10-04 独立搜索状态化简初稿

本稿先独立读官方 `runner/challenge/v4_runner.py`、`v4_scorer.py`、`v4_fiber_map.py`，尚未读 portfolio。它不是全季最优证明，也没有提交或远端作业。

## 精确系统

固定隐藏世界下状态必须保留时间 t、observe_action_index n（空命中 observe 也加一）、有效账本、fault repair 时间及误报额度、连续 report 数、发布/结算游标、loss 是否已触发及 pending wait。无动作序列的访问次数奖励；访问次数通过 loss 窗口和运行时间间接作用。score best、最高 factor、每个已发布请求的窗口内 factor 是三条不同的统计。

终值为 sum_i max_valid c_i - P_req missing_required - U(1-Jain) + request reward + report settlement；请求每个目标是是否有一条完整位于请求窗内的 exposure 达阈值，不累加访问。required/Jain 和请求的阈值必须分开，尽管 L1 默认都是 .5。Jain 不单调，额外完成一个过量 band 的目标可能扣分。

隐藏世界需包含天气/事件、固定 pointing offset、未来请求与 loss 计划。正式在线状态是反馈历史诱导的 belief，不能拿某个估计世界的状态等价当真实 belief 等价。last_result 的 hit/miss 和 score 均提供信息；已满分目标也可能有探测价值。

## 首选精确缩减：一次连续 loss 窗的双向 envelope

官方 `_data_loss_plan` 取 data_loss 的首行；`loss_triggered` 永久置真。因此此版本运行中至多一个连续 action-index 删除窗 W=[floor(aN), floor(bN))。N 包含跨越 trigger 的那次已完成曝光，且与累计 observe 数绑定。

对每个目标的 science 序列 (index,score)，只保留从左严格创纪录的项和从右严格创纪录的项的并集。每个 Boolean 完成谓词（required 阈值、Jain 阈值、每个已发布请求的完整窗合格条件）只保留最早和最晚满足它的 action index。另保留 n、loss 状态及 belief/反馈。

证明：若 score 项 j 既非左纪录也非右纪录，则存在 k<j<l 且 score_k,score_l>=score_j。任何一个连续 W 若不含 j，就不可能同时含 k 与 l，所以删除 j 不会改变 W 后 max。Boolean 内部 witness 同理被端点夹住；两端都被删除意味着所有 witness 都被删除。每目标 zero-score 初末项也须保留以维持 best() 的 observed-id 集。

查询 science 为 max(prefix_best[l],suffix_best[r])；完成谓词成功等价 first<l 或 last>=r。空 loss 窗也涵盖原账本。science envelope 的 suffix 栈可在 append 时弹出 <= 新分的尾项；prefix 纪录只在新分严格大于旧最大时加入。

已 invalidated 的项先删除，只在当前 valid 账本上重新构造；若未来仍可能多个彼此不相邻的 loss 窗，以上 theorem 不成立（三项 [5,4,5] 删除两个端点时中项重要）。loss 已触发后，science 只剩 max；阈值只剩 Boolean。已有请求截止后仍须保留至 loss 已触发，因为 request result 可被回溯撤回。

动作层面，仅能按同一时长、同一 observe_index 增量、所有隐藏世界下相同反馈似然与逐目标转移合并；更高即时 sum_best、更多 required、或更多完成数都不足以支配目标集合不同的动作。

下一步：先与 portfolio/旧剪枝记录去重，若该 theorem 已存在则明确承认重复；再做官方 BestLedger 的可复现合成及记录 ledger 审计，量化存储缩减，不把这当全季提分。
