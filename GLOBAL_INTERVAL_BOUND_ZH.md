# 全局区间 LP 与新的公开练习场无条件上界

本研究只使用 `scenarios/dev-reference` 的公开未来真值；正式比赛仍须在线决策。这里的 LP **不预设 64 块天区的访问顺序**。它本身给出 23,402.45 分上界；更有用的结果是把它的时间容量对偶价送进已有的四关键天区等待投影与请求集合穷举，将已审计的无条件界从 22,524.73 收紧至 **22,417.13**。这不是最优值证明。

## 1. 完整候选集上的松弛

已审计的成功曝光起点共有 918,757 个。每个起点 `e=(u,v,i)` 有一次首次曝光变量 `x_e∈[0,1]`，它占用 `[u,v)` 的每个 150 秒容量格，至多一次取得天区 `i` 的科学分包络 `q_e`。开始时有效的 `(e,r)` 请求标签副本共有 46,382 个；其首次贴标变量 `t_er` 满足 `Σ_r t_er≤x_e`，其复访变量 `z_er` 另占用相同容量。首次贴标和复访都可以支持对应请求的访问数，复访没有科学分。总动作列相当于 918,757 + 2×46,382 = **1,011,521**。

每个天区 `Σ_{e:i(e)=i}x_e≤1`；每个时间格的 `x+z` 用量≤1。18 个请求各有获奖变量 `y_r∈[0,1]`。本实例每个请求—天区关系只需一次成功贴标；要求全部关联天区的请求，对每块添加 `y_r≤Σ(t+z)`，RQ0004 要在两块里任选一块，对其合并添加同一式。RQ0015 无有效成功贴标，因此 LP 自动令其获奖值为零。

再添加两族逐路径必要条件：获奖的请求要求对应天区首次完整曝光的起点早于截止；若后期请求 `s` 获奖、其可用时刻不早于较早请求 `r` 的截止，而 `r` 没获奖且评分器判它可完成，则 `r` 必须付失约罚。后者用 `y_s−y_r≤m_r` 和目标项 `−M_rm_r` 表示。两个条件均没有假设真实路径一定领取全部请求。

复访前须先完成该天区首次成功曝光。为了避免为每条复访列展开大量历史列，只在可贴标起点设置累计变量 `F_i(u)`，用相邻时刻的递推等式把所有首次曝光按结束时刻接入，并约束同一时刻的复访量 `Σ_r z_(u,i,r)≤F_i(u)`。共有 44,572 个此类检查点。原题任意合法路径都映成 LP 的可行点：丢掉等待与天气中断动作后，所有完整成功曝光仍不重叠；首次/复访和请求访问满足上述式子。LP 放松了整数性、等待费用、非必然失约罚和其他非负罚，因此其最优值是原题上界。

这个完整 LP 有 **1,056,127 变量、181,537 约束**。GLOP 约 51 秒求到 `OPTIMAL`，浮点目标为 23,402.4475 分。程序把所有对偶价格取成整数微分（每分 10⁶ 单位），然后在 1,011,521 个动作列以及全部累计、请求、罚项上独立重算拉格朗日弱对偶式，向上取整为 **23,402.45 分**。重算式对任意非负时间、天区、标签连接、请求访问、提前首访、失约与前缀不等式价格，以及任意有符号递推等式价格都成立；因此这个数不依赖 GLOP 的浮点目标恰好正确。新增前缀约束没有改变此实例的 LP 最优值，说明这条加强式尚未触及主要缺口。

## 2. 更紧的请求与等待投影证书

将 LP 对偶中逐时间格的非负容量价独立四舍五入到整数分并保存在 [practice_global_interval_prices.npz](results/practice_global_interval_prices.npz)。任何非负容量价都可用于此前已证明的弱对偶投影；重算后的价格不要求继续保持 LP 最优。新的[全量标量审计](results/projected_wait_global_interval_certificate.json)确认 918,757 条成功弧的分数包络违例为 0、3,044,352 个天区/起点组合漏边为 0、12,030 个评分器天气中断实例漏边为 0。四关键天区 `T00018,T00029,T00030,T00031` 与 `θ=134` 整数分下，投影基础界为 23,358.93。

[全 17 个可获奖请求的条件证书](results/practice_request_global_interval_conditional.json)进一步要求获奖所需天区在相应截止前首次完成，并处理末个请求的最早终止时间，得到 22,417.13。最后用修改后的 [请求全集穷举程序](bounds_request_unconditional.py)枚举 `2^17=131,072` 个获奖集合、196,608 个 RQ0004 分支；对于必然过期且评分器认为可完成的未获奖请求扣除失约罚。新旧审计证书按同一价格文件 SHA-256 交叉核对，全请求分支与独立条件证书逐整数分一致。最终[无条件证书](results/practice_global_interval_unconditional.json)的最大分支仍是领取全部 17 个可获奖请求，故公开练习场任意合法决策表都满足

**总分 ≤ 22,417.13。**

当前本地回放可行解为 21,016.570923，未闭合差距 1,400.559077；已知榜首 21,104.12 距此界 1,313.01。全局 LP 的单独界较松，是因为忽略了昂贵的可避免等待与整数选择；较紧的最终界来自其容量价与精确保留的四块完成状态、天气中断、等待、请求截止的组合。

## 3. 复算

```sh
.venv-solver/bin/python bounds_global_interval_lp.py \
  --out results/practice_global_interval_lp.json \
  --price-out results/practice_global_interval_prices.npz
python3 bounds_practice_projection.py \
  --prices results/practice_global_interval_prices.npz \
  --key-set T00018,T00029,T00030,T00031 --theta-cents 134 --audit \
  --output results/projected_wait_global_interval_certificate.json
python3 bounds_request_projection.py \
  --prices results/practice_global_interval_prices.npz \
  --out results/practice_request_global_interval_conditional.json
python3 bounds_request_unconditional.py \
  --prices results/practice_global_interval_prices.npz \
  --projection-certificate results/projected_wait_global_interval_certificate.json \
  --conditional-certificate results/practice_request_global_interval_conditional.json \
  --out results/practice_global_interval_unconditional.json
```

全量标量审计是数值穷举核对而非浮点函数的形式化误差证明；最终整数分的弱对偶加总和请求集合穷举是严格整数运算。上述上界只说明离线已知天气练习实例的最优分不超过该值，不能直接作为正式未知天气策略的可实现成绩。
