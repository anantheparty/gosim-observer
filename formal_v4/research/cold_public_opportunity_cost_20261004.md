# 全剩余公开日历上的科学机会价格（阶段 1，2026-10-04）

这是有限确定代理模型的研究。当前没有新生产策略、正式完整季节或线上收益。所有本轮文件在 `results/cold_public_opportunity_cost_20261004/`；旧 sealed L4、正式未来 truth、旧教师标签不读取。官方生成器可以写出新世界 truth，但演员及本轮收益比较只接 public/config 初始化。

## 已有工作与本轮差异

已完整阅读 `ALGORITHM_PORTFOLIO_ZH.md`、`cold_horizon_opportunity_policy_20261004.md` 及其 `CONTRACT_RESULT.json`、`cold_common_exposure_control_20261004.md`、`cold_quality_window_control_20261004.md`，并读取官方 scorer/runner/fiber map 与当前冻结 sparse-exact-fault ZIP。共同曝光研究已有 winner-edge MILP、四小时共同续局和空曝光损失分解；这里不把这些称为新发现。新内容限于精确 breakpoint 层 LP 的消元证明、全剩余公开日历缓存图、从 target/time dual 导出原即时候选外的当前 field/duration，以及少量 first-action 的共同 LP recourse。

当前基线 B 是 `results/cold_sparse_science_runtime_20261004/observer_sparse_exact_fault_20261004.zip`，SHA256 `5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`。文件逐字解压到自有 baseline 目录，原强程序保留。B 的即时公开选择作为对照；科学代理比较不被称为 B 的完整正式总分。

## 固定系数的有限模型

公开状态给出 target 科学账本 b_i。候选 e 固定 `(start,end,center,program)`，候选 target 必须在起点落入指定 fiber 并在完整曝光持续满足 minimum altitude。c_ie 是固定的名义贡献；积分按公开 night/slot 边界及最多 120 秒 piece midpoint 计算 Moon/airmass，band 积分不乘效率或方向倍率，factor 积分再乘效率/方向并在一次曝光上饱和。未来 C/E 使用声明的 reference seasonal prior，属于确定代理而不是未来天气、校准后验或 E[max]。

所有曝光端点排序，相邻端点的半开区间 I_j 为时间 atom。a_je=1 表示 e 覆盖 I_j；区间端点相接没有冲突。正式动作没有 slew/readout 时间，本模型 overhead=0；不能在另有开销的应用上沿用这个假设。一般公开状态模型要求将已公布 terrain 的当前 version space 在未来公开几何上评价；未公布天气/请求不进入图，临时通知仅按已公布时间支持使用。这个初始 pilot 无公告，以 clear mask=1 构造名义代理，不构造隐藏地形，也尚未验证有 terrain 公告的 state 接口。

永久 terrain 的扩展接口必须是 horizon 路径函数 `T_i(t)`，而不是固定 target 黑名单或短 TTL 通知：天体的未来 alt/az 变化可能使同一 target 的某时段受阻、某时段清晰。官方生成器的 terrain 从首 slot 到季末永久存在，首 slot 只公布粗方向；粗方向本身不公布精确 sector 宽度/altitude limit，不能当成已知硬 mask。可以固定当前 version-space 的一项假设 T∈{0,1}，或声明 expected-clear 的确定代理。积分为 `H_raw=(1/d) integral T_i(t) lunar_i(t)/airmass_i(t)^beta dt`，而 `H_band=(1/d) integral lunar_i(t)/airmass_i(t)^beta dt` 不乘 T；raw factor 用前者，program band 用后者。expected-clear 先积分再 cap 仍只是名义代理，不能称真实 terrain/天气随机期望。当前 pilot 两者相同，非空永久地形的公开模型连接尚未实施。

精确科学目标是

`F(S)=sum_i max(b_i,max_{e assigned to i in S} c_ie)`。

### 精确 breakpoint 表示

每个 i 取 `theta_i={b_i} union {c_ie:c_ie>b_i}`，去重排序 `b_i=theta_i0<...<theta_iLi`，层宽 `w_il=theta_il-theta_i,l-1`。令 y_e 为执行曝光，x_ie 为 target/fiber 指派，z_il 为该分数层是否得到 witness。

```
max sum_i b_i + sum_il w_il z_il
z_il <= sum_{e:c_ie>=theta_il} x_ie;  0<=z_il<=1
sum_{i in fiber f of e} x_ie <= y_e
sum_e a_je y_e <= 1; 0<=y_e<=1
```

整数 x/y 下，最优 z 正是最高分覆盖的各层，望远镜时间/fiber 约束正是这个有限域的可行性。因此其 IP 精确表示有限域科学 best；没有固定 level 量化误差。它不覆盖任意连续 pointing/start/duration。

### 消去分数层

紧凑形式用 `g_ie=max(c_ie-b_i,0)`，加 target 容量：

```
max sum_i b_i + sum_ie g_ie x_ie
sum_e x_ie <= 1                     for each target i
sum_{i in fiber f of e} x_ie <= y_e  for each exposure/fiber
sum_e a_je y_e <= 1                 for each time atom
0<=x_ie; 0<=y_e<=1
```

IP 等价性：任一物理有限排程中，对每个 target 仅保留其最高贡献曝光的 assignment；删去其余 assignments 不改变科学 max，不增加任何 fiber 或时间负载。紧凑可行解反向直接解码为物理曝光，因此两个整数最优值相同。固定整数 y 后，x 是 target 对曝光/fiber 的二分匹配，多面体有整数顶点。

LP 同值性：给定层 LP 的 x，对每个 target 按 c 降序扫描，将 x 从最高分起保留到累计 1，最后一条可截断，后面的 x 清零。每个分数阈值的截断后前缀和为 `min(1,原前缀和)`，因此原层目标在最优 z 下保持不变；各 fiber 负载只减少，y/time 不变。截断后 target 总量≤1，其边权和等于层宽与 capped-prefix 的望远镜求和。反向对紧凑 x，令各 z 等于相应 prefix 和即可。故两个 LP 最优值相同；紧凑 LP 是上述有限 IP 的松弛，包住所有该域可行排程。

前提是固定 c、science-only、可删除重复 assignment。required 的 max raw factor、REQ 窗口 witness、Jain、信息反馈、report repair、未来 loss 与 observe rank 都不满足这个删指派证明，不能从本式得出正式整体最优性。

随机分数接口也不满足删指派证明：b=0，两次独立曝光各以 .5 概率得 10，否则 0。一曝期望 best=5，两曝期望 max=7.5，而取边的 `E[(score-b)+]` 后单 witness 模型仍只给 5。因此不能将 compact 图的 c 换为新 NN/PMF 边均值就声称真实随机 best 同值或上界。当前固定名义 c 的全局机会压力只服务代理提案；若以后接随机分布，必须显式处理跨曝光 joint tail/survival 与公开反馈后自适应，不能沿用本消元。

## 对偶与原菜单外提案

紧凑 LP 的 target 容量价 sigma_i>=0、time 容量价 lambda_j>=0。固定这些价后，每个 field/fiber 的最优指派是取 `(g_ie-sigma_i)_+` 最大的 target。完整曝光的定价为

`P_e=sum_f max_{i fitting(e,f)}(g_ie-sigma_i)_+ - sum_j a_je lambda_j`。

保留 y_e<=1 的完全对偶目标是

`D=sum_i sigma_i + sum_j lambda_j + sum_e max(0,P_e)`。

它给有限图 LP 的可行对偶上界。LP dual/reduced cost 是代理定价信号，不是真实 gain，也不能用两个上界排名证明正式收益。精确层 LP 中改变 current-covered RHS 的 dual 是 LP value 的一阶超梯度；向正方向给免费 coverage 可获得的 value 增加至多该内积，超梯度不承诺下界。

提案在当前所有公开 target anchor × 四个 fiber phase 的 pointing 上重做 fiber 分类，以 `(g-sigma)+` 而非旧 immediate rate 定价；duration 用本轮固定合法值，并可由固定 field 的 saturation 阈值提案。program 与完整曝光积分重新算，不把 terrain/efficiency 并入 band。只选两条不同完整 action 的最高 reduced-price 提案，不能用真实世界后果选新菜单。

先动作 a 固定真实 assignments，`b'_i=max(b_i,c_i(a))`，`I(a)=sum(b'-b)`；相同未来列全集仅禁用与 `[now,now+d_a)` 冲突的列，解

`J_LP(a)=I(a)+V_LP(now+d_a,b')`。

所有候选结束时刻都加入同一个 first-night start union，避免分支人工网格空隙；其它夜域完全共同。对照含 B、两条 pricing 提案、`y_current=0` 的零时长/零贡献控制，以及同 B duration 的空占时控制。y=0 只用于数学比较，不作为部署动作。没有各 future truth path 先选不同首动作再平均。

## 预声明的小规模与成本门

两个新独立 generated public initializer，catalog seed `20261004901/20261004902`，weather seed `90501/90502`，192 targets、240 平方度、2026-11-02 到 2026-12-04 的完整公开 calendar。生成器配置关闭 stress 与所有新事件/requests/fault；这是公开几何/名义收益 pilot，不是天气或完整 controller 收益测试。truth 文件只由生成器写入；运行选择器前导出仅含允许 public/config 文件的 actor 输入目录。

每夜取均分四个起点，24 个通过公共 catalog 确定的分散 anchor field，3 programs × durations `{120,600,1800,3600}` 秒；夜末越界直接不生成。预期最多 36,864 complete-field columns，约 190k target edges。anchor 根据球面 farthest-point 覆盖选取，独立于即时科学收益，不用旧强候选 top K。当前提案枚举所有可见 target × 四 phase，不限原 B 菜单。三到五次 LP 用相同 sparse graph；禁止调 K、night samples 或 solver budget救负结果。

复杂度：公开几何缓存 `O(N*S*sum_d d/120)`；field 分类 `O(N*S*F)`（小例直接向量化）；稀疏图 `O(E+A)` 存储，紧凑 LP `N+16*A+T` 行、`E+A` 变量、约 `3E+A*mean(interval_atoms_per_e)` nonzeros。通用 HiGHS 最坏复杂度不能用线性式保证；实测记录建图、LP、pricing、common recourse 各阶段与峰值 RSS。

单世界实际选择总成本门为 10 wall seconds、RSS 512 MiB，包含 B/public initialization、全剩余 geometry/cache、graph、初始 LP、pricing 与所有 common recourse。world generation 另外完整记录，并给出含生成的总研究成本。超过门即保存失败/partial结果并停止该具体规模，不能只把 solver 秒记为模型成本。所有 source、输入、原始结果保存 SHA；正式受限 Linux 2CPU/2GiB/900 尚未测。

本阶段正证据是：有限 IP/层 LP/紧凑 LP 合同一致，LP 包住 IP；至少一个 pricing 新提案不在旧菜单；共同 recourse 在代理模型中是否改变 B 的 first action，以及完整成本是否达门。即使代理选择变了，也不自动批准 full season、truth scoring、线上或部署。

## 阶段 1 实际结果与停止

32 个预先固定随机小域通过独立物理 assignment 全枚举、固定整数 field 的 matching LP、紧凑 LP 和精确 breakpoint 层 LP 的合同。physical best 与有限 IP 相同，两个 LP 同值，LP 均包住 IP。72 个 synthetic 恒定 C/E 案例逐 target/program 与官方 scorer 相同，最大科学误差 `6.661338147750939e-16`；完整 minimum-altitude 与官方解析算子最大差 `1.258119368685584e-7` 度。它们是数值门检，理论等价性由上面的消元证明给出。

两个新世界都包含 32 夜、192 targets。原 ZIP 38 个文件保持字节一致；`GENERATION_RECEIPT.json` 的 `baseline_member_count=39` 把一项 `research/` 目录也数入，`ARTIFACT_AUDIT.json` 纠正为 38 文件。各自 public/config 导出目录无 truth。选择器 audit hook 拒绝 `truth/` 和 `generated_worlds/` 的任何 open，未导入 scenario/workflow loader。native/官方代码在自有复制目录运行。这是同进程文件 ingress 门禁，不是正式容器隔离证明。

snapshot 是本轮明确构造的零历史、零通知 public-only freeze，不是 workflow 实际首轮（实际首轮会交付已发布 bulletin/forecast）的复现。B 在这同一个 frozen initializer/snapshot 上调用完整原程序；没有用 synthetic 空通知的 B action 冒称 actual strong workflow 的首动作。

| 项目 | W90501 | W90502 |
|---|---:|---:|
| 初始 complete-field columns | 19,020 | 23,511 |
| 初始 target edges | 75,927 | 106,332 |
| common-union columns / edges | 19,224 / 76,767 | 23,739 / 107,568 |
| 初始 LP 值 | 123.359339444 | 137.077729907 |
| 非零 target / time dual 数 | 110 / 8 | 128 / 5 |
| 对偶上界减 LP 值 | 1.56e-13 | 0 |
| 两条提案在同态弱菜单外 | 是 / 是 | 是 / 是 |
| actual selector wall 秒 | 1.962100 | 1.744940 |
| actual selector CPU 秒 | 1.948997 | 1.728285 |
| 进程峰值 RSS bytes | 605,044,736 | 562,397,184 |
| 最终状态 | 512 MiB cost stop | 512 MiB cost stop |

W90501 的 B 是 DARK/160 秒/6 assignments，pointing `(84.1858058,263.4999426)`；两条 dual 提案为 DARK/3600 秒/10 和 14 assignments，pointing `(81.6160178,302.9074999)` 和 `(81.88785,302.0882021)`。提案由全当前 target × 四个 fiber phase 的定价产生，没有读取强程序 candidate list，也没有扩大旧 top K/M。它们的时长不同于 B，且 field 不同，因此均不在“B、同 B 时长的即时邻 field、wait”的同态弱菜单中。完整公开合法性按原 finite graph 的 min-alt/fiber 条件审查；没有实际执行这些动作。

W90501 在共同未来域上已完成并保存两个比较：B 的当前科学代理增量 `1.855762374494`、future LP `122.810333252221`，J=`124.666095626715`；priced0 当前 `15.184485940836`、future `114.891276327095`，J=`130.075762267931`，LP 代理差 `+5.409666641216`。priced1 求解成功后，累计 RSS 越过门，程序立即停止；其 value 未提交为排名结果。`y_current=0` 与同 B-duration 空占时对照尚未求解，因此没有完整 winner、选中动作或真实 gain。W90502 在 common B 求解后已越门，未产生任何完成的 recourse 排名。

生成两个世界连同 source 复制与 public export 为 `.177839 wall/.170934 CPU` 秒，单世界详情保存在 generation receipt。真实选择阶段拆分如下，单位 wall 秒：

| 阶段 | W90501 | W90502 |
|---|---:|---:|
| public 初始化 + 原 B | .036705 | .044138 |
| 全剩余 geometry/cache + field columns | .422422 | .429080 |
| 初始 sparse graph | .045424 | .054639 |
| 初始 LP + dual | .355285 | .521638 |
| 原菜单外 current pricing | .121333 | .119848 |
| common end union geometry + graph | .045987 | .071051 |
| common B LP | .301649 | .501449 |
| common priced0 LP | .327160 | 未运行 |
| common priced1 LP | .301586，越内存门 | 未运行 |

几何和 field-column 构造当前 timer 合并，尚未得到 pure-cache 与分类/column 的独立实测，不能将 `.422/.429` 全称为纯天文积分秒。实际选择 timer 从函数入口开始，包含上述完整选择工作；Python/SciPy/native import 在其前，启动成本尚未独立计时。RSS 是进程累计峰值，包括 imports；没有假称两 CPU Linux 成本或严格瞬时内存上限。Sparse CSR 数据本身只有 3.23/4.47 MB，solver/repeated-call 的实际进程峰值仍过门，内存归因尚未定位。

两个例子均未完成预声明全部 common-recourse 对照，因此本轮 **拒绝当前原型进入生产**，停止该固定规模，不调 K、夜采样、内存门、solver 配置或时长救结果。没有新 ZIP、训练、full 900、truth scoring 或线上操作。保留的 positive pricing 和部分 LP 反转只证明该名义有限模型可以提出旧弱菜单外的动作；还不能证明未来全容量稀缺或科学真实提升。

失败原样保存：第一次 synthetic minimum-altitude 调用误传函数签名；32 图合同已过、官方算子尚未运行完，修正配置参数后通过。第一次 pilot 在任何 graph/LP ranking 之前，pending 中 datetime 不能 JSON 序列化；保留源/日志/结果，改为记录 pickle SHA，原 pending 对象未改变，模型/规模/先验不变。最终使用 `REPAIRED_LOGGING_SOURCE_LOCK.json`，原 `SOURCE_LOCK.json` 与失败源均保留。两次实际 memory stop 原始输出不改写。
