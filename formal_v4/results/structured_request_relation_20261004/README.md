# 独立请求关系 adapter（2026-10-04）

实现位于 `research/structured_request_relation.py`。它只接收公开 initialize 和已经送达的 capture：每个活动 request 一个节点、每个 request-target 成员一条关联、每个候选的公开 assignment/时间窗/factor 预测。ID 只作关联键，没有 ID 数值特征。raw ledger 与真实 factor/未来反馈/标签均不读取。

现有五个学生模块、policy_iteration 教师与官方 v4 源码没有修改，完整前后 SHA256 在 `report.json`；五学生模块还与原碰撞证明的锁源逐项一致。未读取真实教师标签、训练、运行新季节或改变部署选择。

必要检查运行方式：

```sh
python3 formal_v4/results/structured_request_relation_20261004/check_adapter.py
```

同一固定碰撞的 request 奖励为 `{ab,cd}: control=100, field=0` 与 `{ad,bc}: control=0, field=100`。新增成员关联实际区分它们。目标、请求和成员共同重排后，按关联键对齐的局部池化数值在1e-12容差内一致；任意重命名所有 target/request ID 后，所有数值节点与边特征完全相同。空请求/空账本、重叠请求的不同公开完成状态、夜末实际终点裁剪、不同请求阈值的支持矩阵、非法成员/重复成员/矛盾完成数均检查通过。

`pool_members` 保留 request 轴：先在每个请求内部汇总目标与动作标记，再由后续小模型应用局部门槛，最后才汇总不同请求。`conditional_completion_counts` 中未来支持必须来自公开历史与当前动作条件下的预测器；不同 threshold/deadline/issuance 应使用 request-target 矩阵。各成员完成概率之和仅是期望完成数，把这个和过 quota 门槛不能当作精确请求完成概率。本探针的0/1支持只是显式固定 π“下一曝观察b”的合成机制。

root 只读64个冻结 control 公开 capture 的覆盖统计：L1/L2各16训练状态，只有4/32状态有活动请求，其中仅3个仍有请求缺口。这不足以支持复杂 GNN 或 request 预测泛化声明。此版本只供之后版本化特征设计，不替换当前固定学生比较，也没有真实提分证据。

## 原特征器空账本异常的最小修复建议

原 `research/structured_student_features.py:232`：

```python
eligible = np.array([issued <= exposure_times[int(r)][0] and exposure_times[int(r)][1] <= deadline for r in lr]) & lv
```

账本为空时列表为空，`np.array([])` 默认 float64，故与 bool 的 lv 做位运算时抛 TypeError。最小补丁只增加 dtype：

```python
eligible = np.array([issued <= exposure_times[int(r)][0] and exposure_times[int(r)][1] <= deadline for r in lr], dtype=bool) & lv
```

checker 使用同一公开 fixture 的空账本先重现异常，再仅在隔离内存模块中应用这个关键词，确认原构建器恢复；原文件字节未改。非空账本原表达式本就生成 bool，显式 dtype 不改变其逻辑，不需添加特殊 rank0 分支或伪造历史。

`collision_relation_outputs.npz` 保存两拓扑的实际 adapter 节点、关联及动作边。`report.json` 保存检查、固定 fixture SHA256、源码来源和当前覆盖限制。
