# 在原整季有限 LP 的最优对偶面上选择价格

## 结果

状态：**完成，数值 KKT 门检通过**。本轮只做数学 LP 步骤，没有调用 GPU、新增 pointing、改排程或提交比赛。

输入仍是旧 α `cloud_cd2_alpha_20261003`，官方总分 7094.664204；当前 α 已验证 Phase 分数是 7289.494481。此处保持的是旧有限 master 的 LP 最优值，不是创造了新比赛成绩或连续全局最优证书。

| 项目 | 原最优对偶 | 二次优化后 |
|---|---:|---:|
| 已完成 497 个 mandatory 目标的 ν 总和 | 174.85448245 | **42.44615939** |
| 缺失三个 mandatory 的 ν 总和 | 150 | **150** |
| 原 60 候选中 reduced profit >1e−7 的列 | 60 | **21** |
| 这 60 列的最大 reduced profit | 66.26298513 | **14.92100868** |
| 原有限 LP 最大化值，未加评分常数 | 32078.51073733339 | 同一最优面 |

二次 LP 实测 2.448436 秒，整个捕获原模型、求解、候选比较阶段 5.603687 秒。模型有 51,703 个对偶变量及 21,541 个等式。结果表明可以合法地减少已完成目标的退化高价，而不用人为将 ν 清零。最小值仍有 42.44615939，原有限 LP 的其它约束限制了这些价格继续下降。

## 完整对偶的构造

直接截取未修改的 `season_column_dual_audit.lp_duals` 实际交给 SciPy 的全部矩阵及 bounds，原问题为：

```text
minimize cᵀx
A x = b
G x <= d
l <= x <= u
```

采用 SciPy 的最小化符号：λ 为等式自由乘子，μ≤0 为不等式乘子，α≥0 对应有限下界，β≤0 对应有限上界。完整对偶为：

```text
maximize bᵀλ + dᵀμ + lᵀα + uᵀβ
Aᵀλ + Gᵀμ + α + β = c
```

没有有限界的变量不创建该界的乘子。二次 LP 额外加入 **原最优对偶目标 = 原最优 primal.fun** 的等式，然后最小化已由历史排程完成的 mandatory 行价格 ν=−μ 的总和。原模型的所有 stationarity、符号、上下界和最优目标等式同时保留。

### Science winner 与 mandatory 上界

每个目标、每个曝光的 science winner 局部变量 z 满足 `z<=x_column`，目标 simplex 满足 `sum z<=1`。对应非负价 ℓ 与 ρ，stationarity 要求：

```text
ℓ + ρ >= science_upper
```

新列在给定 ρ 时的最小合法局部贡献是 `max(0, science_upper−ρ)`，不能省掉局部 winner link。

mandatory flag b 同时满足 `b<=sum eligible columns` 与 `0<=b<=1`。其 SciPy stationarity 是：

```text
−ν + α_b + β_b = −50
α_b >= 0; beta_b <= 0
```

ν 与 flag 的上界乘子共同决定这 50 分的 dual accounting。二次 LP 保留上界乘子，因此可以改变 ν 的分配而不改变原对偶最优目标。REQ 的单目标 flag、quorum flag 及它们的上下界也全部来自原矩阵，并完整纳入。

### 时间流与固定前缀

对未固定的时间流弧，原审计 LP 没有冗余上界；stationarity 给出：

```text
pi[end] − pi[start] >= sum local winner + mandatory + REQ prices
```

新列 reduced profit 为右侧最小合法贡献减去左侧时间弧价格。旧池中每个未固定弧必须非正。固定前缀弧的 `l=u=1` 必须保留 α/β；门检同时核验 `raw reduced profit + alpha_arc + beta_arc <= tolerance`。本轮 α 实例没有固定前缀弧，但代码保留了全部原 bound arrays，没有省略这些乘子。δ 尚未运行。

## 数值门检

使用原 primal 解与完整新 dual 核验，而非仅比较 ν：

| 门检 | 实测 |
|---|---:|
| stationarity 最大绝对残差 | 2.2582e−13 |
| 原 primal 与新 dual 目标差 | 8.0036e−10 |
| inequality complementarity 最大残差 | 7.4523e−10 |
| lower / upper bound complementarity 残差 | 0 / 0 |
| 原 primal 等式残差 | 0 |
| 原 primal 不等式违反 | 2.2204e−16 |
| 原 1,386 列未固定弧最大 reduced profit | 7.4523e−10 |
| 加 bound dual 后最大 reduced profit | 7.4523e−10 |
| 原 serialized ρ/ν/η 与捕获 LP 价格差 | 0 |

检查容差为 1e−7（目标/互补条件为 1e−6），原始结果未裁剪。HiGHS 出现约 7.45e−10 的乘子符号残差；这是浮点数值证据，不是有理数精确验证。不能把极小负价格直接提供给要求严格非负输入的 CUDA 张量检查，也不能无记录地剪裁后声称保留完整 stationarity。

原 60 个候选逐条价格复算与旧 GPU 精核结果一致，容差 1e−7。对 prepared 四个 case 的 start/end 使用已有节点上的 λ，记录前后时间弧成本；没有插值新的时间 potential。

## 可回溯文件

- `summary.json`：结果及完整数值门检。
- `pricing_duals_stabilized.json`：新 ρ、ν、η、pi、原 admissibility 及非零 bound dual。
- `full_dual_certificate.npz`：完整 λ、μ、α、β 与原 primal 解、cost、objective；包含 winner links、quorum 等 compact pricing JSON 未列出的乘子。
- `primal_matrix_hashes.json`：实际原 A/G、bounds 及逐行语义 tag 的 hash，供独立重建核验。
- `required_nu_comparison.json`：500 个 mandatory 的 ν 前后比较。
- `existing_candidates.json`：原 60 列前后 reduced profit 和分项。
- `prepared_case_time_costs.json`：原四个 case 每个已有 end node 的时间弧成本前后比较。
- `manifest.json`：源码、输入与输出 SHA256。

这一步改善的是有限列定价的方向选择。它没有表明余下 21 个正价列能提高整数净分，之前加入它们的有限 LP/MIP 未改善；更没有证明所有遗漏列均无改进。
