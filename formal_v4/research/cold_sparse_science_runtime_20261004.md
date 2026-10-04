# 保留 strong / faultv1 / debias 候选域的精确算子融合

2026-10-04。本轮先读官方 `v4_fiber_map.py`、`v4_scorer.py` 与真实 29file `/Users/kamico/Downloads/observer_request_exact_cache.zip`，再读 portfolio、debias 与旧 runtime/geometry 审计。新增文件全部在 `results/cold_sparse_science_runtime_20261004/`，没有读取 sealed L4。没有修改 beam、anchor 数、urgency、quality、rate、时间价或搜索预算；没有采用旧 native arrangement 候选扩张。三个正常入口均从当前原 strong / faultv1 / debias frozen source 运行。

## 1. 已交付与可用范围

已经冻结三个 package / ZIP：`strong_package`（36file）、`fault_package`（38file）、`debias_package`（38file），均从 `sparse_entry.py` 正常启动。该入口只在导入原入口前安装算子；fault 原 `wrapper.py` 与 `persistent_fault_guard.py` 逐 byte 保留，debias 原两个 source 也逐 byte 保留。每包的原 `observer.project.json` run 改为新入口，重算 `build_manifest.json`。strong 保留原27成员，fault/debias各保留原29成员；新增7文件见 `package_receipt.json`。

native Linux x86_64 库在 rhodes1 以 `g++ -O3 -std=c++17 -ffp-contract=off -shared -fPIC` 编译，运行依赖仅 libc。正式镜像已实际加载和执行成功，运行时不安装编译器、没有 C++ runtime/外部服务/子进程依赖。macOS arm64 dylib 仅方便本地复核。actor package 不带 workload fixtures、过去 action tape、host scorer/truth、cut/stop 或测分 harness。

根已接管 fault_fast / debias_fast 的 L1/L2 完整 2CPU/2GiB/900 秒门检；本子任务只跑算子和初始5决策，尚不宣称完整季节分数或完整季节提速。最终 source freeze 是 `FINAL_FROZEN_RECEIPT.json` 与 `source_lock.json`，包源在此之后不再改动。

## 2. 具体瓶颈与被拒绝的方案

L1 初始 fixed workload 的 cProfile：strong 416次 `_evaluate` 累计约.152秒，整体.259秒；4组 `coarse_numpy_local` 约.088秒。NumPy全部 `maximum.at` 仅.021秒（约8%）。单 debias 的400次细评约占.168秒整体中的.158秒。瓶颈主要是逐候选重复构建 raw/robust/science/terminal/value 多维数组、many small NumPy dispatch，以及 coarse centre×program×target 的广播数组。

先实现的 sorted-fibre `maximum.reduceat` 与全部原候选值/动作相等，却令一个 coarse case .088→.123秒，因排序/gather 开销较大。该方案拒绝，没有作为上线加速。没有把删候选、少时长或改变搜索objective称为优化。

## 3. 算法与等价理由

官方 gnomonic 几何与原 `_classify` 整段保留；field proposals、pool order、玻璃margin、原最多72时长的构造/取样也保留。只融合 score 算术与 fibre reduction。

对每个固定 field / duration / program，目标的原 value 是原 science 正部、required/Jain/request terminal、focus shadow subtraction 相加，再乘原 urgency；超出 up 时仍为−∞。C++逐项保持原运算括号、次序及阈值 `+1e-10`，禁用浮点乘加合并。逐 target 流式更新各 fibre 的普通最大值与 focus-eligible 最大值，并分别保存胜者。先到的同值目标保留，等于原 `argmax` 第一项。

每个 fibre 与其他 fibre 的耦合仅由原 quota regret 逻辑使用这两个 maxima。普通最大值、eligible 最大值、各自第一胜者因此是该候选函数的充分统计量。原 NumPy fibre sum、regret sort、完整/部分 quota、rate、plateau tie、program 与duration选择完整保留，避免改变 NumPy求和顺序。最终 winner 依递增 fibre 输出，同原 selected 循环。被 focus 强制的0/负值 eligible胜者保留；没有 finite eligible值的 fibre 不可能成为原强制集合。

fine 的大 `D×3×N` value/science/terminal 矩阵变为流式 score 和 `D×3×F` 两组 maxima/两组胜者，工作内存从随 local target N 放大变为随 fibre F 放大。遍历时间最坏仍O(DPN)，保留全部候选；没有声称全题global bound。

coarse 保留原 NumPy批量几何。每个 group 的 duration×program×target value 先计算一次，替代每个256-centre批次重复计算。native 接收同一 fibres/valid/up mask，只在 valid且up允许的 target/fibre 上更新 max，消除 `C×3×N`广播/scatter中间数组。没有改变 phases、排名、exact probe 或选中动作域。

数值等价的物理输入域是本包实际的有限float64、bool、int64 target/duration、int32 fibre数组。fine 入口检查连续内存，coarse显式转连续内存。正式原Policy产生的frame满足该合同；本轮没有声称能给任意NaN/非连续外来测试frame提供相同API行为。

## 4. 实际验证

macOS NumPy2.0.2，L1/L2各6个同输入 scalar ledger workload阶段：共9,760细候选（rate、center、duration、program、selected/fibres）逐值一致，155,924 phase候选逐rate `np.array_equal`一致，24次完整 choose 动作一致。fair交错3次无profile中位数的均值：strong .200080→.084605秒（2.365×），debias .106501→.055452秒（1.921×）。`benchmark.json`含每阶段全部 stats与parity；cProfile单独保存。

workload scalar scores/factors 是历史输出的算子输入夹具，并非原精确在线ledger/belief/terrain/clock复现，也没有在新actor中读取；其中factor不是要给actor新增teacher特征。所有比较两端都接收相同数组。公开catalogue/几何/日期来自L1/L2，未读未来天气标签。

Linux正式固定镜像 Py3.12.15 / NumPy2.2.6，2CPU固定18,19 / 2GiB / network none：原/新交错，先warmup一次再各3次中位数；12同输入阶段每类 choose动作均相等。strong均值 **.502823→.229765秒，2.1884×，节省54.30%**；debias均值 **.292330→.158435秒，1.8451×，节省45.80%**。详见 `fair_benchmark_linux.json`。这个数是 ordinary science/kernel workload，REQ build、policy/weather/terrain与host费用未计，不能乘到全季直接宣称全季提速。

Linux同镜像2CPU/2GiB额外1000组合，含zero flux、score正部门槛、negative Jain bonus、阈值/截止/可见时长、focus left=1/3/7/16/20：5,596,719个目标×program×duration value、所有fibre maxima和eligibility阵列相等；1000完整细候选rate/duration/program/selected/fibres也相等；2000 coarse batch maxima与eligible maxima相等。`kernel_contract_linux.json`。这覆盖 quota完整/部分/不可完成路径，不替代真实活动REQ full-season缓存/裁短验证。

Linux2CPU16,17 / 2GiB，原 strong、faultv1、debias各自与加速正常入口在L1/L2实际官方初始化后5决策：共6组×5对公开request/response除各自wallclock完全相等，12个participant均退出0。host在第6决策结束，正常package没有stop逻辑。强原/新总wall约3.5→2.1秒，debias约4.9–5.0→2.9秒，含容器/初始化/host，非长季估计。证据 `short_protocol_result.json`、`short_protocol_evidence.tar.gz`。participant只挂只读自身package与NumPy；host拥有官方world，actor无truth mount。

## 5. 保留的失败及修正

三条失败记录在 `failure_history.json`。sorted NumPy方案被拒绝。native初版 coarse假定 advanced indexing产生C contiguous value，但NumPy可能产生Fortran布局，最大rate误差1.5725669877；冻结前已修复 `ascontiguousarray`，上述完整合同与官方协议在修复后执行。

第一版Linux公平脚本直接调用 debias child 并保留policy_config的.22秒普通timer；Linux旧函数较慢会少评候选、新函数完成更多，触发动作差异。这是harness未模拟当前生产 `debias_entry` 已明确传入的`planning_budget_seconds=1e9`。仅公平脚本双方改成既有生产child调用值后重测，actor package未改。失败日志 `fair_timer_harness_failure.txt` 留存；不把不同候选域的失败计时包装为same-domain提速。

## 6. 复现与后续门检

本地：`.venv-solver/bin/python results/cold_sparse_science_runtime_20261004/kernel_contract.py`（需从formal_v4的父目录用完整路径；脚本自身解路径）。Linux：固定镜像、mount自有experiment+NumPy，执行 `kernel_contract.py` / `fair_benchmark.py`。正常部署单独用三个ZIP之一的 `observer.project.json`，无需测试脚本。

完整季节交给root既有同源driver：保持2CPU/2GiB/900、官方world/全公开反馈、原cache/terrain/calibration/report/REQ裁短/预算语义，比较现有faultv1和strong完整control。REQ缓存偶发重建spike、Policy/host成本仍存在，本轮没有将新增精确field加速与另一尚未验证策略混作一个包，也没有通过降低预算保证完成。
