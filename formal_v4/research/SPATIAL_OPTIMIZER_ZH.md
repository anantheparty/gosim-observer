# v4 空间、曝光与光纤分配的数学化简

2026-10-03。实现为 `spatial_candidates.py`，接收官方初始化和当前快照，不读取天气、事件、请求或种子真值。天气估计由入口模块传入。本文件讨论的精确性只限于明确给出的子问题。

## 1. 状态与真实目标

每目标 i 需要独立保存最高科学贡献 s_i 和最高原始完成因子 f_i；两者可来自不同曝光。当前曝光因子为 g_i=min(k_i t,1)，科学增量是 max(0,w_i m_i g_i-s_i)。**真实科学分是线性 g_i，官方示例用于启发式排序的 g_i² 不等于评分器。**

若 required 且 f_i<r，达到 g_i>=r 一次即可消除 P 分终局罚款。过去的多次曝光不累加。因此状态至少包含时间、目标最高分和最高完成因子、曝光有效历史、请求状态、环境信念；只有时间和当前望远镜指向不充分。

把每次候选动作看作占据 t 秒、覆盖若干目标的集合，科学价值依赖此前覆盖记录；required、请求和均匀度加入终局奖励或惩罚。全局是带时间窗口、空间冲突、目标最高值结算和隐藏环境的加权覆盖/调度任务。下面的子问题化简不构成整个问题多项式可解的证明。

## 2. 固定指向、曝光、program 的精确分配

官方光纤格互不重叠，每目标只会落入唯一一格。一个目标也无法同时供两格争用。因此在目标价值可加时，不需要 Hungarian 或一般网络流：每格独立选增量价值最大的目标即可。一次扫描所有局部目标，复杂度 O(n_local+F)。

几何采用官方 gnomonic 投影，逐目标与中心、north、east 向量点积，得到切平面坐标，继而确定 fiber id。实际命中只在曝光起点判定；目标随后跟踪，整次曝光须保持高度>=30°。模块使用公开纬度和恒星时计算 setting deadline，剔除曝光期间会落下地平线的目标。

命令和实际指向的偏差直接作用于 alt/az。模块先优化实际中心，再减去反馈拟合的 `pointing_offset_alt_deg` 和 `pointing_offset_az_deg`；入口不应二次补偿。

## 3. 曝光时长不必逐秒扫描

冻结本次曝光内的质量 k_i，并把 required/request/均匀度门槛作为单目标的离散收益。在所有目标的饱和时刻 1/k_i、门槛时刻 r/k_i 和可见截止时刻之间，每个合法目标的价值是仿射函数 a_i t+b_i。

令 u=1/t。一格的收益率为 max_i(a_i+b_i u)，即若干直线的上包络，是凸函数。对各格求和仍凸。因此每个不含断点的区间中，收益率最大值必可在端点取得。目标之间的直线交点只会形成凸折点，不需额外枚举。可以把 60–3600 秒的整数扫描化为目标导出的断点，整数化时比较相邻 floor/ceil。

实现同时扫描三种 program，每次使用对应目标预估 band 的倍率。科学饱和点使用原始预测 k；required/request 门槛使用 k/duration_safety，以留出质量误差余量。为满足实时预算，超过72种曝光时长时采样其中72种，因此此时是有界近似。实际质量会在120秒积分点和天气 slot 处变化，冻结 k 的断点最优性不能提升为真实动态天气下的最优性证明。

若收益率出现平台，优先选择平台上增量最高、曝光最长的候选，避免 best-only 结算下反复短曝光造成无法累加的时间浪费。

## 4. 一个请求的 quota 有更小的精解

固定指向、时长、program 后，设每格不计请求奖励的最好价值为 B_f，能完成该请求目标的最好价值为 E_f。替换损失为 c_f=B_f-E_f。为了完成剩余 K 个请求目标，只需选 c_f 最小的 K 格。若可完成请求的格不足 K，则该曝光无法单独兑现奖励；否则完整请求价值是 sum B_f - sum_{K最小} c_f + R。

这给出单个请求的精确 quota 分配，复杂度 O(F log F)，比按目标子集 DP 更小。模块把最重要的一个活动请求按此精解；当该指向无法一次完成请求时，使用每个目标 R/K、最多 K 个目标的滚动进度影子价格。其他同时活动的请求采用影子价格。因此多请求交叠和跨曝光规划仍属近似。

## 5. 全局紧迫性与均匀度

初始化为每目标计算所有公开夜晚的可见窗口，得到剩余可观测夜数。required 门槛奖励使用实际配置的 P，科学增量使用实际权重。目标少夜可见、当前正在落下时，给时间稀缺性价格，而不是把当前最高 flux 当成全部策略。

均匀度 J=S²/(B V)，其中 S=sum r_b、V=sum r_b²。其对一个条带比例的导数为 2S/(B V)-2S²r_b/(B V²)。每完成一个该条带目标，比例增量是 1/N_b；模块将此导数转为单目标影子价格。初期完成比例很小会造成不稳定导数，先按完成进度逐渐提高该项权重。该线性化不是 Jain 指数的精确多目标结算。

## 6. 空间搜索与计算预算

候选空间采用公开 catalog 的近等面积 RA/Dec 分箱，按当前科学、required 和请求价值聚合，挑选稠密有价值的分箱和个体种子。保留彼此分散的 anchors，将每个 anchor 放到各光纤中心产生指向，再对最强中心进行两个尺度的平移检查。

因此这不是完整连续平面的枚举或全局最优证明；它覆盖不同区域以及不同格相位，并把每个候选中的光纤指派和曝光断点系统求解。对于100光纤，采用25个分散的格位置控制候选量。

设目标数 N、候选数 M、局部目标数 L、时长断点数 D<=72、光纤数 F、program数3，则每轮主要复杂度 O(N+M*3D*(L+F))，一次活动请求再加 O(M*3D*F log F)。初始化可见性 O(N*夜数)，内存为若干 N 长数组和夜数×N 的布尔矩阵，远小于2 GB。

L1 首轮实测：7800目标、390 required、32夜，初始化约8 ms，8 anchors×16光纤加16次精调=144个候选，约50 ms；加入一个请求 quota 约61 ms。在四个不同时间点，输出每个指派均与官方 `FiberGrid.classify_target` 完全一致；额外请求测试正确选择至少3个预测达标目标。

## 7. 与入口的接口

`SpatialPlanner(initial_payload)`；`choose(snapshot,best_scores,best_factors,env_estimate,active_requests)` 返回纯 v4 observe 动作或 None。入口处理 daytime、wait、finish、report、真实反馈和有效历史。

质量公式为公共模型 H/q0，其中 H=lunar/airmass^beta。所以 `quality_scale=transparency*sky_quality*instrument_efficiency/seeing`，`program_band_quality_scale=transparency*sky_quality/seeing`。若反馈滤波器定义 C=transparency*sky_quality/(seeing*q0)、E=instrument_efficiency，则对应传 C*E*q0 和 C*q0。

默认粗方向先验只影响曝光 Q，不影响 program 判档 B；初始 terrain 粗方向记忆持续存在。当前方向公告使用软降权，不把整片粗方向永久排除。入口可设 `use_bulletin_directional_prior=False`，或提供 `target_quality_scale`/`directional_quality_scales` 替代。rain/storm ALL 的关闭等待由入口处理。地震和仪器效率属于 global quality_scale，不应二次叠加未核实的 quake 系数。`last_prediction` 保存 public_quality、quality、directional_scale、factor、fiber_id、predicted_band，便于入口从反馈反推环境和命中偏差。
