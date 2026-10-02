# CPU phase24 + terrain 完整对照

| 卡 | phase24 | 加terrain | 差值 |
|---|---:|---:|---:|
| L1 | 6206.367823 | 6200.856777 | −5.511046 |
| L4 | 6095.293215 | 6080.065472 | −15.227743 |

单terrain未晋升。L1首REQ3→4但不到6；L4科学+33.431822，但漏掉V4T005316扣50。详细分项、官方结束状态与曝光证据见 gate_summary.json 和各卡完整输出。

重复agent源码已删除，原68文件可从Git `archive/terrain-gate-20261003`、commit `88fb71c351234d48e81e0d105fb571958bb9e345`恢复。source_manifest.json保存SHA256和源路径映射；仅保留必要entry/config。

重新回放前，在仓库内执行：

```sh
python3 formal_v4/results/terrain_cpu_phase_L1_20261003/restore_candidate.py
```

恢复程序逐文件校验SHA256，不依赖目前研究源码的版本。官方runner位于 formal_v4/upstream/gosim-observer-examples/runner/run_local.py；card使用该公开包local-cards/L1或L4，agent-cwd为本目录agent，入口为 `python3 -u agent_terrain_cpu.py`。
