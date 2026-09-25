# K19 GPU 投影上界扫描

`gpu_k19_extension_scan.py` 以已保存的 K18 `T00045,T00001` 证书为固定基础，依次把剩余 46 个天区中的每一个加入关键天区集合。每个案例计算完整的 19 位时间–访问掩码投影 DP，上界取两条 RQ0004 分支较大的分数。`T00004` 与 `T00012` 会改变分支 DP 输入，因此各算两次；其余 44 个案例逐项核对 DP 参数相同后共用一次。总共最多 48 次 K19 GPU DP。

脚本首次运行时用 GPU 重算 K18，逐项对照已保存的两个分支、DP 分数、输入哈希与总界。容量价格和行动图仍来自已有审计文件。全局上界合并采用当前的“最多 16 个请求”证书 `results/practice_sixteen_request_reuse_k18.json`，其上界为 `2,111,925` 分币；脚本同时核对该证书的 SHA-256、容量价格哈希、K18 证书哈希、K18 输入哈希。旧 K8 请求子集证书的较松上界不能用于本次汇总。

## 运行

在有可用 CUDA 的独立 Python 环境里，从仓库根目录运行：

```bash
python gpu_k19_extension_scan.py pilot --state-dir runs/gpu_k19
python gpu_k19_extension_scan.py all --state-dir runs/gpu_k19
```

`pilot` 扫描按已保存 K17 排名的前三个尚未进入 K18 的天区：`T00043,T00009,T00041`。`all` 覆盖剩余 46 个天区。也可以只跑指定案例：

```bash
python gpu_k19_extension_scan.py select --tiles T00004,T00012 --state-dir runs/gpu_k19
```

三个命令共用同一个状态目录；已有的 `cases/Txxxxx.json` 自动核验并复用。默认在单进程中复用审计行动图和 CUDA JIT，以免每个案例重新编译。若需要每个案例的硬超时，可加 `--timeout-seconds 1800`；此时每个案例单独启动 Python 进程，开销较大。`--dry-run` 仅验证输入、价格证书及候选集，不运行 GPU，也不写状态。

状态目录的 `manifest.json` 固定 K18、价格、16 请求证书、源码和 CUDA 发射模式的哈希。`k18_baseline.json` 保存完整 K18 GPU 复核，`cases/` 每个天区一份原子写入的检查点，`status.json` 给出已完成案例中最小的上界与完整排名。程序异常终止后直接重复原命令续跑；若输入或源码改变，应使用新的状态目录。

这里求的是**上界证书**：它能缩小当前 `21,119.494551` 可行解与全局最优的已证差距，不会直接生成更高分的决策 CSV，也不向排行榜提交。
