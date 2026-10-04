# Compact public opportunity pattern master

固定有限 science-only 模型的算法研究。只复用了 `cold_public_opportunity_cost_20261004` 的 W90501/W90502 public-only 零历史 pilot。报告在 `formal_v4/research/compact_opportunity_algorithm_20261004.md`。

`pattern_master.py` 是算法核心；`run.py` 是两 public pilot 的选择器入口，读取相邻旧研究目录并逐文件核对旧 manifest。完整用到的旧源和 public 输入另按原 SHA 冻结在 `frozen_prior/`，receipt 为 `FROZEN_PRIOR_SOURCE_RECEIPT.json`。未保存 truth 或 generated-worlds 目录。

已有 runtime 的机械重现命令（本轮已经运行，主代理无需再跑）：

```sh
PYTHONPATH=/Users/kamico/.cache/uv/archive-v0/HpGhR81W0uAa5ndjg6p5V OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /Users/kamico/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 formal_v4/results/compact_opportunity_algorithm_20261004/run.py --world W90501
```

W90501 全五分支完成，首动作 proposal 为 `pilot/W90501/PROPOSED_FIRST_ACTION.json`。W90502 按预声明 24 轮停止；`STOP_ARTIFACT.json` 明确没有 proposal、common controls 或 winner。其 initial lower/feasible upper 和 sigma/lambda/repair 仍完整保存。

`PATTERN_CONTRACTS.json` 是本算法的新合同；`PERSISTED_DUAL_CERTIFICATE_AUDIT.json` 直接评估保存的图与 60 轮价格，不运行 solver；`SERIALIZED_FEASIBILITY_AUDIT.json` 检查五条 master support 和可执行整数 future controls。`FIRST_MEASUREMENT/` 保存补证书日志前的源码、原成本与全部结果；两个 `FAILED_*contracts*.log` 保存早期机械错误。

所有收益都属于固定 seasonal C/E、clear mask、有限 pointing/start/duration 候选域的科学代理。本轮未执行完整 controller/天气评分、正式 900 整季、训练、部署或浏览器提交。
