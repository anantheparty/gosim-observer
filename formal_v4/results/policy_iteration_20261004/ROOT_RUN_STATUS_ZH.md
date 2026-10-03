# 2026-10-04 JST 批量续局启动检查点

本轮目标是用真实重新规划的终局标签检验普通小型NN或策略搜索能否改善完整赛季。当前生产包与正式平台完整评分没有更新。

## 实际完成

- revision7四卡自然控制和L1早/晚严格过去前缀控制均完整复现READY全部动作、分项与总分。
- L1/rank64五条完整续局已结束：field +21.474136、short +41.425680、long −101.779266、program −125.395166；control 6362.021539。它们是同一真实未来世界的结果，不能直接证明可迁移的决策规则。
- root验证新增9个完整episode档案共154个成员的SHA与凭据扫描；之前3档案已归档。64份公开严格过去前缀压为一个43,119,417字节档案，成员和源锁逐项匹配。
- 小型6598参数DeepSets与纯NumPy推理已在PRO6000真实通过CUDA导出门检；13个合成准入反例通过。没有训练，未读取实际批量标签。

## 正在运行

Rhodes1 driver PID **973012**，启动 **2026-10-03 19:38:56 UTC**。准确预声明为64个公开状态组、最多320条完整季节，每个状态先完成相同动作/分数的control，再运行全部已冻结、互异且可用的分支。缺失与失败保留，不以奖励筛选实验。

8个workers使用物理核0–15，每季2CPU/2GiB，网络禁用、根文件系统只读。参赛进程只挂载只读源码、依赖、严格过去公开前缀及起初为空的公开输出目录。启动实证见 `bulk_live_proof.json`；首8组全部在终局文件出现之前冻结5个不同候选，见 `bulk_first_availability_proof.json`。

源锁SHA：`2e539ee19e06e3a87d0ffb261b223b64be9af9faafe9cc7033effc9cb84f43e3`。预计2.08小时，保守3.45小时；6小时停止启动新任务，已启动任务仍有990秒超时与清理时间。后续真实进度以远端PID/容器及 `bulk_progress.json`、`bulk_summary.json` 为准。

## 下一阶段

完整状态组先通过v2全部门检及档案完整性，再生成显式接受清单。清单引用原始 `control/public_capture/capture.json` 字节及公开features、initialization、availability、pair_audit；不能用重新排版后的capture代替原字节。

L1/L2只提供32个训练状态；L3验证，L4拟合时不打开。先比较小型结构模型、flat、ridge与native控制，不能用训练损失或相关动作对数量当作泛化。部署导出尚未校准，保持 `deployment_calibrated=false`。新策略必须完整隔卡回放才谈生产收益。

## 独立路线与周期机制

闭环GA已独立建模并验证抽象行为树的精确语法压缩，未运行真实GA策略季节。连续时长/完整field组合微域对强控制为负，已停止固定动作数扩参。另两位 `fork_turns="none"` 代理正在分别研究信息价值与可证状态商；先读官方题目独立推导，之后与既有实验查重。

现有每小时任务“GOSIM 独立算法探索”已更新，轮换遗传/群体、图论/网络流、剪枝、概率/信息价值、NN/RL，并先检查已有任务。只在实质进展、完成或失败时通知。

## 恢复档案

`archives/revision7_natural_*_rank64.tar.gz` 分别对应 `natural_control/<card>/rank_0064/control/`；`pilot_L1_rank64_*.tar.gz` 对应 `pilot/L1/rank_0064/<case>/`；late档案对应 `late_control/L1/rank_0858/control/`。解压 `archives/bulk_public_prefixes.tar.gz` 到本目录即可恢复 `bulk_prefixes/`。每个episode内 `archive_members.json` 锁定成员，外部manifest与root inventory锁定压缩档案。正在运行的远端原始文件保持可用。
