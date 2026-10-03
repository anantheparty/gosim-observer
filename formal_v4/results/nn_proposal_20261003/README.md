# 传统 NN 候选 value 初版：完成训练，暂不部署

## 结论

本轮实际生成数据、使用自有 PRO6000 训练了小 MLP，并完成 CPU 推理及未见卡片精核门检。**这个局部监督目标不值得替换现有 coarse 排序**：独立 L4 卡片的 top16 局部 oracle 平均 regret 是 NN 10.53%、原 coarse 0.35%；L3 为 7.42%、0.73%。它没有学习整季 continuation value，不能据此解释或补齐榜首的科学分差，也没有官方新分数。

候选广度有独立信号：宽池的局部 oracle 在 13/32 状态超过当前 CPUPhase 动作率。这里的改善是状态固定时的局部 utility，不能等同于整季得分提高。保留原动作后，任何新候选只在相同冻结 utility 更高时替换，可保证该局部量不下降；最终科学分并无单调保证。

## 数据与标签

只读取自有 local-cards L1–L4 的公共目录与 `gpu_direct_calendar_witness_20261003/L*/` 参赛者输出。没有读取平台 alpha–delta 隐藏 truth，也没有读取本地 truth 文件。32 个状态来自每卡 8 个分离夜晚；半数带删去部分 ledger、随机增加完成比例的反事实扰动。

ledger 起点使用归档中**最终有效、且在采样时刻以前完成**的本地观测。由于最终 validity 可以受之后的事件影响，它是构造训练状态的来源，不声称是逐时刻精确恢复的在线状态。反事实训练状态也不声称与官方某一完整轨迹一致。

每个状态包括原基线中心、按 merit 和均匀随机选择的可见全局锚点、随机纤维对齐及连续玻璃偏移，共 **16,775 个候选**。新的锚点分布覆盖四个 Phase seed 以外的空间。

标签来自 `SpatialPlanner._evaluate` 的球面几何、纤维冲突、三种 program 和曝光断点评价，**不是模仿 incumbent 动作，也不是季节 DP 的标签**。它在现有固定 Q 模型与最多 72 个采样断点内优化；质量没有沿曝光积分，active request 设为空，uniformity 使用现有梯度影子价。这里的 “oracle” 仅指这一明确限制内的局部评估器，不是问题最优解或实际科学分。

所有训练候选的被选 target/fibre 对通过球面几何验证。每状态前 8 个候选的 coarse 特征运算，与 `coarse_numpy_local` 完整有用目标池逐项对照，误差小于 1e-10。

## 模型、目标与隔离

模型为 **27→64 ReLU→1** 的 MLP，预测 `log(1 + local_rate)`。输入是几何摘要、目标/纤维统计、质量尺度与四个固定曝光下三种 program 的局部粗率；不输入目标 ID 或卡片 ID。

目标是 top-decile 加权回归损失，加同状态成对 value 差回归。训练用同状态成对 minibatch、Adam、固定 2000 step、batch512、seed261003。输入和标签的标准化只拟合训练集，测试集不参与选参数或停点。

| 分组 | 状态/候选 | log-value MSE | NN top16 regret | coarse top16 regret |
|---|---:|---:|---:|---:|
| L1/L2 夜序号 <20 训练 | 10 / 5253 | 0.00113 | 6.69% | 3.44% |
| L1/L2 晚夜隔离 | 6 / 3147 | 0.35063 | 0.785% | 0.0128% |
| 整卡 L3 验证 | 8 / 4182 | 0.06904 | 7.42% | 0.731% |
| 整卡 L4 测试 | 8 / 4193 | 0.08689 | 10.53% | 0.350% |

regret 的分母是同一宽候选池的最优局部标签。MSE 很小不意味着 top-k 找得准；top-k 好也不意味着实际整季分数高。

## 算力与 CPU 部署成本

通过 `ssh elevatia-wsl` 使用已有 Windows Numba CUDA 环境，在独立 `ownedbenchmark/nn_proposal_20261003/` 中训练。未安装 Torch、改服务、API 或显卡功耗配置。最终训练 PID 为 WSL 2923592，任务已完成；实际设备 RTX PRO6000 Blackwell。2000 step 训练段约 **1.52 秒**，含该训练段的首次 JIT；初始化和文件传输不在此计时内。CUDA 与 NumPy forward 最大误差 **7.15e-7**。

导出 `model.npz` **9590 bytes**。CPU 推理只需要 NumPy：768 候选加 top16 约 0.00016 秒，32768 个约 0.0106 秒。CPU 用显式 einsum，避免本机 BLAS 在有限正常输入下出现的浮点状态告警；结果排序与原 matmul 版本一致。

真正成本在特征，而不是 NN 本体。实际 L4 未见卡片状态重建并精核 519 个候选：

- 原 CPUPhase：0.195 秒。
- 新候选特征：0.119 秒。
- NN 排序：0.00018 秒。
- top16 精核：0.00479 秒。
- 新增总成本：0.124 秒；该状态没有找到比原动作更好的局部值。

重建的全部特征与 dataset 逐字相等；top16 标签与重新精核最大差 1.23e-8，指派几何合法。这还不是整卡 900 秒部署门限证明。

## 下一条 NN 主路线：整季机会成本

本轮 NN 只是广候选提案/排序基础模块。当前榜单差距主要来自整季科学分，应重新定义 value，而不是继续压低这个局部 MSE：

1. 用目标最佳曝光分、required 覆盖、request 完成及精确 Jain uniformity 定义实际终局目标 `F(S)`。对动作学习 `Q(s,a)=即时收益+V(后继状态)-V(当前状态)`，后继中必须包含 best-only ledger、剩余时间、未来可见窗口和已公开或可条件推断的质量机会。
2. 在拥有 truth 的 L1–L4 及自建训练实例做分叉整季 rollout。教师包括多起点 greedy/beam、LP/MIP、跨夜 LNS 和随机策略的最佳实际终局结果；同一初始状态和同一天气 realization 比较动作后的完整续局。有限 DP 可加入经验，但不作为唯一教师。动作监督采用各分支**最终得分差**，避免直接模仿某条 incumbent。
3. 另一教师是 season LP 的时间/目标/required/REQ dual：学习时间资源价与目标机会成本，随后仍以精确纤维指派和预算约束执行。现有 alpha `joint_compensation` 张量包含真实有限 LP dual 条件价格，可作为研究标签；它只是冻结 realization 的有限模型，不能当当前 leaderboard 全局真值。
4. 用候选 field 的未来最高质量、未来可观测次数、机会窗口长度和整季剩余需求，替代只看当前 rate 的特征。模型可采用 target/field DeepSets 加状态 value head，不需要语言模型或文本接口。
5. 分开通过三个门：监督/排序 heldout；未见卡片整季实际分数；900 秒 2CPU CPU 推理完整回放。最终只以官方或同引擎完整终局得分判定提升。

目前还没有这一整季模型的 rollout 标签、训练结果或官方评分；本报告不会把本轮局部训练包装成整季解法。

## 文件与复现

- `research/nn_proposal_data.py`：公共初始化、宽候选、局部 oracle 标签与训练数据。
- `research/nn_proposal_train.py`：独立 Numba CUDA MLP/Adam 与 NumPy 推理。
- `research/nn_proposal_checks.py`：按整卡和晚夜隔离的统计、CPU 耗时与实际未见卡精核。
- 本目录 `dataset.npz`、`data_manifest.json`、`model.npz`、`train_progress.json`、`train.log`、`heldout_report.json`。
- 模型 SHA256：`f31096ae37468331108f3306729f46df2ebe2bf5f8c6deca9d1deabe63d4ee95`。

数据复现：`python3 formal_v4/research/nn_proposal_data.py`。
GPU 训练：在有 NumPy/Numba CUDA 的自有环境运行 `python nn_proposal_train.py <本目录> --steps 2000`。
CPU 检查：`python3 formal_v4/research/nn_proposal_checks.py formal_v4/results/nn_proposal_20261003`。

production policy、已有 ZIP、Git index 与线上提交均未变更。
