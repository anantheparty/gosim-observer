# 固定公开 δ 模型的 CUDA 后端与资源价格

真实执行于 `elevatia-wsl / setsu`，Windows Torch `2.7.1+cu128`，RTX PRO 6000 96GB，功率上限保持 600W。工作目录为 `C:/Users/hedge/gosim-quality-window-20261004`；仅调用既有 Python，SciPy 1.16.1 安装在该新目录的 `pydeps`。未改旧 venv、服务、教师、学生或生产 actor，未读 truth/L4 sealed，未线上提交。

冻结后端 SHA256：`db8c36ff5feab172861c0118d168f918a9b4c84745950a6d19ef068675d90506`。输入按原 receipt 的固定字节传输，见 `MANIFEST.json` 的来源路径与 SHA；公共 model `1d95a0a3…`，CPU reference 源 `11c7092a…`，门检 fixture `fc5539bb…`。本目录不重复归档同字节 model/reference。

模型接口为 `normalized_score/raw_factor[W,A,S,N]`、`probabilities[W,S]`、`durations[W,A]`、`weights/required_bonus[N]`，threshold `.5`。原 score/raw 数组 float32 的存储值按原值转为 float64；其他概率与参数 float64。公开分数先由 NumPy 六位 rounding 分组，再更新 `π'=π+(1−π)Pr(raw≥.5|公开score)`；所有 latent 结果期望完成后再 max action。Bellman 使用 float64 与原 `> current+1e−10` tie 规则。

## CPU/CUDA 一致性与全规模执行

门检包含全部 W38/A9/S3、冻结的 128 个目标索引、B25/P9、非零价格及非零初始 best/π。现场 CPU 结果与冻结 CPU fixture 的 value、policy、demand 完全相同。CUDA policy 差异 **0**；最大 value 误差 `1.42e−14`，float32 suffix 误差 **0**，最大 demand 误差 `4.00e−11`。该门检证明此有限子问题一致性，不宣称全 9400 目标 policy 经逐项 CPU 比较。现场门检 CPU 0.777s、CUDA 2.108s；CUDA 含首次设备启动。

完整模型为 **W38/A9/S3/N9400/B25/P9**，μ=0、初始 ledger=0：

| 测量 | 实际结果 |
|---|---:|
| Backward / forward / 合计 | 1.831s / 0.635s / **2.466s** |
| Torch CUDA allocated / reserved 峰值 | 453,442,560 / 490,733,568 bytes |
| Windows working-set 峰值 | 1,231,790,080 bytes |
| nvidia-smi 采样功率峰值 | 205.33W |
| 初始有限值 / 总预期需求 / 总容量 | 38273.3092 / 37.6807M / 16.9776M fiber-seconds |

Torch 峰值包含 score/tau、policy 和插值临时张量；滚动只适用于 Bellman 主值。nvidia-smi 是整卡采样，包含既有桌面/VR负载，峰值不等于连续瞬时峰值。原 CPU pilot 使用 B13/P5（56.12s）；网格不同，不能据此报相同问题的加速比或把有限值差当官方提分。

## 有限模型价格

在 bonus、capacity 非负、duration 正的固定模型上，`R_i=1.2*w_i+bonus_i`，每窗安全盒为 `0≤μ_k≤max_i R_i/min_a d_ka`。此 receipt 的各窗上限均为 **0.05782222222222222 points/fiber-second**，与冻结 receipt 一致；在上限处服务被 skip 支配。目标为固定插值模型的 `F(μ)=Σ query(Vμ,初始状态)+μ·capacity`，政策斜率 `g=capacity−demand`。

执行了 25 次 uniform 二分、1 次安全高端 oracle、32 次 Kelley oracle，共 **58 次新 GPU oracle**，123.501s。最佳仍来自 uniform，`μ=0.000162101411819458`，有限 F **37730.40414090836**。最后区间 `[0.000162101411819458,0.00016210313505596584]`，`区间宽度×总容量=0.02925642`。最佳端的总需求 16,977,711.37，比总容量高 111.37；上端需求 16,977,364.33。按两端有限 F 取最佳端，未强称精确容量匹配。

uniform 最佳端仍有 **16 个窗口过载，最大 demand/capacity=7.60736**，因此不是可执行预留计划。Kelley 32 次未改善最佳端，末 LP 数值 lower **33123.17912734773**，含余量数值 gap **4607.225432013722**；**未收敛**，预算后停止。所有 oracle 及 cuts 日志保留。价格产物是 `prices/price_arrays.npz` 的最佳价格、需求与容量；optimizer 的最优 policy 未额外保存，μ=0 的完整 policy 在 `mu0_v2/full_arrays.npz`。

价格 oracle 前传保留所有正 mass，门检仍保留 reference 的 `1e−15` cutoff。记录 tie policy ε=`N*W*1e−10=3.572e−5`、cut 数值 slack=`F(0)*1e−8=0.0003827330922`；gap 仅为此有限模型的数值诊断，未宣称严格证书。价格阶段 allocated 峰 453,442,560 bytes，working-set 峰 1,337,667,584 bytes；242 次 nvidia-smi 样本功率最高 **229.09W**、均值 **192.24W**。

`prices/result.json` 保留全部 **59 行** oracle（含复用的 μ=0 行）与 32 行 LP，`prices.log` 保留执行输出。选定 policy 的固定模型值关于 μ 是 affine，因此未截断 policy 需求给出的切平面在精确算术下低于精确有限 max；tie ε用于 best evaluated F 的余量。这里的 **33123.1791** 是加 slack 后切平面 master 的数值 LP 值，未给 floating-point roundoff 的严格证明。`NUMERICAL_PRICE_AUDIT.json` 对所有已执行 oracle 交叉检验 cuts：相对 `F+tieε` 的最大差为 `−0.0004184530`，排序后的 uniform demand 无上升，保存的 master 点最大 cut/LP 残差 `2.08e−10`；这些是数值一致检查，不能扩大 lower 的口径。

数学层面的下一步可用 level/bundle 稳定化同一 38 维凸目标：保留 cuts 与盒，取当前 numerical lower 和 best F 之间的 level，在该 level 的 cut 可行域中求离当前最佳价最近的点（按安全盒缩放坐标）。这可避免当前无稳定项的 Kelley master 反复跳至远端；serious/null step 规则再决定更新中心或仅补 cut。它解决的是求价稳定性，32 次 Kelley 未收敛不能说明有限模型不存在更好的异质价格。本次未新增该 job、未扩大预算、未改 PMF；真实服务机会与条件后验准入仍须单独完成。

原 B13/P5 三步 subgradient 的负结果保留在来源 `delta_public_pilot.json`：38279.2932 → 49912.8234 → 55869.9705，最佳仍 μ=0。未换 PMF、raw/score 模型、初始状态或参数来救结果。

窗口服务机会、固定 `[.25,.5,.25]` PMF、独立 completion 更新等仍是该原型的假设，尚未完成真实服务机会、当前 ledger 条件后验、冲突容量以及同源完整季节回放准入。GPU 吞吐和上述有限值均不表示官方分数改善或原题最优界。

## 进程与失败记录

`JOB_REGISTRY.json` 登记 μ=0 WSL PID3223716 / Windows PID57144、价格 WSL PID3224489 / Windows PID88248，均已结束。首轮 WSL PID3221221 在门检后的 Windows RSS 采集因 HANDLE 类型未声明报错；`first_attempt/` 保存原 receipt 与功率样本，这是计量失败，未认定数值门检失败。修复后同冻结输入通过门检。任务结束 nvidia-smi 为 5% utilization、111.10W、600W 原功率上限。
