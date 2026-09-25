# 八关键天区上界的容量价格直接优化

本试验只处理公开 `dev-reference` 实例。现有 21,796.70 分无条件上界的容量价格来自另一个全局区间 LP；这里固定八关键天区集合，对**实际使用的请求条件投影上界**直接调价。搜索只提出非负整数分价格，最后仍由完整候选弧审计、原投影 DP 和全部请求子集枚举出具证书。

## 模型与次梯度

固定关键天区集合 (K)、外侧无标签动作收费 θ，以及全部 17 个可获奖请求都完成的分支 (b)。令 (E_i^b) 为天区 (i\notin K) 截止时间前可作为首次成功曝光的全部弧；非强制天区另有不访问的零选项。全请求条件上界可写成

\[
U_b(\lambda)=\sum_t\lambda_t+\sum_{i\notin K}M_i^b(\lambda)
+D_K^b(\lambda,\theta)+R+\sum_{i\notin K}\theta_i,
\quad \lambda_e=\sum_{t\in e}\lambda_t,
\]

强制首访的外侧天区取 (M_i^b=\max_{e\in E_i^b}(q_e-\lambda_e))，其他外侧天区还允许零选项，取 (M_i^b=\max\{0,\max_{e\in E_i^b}(q_e-\lambda_e)\}\)。其中 (D_K^b) 是完整 150 秒游标图上的精确投影 DP，仍保留八块的首次完成位、等待 OR 罚款、天气中断和请求截止。对两个 RQ0004 选择取较大值。每个外侧最大值和 DP 都是有限个仿射函数的最大值，因此 (U=\max_b U_b) 关于容量价格是凸的分段线性函数。**任意非负整数分价格均有效**；只有 DP 在该价格下的实际计算结果可作为原题上界，主问题的代理目标不可直接当作证书。

从一个实现外侧最大值的首次曝光弧，以及 DP 实现其最大值的八块首次曝光弧，可得到次梯度

\[
g_t=1-\#\{\text{所选首次曝光弧覆盖时间格 }t\}.
\]

程序先用该梯度做整数分线搜索；随后在目前有正价格或曾出现重叠曝光的时间格构造局部切平面 LP，加逐格信赖区间和 (L_1) 稳定项。每个 LP 输出仅是下一份候选价格，候选都重新运行原投影目标。这个稀疏主问题的下界**只针对其固定价格坐标和信赖区间**，不属于原调度问题的全局上界。

## 试验结果

固定 `K=(T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015)`，原价格 220 个格非零、统一 θ=140 个百分之一分时，完整请求条件界为 **21,796.70**。重新扫描统一 θ，135 个百分之一分把它降至 **21,794.30**。稳定切平面价格搜索进一步在 34 个时间格调整价格（其中 224 个格为正），得到统一 θ=135 个百分之一分的条件界 **21,792.96**；RQ0004 两个选择分别为 **21,791.96** 和 **21,792.96**。新价格文件见 [best_prices.npz](results/projected_price_search_prox/best_prices.npz)，SHA-256 为 `cc9cc30fd29b3e050f3bbe72a88c66dfd033d6a2c3de6ab94225ccb5fa995d65`。旧/新价格下实现松弛界的逐块首次弧见 [relaxed_arc_choices.json](results/projected_price_search_prox/relaxed_arc_choices.json)。

导数实现已用原 `conditional_projected_dp` 在基准和两组扰动价格/θ 上逐整数分交叉核对；30 个单时间格有限差分均满足次梯度支撑不等式。最终价格上的[独立请求条件证书](results/projected_price_search/conditional_new.json)给出同一个 21,792.96 数值。[全量标量审计](results/projected_price_search/projection_new_audit.json)检查 918,757 条成功曝光弧、3,044,352 个标量起点及 12,030 个天气中断实例，分数包络违例和漏边数均为零。[全请求子集证书](results/projected_price_search/unconditional_new.json)重新枚举 131,072 个获奖集合与 196,608 个 RQ0004 分支，最大仍是全部 17 个请求获奖时的 **21,792.96**；恰好 16 个请求获奖的最高界为 **21,610.58**。因此这是对任意合法决策文件成立的**无条件上界**，距已验证可行分 21,119.494551 仍有 **673.465449** 分。

## 复算

```sh
.venv-solver/bin/python projected_price_search.py \
  --iterations 0 --bundle-iterations 30 --bundle-radii 2,5,10 \
  --bundle-prox 0.5 --seconds 180 \
  --out results/projected_price_search_prox
.venv-solver/bin/python bounds_practice_projection.py \
  --prices results/projected_price_search_prox/best_prices.npz \
  --key-set T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015 \
  --theta-cents 135 --audit \
  --output results/projected_price_search/projection_new_audit.json
.venv-solver/bin/python bounds_request_projection.py \
  --prices results/projected_price_search_prox/best_prices.npz \
  --keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015 \
  --theta-cents 135 --out results/projected_price_search/conditional_new.json
.venv-solver/bin/python bounds_request_unconditional.py \
  --prices results/projected_price_search_prox/best_prices.npz \
  --keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015 \
  --theta-cents 135 \
  --projection-certificate results/projected_price_search/projection_new_audit.json \
  --conditional-certificate results/projected_price_search/conditional_new.json \
  --out results/projected_price_search/unconditional_new.json
```

容量价格的直接优化只收紧了上界 3.74 分，当前尚不能凭它断言 21,119.494551 分已达全局最优。主要未弥合的松弛仍是 56 块外侧天区的逐块独立首访及请求见证路径占时。
