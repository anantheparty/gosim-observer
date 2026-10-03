# 跨时段联合 fiber 竞争：独立推导与验证（2026-10-04）

## 独立推导（先于阅读 portfolio / objective_graph）

正式 runner 的动作从当前 now 连续推进 duration；曝光在夜末截断；16 个格子的命中只在起始时刻判定，之后随赤道坐标跟踪。各目标终值是所有合法曝光中 c_i 的最大值，required 和请求使用另一个 max factor 账本。因而当前动作同时改变 (1) 下个决策的真实起始时刻，(2) 各目标 best 向量，(3) 每个未来格子中的有价值候选集。把单目标的未来最好小时转成价格不能描述竞争：两个有相同未来质量峰值的目标可能一直落在同一个 fiber；当前完成其中一个能释放未来格子，完成另一个则不能。

时间 DAG 的一条弧是完整 field 动作 e=(start,end,center,program,assignment)。一个节点包含当前时刻、科学 best 向量、完成 factor 保守向量、请求窗口账本和已获消息。目标 i 在弧 e 的贡献是 max(0,c_ie-best_i)，而 max factor 完成阈值与科学贡献需要分开。相互冲突有两层：同一时刻只能选一条覆盖时间的曝光弧，同一弧同一 fiber 只能分配一个目标。选择当下弧 A/B 后，必须从各自真实新时刻重新生成并重新分配未来弧；后缀 tape 固定再删重复会忽略释放 cell 后的替换与时间平移。

可执行新机制：对生产候选生成器返回的前 K 个完整动作，从同一真实前缀状态分别强制第一动作，再让原策略真实 replanning 至夜末或季末。以终局官方 scorer 差作为教师，保留每分支的重新分配替代链。低成本第一步找季末窗口（未来短且 known geometry 强）：穷举某时刻同 cell 的 A/B assignment，前缀不变，分支均真实续局；若即时排序与终局排序反转，检查释放的未来 fiber 导致哪个 C/D 被接替。可扩展学生是结构化 action critic：输入 current action、未来 sampled full-field cell occupancy graph 与 best 向量，输出续局 value；GPU batch 对象为 [branch,state,future-time,pointing,target] 的质量和 cell assignment，以及 [branch,scenario] replanning fitness，先测 CPU 续局的实际瓶颈再决定 GPU。

待去重：已有研究中是否包含真实 replanning 的 action branch 终局教师，以及跨目标未来同 cell 的结构特征。若只是单目标 hour reservation、即时 rate 几何全局搜索或固定 suffix tape 删除重叠，则不等价。

## 去重结果与实际实现

`objective_graph_DESIGN_ZH.md` 的第4节已有竞争图/真实replanning教师的概念；本轮的新工作是实现公共信息有限时间DAG上的完整field重指派beam，并对强native轨迹实际构建A/B干预候选。旧 action critic 的固定suffix删除标签没有复用。beam每节点重新调用冻结native候选生成器；随后固定该弧时长，对全部可落入field的目标、16个fiber和三个program重新指派。更新science max和保守factor，叶上精算required/Jain。每个公共研究frame和每个beam节点独立复制planner，避免先运行的分支影响下一条分支或原前缀。

预声明有限范围：L1/L2各最后一夜8个等距rank，当前pointing/program/duration均保持；从同cell备选中取即时模型损失在[−.20,.01]内的前2项。beam未来弧固定600秒、宽3、深3、每节点保留3个完整field候选，双方在同一1800秒或夜尾结束。预声明的教师点须即时差≤0而beam差>.05，并出现未来争用路径改变；按最早rank/fiber/target ID选点，不按truth终分峰值挑选。

最终L1 13对、L2 14对，**零反转，零未来路径改变**。自然喂入公开反馈、强制原动作tape的官方完整回放逐动作一致，终分分别精确重现6362.021539/6823.661561。状态隔离修复后27个beam差与修复前逐项完全相同；该一致只是此有限样本的结果。没有合格点，因此没有启动真实replanning教师或新整季策略实验。

## 模型适用范围与下一步门检

- 固定600秒未来弧是有限减少模型，没有完整连续时长/时间DAG。当前弧保持原始短时长。
- 未来C/E和target方向prior冻结在当前env；公共airmass/月亮/目标sky geometry随真实future时间重算。没有未来反馈的belief更新或未来公告分支。
- 本轮只取末夜且snapshot的active_requests为空；官方完整结果证明已知两条REQ截止均在末夜之前。beam本身不实现一般k-of-n request gate。
- beam不预测未知未来回溯loss；提供教师的L1/L2 stress关闭、全季失效0，这是此例的适用范围，不能推广到gamma/delta。
- 叶上的factor是预测raw/safety，不是由未来公开feedback反演得到的严格完成证书。
- 当前同cell单target替代局限了扰动强度；没有扩搜其它晚或用别卡救参数。该负结果仅涉及16个末夜state、27个局部替代，不否定全季竞争、完整field交换或更宽beam。

所有微扫描在Mac Python3.10/NumPy2.0.2上执行，强native动作tape来自Linux pinned image。强制整个旧tape只能证明官方计分/反馈重构；它不是Linux源策略自然续局的控制。真正teacher必须在原pinned Linux Python3.12.15/NumPy2.2.6/冻结release中，由同prefix恢复源policy，control逐动作重现原后缀；两分支再按各自真实feedback重新规划至季末。当前没有生成这种标签。

## GPU批对象与实际成本

可批量的对象已明确：每个(public-time, branch)的完整候选center与所有target之间的fiber分类矩阵、[field,program,target]的科学overwrite增量/threshold效用，以及[branch,field,fiber] maxima。不同branch的best向量会改变winner，不能把GPU任务降成当前候选即时rate扩搜。实际42个beam包含243次完整候选生成、6871个保留assignment选择，约38.51秒；原前缀官方重放总用时约76.10秒。当前这些A/B没有改变任何未来path，尚不能据此形成有效结构化NN教师；没有需要占PRO6000的大batch任务，未使用GPU或Rhodes。独立planner深复制与native候选生成在公共beam循环内顺序进行，未来只有候选/field batch充足且教师存在时，才有理由拆测GPU kernel和真实往返。
