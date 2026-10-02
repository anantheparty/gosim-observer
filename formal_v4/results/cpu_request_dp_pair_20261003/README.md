# CPU24相位 + 请求DP：同源L1回放

每模式900秒，Mac `.venv-solver` NumPy2.0.2，所有模块CPU-only，无Numba/CUDA/网络导入。原policy字节不变，仅入口组合 `RequestDeadlineMixin` 与 `CPUPhaseSpatialPlanner`。68个冻结输入hash零差异，配置见deadline_policy_config.json。

两模式均 **6206.367823**、science6106.651481、REQ100、report100、required−100、均匀度−0.283658；首REQ3/8未完成，后REQ6/8完成。两次均survey_complete，无错误report处罚。旁路338.993秒，DP424.126秒，900秒预算仍有余量。

请求构列28次、117.252秒，92次DP共0.237秒，其中70次预测不可行；实际override、裁剪、边界等待全部0。旁路准确复现之前24-anchor CPUphase L1，因此CPU迁移保持基础算法与轨迹，但该组合没有任何得分提升。当前不推荐上线此REQ版本。

明确需要复查的模型缺陷：把当前每目标target_quality_scale永久冻在该目标上，未来该目标的alt/az改变之后仍沿用同一地形/临时方向衰减。这可能虚判整个截止窗不可行。今后的模型应分离静态地形场（随未来alt/az重算）、当前槽的临时bulletin证据、已发布forecast指定的night_date支持、以及有到期时间的经验黑区。不能直接把当前临时天气公告延伸到未来整个窗口。

入口SHA256 `d9ebcce3dae477ac296295b1676ff8f55037be223e9b74de1c00b3ab2aa787f1`；共同模型 `47753b98031a61d00def3fdbec5f5115676f5ec2f40ad7ced48da1b73a8450bf`。原GPU版本同方法在不同基础轨迹下曾+132分；本CPU实验说明那一结果不能直接外推到生产CPU策略。

完整decisions/observations/messages/reports与agent累计统计分别位于bypass/L1、deadline/L1。两次入口和研究脚本未读取未来隐藏天气或未知请求。
