# 必需目标的全季匹配预留实验

2026-10-03。独立阅读官方光纤几何、评分、runner 和 L1–L4 后，将 mandatory 阈值观测建模为不能拆分的时间任务，并实现公开输入驱动的全季匹配预留。固定 L2 验证失败，拒绝采用。随后按预先声明的固定源码完成 L3、L4；没有根据留出卡调整参数。

## 完整同源结果

两模式使用同一个冻结 Policy、环境反馈、CPUPhase、请求和数据失效实现。新增模式在完整 CPUPhase 动作生成后执行预约屏障或必需目标阈值曝光。八条轨迹均由未修改的官方 `run_scenario` 结算，均为 `survey_complete`；每卡两模式源码哈希逐项一致。

| 卡 | CPUPhase | 匹配预留 | 总分差 | 科学分差 | required 缺失 | 请求奖励差 |
|---|---:|---:|---:|---:|---:|---:|
| L1 训练 | 6206.367823 | 6205.798907 | −0.568916 | −0.620541 | 2 → 2 | 0 |
| L2 验证 | 6808.597984 | 6602.520628 | −206.077356 | −206.290062 | 3 → 3 | 0 |
| L3 留出 | 5910.930583 | 5737.635073 | −173.295510 | −72.825696 | 5 → 5 | −100 |
| L4 留出 | 6095.293215 | 5723.628729 | −371.664486 | −222.355985 | 0 → 3 | 0 |
| 均值 | 6255.29740125 | 6067.39583425 | **−187.901567** | | | |

L1–L3 未救回任何原 missing；L4 新增三个 missing。L3、L4 的公开 `state_resync` 各触发一次即时重新匹配，官方账本完整处理回溯失效。详细组件、missing ID、阈值覆盖数和时长统计见 `paired_summary.json`。

## 构造

官方 required 判断依赖某一次有效曝光的最大原始因子。若目标流量为 `f_i`，曝光公共几何质量为 `H_i(t)`，则单次任务要求 `f_i × integral(Q_i(t), exposure) / (f0 × t0) ≥ 0.5`；分开的短曝光不能累加完成。

把公共夜历从夜末向前切成互不重叠、最长 3600 秒的块。每个目标到每个块的边，保存块内某个单次曝光的起点与阈值时长。公共月球和气团质量按 120 秒网格积分，起点每 300 秒采样；曝光必须整段在块内，端点高度高于公开最低高度加 .04 度。未知未来站点质量采用明确的有利条件假设 `.85 × revealed_efficiency / .95`，阈值时长加 1.12 安全系数。这不是对未来天气的保证。

当前缺失且有边的 required 中，最短条件时长至少 1200 秒或剩余可用块至多 6 个的目标进入匹配。目标和时间块形成容量为一的二部图。NumPy 实现最短增广路指派，先最大化已安排目标数，再最小化 `duration + 120 × days_until_block`。足够贵的 dummy 列使这两个目标按顺序优化。各已匹配曝光在独立块内，构造阶段没有时间重叠。

执行时取消已完成目标的预约；当前科学曝光碰到未来预约起点时截短。到期目标用完整球面光纤分类、三个 program 和阈值时长生成强制完成动作，同时保留伴随目标的正常收益选择。当前反馈条件不足时阻止该边并重新匹配；强制曝光也受本块末端和下一预约限制。初始目录、夜历、当前 snapshot 和已公开反馈是全部 participant 输入。

## 失败证据与范围

这版匹配没有科学续局时间价格，也没有把未来天气、方向性遮挡和请求竞争纳入边的可靠性。L2 出现 422 次到期条件不足和 235 次屏障，仅执行 15 次强制动作；小于 600 秒的曝光由 502 次增加到 573 次，原始因子至少 .5 的目标由 7040 减少到 6860，至少 .99 的目标由 3618 减少到 3432。它反复为条件可行但当前不可完成的任务截短科学曝光，最终 missing 集合完全相同。这些统计支持模型失配的解释，不能单独证明每次截短的因果终分差。

图的精确性只覆盖所定义的有限块、采样边和加性成本。每块一个任务限制了共同观测机会；未知天气假设和在线执行仍是启发式。完整 scorer 验证其实际失败，未提出整季最优或分数上界声明。

## 源码与核验

- `../../research/required_allocation_calendar.py`：公共几何、条件时长、增广路匹配、预约执行。
- `../../research/required_allocation_experiment.py`：固定同源完整回放；默认结果写入 `final/`。
- `../../research/required_allocation_checks.py` 与 `checks.json`：75 组指派对照 SciPy 最优值零误差；公共质量最大误差 2.78e−17；15 个初始预约独立使用官方几何和 scorer 核验，最低条件因子 .560001821。
- `dot_audit.json`：144 个真实方向 dot 均有限；Mac BLAS 状态警告下与 `einsum` 最大差 2.22e−16。最终实现使用等价 `einsum`。
- `source_final/`、每卡 `experiment_summary.json`：锁定源码和全部依赖哈希。
- `model_spec.json`、`paired_summary.json`、`final/{control,allocation}/{L1,L2,L3,L4}/`：模型边界、组件汇总和完整官方输出。

初版 L1 得分 6212.966037，但审计发现 36 个过期起点预约和 8 次越过自身块末的强制曝光。`source_v1/` 与原始 `allocation/L1/` 保留该结果。修正版重算当前块剩余起点并限制自身块末，最终所有匹配历史的过期起点均为零。配对端点高度计算由不必要的外积矩阵改为逐目标向量；初始完整 duration/start 两数组与旧实现逐元素完全相同，构建耗时 4.65 秒降为 .20 秒。`source_v2/` 和 `v2_mechanical_checks.json` 保存这项核验。最终再增加公开 resync 的即时匹配。

最终匹配模式在四个单线程进程并行的 Mac 上完整耗时 246–290 秒。15 文件的隔离 NumPy participant 保存在 `participant/`，仅完成导入检查。因固定 L2 验证失败，按预先约定停止部署准备，没有运行 2 CPU、2 GB、900 秒协议资源门检，也没有占用 Rhodes、调用 LLM、修改生产源、Git index、网站提交或设计备注。

复现命令在仓库根执行：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv-solver/bin/python formal_v4/research/required_allocation_experiment.py --card L2 --mode control
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv-solver/bin/python formal_v4/research/required_allocation_experiment.py --card L2 --mode allocation
.venv-solver/bin/python formal_v4/research/required_allocation_summarize.py
```
