# 正式赛：从本队已完成输出反演质量积分

## 结论与使用范围

这是一个可落地的系统信息利用方向：官方 `observations.csv` 保留曝光的**封顶前 quality**。结合公开目标、夜历、几何和已公开消息，可以把本队过去合法完成的曝光转成关于逐天气槽质量的稀疏线性约束。满 factor 的曝光仍有信息。

本次只读取四张公开卡与本队两次正式回放的下载结果；没有读取隐藏 weather/events/stress 产品、没有操作云端、没有修改生产策略。数值检验表明，同次回放的积分模型可跨曝光预测 quality 到 CSV 的舍入精度；第二轮共 2,055 次不同曝光、28,306 条正 quality 行也全部落入第一轮模型的窄区间预测。这个证据支持已识别槽的跨轮稳定性，仍不能证明所有未观测槽完全相同，也不能唯一分离效率、透明度、背景、视宁度。

目前输出适合作为下一次回放的**预测先验和当前反馈校准依据**。未观测槽只能插值/统计预测；多槽积分未识别的分量必须保留不确定性。不能把点拟合曲线当作已恢复的完整先知天气。

## 1. 官方字段与准确积分公式

证据来自公开仓库 `gosimfoundation/hackathon-survey26`（审读版本 `e01939d060f304c2a7cf04d9b3e46009b564fc23`），以及本地公开示例 runner：

- `runner/challenge/v4_scorer.py:315` 起的 `score_target_exposure()`：每个 slot overlap 在事件时间切点后以不超过 120 秒的子段中点积分。
- 同文件 `quality=(total/weight_sum)/q0`，只对 factor 执行 `min(...,1)`。**quality 没有裁到 1。**
- `runner/challenge/v4_runner.py:786` 起写出 `quality`、`factor`、`prog_mult`、`score`，均保留六位小数；`valid`/`invalidated_by` 是事后分数账本失效标记。
- `decisions.csv` 提供实际 `start_utc/end_utc/duration_seconds`。必须用实际时长，不可用原计划时长；本次四卡检查未发现三字段矛盾。

令目标 i 的公开几何函数为

\[
H_i(t)=\frac{L_i(t)}{X_i(t)^\beta},\qquad
Z_s=E^{\mathrm{effective}}_s\frac{\tau_s K_s}{\mathrm{seeing}_s}.
\]

L 为官方月光模型、X 为规范化 airmass，\(q_0=0.68,\beta=0.6\) 来自四卡公开配置。对背景关闭的槽可记 \(Z_s=0\)。对确认没有方向遮挡/方向乘子的曝光行 j，使用官方相同中点分段：

\[
y_j=q_{\mathrm{exp},j}
=\sum_s A_{js}Z_s,\quad
A_{js}=\frac{1}{d_j q_0}\sum_{p\subseteq s}\Delta t_p H_{i_j}(t_p).
\]

\(d_j\) 是实际曝光秒数。A 非负，单次最长 3600 秒最多触碰五个 900 秒槽，因此矩阵很稀疏。`quality` 打印为六位小数，故约束是

\[
\max(0,y_j-0.5\cdot10^{-6})\le (AZ)_j\le y_j+0.5\cdot10^{-6}.
\]

实现另加 \(10^{-9}\) 几何浮点保护；40 次独立官方 scorer 正对照最大误差为 \(3.13\cdot10^{-10}\)。这不包含任意自定义、非槽对齐事件切点的误差。

### factor、flux、program 的作用

factor 满足

\[
g_j=\min\left(\frac{f_i d_j y_j}{f_0t_0},1\right).
\]

直接使用 CSV quality 时，不需要通过 flux、science_weight、program 倍率反推。若只能取得 factor：未封顶 factor 可反推 y，但舍入误差应乘 \(f_0t_0/(f_i d_j)\)；满 factor 只给 y 的下界。只有 score 时还要处理 program 分类歧义，信息更少。

数据丢失后的 `valid=false` 不会改变已经测量并写出的原始 quality。这些行可用于物理质量反演，却不可用于有效科学分/required/request 账本。当前 gamma/delta 分别有 274/213 条这样的物理记录。

## 2. 能识别什么，不能识别什么

### 乘积、维修状态与秩

纯 quality 只观察 \(Z=E\tau K/\mathrm{seeing}\)。保持这一乘积的不同 E、透明度、背景与 seeing 给出完全相同反馈，不能把一次拟合的 E 当作故障真值。

即便不分解乘积，也未必逐槽唯一：若所有行都与 \([1,1]\) 成比例，那么两槽只识别 \(Z_1+Z_2\)，\((0.2,0.8)\) 与 \((0.5,0.5)\) 一样。实际同场 fibres 的 H 很接近，跨槽系数常近乎成比例，六位舍入会放大不确定性。数千行并不等于数千个独立天气观测。

正确 report 在当前时刻恢复故障乘子，`WeatherTruth._apply_fault()` 会据此改变 effective E。900 秒槽可能在 report 时刻发生 E 跳变。实现用本队 `report_result.correct && repaired` 时间把该槽分为维修前/后 cell；官方报告动作耗时为零，不会穿插在本队上一条 observe 的内部。**第二轮改变维修路径后，即使基础天气一样，旧 Z 也可能失效。**

没有额外 E 证据时，只在相同维修历史附近复用旧乘积，或将旧曲线作为有不确定性的先验并由当前反馈校准。不能直接除以先前拟合出的 E 来宣称得到基础天气。

### program band 给出另一组信息

官方 `band_quality()` 不含 E，也不应用方向事件，积分的是

\[
B_j=\sum_s A_{js}W_s,\qquad W_s=\tau_s K_s/\mathrm{seeing}_s.
\]

若 `prog_mult` 是匹配倍率，则已知实际 band：DARK 的 B≥0.65，BRIGHT 的 0.4≤B<0.65，BACKUP 的 B<0.4。mismatch=1 时，declared DARK 给 B<0.65，declared BACKUP 给 B≥0.4，declared BRIGHT 给 B<0.4 或 B≥0.65 的非凸并集。

这是关于 W 的第二组线性/析取约束，可比单纯拟合 CE 更强；本次程序没有进一步求解 W。它仍不足以唯一分离每槽 E，尤其在跨槽积分和维修变化时。

## 3. 方向事件与零反馈

真实目标质量可含目标/时间相关遮挡和乘子，形式为 \(y_j=\sum_p a_{jp}Z_{s(p)}D_{jp}\)。同场 16 fibres 都落在同一片方向衰减区时，整场衰减与低 Z 完全混淆。不能通过多数投票自动消除这一异常。

零反馈还可能来自永久地形、火箭关闭、方向天气和背景关闭；门检构造了“正常背景+地形全遮挡”与“背景关闭+无地形”的完全相同 quality=0。因此本次保守 pilot 不把任何零行硬写成全局 Z=0。

公开 generator 的天气、火箭、故障、地震时间边界均在发布天气槽边界；永久 terrain 从首槽到末槽。按此生成路线，可重建干净行的官方中点分段。任意非槽对齐的隐藏自定义事件不在已证范围内。

本次采用明确的**参考生成域条件**筛选干净行：initial 地形 coarse 方向持续有效；每槽 bulletin 只表示该槽方向事件；ALL 已折入 Z。参考地形最大宽 70°/高 50°，天气最大宽 120°/高 80°，火箭最大宽 80°/高 60°；八方向通知限制 sector 中心在对应方向 ±22.5°。连续轨迹的高度/方位包络若避开所有可能 sector 才选为 clean。缺失 bulletin 不推断“无事件”。

上述域来自公开参考 `challenge/reference/v4/v4_weather_stress_config.json`，正式卡的六个公共文件**没有证明 hidden 生成配置采用这些参数**。所以这套 clean 标签与区间均属条件推断。可在下一轮相同时间 quality 交叉验证中检验它的实践适用性。

特别更正：该参考配置 `sky_quality.maximum=1.50`、seeing minimum=0.50，E/tau≤1，所以参考 Z 上界是 **3**，不是 2。生成时全局字段再次 clip，正确修复的 E 也最多 1。无上界 NNLS 点预测单独计算，不以参考 cap 阻止实践拟合。

## 4. 区间传播与数值点拟合

从条件域 \(0\le Z_s\le3\) 开始，对每条舍入区间 \(l_j\le\sum a_{js}Z_s\le u_j\)，更新

\[
\underline Z_s\gets\max\left(\underline Z_s,\frac{l_j-\sum_{k\ne s}a_{jk}\overline Z_k}{a_{js}}\right),\quad
\overline Z_s\gets\min\left(\overline Z_s,\frac{u_j-\sum_{k\ne s}a_{jk}\underline Z_k}{a_{js}}\right).
\]

每步保留所有可行解，是一个外包区间；没有矛盾**不等于**整个约束系统已证可行，更不等于唯一。300 次传播仍可能未达到固定点。本次所有四卡没有检测到区间矛盾。

另行求 \(\min_{Z\ge0}\|AZ-y\|_2^2\)，不设参考上界、不对无观测槽加入伪真值。本次 LSQR 内部迭代/非负外层在近病态矩阵上达到限制，`status=0, success=false` 如实保留；RMS 残差约 \(2.83\!\sim\!3.43\cdot10^{-7}\)，最大约 \(2.17\!\sim\!6.57\cdot10^{-6}\)。这条点曲线没有被验证为全局最小点，更不能作为真值部署。

## 5. 四卡小门检结果

| 卡 | quality 行 | factor=1 行 | max quality | 条件 clean 正行 | 支持 cell / 全部 | 区间宽≤1e−4 |
|---|---:|---:|---:|---:|---:|---:|
| alpha | 15843 | 3654 | 1.174305 | 13371 | 1050 / 1253 | 462 |
| beta | 14986 | 3410 | 1.205826 | 13001 | 1049 / 1199 | 434 |
| gamma | 15434 | 3527 | 1.133374 | 13527 | 1139 / 1235 | 475 |
| delta | 13365 | 3001 | 1.335269 | 10372 | 944 / 1180 | 373 |

同一 realization 的额外交叉检验：**按整次 observe 动作**将 index%5==0 全部留出，不拆同场 fibres。只用训练集单 cell 行直接给出的 Z 中位数锚；只检验每个 cell 都有训练锚的留出行，不用插值制造支持。

| 卡 | 留出独立曝光 | 支持的留出 quality 行 | max absolute error | RMS error |
|---|---:|---:|---:|---:|
| alpha | 58 | 808 | 8.28e−7 | 3.20e−7 |
| beta | 67 | 875 | 7.16e−7 | 3.08e−7 |
| gamma | 55 | 698 | 7.46e−7 | 3.13e−7 |
| delta | 43 | 521 | 8.21e−7 | 3.03e−7 |

双端都只有六位 quality，加之公开几何误差，上述最大误差符合其舍入信息尺度。它支持“公开几何与 quality 可以约束同次回放中的槽乘积”，没有验证第二轮隐藏 realization 相同。

## 6. 两轮稳定性：应检验什么

`score_report.sha256.scenario` 在 `v4_runner.py:892` 只是 `sha256_file(scenario_path)`，即 YAML 文件本身。它不涵盖 YAML 引用的天气真值内容，更不能单独证明未来天气固定。

`compare_runs(first,second)` 依次报告：

1. scenario YAML 哈希是否相等，仅作配置路径/文件内容证据。
2. 相同 issued_at 时刻的 bulletin/forecast canonical 内容是否一致；缺失消息分开统计，不以整份 messages 哈希判断，因为本队报告/REQ/state_resync 会随决策变化。
3. 相同 target、start、end、actual duration 的 quality 是否在六位舍入范围内一致。
4. 正确维修时间序列是否一致，防止把修复造成的差异解释成基础天气变化。

### 第二轮已下载输出的对照结果

第二轮只读本队下载的 `gosim_phase_gpu_{alpha,beta,gamma,delta}_result.zip`；输入 ZIP 和 normalized public 输出 SHA 已存 `quality_profile_two_run_stability_result.json`。四卡所有 bulletin/forecast 都在相同 UTC 具有完全相同 canonical 内容，共 4,887 条，无新增、缺失或变化。scenario YAML 哈希也相同。

严格相同 target/start/end/actual duration 的 quality 行分别为 13/120/0/26，全部六位打印完全一致。但 gamma 没有这样的重合行，所以进一步用第一轮 profile 预测**第二轮新时间、新目标曝光的积分**。筛选规则是：旧每个触碰 cell 均有支持且区间宽≤1e−4；第二轮方向几何满足同一条件 clean 筛选；quality>0；不插值；排除曝光与两轮不同正确维修时间之间区间相交的情况。

| 卡 | 旧窄 cell | 第二轮独立曝光 | 第二轮正 quality 行 | 落出旧预测区间的行 | 中点预测 RMS error |
|---|---:|---:|---:|---:|---:|
| alpha | 462 | 576 | 7959 | 0 | 3.74e−7 |
| beta | 434 | 544 | 7451 | 0 | 3.46e−7 |
| gamma | 475 | 537 | 7465 | 0 | 3.15e−7 |
| delta | 373 | 398 | 5431 | 0 | 7.83e−7 |

第二轮中点预测 max error 为 4.08e−6/4.23e−6/2.79e−6/1.22e−5；这些较大误差仍在旧模型自身的宽度内，因此不当作天气差异。累计 28,306 行全落在旧条件区间加新 CSV 舍入半径内，是比“scenario 文件相同”强得多的已测量积分一致性证据。

维修差异已显式排除：alpha 10/30 UTC 01:50:01↔01:54:35，beta 11/24 02:32:36↔01:52:57，gamma 10/28 02:10:45↔02:25:19，delta 11/29 06:51:11↔06:57:21。分别排除了 1/2/1/1 次可能受不同 effective E 影响的曝光。

可以据此将已测量、已有窄区间的槽作为有实测稳定性支持的未来 profile 先验，并以当前反馈监测偏离。未测量槽、未识别分量、不同修复路径仍不自动获得证明；整个隐藏天气相同不是该有限检验的数学结论。

## 7. 文件与运行

- `quality_profile_inversion.py`：公开 A 构造、连续轨迹条件筛选、区间传播、无上界 NNLS、整动作 holdout、两轮公开稳定性比较。
- `quality_profile_inversion_checks.py` / `_checks_result.json`：40 次官方正对照及不可识别反例。
- `quality_profile_{alpha,beta,gamma,delta}_result.json` / `.npz`：输入 SHA、统计、cell 范围、外包区间、稀疏 A、原 quality、非唯一点预测和支持度，全部只源于公开/本队已获输出。
- `quality_profile_two_run_stability_result.json`：两个完成版本逐 UTC 公开消息与精确同曝光 quality 对照。
- `quality_profile_{alpha,beta,gamma,delta}_cross_run_result.json`：第一轮窄区间对第二轮新积分的验证，记录 ZIP/profile SHA、维修排除窗口、未支持曝光与区间违例。

使用本仓库 `.venv-solver/bin/python`（含 NumPy/SciPy）。生产 agent 没有导入这些文件。

后续最有价值的动作是把有跨轮验证支持的窄区间槽，与带当前 E 校准及未观测槽预测的不确定性，接入未来机会模型。无需假设种子或把未观测天气强行补成先知曲线。
