# 末夜完整field竞争beam微验证（2026-10-04）

已实现公共信息时间DAG上的完整field重指派beam；**本轮没有找到可做正式续局教师的反转点**，未启动整季新策略、GPU训练、Rhodes任务或线上评分。

| 卡 | 公共末夜state | 当前同fiber A/B | 原native官方分 | 强制原tape官方重放 | 合格反转 | 未来path改变 | 总秒数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| L1 | 8 | 13 | 6362.021539 | 6362.021539 | 0 | 0 | 35.368 |
| L2 | 8 | 14 | 6823.661561 | 6823.661561 | 0 | 0 | 40.730 |

范围：fixed 600s future arcs，3层/宽3，每节点3个完整field候选；当前C/E与target方向prior冻结；最后一夜没有活动REQ，供评分的L1/L2无loss。每个节点重生候选field并对全部目标/16fiber/三program重指派；science best-only与required/Jain在叶上结算。该负结果只涉及16个末夜state与27个局部替代，不能否定全季竞争、更多field交换或宽beam。

公共模型数值与真实终局教师分开：micro文件中的beam差是模型预测；官方分是完整旧tape重放的控制门检。未生成自然replanning教师。未来教师必须在原pinned Linux Python3.12.15/NumPy2.2.6冻结release重现control后缀；本轮Mac NumPy2.0.2只做公共beam和强制动作反馈重构。

首版出现wrapper递归并退出，保留诊断于failed_attempt_01.json。修复前的成功扫描JSON/log保留为*_v1.*；完成state isolation、public pointing offsets、observe rank计数与末夜REQ/loss范围门检后重跑，两卡终分精确重现，27个模型差与v1逐项相同。全catalogue调用原_classify时对不在field的投影产生两条NumPy cast warning；它们的valid均false，所有实际备选assignment均通过官方schema/fiber/整曝光高度门检。没有忽略traceback的成功记录。

代码与方法：research/horizon_contention_probe.py及horizon_contention_DESIGN_ZH.md。最终源码副本在source_snapshot/，summary.json保存冻结release源锁、脚本SHA、运行环境、实际243次choose/6871个assignment选项及预算。微扫描数据源仍是既有READY强native完整公开轨迹。
