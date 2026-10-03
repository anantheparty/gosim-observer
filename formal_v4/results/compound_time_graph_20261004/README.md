# 连续时长、多完整 field 组合：预声明真实 prefix 微验证

本轮先独立读官方 runner/scorer/fiber map/guide/initialize，写模型，再查 portfolio。
**结论：停止此固定动作数 family；没有强策略提高或季末 teacher 证据。**

预声明选点：L1/L2前200个observe中，首个“同900s槽已有公开反馈、槽余至少600s”的observe决策。得到两卡 rank=1；只有一个已完成曝光，尚无active REQ。候选只用公共catalog、当前公告和这一真实反馈，不用未来base tape或未来weather truth。native下一个完整动作在两点均字面重现强release。

| 卡 | 公共开始 | 剩余秒 | 最优双field时长 | 对同域双field rate greedy的官方差 | 对强base首动作+最佳第二field的官方差 | 对原base真实多field槽内控制的官方差 |
|---|---|---:|---|---:|---:|---:|
| L1 | 2026-11-02 00:31:58Z | 782 | 303+479 | +51.324625 | +51.790229 | **−53.351853** |
| L2 | 2026-11-09 00:31:43Z | 797 | 689+108 | +0.248636 | +0.250870 | **−122.192665** |

L1两场的正差主要为提前多完成一个required（+50），不代表季末仍有这个优势。原base分别有5场[292,64,77,178,171]和3场[231,390,176]；它们只作冻结候选后的held-out adjudication，最后一场duration截到公开槽尾以确保同资源。整个后续base历史未进入候选生成。

方法：从当前强native实际候选中确定12个赤道天区；第二个曝光按其真实开始重算水平轴、玻璃格、所有可落入场内的target、program band、全段airmass/月亮平均和assignment。时长提案来自每个target的旧best替代点、完成阈值、各自饱和点及其容量互补点的整数邻域。这是连续物理时间下的有限整数提案集，不是全域精确最优。每个叶精算best overwrite、required、Jain；assignment用science+required的可加部分，未证明全局Jain指派最优。REQ、loss、rank的完整模型见研究稿；本次实际域active REQ为空、L1/L2无stress/原source失效0，未声称验证一般REQ或loss。

L1 601个时长提案、237个相关target、777600双field叶，批量重指派9.23秒；L2 269提案、47个target、347328叶，3.87秒。批量的是不同首动作best账本上的第二场匹配，原相同L1标量循环49.78秒。无需GPU/Rhodes。

一个L2三场微跑已在root要求停止固定动作数扩展前开始，27.74秒内结束。它从公开frozen-belief greedy rollout推演未来场，16个field/155 target，beam6不完全DP，三条守容量整数时长交换线共1213次、3202320 assignment选项，输出261+407+129。完整官方核验后相对原三场控制仍**−1.459190**（science−1.135484，Jain−0.323707，required相同）。没有继续2→3→5扩参；固定动作数没有包含一般原greedy path。

`*_search_frozen.json`为官方候选裁决前落盘的动作；`*_result.json`和目录内CSV为官方短域结果。`MANIFEST.json`锁住源码、prefix和runtime。所有最终候选都经过官方合法动作、完整field/fiber、精确全段minimum-altitude及官方积分/结算检查。强source prefix每个target的命中fiber/factor/quality/prog_mult/score/valid字段全部重现；CSV行序编号因assignment键插入次序不同而不同。

下一个模型若继续，应以public causal greedy path为可行初解，允许可变动作数，在相同完整时间资源中搜索ledger状态；保留初解是门检，不可把真实未来tape当公开提案。fixed-time同状态双max/request覆盖支配有条件可证，action-rank/loss-history不同则不能安全支配。当前连续时间简化只压缩相关target并批量共享第二场几何/质量，没有获得能覆盖可变动作数的可靠小DP状态。将本轮负短域动作留给root更广的真实replanning teacher，不申请额外整季预算。
