# 公开 score 历史的联合质量世界模型

2026-10-04。源锁为公开官方 `e01939d060f304c2a7cf04d9b3e46009b564fc23`；只写自有 results 和本文。未读取 L4 truth、L4 teacher、最终隐藏卡或旧 32 状态教师排名标签。

已完成新独立 seed 世界训练、普通 NN 联合分布、NumPy actor 和可回放 33-file 包。尚无本策略完整正式季节得分；不把下面的人工候选 regret 或分布校准当整季收益。

## 1. 新机制和可辨识性

令每个天气槽的站点质量为 `C = transparency * sky / (seeing * q0)`，有效质量为 `Z = C * E`。官方 program band 由 C 积分得到，raw factor 由 Z 积分得到。未封顶、已知真实 program 倍率时，score 给出 Z 的一条精确测量；实际倍率未知时保留两个倍率分支。跨多个 H_i 的 band 条件能限制 C，却通常不能唯一分离 C 与 E。封顶 score 只给不等式。跨槽时，这些是曝光加权积分约束，不是某一个瞬时槽的真值。

原强策略的 `fit_feedback` 返回单个 C/E，随后做 scalar AR 均值规划。本轮不同之处是：用过去八条 score 的 C/E likelihood-grid 特征预测未来四个槽的完整联合分布；同一条天气路径同时给所有目标使用；先积分，再做 program/cap/historical-best，最后求均值。不沿用 16 条无反馈校准的先验路径，也不把本轮 token 网格称作精确 Bayes 后验。

路径 `s` 中目标 i 的计算为：

```
q_band[s,i] = sum_k overlap_seconds[k] * C[s,k] * open[s,k] * H[k,i] / duration
q_exp [s,i] = sum_k overlap_seconds[k] * Z[s,k] * open[s,k] * H[k,i] / duration
factor[s,i] = min(flux[i] * duration * q_exp[s,i] / 450, 1)
score [s,i] = weight[i] * factor[s,i] * program_multiplier(declared, band(q_band[s,i]))
gain  [s,i] = max(0, score[s,i] - valid_best_score[i])
```

共享路径自然保留光纤间的质量相关性。四槽 full covariance 保留时间相关性，joint 16-pattern closure 表示槽间关闭相关性。关闭模式与连续质量混合分量条件独立是模型近似；Gaussian 混合未强制 `Z/C` 的物理上下界。模型仍有近似偏差，不能宣称 exact PF。

同一 normal/mixture/closure bank 对所有候选共用，与候选最大曝光时长无关。不同长度只能裁剪同一槽路径。这个设计解决旧 scenario 候选最大长度重排随机路径的问题。

## 2. 独立世界和模型

`build_world_dataset.py` 调用锁定官方 `build_nights/generate_events/generate_weather/generate_bulletins/generate_forecasts`，采用 sha256-v1 streams。基础连续天气参数来自官方 reference；38 夜从 2026-10-01 开始。各 world 的 weather 各类次数为 0–3、quake 0–2、fault 0–2，均由独立 host 随机流选取。它们是明确训练先验，不是实际比赛卡参数。

| split | seeds | worlds | records |
|---|---|---:|---:|
| train | 710000–710127 | 128 | 45,022 |
| val | 720000–720031 | 32 | 11,514 |
| test | 730000–730031 | 32 | 11,001 |

观测动作与隐藏状态无关，随机生成非重叠 60–3000 秒曝光、三种 program 和公开类别 flux/weight 分布。高仰角 sensor 避开 reference 方向事件；score 由真实跨槽 C/Z 积分、band/cap/program 后舍入六位产生。field 共享 H，目标间为 ±2% 小变化。初稿把 H_i 独立抽满范围，会过度辨识 C，已经在未见训练结果和测试标签前停止并改正；旧日志保留。

actor 输入只有过去公开 score、weight、flux、逐目标公共 H、动作长度/program、日历和时间；host future C/Z/open 标签只写 dataset，从不进 actor 包。token 为 17×9 的 C/E grid 残差特征，加八个公共统计量，每条 161 维；八条记录加 age、night-age、season/currentfraction，共 1306 维。grid 中的残差宽度只是 NN 特征设计，不声称官方 score 有额外 Gaussian 测量噪声。训练 sensor 的几何是人工设计，实际 H 的时间变化和 field 内更宽差异仍是行为条件偏移风险。

普通 MLP 为 1306→128→128→196，209,092 参数。输出为四个 8D full-covariance Gaussian 混合分量（未来四槽 log C、log Z）与 16 个 joint closure logits。NLL 训练用 closed 槽缺失值 mask；检查点按固定 384 个独立 val 状态上的 nonlinear candidate regret 选择，12 epoch 后选 epoch10。测试标签仅在选择结束后读取一次，未据 test 重调模型或阈值。

GPU 实际为 RTX PRO 6000，训练 85.9104 秒，Torch peak 386,113,024 bytes。独立目录 `C:/Users/hedge/gosim-predictive-world-20261004`；没有改服务、原 venv、功率限额。首次训练只因日志 NumPy int64 JSON 序列化在 epoch0 后终止，修复日志类型后用相同 seed/数据/参数重跑；失败日志保留。

## 3. 独立 world 结果及其限度

固定 test 1024 个状态的候选是四个人工 field ×300/900/1800 秒×三 program，另含 wait；各 duration 统一收费 `lambda * duration`，避免在人工验证中免费增加时长。lambda 只用于这个有限验证域，actor 没有新增时间价或 surplus 规则。

| 方法 | test mean immediate regret |
|---|---:|
| 联合 NN 分布，路径内结算 | 0.1235935265 |
| 同一 NN 均值先积分结算 | 0.1333836822 |
| 最新 score-grid point + scalar AR | 0.1878051302 |

point 是清楚写明的人工控制，不是生产 RequestCache 策略。相对 point 的推荐变化 157 次，实际条件收益正98、负57、其余tie；next-Z 90% 区间覆盖87.714%，closure Brier .0103005。分布近似有 undercoverage。这些数值支持进一步检查模型，不能证明生产策略或整季胜出。

## 4. 官方算子与导出门检

`check_operator.py` 300 随机曝×16目标，共 4800 个官方 scorer 对照，涉及 slot overlap、关闭、各 program、cap、历史 best；最大误差 5.3290705e-15。无 lunar 的常高度算子 gate 成功。第一次检查误用简单 sec(alt) air mass，发现误差 .00148，改用官方 normalized Kasten–Young 后通过；失败没有被称作通过。

CUDA float64 权重导出对 128 个 train 输入与 NumPy output 最大差 6.22e-15；target 置换 token 差0，输出有限。first public initialize/decision 动作与原 RequestCache JSONL 完全一致。后续 Mac NumPy BLAS 发出有限值上的 floating-flag warnings，改为等价 einsum，重新执行算子/导出/public-prefix 检查；最终 gate 原件见 results。

## 5. 首版实际部署 scope

`predictive_policy.py` 首版完全继承原 29-file RequestCache。保留原 physical field、duration、assignment、REQ/rate/repair；只重新比较同一物理曝的三 program。参考先验支持规则为：八条合格公开 score history；无当前非 terrain 公告；目前公开 forecast 覆盖且未列出此 night 的事件；无 active REQ；夜末剩余≥四槽；候选整段每个目标 altitude≥80.05°；历史 sensor 整段 altitude≥55.05°。model 预测 program 净差超过三倍 Monte Carlo 标准误差才更换。

55°历史 sensor 的方向排除依赖 reference generator 中 terrain 高度≤50°、forecast 粗化完整等条件。这些是本模型条件，不是正式协议已知必然。80°候选域也不构成任意未发布事件的绝对排除证明；ground motion、fault/background closures 等未预报因素保留在训练世界中。

公共强轨迹仅用 target/action/decision/message 与 CSV 中投影的 `(observe_index,target_id,score)`，未用 CSV 的 factor、quality、prog_mult、valid，也未读 truth。静态 prefix audit 每次仍喂原实际公开反馈，没有把改 program 后的未知反馈造出来。

| card | physical all-target ≥55° / ≥65° / ≥80° | NN-supported | program changed |
|---|---:|---:|---:|
| L1 | 684 / 454 / 69 | 25 | 1 |
| L2 | 818 / 528 / 88 | 9 | 3 |
| L3 | 706 / 480 / 103 | 22 | 0 |

另一份粗支持 audit（不含实际 4-slot geometry 截取）在 history8、非REQ、无事件 forecast night 条件下，55/65/80 域分别为 L1 221/141/22、L2 131/76/10、L3 144/96/23。与 adapter 精确数量差异来自 .05°余量、history stale/跨槽覆盖和 sensor 接收细节，不能混为同一种 gate。

首版 program 变化：L1 observe329 BRIGHT→DARK；L2 observe291 BRIGHT→DARK、468 BACKUP→DARK、469 BRIGHT→DARK。这些索引只用于公开前缀审计，actor 没有索引/卡身份触发规则。

## 6. 可回放产物

`results/cold_predictive_world_model_20261004/observer_predictive_world_v1.zip` 共33成员，新增 entry/core/adapter/NumPy weights 四项；原27源码和配置逐字节保留，只有 run manifest/build manifest 更新。Actor 不包含 dataset、官方 generator、未来 labels 或旧 quality profiles。zip/model/dataset SHA 在 `package_receipt.json`。

`training_result.json`、`dataset_manifest.json`、`operator_gate.json`、`numpy_export_gate.json`、`first_action_gate.json`、`public_program_audit.json`、`public_support_audit.json` 提供对应原件。首版覆盖和实际动作改动很小；完整受限闭环回放仍是决定是否采用的必需证据。若首版失败，不用 L4 或增大 epochs 救这套固定结果。
