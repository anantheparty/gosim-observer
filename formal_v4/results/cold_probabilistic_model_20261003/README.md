# READY: 独立概率实验与全季资源图初证书

本目录没有建立生产策略提升，也没有新平台提交或完整赛季策略回放。概率实验先独立从官方协议/计分推导，再读取现有实现和自己的 cloud 输出作对照；全季资源图只使用允许读取的公开本地 L1/L2 真值。

## 概率模型结果

`cold_probabilistic_model.py` 对 L1–L4 做 leave-one-card-out 的固定 900 秒视场、命中条件下 program 选择实验。环境侧用公开官方逐目标 scorer；估计器只看当前公告、公共月相/airmass、过去声明的 program 和四舍五入得分。

| 卡 | 公告经验先验 / 条件 oracle | 联合概率后验减先验 science |
|---|---:|---:|
| L1 | 99.307% | -23.201 |
| L2 | 97.892% | +1.822 |
| L3 | 99.702% | -0.993 |
| L4 | 99.494% | +0.516 |

没有稳定收益。把含效率损失的有效质量直接当 program 档位质量，会比联合模型低约 6–8%；这不是当前生产策略基线。现有生产已经分离 C/E 并使用无条件 raw factor 下界。

自己的 `cloud_verified_portfolio_*` 只读审计表明，四卡最终都没有“实际 required 已完成、在线得分下界仍不证成”的目标。request 正/负状态可提供在线数字档位探针，但这些记录只有 beta 一条新增约束。因此本轮不推荐把更复杂 program 后验接入生产。

## 全季资源图与上界

构造全部 target × 全部站点可观测 slot 的可见边，不使用历史动作列。slot 内连续最高高度可达到最低高度的目标得到整 slot 的乐观服务容量；保留 16 根光纤的总时间容量。任意真实连续曝光可以按天气 slot 边界切分服务秒数嵌入图，跨 slot 曝光不会遗漏。

允许分割、跨曝光及跨夜累积有效信号，并删除共同 field/单纤维格要求。这是对“每 target 只取一次曝光最高贡献”的乐观松弛。另以最大曝光时长乘全季最大逐秒质量，约束每 target 的最大单次完成因子 `gmax`。

质量上界使用本地站点实际天气。非故障时保留 raw 效率，包括地震损失；故障相交 slot 取 `max(raw, min(1, raw/fault_multiplier))`，覆盖任意修复状态。没有假定 raw 效率 ≤1。所有相交同类事件的正向质量乘积都显式纳入上界；月光取上界 1，airmass 用 slot 连续最高高度取上界。配置的非负性、月光参数和 airmass 指数经过门检。

required 阶跃奖励用 `P min(g/threshold, 1)` 凹包络，保留 `-P * required_count` 常数；若 `gmax < threshold`，required 奖励恒为零。异质质量边形成广义流/凸 LP，不能称为普通最小费用流。

对任意非负 target 乘子 ν 和 slot 乘子 λ，独立最大化 target 完成因子与有容量边，得到可重算的拉格朗日上界。加上全部正 request 奖励和每个本地 fault 一次 correct-report 奖励，Jain 贡献上界取 0。忽略 data loss 只会乐观。完整表达式与任意曝光嵌入证明见 `resource_graph/proof_and_scope.json`。

| 卡 | 完整可见 target-slot 边数 | science+required 上界（加 1 分数值余量） | REQ 上界 | report 上界 | 总上界 | root 报告的新可行下界 |
|---|---:|---:|---:|---:|---:|---:|
| L1 | 5,511,827 | 8,388.186251 | 200 | 100 | 8,688.186251 | 6,409.988920 |
| L2 | 6,769,548 | 9,216.714933 | 200 | 100 | 9,516.714933 | 7,006.280570（中途） |

这些是有明确本地天气条件的完整边图上界，不是 alpha–delta 平台上界。逐目标精度校验、图上界和完整赛季得分是不同对象。图删掉空间共 field、月光和独立曝光信号要求后仍很松。有限坐标优化没有优于零对偶，因此保存的最佳证书 ν/λ 都为零，**本轮没有得到可用于生产的未来容量价格，也没有证明最优容量价格为零**。不能从这组结果推断真实资源不紧张。

独立 verifier 重算两卡对偶残差均为 0；各抽查 160 个官方曝光（共 180 个跨 slot、124 个长于 900 秒），没有超过质量/完成因子上界。数值使用 outward padding 与 longdouble 求和，最终额外上调至少 1 分。这是带明示数值容错的上界证书，不是严格区间算术证明。

## 复现与 stage 范围

```sh
python3 formal_v4/research/cold_probabilistic_model.py
python3 formal_v4/research/cold_probabilistic_cloud_audit.py
python3 formal_v4/research/cold_probabilistic_resource_graph.py L1 L2
python3 formal_v4/research/cold_probabilistic_verify_resource.py
```

四个研究脚本只需 NumPy；资源图当前不依赖 SciPy。它们只写本目录。

具体可 stage 的路径：

- `formal_v4/research/cold_probabilistic_model.py`
- `formal_v4/research/cold_probabilistic_cloud_audit.py`
- `formal_v4/research/cold_probabilistic_resource_graph.py`
- `formal_v4/research/cold_probabilistic_verify_resource.py`
- `formal_v4/results/cold_probabilistic_model_20261003/`

`manifest.json` 列出源文件、结果、允许的本地输入 SHA-256。两个完整边图 NPZ 约 42/54 MiB；它们支持不依赖优化器的证书重算。若不归档大文件，需保留源代码、manifest、摘要、证明和验证结果，并按复现命令重建。

后续空间支持函数在独立文件/目录继续：对任意 ν，完整球面 cell 覆盖与“field 外接球面圆半径 + cell cover radius”给出每 cell 的目标超集，其 top16 加权质量之和包住所有连续指向。需继续使用 slot 内质量 supremum、包含所有可见性边界，并明确这是单 fiber 匹配的乐观放宽。
