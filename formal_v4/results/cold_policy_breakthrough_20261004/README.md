# Terminal report：冻结最后动作前的一次免费结算

本目录是独立候选，现有生产/student/native源码均未修改。Actor只读初始化与实时协议；L3公开truth只在evaluator用于单末动作裁决，不进入wrapper。

实际局部证据：固定L3最后rank992曝光前插入一次report，再原样执行902秒/同program/同pointing/13 assignments。correct report直接+100；science+4.375264122786；Jain+0.028629116623；required/REQ不变；官方末状态runner packet总差+104.403893。末状态恢复不是完整赛季协议回放，不报告为新L3全季策略成绩。

机制区别于已失败的早期免费诊断：触发后不再规划；新增report的反馈只更新wrapper日志与quota，绝不调用原actor的report ingestion。false时原尾部轨迹与belief保持相同；correct时efficiency修复不改变program band，同曝光factor/science非减。Jain负边际由公共score完成证书解析上界约束。

## 文件

- `PRE_TRUTH_PLAN.md`、`PRE_TRUTH_LOCK.json`：读L3 truth前冻结的唯一评估点、参数、动作和来源hash。
- `terminal_report_audit.py`、`public_audit.json`：只取公共等价列，计算四卡最后动作、quota和Jain损失界；不读取factor/quality/prog_mult。
- `evaluate_terminal_report.py`、`terminal_report_evaluation.json`：evaluator-only单末曝光官方积分和prefix ledger核验。
- `official_runner_packet_check.json`、`terminal_packets/`：原官方runner内存函数只恢复已知末状态，control原observe与candidate report+原observe，证明report不动now/rank/旧ledger。
- `terminal_report_agent.py`：通用JSONL wrapper；没有card、rank、日期或targets硬编码。
- `check_terminal_report_agent.py`、`synthetic_guard_checks.json`：16项合成守卫/JSONL检查；未导入native policy、未跑赛季。
- `check_public_initialize_integration.py`、`public_initialize_integration.json`、`public_initialize_integration/`：固定真实L3公开initialize、两次原捕获反馈，实际READY及enabled0/1三条JSONL响应完全相同；不是新环境评分或全季。
- `FAILED_IMPLEMENTATION/`：首次初始化失败的旧wrapper/preparer/harness、旧来源锁及旧22文件包；旧hash和原失败输出目录保留。
- `FULL_L3_PACKET.md`、`FULL_L3_PREPARATION_LOCK.json`：当前修复包与harness的精确来源和root独立回放命令。
- `MECHANICAL_FAILURES.md`：root路径和frozen dataclass的机械错误保留。
- `EVALUATION_MANIFEST.json`、`NATIVE_READY_SOURCE_LOCK.json`、`CANDIDATE_MANIFEST.json`：来源锁。

## 使用方式

独立22文件包已准备，基础代码采用unchanged native READY。Root首个旧包执行在initialize失败，decision为0；旧包保留，当前包已修复正式columns/rows契约，完整运行由root另开输出目录。

```sh
TERMINAL_REPORT_BASE_ROOT=/absolute/path/to/unchanged/native/participant \
TERMINAL_REPORT_ENABLE=0 \
python3 /Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_policy_breakthrough_20261004/terminal_report_agent.py
```

设 `TERMINAL_REPORT_ENABLE=1` 开启。默认关闭；`TERMINAL_REPORT_MIN_WALLCLOCK` 默认10秒。基础planner模式仍用 `GEOMETRY_NATIVE_PLANNER` 的原sweep/union规则。Base root只用于加载现有policy/native库，wrapper不打开任何卡、capture、teacher或真值文件。

只有以下条件均满足才插入一次report：

1. 下一原动作是finish，或wait实际到survey_end，或observe在当前同一night中实际到survey_end；跨日长曝光不算terminal。
2. 自初始化按公开report结果维护的false_count小于免费额度。
3. 当前连续report数仍低于官方cap。
4. 快照含至少10秒剩余wallclock。
5. 公开有效hit score给出的完成比例区间证明，最终assigned targets最坏Jain损失不超过correct_reward。区间不能形成有效界时拒绝observe分支。

原actor先接收上个正常动作反馈并选择terminal action，wrapper保存该动作及原pending。新增report后次轮检查now和observe rank未变，再绕过原actor直接回发深拷贝的动作。若report改变了这些状态，或报告应答缺失，直接终止，避免发送不同尾部。stdout只含正式decision_response；stderr含三个 `terminal_report_*` 事件和完整summary的自定义 `terminal_report` 对象。原actor reports/C/E字段不被新增report污染；新增结果在该自定义对象中报告。

## 已验证与下一门检

16项合成检查覆盖关闭分支动作/调用数相同、correct反馈不重置actor、free false quota、连续cap、wallclock缺失、夜末截断、未知完成比例、较大Jain损失、state_resync、now/rank突变、finish、只插入一次，以及完整JSONL序号/summary。它们不是从初始化native实测parity。

正式公开initialize与两次真实prefix反馈的新增检查已通过；READY、enabled0/1的三条完整JSONL响应逐字相同，也等于原捕获动作。三分支均仅处理固定公开前缀，不调用模拟器；完整snapshot中公开history未保存的其余字段按官方契约恢复，局部Darwin/NumPy2.0.2验证范围在结果中明示。

Root已独立完成新student native-control强同源reference（6004.504542，全部动作/分项同READY），新的intervention门检使用该reference；关闭入口仍保留。若开启多改一个正常动作，拒绝该候选。本子代理没有启动全季、GPU、SSH或网页提交。
