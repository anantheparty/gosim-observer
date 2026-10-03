随机曝光完成价值研究已完成，**拒绝采用：L2 验证失败**。8 条官方完整协议回放全部 `survey_complete`，初版、两次物理一致性修正与最终结果全部保留。参赛策略只读取 initialize、公开消息和公开 score 反馈；没有 runtime LLM、GPU 或未来真值特征。

最终版本固定 16 条路径、8 个字段、两种近似时长构造；source 均值和修复策略保持冻结源。每条路径按槽边界和 ≤120 秒网格积分，再做 program 分类、raw saturation、历史 best 正部和 required 阈值，最后取期望。节点 bank 覆盖最大合法曝光，短候选截取共同前缀。数学模型与近似限制见 `final_source_snapshot/scenario_value_MODEL_ZH.md`。

| 卡 / 预声明角色 | 固定强 CPUPhase | 最终随机版本 | 差值 | required 缺失 |
|---|---:|---:|---:|---:|
| L1 / 开发 | 6206.367823 | 6232.156101 | +25.788278 | 2 → 2 |
| L2 / 验证 | 6808.597984 | 6749.276565 | −59.321419 | 3 → 3 |

两卡平均下降 **16.766571**。L2 科学分下降 59.442070，required 与请求奖励均不变；末季机会成本没有由当前随机边际收益得到改善。按照预声明的开发/验证/留出划分，停止该模型，没有使用 L3/L4 救参，也没有追加 ablation 或修改 sigma、seed、路径数与字段数。

早期 L1 观察依次为 +161.416771（初版）、+161.416771（tie 修正）、+229.682088（起始高度修正）。这些版本仍存在随后修复的节点 prefix 一致性缺陷，不能拼接成已验证成绩。初版 deterministic integrated 消融为 +166.698785，比初版随机方案高 5.282014；候选构造相同，但有限节点的 `mean(C*E)` 最大漂移约0.32%，且它使用修正前源码，因此不是最终版严格 variance-only 归因。

- `final_comparison.json`：最终同源完整季节差值、全部结算分项及路径。
- `version_history.json`：8 条完整回放，不隐藏实现修正或较差结果。
- `baseline_branch_proof.json`：原始与最终源码的 baseline 控制流、初始化、精算入口及 installer AST hash 完全一致；修正只进入 scenario 分支。
- `checks.json`：3456 项与官方 scorer 对照，最大误差 1.8e−15；1/3/5 槽候选集合下共同输入分布和曝光积分逐位相同。
- `physical_trace_checks.json`：最终 L1/L2 共 28485 个指派逐一通过官方全曝光高度检查，零高度违例。
- `implementation_audit.json`：独立只读审查、原始起始高度 bug、prefix 缺陷及修正记录。
- `finiteness_checks.json`：192 组局部公式与源 public 公式一致，非有限值为零。Matmul FPU warnings 被保留；没有据此改动活跃源码。
- `final_source_snapshot/`：最终研究源、数学说明和全部冻结生产 Python 源，包含公开配置，无 remote runtime 或凭据。
- `artifact_manifest.json`：所有归档文件的 SHA256。

最终两条随机回放分别约231/264秒，参赛子进程单线程，观测 RSS 约119/123MB。此处为本机协议门检，未额外运行受限 Linux 部署门检或云平台评分。生产文件和 Git index 均未修改；所有计算进程已结束。
