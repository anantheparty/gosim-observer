# 公开 history 的 report 期望价值与免费额度 DP

日期：2026-10-04。正式源码 e01939d060f304c2a7cf04d9b3e46009b564fc23。此轮完成独立模型、PRO6000 普通 NN、有限 world 决策评估和原强 ZIP 适配；**生产支持域审计失败，当前 v2 包不启动实际整季**。后续不同观测域另立 trial，不能把这轮 finite sensor 收益当正式提升。

## 官方数学模型

令 b 为全部已公开 history 的联合后验，F 表示“此刻有尚未修复的 instrument fault”，p=P(F|b)，q∈{0,1,2} 为剩余免费额度。report 不推进模拟时间和 observe rank，结果在同一时刻返回。正确报告 +100，修复当前事件并重置 q=2；false q>0 消耗一额度，否则 −150。false 和 correct 两分支都让当前 F=0，因此同一时刻再次 report 被支配。

正确 Bellman 为

\[
V_q(t,b)=\max\{W_q(t,b),R_q(t,b)\},
\quad R_q=p[100+W_2(t,b_C)]+(1-p)[-150\mathbf1_{q=0}+W_{(q-1)_+}(t,b_N)].
\]

W 强制现在推进时间、观察或结束，避免零时间自环。b_C 和 b_N 的未来 hazard 不相同：已修复的事件可能仍持续，不能立即重新抽一个新事件。公开 correct_count 必须在 correct 严格加一，在 wait/false 保持。

固定下一曝光动作并用健康状态的科学增量为共同基准，可以写

\[
W_q=-p\ell+\mathbb E[V_q(t',b')],
\]

其中 ℓ 是当前故障导致的 **best-only 新增科学分差**，先做时段积分、program/cap/best 结算后求差。R−W 中是提前修复避免的延迟损失与 quota/信息 continuation 差，不能直接用 p×全部剩余 repair gain。如果下一步完美识别仍活跃的故障，等待也能领取 +100 及之后修复收益，提前报告只挽回这一段 pℓ。终局无未来额度价值时，q=1/2 的纯报告对任意 p>0 有正价值；q=0 的纯报告阈值为 p>0.6，必须在最后合法调用、越过 survey_end 之前执行。

C/E 从某次 score 通常不可辨识。模型保留 17×9 的 C/E score likelihood 网格，用概率混合表达故障与 quake/天气/饱和的混淆，没有宣称低 E 是故障的充分证据。

## 本轮独立训练与小 DP

全部位于 `results/cold_report_value_model_20261004/`。host 复用官方生成器；actor 包不含生成器、world 标签、旧 32 teacher、实际本地故障日期或封存 L4。

| 划分 | 独立 seeds | worlds | 公共状态 records |
|---|---:|---:|---:|
| train | 740000–740127 | 128 | 129630 |
| calibration | 750000–750015 | 16 | 16359 |
| validation | 750016–750031 | 16 | 16101 |
| 原 test v1 | 760000–760031 | 32 | 保留，含后述实现缺陷 |
| 修复后锁定 test v2 | 770000–770031 | 32 | 仅运行一次 |

观测域为保护高度的共同 H±2% 的 16 fiber sensor、240–2400 秒为主的随机非重叠曝光、9400 目标的公开类别/flux 先验和 best-only 账本。公告/已发布 forecast、quake 与 fault 并存均参与输入，report 行为以独立随机探索采样。每个训练状态重算 **同一未来天气、同一物理 sensor 动作** 的 report/wait 下一条公开历史；counterfactual report outcome 由 host 标签决定，actor 只见公共 score 和 report result。

普通 MLP 为 1382→64→64→1，在 NVIDIA RTX PRO 6000 Blackwell 实际训练，16 epochs，按 calibration NLL 固定 epoch0，再拟合一次 logit scale/bias。21.200 秒，CUDA 峰 1,262,177,792 bytes。calibration NLL .103716/Brier .026255；独立 validation NLL .152748/Brier .039110。validation prevalence .06739、平均概率 .04647，说明此模型的跨 world 概率仍有下估，不能把概率校准称为无误差证明。

DP 投影状态是 q3×posterior15 bins×public quake age3×public correct_count3；1024 有限 epoch。wait/correct-report/false-report 各用自己的 coupled 公共下一状态 kernel，稀疏行以 32 个等效样本 shrinkage 回退。science loss 来自训练 host 的同一曝光 paired best 增量差。免费版允许使用最后一次免费额度；q0 paid 版保留，但原 validation 两条负例，按预声明均分规则冻结免费版，不做阈值扫描。

该投影不是完整充分状态：旧故障结束/renewal 后验、天气共享长期相关、目标机会/REQ/Jain/data-loss，以及真正报告后重新选择场域与时长没有被消去。其报告价值是 finite sensor 近似，不是全题 bound。

## 实现缺陷与修复记录

初版 sparse kernel 回退 globalpool 会把 public correct_count 从 1 回退为 0，制造虚假后续 repair 奖励，最大 R−W 约12833。旧 `test_evaluation.json`、`report_dp_v1.npz`、`selection_lock_v1.json` 与日志全部保留，不能当合格 test。模型、calibration 和免费版选择未重训/重选。

机械修复强制 wait/false 保持计数，correct +1；源/模型/DP/包在新 test 之前冻结为 `SOURCE_LOCK_V2.json`（01:29:48 UTC）。修复后最大 R−W 130.346。126 可穷举两 epoch Bellman 树误差≤2.85e−14；3240 转移行计数违规 mass0、行和误差≤2.23e−16；q 路由复算误差0，无隐式 quota regeneration。独立生成 world740000 的官方同 future 两分支 32 条 six-decimal target score 比较误差0，correct reset/重复 false 额度合同通过。见 `semantics_checks.json`。

## 修复后的 finite world 结果

| 策略 | 32 新 test worlds 均分 | 相对同 posterior p>.9 free | oracle regret |
|---|---:|---:|---:|
| none | 3645.632768 | — | 445.465960 |
| p>.9 free | 3797.578189 | 0 | 293.520539 |
| quota DP free | 4055.259519 | +257.681329 | 35.839209 |
| 可见当前 F 的 oracle | 4091.098728 | — | 0 |

DP 对 p90 18 赢/0 输/14 同，paired SE56.804169；平均 correct .8125、false1.03125，未花付费罚分。这里所有策略使用同一随机 sensor 物理轨迹，区别为 report 动作与由此导致的公共反馈/repair。**不能与真实强 faultv1 的完整季节分或 root 的均分改善相减。** 新 test 完成后全部冻结源码 SHA 再核对未变；见 `FINAL_RESULT.json`。

## 生产支持域失败与可跑包

从原最强 29-file ZIP 适配到 36 members，27 原源码字节相同，仅入口与 manifest 改写并添加7文件。false 返回之前已选 science action/pending，保持 C/E、belief clock、ledger；true 交由原强正常 ingestion/replan。L1/L2 三动作公共入口原包/disabled/DP/p90 逐项相同，quota1 可用/quota0 拒绝及因果接口通过。见 `public_interface_checks.json`。

生产 adapter 为训练保护域设置了 min altitude80.05、hit≥12、duration240–2400、共同 H，以及八条历史的年龄支持 gate。已发生原强 **公共** 历史审计结果：

| 卡 | 支持的 sensor feedback | 可查询八条 history | 首个会触发 |
|---|---:|---:|---|
| L1 | 41 | 0 | 无 |
| L2 | 46 | 0 | 无 |
| L3 | 64 | 41 | 无，max p=3.972e−5 |

审计只投影 observe_index/target_id/score 和已经发出的公告/预报/report result；删除假定 wallclock 和 active_requests，不做策略规划重放，也不合成反事实结果。没有读取 L4。见 `public_support_audit.json`。这说明其训练观测设计无法覆盖当前 strong 采样行为；不能直接放宽旧 NN gate 来救此包。因此 root 已明确不启动当前 v2 三条实际整季。

冻结候选 ZIP：`candidate_package.zip`，SHA **14f0ec890da6296aaf200836c437485d3c5d0beefa6ba3f50d418dc5dfcdef60**。

同一 posterior 的 p90 conformance ZIP：`posterior_p90_control_package.zip`，SHA **7143ed68e1ed34236239499672d85f830026669847abce82cbff04e37dd35312**。两包用于保存/复现此轮失配，不是部署建议。

## 下一 trial

保持本轮全部失败与冻结 test。新域应生成稀疏的、不同 field/alt/direction 的公共轨迹，使用真实公开 geometry、coarse notice/forecast 和 score；监督当前可修 F 与 paired marginal science loss，并保留 coupled future天气。先用小 CPU world 管线确定接口与计算量，再在 PRO6000 拟合普通 NN；不盲开128×900秒 strong rollout。actor 在新域未支持的状态应 fallback 到已正式完整验证的 faultv1，而不是追加无效 NN 计算或放宽 v2 gate。最终仍须与 faultv1 做真实强闭环比较。
