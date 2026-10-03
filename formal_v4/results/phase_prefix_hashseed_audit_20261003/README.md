# α 第25次动作分歧的公开前缀重建

## 已确认的共同输入

旧Phase与新portfolio α，第一个动作差在index24，即第25次observe，simulation时刻 `2026-10-05T01:59:55Z`。

- 前24个actions语义逐项相同；前24条decisions CSV逐字段相同。
- observe_index0..23的351条observations逐字段、逐行顺序完全相同。
- 截止上述时刻的9条messages逐项完全相同，包括原始顺序。
- 官方 `v4_runner.py` 的last_result.hits只传target_id与round(score,6)。因此上述CSV足以重建这部分反馈；不能把未传输的raw factor/quality当作分歧解释。
- 这个前缀全部是observe，没有report、REQ、resync或wait-until展开，协议重建没有这些阶段的歧义。

六个public文件重建initialize，typed inventory在 `initialize_inventory.json`：10000行，四个数值target列为float，required为bool，ID/class为str。geometry使用官方六位round规则。旧线上实际initialize JSON和内存state未归档，因此不能直接比较旧run的实际初始化type/值与这些public重建结果。

## 可重复重建

`research/phase_prefix_hashseed_audit.py` 从冻结原 `observer_phase_gpu.zip` 解包原算法、读取原policy_config。构造原ModelGPUPolicy与实际CPUPhaseSpatialPlanner，不使用portfolio分支重写算法。remote runtime禁用；仅重建本队公开反馈。每步记录数学state/env hash、416个exact候选结果hash、phase粗筛centers/pools/durations/rates hashes与最后动作。

四个PYTHONHASHSEED=0、1、2、17中，前24动作全部精确重现，没有强制重写pending。第25动作均完整重现**新portfolio**：

```text
pointing = (82.4323591, 54.706859)
duration = 60
program = DARK
15个assignments与新portfolio完全相同
```

25步state/env/exact/coarse hashes跨四个seed全部一致。NEXT state SHA `2ca195a570cd709d4fef171a5d70bb7050a65d18f7b789da20330c27528669e6`；env SHA `45ad281fcf681b2713536da2727e8e81142cd11bbb68592e61da5a5fb2a06b91`。

`variant_comparison.json` 保存每个控制变体的逐步比较。

## 控制变体

- snapshot.remaining从900改为31：outer planning budget确实变化，但CPU fixed-work覆盖它；25步数学state/env、候选hash、动作均相同。
- 真实OptionalModelGPUTransport构造器及原check/request/chat_packets执行；只将_post替换为离线TimeoutError，不进行网络请求，使用公开dummy凭据。与DisabledFactory相比25步数学hash与动作相同。
- 本机NumPy2.0.2与临时隔离NumPy2.2.6：完整前24动作与NEXT动作、25步数学hash也完全相同。没有改系统NumPy或生产依赖；临时目录仅用于审计。
- 在用户自有Rhodes1的Linux/Python3.12.3/NumPy1.26.4上用同一公开重建输入与冻结算法执行，前24动作和NEXT再次完全重现新portfolio；NEXT的数学state hash与Mac相同，但中间部分步骤与candidate数组hash存在跨平台浮点差异，不能声称全程逐位相同。执行使用临时目录，结束删除，没有触碰远端服务或使用GPU。

源码上transport只是保存initial引用、复制remote config并创建网络状态；health以空payload构包、不写initial/Policy config/planner，也不修改NumPy精度。真实health的socket调度与所有可能allocator/platform差异不在这个mock gate的全称覆盖范围，但该gate排除了其正常构造与失败逻辑作为这里可重复的数学原因。

Python set没有在此复现中引出顺序差异。Policy terrain对每个方向乘同一0.05，重叠次数固定；Spatial的directional prior在env中明确false；大量set只用于membership。不能依据“未设置HASHSEED”直接宣布它就是根因。

## 两动作的客观冻结值

共同前缀重建得到的NEXT同一frame：

- 新动作的selected exact rate：**0.8924053971537739**；即便基础400个候选阶段，best rate已达 **0.8900243331883023**。
- 旧动作 `(30.9945829,148.7807177),97s,DARK` 的原assignments冻结rate：**0.554785250500924**。
- 将旧command加上同一已估offset后，用全useful catalogue重做exact duration/program优化，得到 **0.5547852505009242**，仍为97秒。

这些rate包含求解器的required/uniformity/urgency项，是当前冻结模型的utility/秒，不是官方科学分或全季收益。两动作差约61%，不是最终候选的近乎同分舍入tie。新Phase的多个pointing虽有完全相同的rate平台，但它们均在高rate新field附近；这不能解释低rate旧field成为赢家。

## 当前结论及未解决项

共同public前缀支持新NEXT动作的稳定数学复现。这个分歧没有在hashseed、remaining控制、transport正常失败逻辑或本机两版NumPy中复现。旧run的内部state/frame或所访候选集合必有至少一项与当前重建不同，但旧输出没有这些hash，尚不能判断在哪层，也不能声称根因已经确定。

不同硬件的浮点库、旧实际initialize/config路径/运行代码绑定等仍需要实际证据。不能把“相同source标签”当作已记录了运行时module/config hash；也不能把未验证的隐藏数据问题当结论。后续应在受控candidate中将实际module路径与source SHA、读取的config SHA、initial typed hash、数学state/env hash、base/phase candidate hash写入stderr，以确定第一处差异。

没有新线上评测、生产/ZIP更改或Git index操作，没有读取隐藏truth。重建输入文件与全部变体trace仅用于公开输出离线审计。
