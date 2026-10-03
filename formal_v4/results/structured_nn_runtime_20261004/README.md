# 独立结构化 NN 训练环境

2026-10-04 JST，已安装并真实验证，尚无比赛模型训练或分数提升。

- 主机：`elevatia-wsl`，RTX PRO 6000 Blackwell Workstation Edition，96GiB，driver 616.92，现有限功率600W。
- 独立 Windows 环境：`C:/Users/hedge/gosim-structured-nn-20261004`；Python3.13.6、PyTorch2.7.1+cu128、NumPy2.2.6。原有GPU RPC/Numba环境未修改。
- 官方 cu128 wheel 包含 `sm_120`；实际 CUDA 双精度16×16矩阵与CPU差 `2.220446049250313e-16`，反向梯度有限。初始化及该检查15.417秒，不能当作训练吞吐或搜索加速倍数。
- `runtime_ready.json` 是实际设备输出；`requirements.freeze.txt` 固定完整依赖；安装日志保留。准备脚本和验证脚本位于 `research/structured_nn_runtime_*.py`。
- 待完整自然重新规划教师通过后，使用普通结构化学生；小样本验证和隔卡完整季节得分是后续工作。

版本与安装来源：[官方旧版安装说明](https://pytorch.org/get-started/previous-versions/)、[PyTorch2.7 Blackwell支持说明](https://pytorch.org/blog/pytorch-2-7/)。这两个网页支持运行库选择，设备结果来自本机实际运行。
