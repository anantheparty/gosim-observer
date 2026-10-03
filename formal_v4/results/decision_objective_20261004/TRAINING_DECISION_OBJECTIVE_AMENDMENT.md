# 固定候选下按决策收益选择检查点

2026-10-04 JST。未读取或接受实际bulk标签，未训练。本修改只改变小型学生的检查点选择与报告，不改变teacher、数据划分、候选、损失、准入合同、CUDA模型或NumPy部署。

## 实际反例

调用实际 `group_metrics`，合成三个候选终局相对收益为 `[0, -100, +1]`。模型M预测 `[0, -99, -1]`，MAE **1.0**，却选择control，真实相对收益 **0**；模型N预测 `[0, -95, +1]`，MAE **1.666667**，选择真实收益 **+1** 的候选。M对永远不会被选择的负动作预测更准确，使总体MAE更好，但决策更差。

反例确实运行，见 `counterexample.json`，对应执行时trainer SHA `039bedbfb43125abfdd917d3bb390356f0e813c18b21642589b017247e9e318e`。不使用真实数据、外部天气或模型训练。

## 修改的数学目标

固定验证组及候选集合。设组i候选终局差为Δ_i(a)，模型选择a_i。其regret为 `max_a Δ_i(a) - Δ_i(a_i)`。第一项对所有模型/检查点相同，所以降低平均regret严格等价于提高所选候选的平均已实现续局收益。

新检查点按 `(teacher_regret_mean, raw_advantage_mae)` 字典序比较：先看决策收益损失，只有同损失时用数值MAE打破平局。pairwise Huber训练损失、auxiliary分项、原200 epochs/30 patience默认上限均保持。L1/L2训练、L3验证，L4拟合时不打开。

这仍是同一真实世界下的有限单状态教师指标。各状态未来相关，模型连续接管策略会到达新的状态；该目标不能证明条件期望、整季部署收益或独立泛化。全部导出保持 `deployment_calibrated=false`，后续仍需完整受限协议赛季。

## 来源与验证

新trainer SHA：`933e40c2e5399067f34a7d9ff67c7e8d0d3d28a852f1a4ba68c84b6f11249585`。

旧guard补充与13合成检查是039版本的历史记录，保持原样。`selection_check.json` 记录旧版Git提交和两版SHA，并确认除train之外全部既有函数AST未改、四个CUDA已核验模块字节未改。实际新的 `decision_selection_key` 在上述反例中选择N。

复现反例：在仓库根目录运行 `.venv-solver/bin/python formal_v4/research/decision_objective_probe.py`。当前函数相同，再运行会记录当前trainer SHA；已保存的执行记录和Git版本保持可回溯。
