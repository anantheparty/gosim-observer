# 闭环进化策略：独立建模稿（先于旧研究阅读）

状态：2026-10-04，先独立阅读官方源码和 participant guide，尚未阅读仓库旧 GA/oracle/portfolio 研究。本文提出待验证模型，不代表已经获得分数提升。

## 1. 真实优化对象和信息边界

策略是 `a_t = π_g(initialize, H_t)`，其中 `H_t` 只含截至 `now_utc` 实际送达的公告、预报、活动请求、先前动作和结果、状态更正以及 wallclock。进化种群保存策略基因 `g`，不保存整季动作带。相同 `g` 在不同天气、指向偏差、数据丢失和请求发布下必须重新决策。

官方终值为 `Σ_i max_e valid_score(i,e) - required_cost - U(1-Jain) + report_settlement + request_reward`。其中 required 和均匀度用每个目标最大 valid factor，不是 best-score 对应 factor；请求只接受完整落在发布至截止区间内的曝光。这三个账本不可合并。

公开 `last_result.hits` 只有 target_id 和 score。策略不能读取 scorer 的 factor、quality、天气真值、actual event times 或将其缓存成测试卡动作序列。若选择程序的可得乘数为 `m>1`，观察得分 `s` 仅证明 `factor ∈ [s/(w m), s/w]`（截断到 [0,1]），不能直接把 `s/w` 当作完成因子。活动请求公开 completed_target_ids 是合法更精确信息，可用于该请求自身的进度。未来请求不可提前加入计划。

## 2. 结构缩减：进化“终值承诺语法”，动作由统一解码器构造

完整动作空间有连续指向、60..3600 秒时长、16 根光纤及目标组合，直接编码动作序列会把搜索花在几何合法性上。统一、公开信息解码器先产生有限的非支配动作包：

* REQUIRED：一个或多个尚未稳健过门槛目标的 0.5 完成包；
* REQUEST：当前已发布请求中能组成 minimum_completed 的若干目标包；
* VALUE：未饱和目标的最佳分增量包；
* RECOVER：状态更正后消失的承诺；
* INFORMATION：沿用已有合法探测/故障机制的包，不让进化直接搜索危险 report 字符串。

每包保留最早/最晚公开几何可见时窗、同指向可共同命中的目标、公共阈值处的曝光断点、预报/公告下成功概率区间、时间成本。曝光只在目标达到 0.5 或 1、slot/夜末、公告刷新等断点加安全裕量。被另一包在时间、稳健 required 完成数、预期最佳分增量和请求可完成性上同时支配的包剔除。若这些删减损失可达最好分，作为可证伪失败，不能先假设正确。

基因编码有限的决策语法，而非给现有贪心器几个权重：

1. 当前活动请求的承诺/放弃条件：以剩余可见窗口、完成缺口、可行包时间和机会成本作离散分支；
2. required 包与 VALUE 包的选择规则：比较终值替换损失和后续可见供给，支持“现在低效率完成”及“保留窗口再做”；
3. 带记忆的阶段转换：每个公开几何区域或 RA 带保存未履行承诺与完成状态，反馈低质量后可更换包；
4. 数据丢失触发的重建规则：从原始公开 hits 和 resync 回滚，无不可撤销 target_done 位；
5. 在包内用固定几何优化和固定诊断模块解码真正动作。

允许的语法节点为公开状态谓词和上述包算子；禁用目标 ID、卡 ID、绝对测试时刻常量和生成种子。 crossover 交换整条承诺子树；mutation 改变承诺可行性判据或替换包算子。这样才检验“进化策略结构”的增益，而非卡片记忆或数值微调。

## 3. 终值耦合和信用归因

Fitness 必须用官方 scorer 的完整终值。输出分量和 paired regret 是诊断，不是把代理奖励冒充最终分。

每个 offspring 在相同生成实例/随机环境下与父代成对运行。因行动改变反馈历史，不能复用父代未来观测结果当作 offspring 反馈。定位信用时仅重跑变更子树首次触发前的公开前缀，随后按该子代真实动作重新模拟；不存在 prefix 对齐就完整重跑。明确区分：环境可持有 latent truth；策略入口严格只有官方 initialize/snapshot。

对 required/request/时间三个强耦合项，使用“承诺删除差分”：固定其他策略子树和同一环境种子，删除一类承诺规则，比较完整终值。若请求奖金增加但 required missing 更高，fitness 会显式结算该代价。均匀度损失最多 U，不能成为压倒 required 的无界常数奖励。

## 4. 可证伪预测

H1：结构进化能产生固定贪心无法表达的“请求可行性承诺—放弃—恢复”分支，在请求截止附近提高最终分；其证据必须是未见请求集合/发布时间上的成对终值提升。

H2：required 的未来几何供给进入规则后，进化能降低末季遗漏；仅提高 sum_best 或取消更多请求不算成功。

H3：基因中的有限记忆可在低质反馈/数据丢失后改变动作，而在完全相同公开历史下对不同隐藏真值保持动作一致。若做不到，说明训练或实现泄露。

H4：统一包解码器减少搜索空间足够多，使结构搜索的评估预算落在 CPU 小试可承受范围内。GPU 只有在要批量拟合公开反馈模型/学习包排序器时才有明确作用；不能预先声称 PRO6000 是进化搜索的瓶颈解法。

## 5. 官方依据

* `upstream/gosim-observer-examples/runner/challenge/v4_scorer.py`：BestLedger.best/max_factors/request_factors、required_penalty、uniformity_penalty。
* `upstream/gosim-observer-examples/runner/challenge/v4_runner.py:617`：公开 snapshot；`:819`：hits 仅返回 target_id 和 score；`:849`：完整终值。
* `upstream/gosim-observer-examples/docs/participant-guide.zh.md:265`：initialize 和运行限制；`:280` 起：公开历史；`:370` 起：反馈粒度；`:744`：900 秒含后端处理的全局 wallclock。

下一步才对照旧研究，判断此路线是否已经被测试，并把重复部分明确剔除。
