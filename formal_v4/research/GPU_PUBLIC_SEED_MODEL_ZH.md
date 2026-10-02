# 公开目录指纹：GPU 枚举与中心池大小的精确化简

2026-10-03。研究输入只有官方公开生成器、α–δ 的公开 footprint/targets、公共 synthetic seed。模型只枚举公开目录生成假设，不读取任何服务器私有数据，也不包含服务凭据。

## 已完成与正在进行

- 旧模型：SHA-v1 master `0..2^32−1`，中心池大小 `3..16`，已完整检查 **4,294,967,296** 个 master，**无 9-phase 匹配**，无 overflow。实际端到端 **124.824787 秒**，16384 批，每批主动让出 2 ms。机器结果：[gpu_public_seed_sha256_32bit_result.json](gpu_public_seed_sha256_32bit_result.json)。
- 新模型：把中心池大小 `3..2^32−1` 精确化简为少量 RNG 消耗 offset。CPU 40 个公开 synthetic seed 的 **87050** 次 Python `sample` 对照全相符；GPU 256 个 synthetic seed × 两种派生模式的完整 offset 集合及 fallback 标志全相符；另有 12 项 phase/candidate 正对照，包含强制 CPU 回退。
- 新模型小批：262144 个 master 的 GPU 核中位约 **9.79 ms**、最大 **15.43 ms**；端到端中位约 **11.94 ms**。加上每批 2 ms yield，完整 32-bit 扫描预估 **228.39 秒**。短基准受同时负载、温度和功率状态影响；真实长扫描另行记录。
- 新 SHA offset 全集已完成：master `0..2^32−1`，全部中心池 `3..2^32−1`，**4,294,967,296** 个 master，**无 9-phase 匹配**，无 fallback。真实端到端 **126.658477 秒**，最大 GPU 核 **18.812 ms**。机器结果：[gpu_public_seed_sha256_allpool_32bit_result.json](gpu_public_seed_sha256_allpool_32bit_result.json)。
- 同范围 legacy offset 全集也已完成：**4,294,967,296** 个 master，**无 9-phase 匹配**，无 fallback。真实端到端 **122.611045 秒**，最大 GPU 核 **29.112 ms**。机器结果：[gpu_public_seed_legacy_allpool_32bit_result.json](gpu_public_seed_legacy_allpool_32bit_result.json)。至此没有后台 seed 扫描任务。

以上数字只能排除给定假设范围，**不能证明 master seed 是 32-bit，更不能证明随机数不可恢复**。尚未找到 α–δ 的 seed 或恢复其未来天气。

## 1. 精确的公开 fingerprint

固定官方源码 commit：`e01939d060f304c2a7cf04d9b3e46009b564fc23`。

官方 [contracts.stream_seed](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/contracts.py) 的 SHA-v1 catalogue 流是：

```python
seed128 = int.from_bytes(sha256(f"{int(master)}:v4.catalog".encode()).digest()[:16], "big")
rng = random.Random(seed128)
```

legacy catalogue 流是 `random.Random(master)`。官方 [v4_bundle](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_bundle.py) 显式选择 SHA-v1，因此 legacy 是额外历史路线假设。

公开卡均有三个 component、每个三阶谐波。官方 [generate_footprint](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py#L307) 先 `rng.sample(centers,3)`，再为每个 component 抽取三个 phase、三个 amplitude。形状的面积缩放与几何计算不再消耗 RNG。由公开顶点反求中心、径向距离、FFT 后得到九个 phase，推导及公共 demo 全文件复现证据见 [PUBLIC_SEED_AUDIT_ZH.md](PUBLIC_SEED_AUDIT_ZH.md)。

匹配容忍度 `1e-4 rad` 也经过舍入误差检查。官方以六位小数发布顶点，每个RA/Dec误差至多 `0.5e-6°`。利用中心公式的偏导上界、球面三角不等式，先界定每个径向距离的误差；归一化DFT系数误差不超过各顶点径向误差的平均，故phase误差至多 `asin(E/abs(C_h))`。四卡36个phase的最大保守界 **9.7078183e-5 rad**，小于匹配容忍度；还包含 `1e-11 rad` 浮点计算余量。脚本与机器证据：[phase_rounding_bound.py](phase_rounding_bound.py)、[phase_rounding_bound_result.json](phase_rounding_bound_result.json)。因此在同一官方几何模型下，六位小数的发布舍入不应排除正确seed。

若 `sample` 消耗了 d 个 32-bit MT 输出，则九个 phase 对应输出起点：

```text
d + [0,2,4,12,14,16,24,26,28]
```

每个浮点随机数消耗两个 MT 输出。第三个 component 的最后 phase 使用 `d+28,d+29`；全部 phase/amplitude 用完后，class roster shuffle 从 `d+36` 开始。官方随后先 shuffle 类别，再抽样 required flags，最后才生成簇/目标坐标和 flux。因此 phase 命中后还可以检查全部公开类别序列和 required 集合，无须猜后段目录配置。来源：[sample_targets](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py#L613)。

## 2. 不枚举几十亿中心池大小：区间证明

令中心候选池大小为 n，抽样数固定为 3。[CPython 3.13.6 random.sample](https://raw.githubusercontent.com/python/cpython/v3.13.6/Lib/random.py) 对本题分为两支：

- `3≤n≤21`：缩小 pool 的算法，分别执行 `randbelow(n),randbelow(n−1),randbelow(n−2)`。只有 19 个模型，逐一模拟消费次数。
- `n>21`：selected-set 算法；反复 `randbelow(n)`，接受三个不同索引。

对后一支，固定 `k=n.bit_length()`。第 j 次 getrandbits 输出为 `v_j = U_j >> (32−k)`，其中 U 是同一条 MT 32-bit 输出流。拒绝 `v_j≥n`，接受小于 n 的不同值。

令 `b_3(j)` 是前 j 个 v 中**第三小的不同值**，若不足三个不同值记为无穷。

**引理：抽样已于第 j 个输出完成，当且仅当 `n>b_3(j)`。**

证明：完成等价于前 j 个值中至少存在三个互异且小于 n 的值；这恰好等价于第三小的互异值小于 n。值的出现顺序只决定先后，不影响这个完成判据。

故恰好在第 j 个输出完成的 n 区间为：

```text
b_3(j) < n ≤ b_3(j−1)
```

再与本 k 的合法区间取交：k=5 时为 `[22,31]`；k=6..32 时为 `[2^(k−1),2^k−1]`。只有第三小值下降时才可能产生一个非空区间。每一步只保存三个最小互异值；此前比第三小值更大的数今后不可能进入最小三元组，因此丢弃它们不会影响判据。

一旦第三小值小于该 k 区间下端，整个区间内每个 n 都已经完成，可停止。将所有区间产生的 j 与 n≤21 的消费次数取并集，得到**全部可能 offset**。同一个 offset 的后续 phase、类别和 required 流相同，可合并检查。

这覆盖每个 `n∈[3,2^32−1]`，与中心值和原始列表顺序无关。它没有覆盖 `n≥2^32`，因为该范围 getrandbits 需要多于一个 32-bit 输出。

## 3. 227 输出优化不会悄悄丢掉候选

[CPython MT 实现](https://raw.githubusercontent.com/python/cpython/v3.13.6/Modules/_randommodule.c) 使用624-word状态。一次 twist 中前227个新 word 只依赖未修改的旧状态；位置227以后开始使用已更新状态。GPU 先精确构建初始624-word状态，只按需计算前227个输出，不执行完整 twist。

phase 检查最远需要 `d+29`，因此 GPU 直接处理 `d≤197`。

以下任何情况都把整个 master 标记为 CPU fallback：

1. 某个 n≤21 的 sample 在227word内尚未结束；
2. 任一 bit-length 区间在227word内尚有未完成 n；
3. 存在合法 offset d>197。

CPU fallback 使用真正的 `random.Random`，增加输出前缀直至所有 n 区间结束，然后逐一检查所有 offset。任何 output buffer 溢出都导致当前批次不认证，减小批次重新运行；任何未完成 CPU fallback 都导致报错，不能推进 checkpoint。

所以前227word是加速路径，**不是“预计足够”的剪枝假设**。

## 4. 实现和正对照

| 文件 | 作用 |
|---|---|
| [gpu_seed_throughput.py](gpu_seed_throughput.py) | SHA单块、CPython整数seed拆分、MT init_by_array、earlyword、random浮点精确实现 |
| [offset_coverage_model.py](offset_coverage_model.py) | CPU 区间证明模型、实际 Python sample 消费计数对照 |
| [gpu_offset_seed_model.py](gpu_offset_seed_model.py) | CUDA 区间并集、短批次过滤、CPU fallback、小批基准 |
| [gpu_public_offset_scan.py](gpu_public_offset_scan.py) | 可恢复分片、源文件hash约束、候选类别/required核验、停止标记 |
| [public_seed_fingerprints.json](public_seed_fingerprints.json) | 仅公开九phase/类别/required/输入文件hash |

最底层正对照：256 个公开 synthetic seed（含0、1、5021、最大32bit、固定PRNG生成样本），full SHA-256 八个 word、前64个MT输出、所有 component phase 均与 CPython 完全相同，最大phase误差0。机器证据：[gpu_seed_throughput_result.json](gpu_seed_throughput_result.json)。

区间对照：40 个 synthetic seed，n=3..2048 以及每个推导区间的两个端点，87050 个实际 `rng.sample(range(n),3)` word-count 对照，全部一致；没有未完成 band。offset并集平均3.55个，最多10个，最高offset16。机器证据：[offset_coverage_model_result.json](offset_coverage_model_result.json)。这些统计只描述正对照，不作为排除异常长样本的理由。

GPU区间对照：256 个 synthetic seed × SHA/legacy，完整offset集合及fallback标志与CPU逐项相同。phase对照：三个已知seed×两模型×正常/强制短前缀，各检查seed附近完整candidate集合，一共12项全部相同。强制前缀4word确保CPUfallback路径确实运行。机器证据：[gpu_offset_seed_model_result.json](gpu_offset_seed_model_result.json)。

关键hash：

```text
RNG helper: 25ef28efbcce635c8e71799fa4dd340cad3359909eef74a15e7ac91b0f0711de
offset GPU: 5d5dff53f6c18fc6213f4d657159505aba88c9399f5c54fc4430e5c543ddcf55
offset CPU: 8f65962a9096fd1e63ece54c1abcc68011e70a665026b703d44633835875086e
scanner: b63c526c32a00a1c2c57f879a6d1292f8f37fe5fe6f4ed0986689681f1b439b2
public fingerprints: b8d26d9d816994f97d697ef4ba8154a457466bc967e21bd82a311acdf12e2269
```

## 5. 可恢复运行与结论边界

GPU环境为PRO6000 Blackwell 96GB、Windows CPython3.13.6/Numba0.67。独立研究目录为 `C:/Users/hedge/gosim-public-seed-pilot-20261003`。

执行入口：

```text
gpu_public_offset_scan.py
  --fingerprints <public_seed_fingerprints.json>
  --checkpoint <scan_sha256_offset_checkpoint.json>
  --mode sha256-v1 --full32 --batch 262144
```

每5秒原子保存checkpoint，绑定所有算法源码及输入hash，模型改变时拒绝跳过旧范围。`STOP_PUBLIC_OFFSET_SCAN` 文件存在时在批次边界停止。每批sleep2ms；若实测核超过30ms，后续批次减半。输出仅完整九phase候选和显式fallback计数，不回传几十亿浮点数组。

完整无匹配只能排除：指定master整数范围、派生模式、公开源码的抽样/三component三harmonic消费顺序、中心池范围、当前公开phase误差容忍度的组合。仍未覆盖：更大master空间、非整数/其它派生、其它生成版本、footprint之前额外RNG消费、不同谐波生成机制等。

即使完整类别和required也匹配，下一步仍需验证目录一致性及独立天气/事件/请求配置。SHA-v1分离随机流，catalogue MT状态不能直接预测其它流。研究“生成规律”与声称“恢复全部隐藏未来”之间还有这些检验步骤。
