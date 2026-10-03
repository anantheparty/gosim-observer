# 有真实对偶价格的有限列生成门检

只用公开卡、自己的下载输出和条件质量区间；CPU 研究，无网络/GPU choose。原READY主问题/源文件未修改。新脚本 `research/season_column_dual_audit.py` 在隔离进程构造相同池，拦截第一次 solve，在写旧输出前返回；所有新输出在本目录。

## SciPy最小化符号与紧凑max消元

原LP最小化负奖励。时间弧流列为 start节点+1、end节点−1。令 π 是 `linprog.eqlin.marginals`；令 ρ/ν/η分别是 target winning simplex、required coverage、REQ target coverage 的 `-ineqlin.marginals`，均非负。

对新的共享指向曝光列 c，每个 target 科学 winning 变量 z受 z≤x 和同target Σz≤1 限制。消去新局部 z≤x 对偶后，其贡献为 `max(0,s_ic−ρ_i)`。required/REQ完成 incidence 分别加 ν和η；REQ必须同target distinct、曝光整个包含 issued/deadline。

```
value[d,p,i] = max(0, science[d,p,i] - rho[i])
             + required_nu[i] * (factor[d,i] >= .5)
             + sum(request_eta[r,i] * eligible_complete_in_request_window)
time_arc_cost = scipy_pi[end] - scipy_pi[start]
reduced_profit = sum(chosen_unique_fibre_target_values) - time_arc_cost
```

若使用“start potential−end potential”表示时间成本，必须定义 potential=−SciPy marginal；不能漏这个符号转换。program由整条列共同声明，不能每fiber独立选program。

为得到可定价的时间势，本脚本去掉 flow/winner 的冗余upper=1：DAG单位流已蕴含每弧≤1，target simplex已蕴含每winner≤1。保留required/REQflag上界、δ固定前缀bounds。如果保留冗余弧上界，used arc的bound dual可能吸收价格，使未经校验的时间势不适合新增无上界列定价。

## 已核验的数值

- α：1386列，200个非basic；所有未固定列的最大reduced profit约2.15e−13，nonbasic最大0；完整KKT stationarity残差约2.15e−13。
- δ：1117列，65个非basic；nonbasic及所有未固定列最大约1.42e−14；保留原552前缀，不允许其前的新列，也不跨原report。
- 对150个现有指向/同时间节点组合，按ρ/ν/η逐fiber重选target。top20列加入后，α乐观受限LP目标提升40.69355554，δ提升35.77397740。此前最强单列虽有正reduced profit，单独加入却不涨：旧dual被切掉后存在另一同值dual/退化步。**正pricing不等于已经取得严格primal提升**；batch重新解LP后才报告有限LP变化。
- α同一20条assignment列再次用原quality lower、共同DARK的保守program下界重建，301个assignment经官方glass/fiber检查。完整科学max+required+REQ MIP optimal gap0，重算真实均匀度后净变化约9e−13，未选新增列。没有报告为新策略提分。

## 价格输入与限定

每卡 `pricing_duals.json`：`target_order`对应公开目标顺序；`rho[N]`、`required_nu[N]`、`request_eta[R,N]`；完整`requests`；`time_nodes`是UTC秒；`time_potential`是上面的SciPy π；`admissibility`保存固定resync开始限制/report时刻。

本门检只在已有时间节点间定价，没有插值π。若新端点不在图里，应先显式增节点/拆等待弧并重新求势，或使用确实满足等待边单调性的对偶扩展并标明范围；不能把普通线性插值当作已求新图对偶。

当前pricing用质量区间upper与最高可能program倍率，所以是条件乐观模型。不是原隐藏天气，不保证program实际匹配，也没有恢复hidden pointing offset。新增指向使用声明零offset及>.03°glass余量，方向轨迹满足参考几何域clear；所有质量/几何/E/report/validity假设沿用固定原场景模型，不新增无条件保证。未列出的连续几何/time/duration reducedcost仍无全局界。

文件：`audit.json`含KKT/目标残差、LP变化、保守MIP分项；`priced_batch.json`保存动作/指派；`conservative_schedule.json`是下界MIP路径（如净得分无改善应继续使用原incumbent）。全为研究产物，没有平台评测分数。
