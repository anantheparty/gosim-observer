# L1/L2/L4：复用真实 READY reference 的一次 intervention

本包只新增`run_remaining_cards.py`和此说明/来源锁。现有wrapper、preparer、L3 harness及22文件运行包全部保持冻结。Root回报完整L3已通过全部门检：6004.504542→6108.908435，净增104.403893；只新增一次report，其他1141个动作完全相同，454.047秒。其receipt在远端`/tmp/geometry_native_20261003/results/terminal_report_20261004/repaired_L3/gate_result.json`；本包不覆盖或重跑L3，也不把公开卡改进称为正式均分。

## 已核对的真实 reference

下列文件均已在本地核对。运行时每卡独立锁定6个reference文件（actions、score、workflow、decisions、messages、原READY gate），以及natural-control交叉receipt和其actions/score。精确SHA在`REMAINING_CARDS_SOURCE_LOCK.json`与harness常量中。

| 卡 | 真实READY总分 | decision requests | observe actions | cpuset | reference相对目录 |
|---|---:|---:|---:|---|---|
| L1 | 6362.021539 | 1073 | 981 | 20,21 | `protocol_gate_remaining/L1` |
| L2 | 6823.661561 | 1231 | 1107 | 22,23 | `protocol_gate_retry/L2` |
| L4 | 5974.281941 | 1064 | 928 | 16,17 | `protocol_gate_retry/L4` |

远端reference根目录为`/tmp/geometry_native_20261003/results/geometry_native_20261003/`。对应交叉receipt为`/tmp/geometry_native_20261003/results/policy_iteration_20261004/natural_control/L*/rank_0064/control/gate_result.json`。

原READY gate没有schema且`passed=false`/`exact_score_match=false`，比较的是历史Mac/Phase期待6378.655366、6808.224288、6078.613462。本包保留这个原始失败状态，没有改写为true。可用性证据另行核对：完整survey_complete、exit0、无traceback、900秒内、实际native入口、固定镜像、原20文件source_sha256全部一致；workflow/score/各输出哈希和动作/decision计数自洽。natural-control三张通过receipt的READY动作、总分及分项parity均true，其actual actions/score字节与上述reference完全一致。这些仅作来源证明，没有读取teacher target/terminal labels或observations factor CSV，也没有重跑control。

## 固定运行来源

| 来源 | SHA256 |
|---|---|
| 新remaining harness | `abb75757f3b89ae852894f4a1a7016651480b50b8e4e719f877745cef153e091` |
| 冻结L3 harness | `0990cc8c4d00dab936468d9d5d921c5cca6990a86cfa5f235b914696c1557002` |
| wrapper | `59b60a48ba3dfb7fd0cefe0e15734e20d151c0779112449ea35d2cec10f753f3` |
| package lock | `9d488dda33db7448106d0b32fd25c7ab500e037ae9c3fd44e513fdd61ae7bc97` |
| 官方/READY source lock | `eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72` |

新工具按SHA导入冻结L3 harness，只复用其已成功运行的container lifecycle、immutable ID owned cleanup、动作/分项/消息/末动作冻结门检；不修改原文件。`--l3-harness`支持root远端已经存在的`repaired_run_protocol.py`。每卡只运行enabled=1，不再产生control季节。

默认只plan，**没有`--execute`就不会调用Docker**。完整plan需读取目标主机已有NumPy2.2.6 deps metadata并锁定全部依赖字节；本地未伪造Linux依赖或reference。

示例L1命令如下；L2/L4只须按表修改`--card`、`--reference`、`--parity-receipt`和全新`--out`。cpuset默认按上表固定，其他CPU组合会拒绝。Root执行前应确认这些CPU对仍空闲。

```sh
python3 /tmp/geometry_native_20261003/results/terminal_report_20261004/run_remaining_cards.py \
  --card L1 \
  --project /tmp/geometry_native_20261003/results/terminal_report_20261004/repaired_release \
  --dependencies /tmp/geometry_native_20261003/.deps \
  --kit /tmp/geometry_native_20261003/upstream/gosim-observer-examples \
  --reference /tmp/geometry_native_20261003/results/geometry_native_20261003/protocol_gate_remaining/L1 \
  --parity-receipt /tmp/geometry_native_20261003/results/policy_iteration_20261004/natural_control/L1/rank_0064/control/gate_result.json \
  --official-source-lock /tmp/geometry_native_20261003/results/policy_iteration_20261004/source_lock.json \
  --l3-harness /tmp/geometry_native_20261003/results/terminal_report_20261004/repaired_run_protocol.py \
  --out /tmp/geometry_native_20261003/results/terminal_report_20261004/remaining_L1 \
  --harness-sha256 abb75757f3b89ae852894f4a1a7016651480b50b8e4e719f877745cef153e091
```

最后增加`--execute`才启动该一张卡。任何已存在out都拒绝；仅支持L1/L2/L4，不接受L3。每次owner hash绑定card、独立out、CPU对及全部inputs，container name带该card/owner。结束/host990秒timeout时先保留退出/OOM/error状态，仅清理owner匹配的immutable container ID，绝不清理别人的容器。

镜像固定为`python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016`；2CPU、2GiB、900秒official wallclock、network=none、readonly根文件系统。仅两个只读actor输入mount：冻结package和NumPy2.2.6 deps。Entry仍为`python3 -u /workspace/wrapper.py`、base root仍为`/workspace`，显式开启report；不挂kit、reference、receipt、truth、captures或host out。Host只用官方runner正常评分，并对kit/card文件做前后opaque字节hash，actor不接触这些文件。

## 零次或一次插入的严格门检

- 通用：完整official protocol、真实card scenario、900秒内、容器退出0/owned cleanup、所有host输入前后hash相同、无traceback、仅一份完整自定义terminal_report summary、public-only声明、decision bookkeeping一致。
- **0插入**：guard可能拒绝安全条件不足的末动作；enabled必须仍为true、terminal events必须空。所有action字节、decisions CSV字节、public messages字节，以及完整official score对象和全部分项都必须等于真实reference。不能把改变正常动作但没report的轨迹当control。
- **1插入**：直接调用冻结L3成功门检；删除唯一report后所有actions与READY完全相同，report只在原最后动作前。prefix/前驱/冻结末动作/释放hash匹配；决策字段除新增行和decision_id外相同；report duration0、公开now/rank不变、observe数和loss invalidations不变。唯一新增official report_result与actor事件/summary一致，其余公开messages完全相同。
- correct：真实report reward/repair结果成立，同冻结末曝光science、required、REQ非减，完整official total满足公开Jain保守净增下界。false：report_delta严格0，完整total和全部components必须完全相同。完整季节得分只读新的官方score_report，不能用末packet近似数代替。

任何门检或审查异常都保留gate_result/driver/原输出且passed=false；不重试或自动补跑。

## 本地准备验证范围

`--self-check`的24项小检查已通过，覆盖三卡card/CPU、冻结entry、两ROmount、资源/镜像/network、拒绝共享L3 CPU对以及0/1动作门检。另用三张真实reference输出加**明确合成**的零插入summary和mock host退出/cleanup，直接测试完整零插入verifier：三卡均通过，随后各改一条public message均被拒绝；这6项是门检测试，不是新actor或环境回放。

可只读复核现成reference：

```sh
python3 run_remaining_cards.py --self-check
python3 run_remaining_cards.py \
  --review-reference-root /Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/geometry_native_20261003 \
  --parity-root /Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/policy_iteration_20261004/natural_control
```

此次子代理新season/Docker/SSH调用均为0，teacher labels读取为0。旧FAILED_IMPLEMENTATION、旧tar/job、L3 gate/source/运行包保持原封锁状态；三卡真实新结果由root另开目录执行。
