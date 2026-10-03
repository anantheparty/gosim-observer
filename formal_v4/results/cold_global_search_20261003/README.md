# 独立整季随机搜索：完成公开本地强初解对照

本轮先从官方评分/协议独立建模，之后才读取已有强策略轨迹。没有修改production或平台提交。

## 实际强初解结果

| 本地卡 | 原完整强排程 | 600秒搜索后官方native | 增加 | 科学增加 | required缺失 |
|---|---:|---:|---:|---:|---:|
| L1 | 6348.155319 | 6409.988920 | +61.833601 | +11.931757 | 2→1 |
| L2 | 6949.795139 | 7008.567151 | +58.772012 | +8.717827 | 3→2 |

两请求奖励仍为200，报告仍为100。原样初解重放的score/components/counts/decisions逐字门检通过；观测内容逐字段一致，CSV行序可以因assignment字典顺序而不同。全部原始短曝光进入候选池，L1含667次短于900秒的曝光。新候选按官方逐目标积分计算，并重新核验geometry和request窗口；共200条新曝光抽查最大误差低于4e-12。两卡最终native与搜索模型的总分误差低于5e-7。

使用绝对整数秒的曝光列、best-only全季账本、required/REQ/Jain结算及固定原报告时点。搜索以原完整排程启动，采用群体候选与随机破坏/修复，90%单晚、8%双晚、2%非连续四晚。单晚产生大部分实际最佳解提升；双晚科学贡献约2.988/0.769，四晚本轮没有贡献。按连续incumbent增长记账不能证明算子的独立因果优势。

完整结果见 `continuous_summary.json` 与 `continuous_L{1,2}/report.json`；完整可执行动作在 `continuous_L{1,2}/optimized_actions.jsonl`，官方本地输出在 `optimized_native/`。

**范围：公开本地truth的先知方案、有限候选池、原报告时点固定。尚不支持L3/L4的回溯data loss，也没有在线生产提分、平台新分数或全局最优证书。**

## 初版与消融

初版最短900秒、按900秒栅格生成曝光，L1贪心4943.056492→LNS5346.826857，L2为5132.796409→5495.837709；两卡官方native验证。它们低于强策略，不能据此声称生产提升。

同样100秒L1消融，单晚修复5434.5573，高于多晚5346.8269约87.73分。大邻域每次更贵，不能只按邻域尺寸推断优势；后续因此使用高吞吐单晚主算子并保留少量联合算子。

## 复现

```sh
.venv-solver/bin/python formal_v4/research/cold_global_incumbent.py --card L1 --source gpu_direct_20261003 --seconds 600 --anchors 3 --seed 407
.venv-solver/bin/python formal_v4/research/cold_global_incumbent.py --card L2 --source gpu_phase_followup_20261003/phase --seconds 600 --anchors 3 --seed 407
.venv-solver/bin/python formal_v4/research/cold_global_continuous_report.py
```

原评分引擎、公开输入、初解动作及源文件SHA见 `artifact_manifest.json`。pickle候选池与quality矩阵是可重建缓存：保留本地、在Git中忽略，recipe和hash仍记录；其中一个原始缓存超过GitHub单文件大小限制。重建不依赖缓存文件。模型/geometry结算与实际平台alpha–delta是不同数据，不能跨数据比较分值。
