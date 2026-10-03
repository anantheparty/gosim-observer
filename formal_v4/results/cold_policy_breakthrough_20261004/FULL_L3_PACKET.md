# 完整 L3 回放包：只准备，未执行

Root已完成的新student native-control是强同源reference：官方total6004.504542，全部READY动作与components相同，accounted454.603秒。本候选不额外自动重跑control；默认enabled=0保留控制入口，只有显式`--enabled 1 --execute`才运行一次intervention。

`full_l3_package/`已经复制原20个READY文件加`wrapper.py`和package lock，共22文件；20文件及observer.project.json字节未改。实际entry为`python3 -u /workspace/wrapper.py`，harness显式传`TERMINAL_REPORT_BASE_ROOT=/workspace`，并不采用nativeobserver.project的run命令。正式initialize目录格式修复后，当前wrapper SHA为`59b60a48ba3dfb7fd0cefe0e15734e20d151c0779112449ea35d2cec10f753f3`。

准备器可在root指定的另一主机目录重新复制同样的包：

```sh
python3 prepare_package.py --native-root /path/to/unchanged/READY/release --destination /new/isolated/package --wrapper terminal_report_agent.py
```

本地package lock SHA：`9d488dda33db7448106d0b32fd25c7ab500e037ae9c3fd44e513fdd61ae7bc97`。harness SHA：`0990cc8c4d00dab936468d9d5d921c5cca6990a86cfa5f235b914696c1557002`。准备器 SHA：`708a58e7eb8b1e05a892a16912e97c3b3f334a57201db2d21d3c94a67c7476e4`。

以下命令路径由root替换。省略`--execute`只检查来源并打印command plan，不调用Docker。reference必须是新完成student native-control的完整输出目录，包含actions/score/workflow/decisions/messages；`--reference-gate`指向其已通过的control gate。harness将核对该receipt中的actions/score SHA和三项READY parity，再对全部使用的reference文件锁hash。没有读取teacher labels。

```sh
python3 run_protocol.py \
  --project /path/to/new/package \
  --dependencies /path/to/existing/numpy-2.2.6/deps \
  --kit /path/to/official/gosim-observer-examples \
  --reference /path/to/completed/student-native-control \
  --reference-gate /path/to/control_gate_result.json \
  --teacher-source-lock /path/to/policy_iteration_20261004/source_lock.json \
  --out /new/isolated/terminal-report-L3-output \
  --harness-sha256 0990cc8c4d00dab936468d9d5d921c5cca6990a86cfa5f235b914696c1557002 \
  --package-lock-sha256 9d488dda33db7448106d0b32fd25c7ab500e037ae9c3fd44e513fdd61ae7bc97 \
  --teacher-source-lock-sha256 eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72 \
  --reference-actions-sha256 9a15a598c604ccc94ce3e9c558a1a9331a116944025283bcf1c8da7a864a5d07 \
  --reference-score-sha256 f83da72c9e9804e3d5fc4362c420ae814d4225dc4f5fb4fca0400781fe6b7bd1 \
  --reference-gate-sha256 761da88adaf431d8767c23b09347158db5093bf67bb5929f08e2d23358f91071 \
  --cpuset 18,19 --enabled 1 --execute
```

容器固定2CPU、2GiB、900秒官方wallclock、cpuset18,19和既有pinnedPython镜像digest；依赖metadata必须NumPy2.2.6，完整依赖字节前后锁。network=none，仅两个只读actor输入mount（package/deps），不挂kit、reference、truth或host结果目录；actor日志由正式runner收集。没有`--rm`，执行结束或990秒host timeout均核对本次owner label，再按immutablecontainerID清理，保留退出/OOM/error证据。遇到其他owner不删除。

完整结果门检包括：

- 无超时/traceback，container正常退出、owned cleanup、正式survey_complete、900秒以内；所有host输入前后hash相同。
- 恰好一份完整summary，`terminal_report`的enabled及reads_truth=false匹配；decision计数=原base次数+新增report，三个事件与summary一致。
- control开启0时，actions字节、total和五分项全部同READYreference。
- intervention时恰好增加一次report；只删除该单一位置后，所有actions对象与READY完全相同；它位于原最后动作之前。整段prefix与前驱动作hash、frozen末动作及releasedhash逐项一致。
- report的公开now/rank不变；删除新增report的decisions行并忽略decision_id后，其余行全部同reference；原observe数与loss invalidations不变。
- 恰好一个新增官方report_result，其他public messages与reference相同；官方correct/false/score_delta与actor事件/summary及report分项一致。
- correct时科学、required、REQ非减且实际完整total达到公开下界；false时免费report_delta=0，完整total/components必须与reference相同。

实际完整total只读新的官方score_report.json，并与reference计算差；**没有把单末packet的104.403893或估计6108.908435预设为完整赛季精确值**。未通过任何门检都保存失败。

`run_protocol.py --self-check`的20项syntheticargv/action检查已通过；默认control、固定资源、只有两个ROmount、显式wrapper、单report严格动作parity及变更tail拒绝均覆盖。`FULL_L3_PREPARATION_LOCK.json`记录源码hash、package及零season/Docker/SSH/teacher label调用。本子代理没有执行容器或完整赛季；wrapper仅修复公开columns/rows契约，其他生产/代理文件未改。Root的旧包首次尝试在initialize即失败；详情见下节。

## 首次实现失败保留与真实公开入口复核

Root首次enabled_L3运行在0.399秒initialize失败，decision为0：旧wrapper把targets dict误作list。旧代码、旧锁和旧22文件包保存在`FAILED_IMPLEMENTATION/`；原wrapper SHA `297bec972e2611e1f1f6a4b4aa06f8cb363667e8c9712bd1eebd6f76b58c0278`、原preparer SHA `ad2e1f6e22f95aca697f29d07a081c2f1c45c571a4c00528fa0b5a4f3b5df36a`、原harness SHA `860a454e22ebd28abeba5b7c0b8f0adc6465cd3ec058363bb1ac75078ad23128`、原package lock SHA `eddb7e6187d125976a817025f9189e2d6a014a8c253732963f9ec41db1ef91fd`及原preparation lock SHA `c42aac5d3af3e3abd11fb150f0e308bed34a3e49a517e06b069b3b72baf936b5`均保留。失败锁SHA `e7a0fa0ff07fd8a72187e50e5ba69d50b2bda76b59feaae2ab953ddf4ec96a32`。

根因修复按官方workflow和READY planner的同一列索引读取targets.columns/rows，8,700个目标全部构造成功。触发规则、reward/quota/Jain模型、冻结与释放规则、stdout协议和无initialize ACK约定均未改变。`initialize_catalog_fix.diff`是wrapper全部改动。

`check_public_initialize_integration.py`用固定`L3_initialize_public.json`及既有natural-control公开capture的前三行public_history（first action + first two feedback），调用官方V4Workflow静态envelope构造器，分别启动实际READY、wrapper enabled0和enabled1。每个进程只走三次decision，未启动runner或完整季节。三份stdout JSONL完全一致；前三动作均与原捕获一致；guard入账ranks0/1，14/13个public hit；base summary除计时字段外一致，完整自定义terminal_report summary正确。

公开history本身只保存now/rank/last_result/new_messages/action，完整snapshot中的survey_end/latest bulletin/latest forecast/public running_total/active_requests由同一公开prefix按官方runner契约恢复；所有分支同设900秒测试wallclock，六位score构造running_total。没有伪造targets目录或真值反馈。该检查验证真实初始化、两次反馈解析和JSONL入口，局部环境Darwin/NumPy2.0.2仍不能证明Linux/NumPy2.2.6完整赛季parity。新的完整回放须由root另开输出目录，旧失败目录与本地旧tar/job/run_source_lock保持历史证据，不能拿旧tar作为修复包。
