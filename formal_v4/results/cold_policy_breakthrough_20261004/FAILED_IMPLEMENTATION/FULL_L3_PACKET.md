# 完整 L3 回放包：只准备，未执行

Root已完成的新student native-control是强同源reference：官方total6004.504542，全部READY动作与components相同，accounted454.603秒。本候选不额外自动重跑control；默认enabled=0保留控制入口，只有显式`--enabled 1 --execute`才运行一次intervention。

`full_l3_package/`已经复制原20个READY文件加`wrapper.py`和package lock，共22文件；20文件及observer.project.json字节未改。实际entry为`python3 -u /workspace/wrapper.py`，harness显式传`TERMINAL_REPORT_BASE_ROOT=/workspace`，并不采用nativeobserver.project的run命令。原wrapper SHA保持`297bec972e2611e1f1f6a4b4aa06f8cb363667e8c9712bd1eebd6f76b58c0278`。

准备器可在root指定的另一主机目录重新复制同样的包：

```sh
python3 prepare_package.py --native-root /path/to/unchanged/READY/release --destination /new/isolated/package --wrapper terminal_report_agent.py
```

本地package lock SHA：`eddb7e6187d125976a817025f9189e2d6a014a8c253732963f9ec41db1ef91fd`。harness SHA：`860a454e22ebd28abeba5b7c0b8f0adc6465cd3ec058363bb1ac75078ad23128`。准备器 SHA：`ad2e1f6e22f95aca697f29d07a081c2f1c45c571a4c00528fa0b5a4f3b5df36a`。

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
  --harness-sha256 860a454e22ebd28abeba5b7c0b8f0adc6465cd3ec058363bb1ac75078ad23128 \
  --package-lock-sha256 eddb7e6187d125976a817025f9189e2d6a014a8c253732963f9ec41db1ef91fd \
  --teacher-source-lock-sha256 eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72 \
  --reference-actions-sha256 9a15a598c604ccc94ce3e9c558a1a9331a116944025283bcf1c8da7a864a5d07 \
  --reference-score-sha256 f83da72c9e9804e3d5fc4362c420ae814d4225dc4f5fb4fca0400781fe6b7bd1 \
  --reference-gate-sha256 CONTROL_GATE_REVIEWED_SHA256 \
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

`run_protocol.py --self-check`的20项syntheticargv/action检查已通过；默认control、固定资源、只有两个ROmount、显式wrapper、单report严格动作parity及变更tail拒绝均覆盖。`FULL_L3_PREPARATION_LOCK.json`记录源码hash、package及零season/Docker/SSH/teacher label调用。没有执行容器或完整赛季，没有改wrapper或其他代理文件。
