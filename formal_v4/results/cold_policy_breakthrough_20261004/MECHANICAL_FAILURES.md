# 保留的机械失败

1. 首次 public audit 路径 root 使用 parents[3]，落到 OBSERVER 而非 formal_v4；纠正为 parents[2] 后重跑。此前未访问 truth。
2. scorer 单动作核验首次全部通过；追加官方 runner terminal packet 核验时，`Scenario` 是 frozen dataclass，直接修改 survey_start 抛出 FrozenInstanceError。改用 dataclasses.replace，仅用于原计划中的 evaluator 末状态恢复。candidate 时间、report、原末动作、公共收益界均未更改；没有新增季节任务。
# 完整入口首次失败与正式初始化修复

Root首次完整L3执行在0.399秒initialize阶段失败，decision数为0，状态为`FAILED_IMPLEMENTATION`：旧`TerminalReportGuard.__init__`把`initial['targets']`误认为list of dict，实际正式v4是`{"columns":[...],"rows":[...]}`。这是实现失败，不是候选得分失败。旧wrapper、preparer、harness、合成测试、旧来源锁和完整22文件包均已封存在`FAILED_IMPLEMENTATION/`，失败远端目录`/tmp/geometry_native_20261003/results/terminal_report_20261004/enabled_L3`由root保留且不覆盖。

旧wrapper SHA为`297bec972e2611e1f1f6a4b4aa06f8cb363667e8c9712bd1eebd6f76b58c0278`。修复只按官方`v4_workflow.initialize_payload`与READY`SpatialPlanner.__init__`的真实字段契约读取columns/rows，目标ID转str，与native保持一致；触发规则、参数、模型、冻结动作与serve/ACK均未变。`initialize_catalog_fix.diff`给出完整wrapper差异。

新增真实公开初始化集成检查初次将官方类名写成`Workflow`，在执行任何actor前ImportError；核对源码后改为`V4Workflow as Workflow`。未调用场景/评分器、未访问truth，修正后检查通过。原合成fixture改为正式columns/rows格式，16项守卫和20项harness检查继续通过。
