# 自然续局教师：当前锁源与已完成门检

2026-10-04 JST。operative源为revision7，SHA `eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72`。`PRECISION_AND_BUDGET_LIMITS.md`中revision5是原始限制说明，因子近似和小样本限制仍适用；当前锁源以`source_lock.json`为准。

- 完整自然L1控制：6362.021539，host442.043秒；READY逐动作/分项相同，capture与后续反馈完整，teacher_valid=true。
- 初次revision5也重现READY，但stderr截短造成metadata失败；raw/source保存在`archives/failed_revision5.tar.gz`。revision6只做metadata传输微验证；保存在`metadata_revision6.tar.gz`。revision7增加公共候选预测、目标顺序和原生候选效用，未修改READY20文件。
- `archives/revision7_natural_L1_rank64.tar.gz`含完整自然控制原始账本、公共trace、capture、features及门检。raw保留用于后续严格公共前缀；不将计算中的pilot文件加入冻结清单。
- 正在比较同rank64公共状态的control/field/short/long/program，真正继续原native到季末；不是删除重叠曝光后的固定suffix结算。完整对照逐动作一致后才能接受标签。
- 已完成首轮：control6362.021539（403.747秒）、field6383.495675（+21.474136）、short6403.447219（+41.425680）、long6260.242273（−101.779266，其中REQ少100）。四者observe数981/1001/1005/989，required missing均2。program尚在计算，全部五分支完成后才冻结完整组审计。这些是一个实际未来世界的标签，尚非NN得分、条件期望或通用策略。
- 三张其他卡的自然控制、L1后期前缀恢复对照为下一步吞吐/语义门检；320季大批教师尚未启动。

参赛ZIP与正式实分没有改变。后续学生以全公共原始ledger生成有限summary，属于近似表示；原native与官方teacher保留完整历史和结算语义。
