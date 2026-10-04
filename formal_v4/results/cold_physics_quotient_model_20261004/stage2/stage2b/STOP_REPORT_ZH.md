# 连续物理商模型 2B：生成完成，拟合未启动，按用户要求收尾

2026-10-04。用户要求提交后收尾、写报告供其思考，再继续；后续研究启动授权已撤销。没有启动 GPU fit、模型选择、数值 export fixture、validation、test、正式900季节或部署。CUDA child PID 为无；production20/50ms成本门维持失败。这里没有 NN 提分或失败结论。

## 已完成

- stage1 11项文件与 stage2A 351项文件保持原 SHA。stage2A 四个 fresh world PASS，共59,059候选、3,745官方scalar对照，最大误差8.88e−16；完整原输出、wait控制、两个机械失败源/world/log均保留。
- 2B source 在生成前经 root 独立 SHA/AST/member审查并私有备份。最终 freeze `3a1e822aae54cad17716c40a6a9b2ff749972485b93975b73be166770dcc653d`，parent70 source原样 + 新9项source/locks。source package SHA `050ace57a3634a21a2ed8012d02001307a324d8d3a0b57b197fefbf0eee32aa7`。
- 新独立 train96/cal16/val24（共136）全部生成 PASS，耗时713.180872秒，共1,977,614条候选标签。只使用冻结官方source、新生成天气/事件/fault及公开initializer；旧data/cache/model/truth不消费，四pilot也未进入train/cal。
- 全部136 NPZ、cases、原point actions、worker receipts、最终136PASS receipt已在本机 `local_datasets/`。原始完整world、host truth、公开short execution、historyjudge与Docker logs/inspect保存于Rhodes独立目录，5170个文件已有逐byte SHA manifest。
- 136 world仍未出现实际report状态，REQ为空。缺口保留；schema支持不能当作真实healthy-report/REQ支持证明。

## 精确产物与恢复路径

| 产物 | SHA256 | bytes |
|---|---|---:|
| DATA_TRAIN.tar.gz | `2bf8cbcbd4dbe8da105366e6582d6e804fa2b76a0c9d3dab6e2cc51370be4c48` |129,400,471|
| DATA_CALVAL.tar.gz（含最终136PASS receipt） | `b9c2554781793c175a2e3b58a0c4436b4c2c839e801a6b46f25424af487ccca6` |53,880,326|
| ALL_OUTPUTS.tar.gz | `8ed699b5d2127acf1d3809e527bf6dfed32e486a36d41a7221b99e5abb909af2` |290,405,561|
| ALL_OUTPUT_MANIFEST.json（5170 files） | `7a78cff3a6d931fba79788048ae99d8ad59e81e9e6a36b25ffc9a7bd72a5d793` |见文件|

本机路径均在当前 `stage2/stage2b/`；训练/校准/验证已解包到 `local_datasets/datasets/{train,cal,val}`。完整raw位于Rhodes `/tmp/physics_quotient_stage2b_20261004/output`；同目录上层保存source archive、ALL_OUTPUTS archive/manifest/receipt、generator launcher PID记录。root可独立备份，无须重生成。

训练数据首次 `scp -3` 因reverse-forward gateway断开exit1，1,827,840 bytes partial与失败hash在PRO自有transport/failure目录保留。随后改用8MiB内容hashchunks + 5s keepalive，实际完成train4/16（part0000–0003），每chunk约267–294s；后续gateway不可用，producer自行exit1，各失败partial/log保留。calval0/7。未因传输问题更改source/data/gates，也未拿partial启动fit。

完整raw首次本机下载timeout exit255，保留190,878,720 bytes前缀；收尾只恢复这份已生成archive。rsync append 于09:45:41 UTC完成，290,405,561 bytes wholeSHA匹配，解包后5170-file manifest逐项bytes/SHA全部匹配。完整raw已在本机 `raw_outputs/output/`，见 `ARCHIVE_COMPLETION_RECEIPT.json`。该归档恢复没有启动新研究。

## 计算停止

`STOP_REQUEST_RECEIPT.json`记录：owned generator PID2956637已退出，所有本阶段owned Docker running数0；慢chunk producer及其子SCP不在活动进程表；没有GPUfit/CUDA child；未触碰外国进程。所有生成容器、source、数据与失败证据保留。root的private GitHub draftasset上传实际EOF、exit1、资产数0；全部545项训练范围文件已在private commit `f5d9cc891bf7aa9e79db6196753165c96ceacac4`。本分支不再请求或启动PRO下载/fit。

## 留给后续思考的模型与采用条件

待评估的普通网络预测当前曝光联合 `P(b,R | public history,current publications,public trajectory,duration)`，R=Q/Hbar未饱和商。未来flux/weight/best/program/cap在解析层处理，G先对band/R积分再fiber max。它是当前曝光marginal近似；单target历史band反演不是多slot联合posterior，不提供共享future path或未来复访Emax。

如果以后重新授权，冻结的计划为 full/current 同一5963→128→128→39模型、各12epochs，cal world等权NLL选checkpoint和25格temperature×sigma，再由cal选择full/current。val必须同时相对完整原动作与同finitefamily point-rescore，两个pairedworld95%lower均>0。没有本轮fit结果，不能用已生成val救source、调阈值或新开test。

已有point-rescore采用旧public point_distribution的起始时刻H/C/E与方向heuristic；新模型解析外层使用公开积分Hbar。因此即使后续同时赢这两个控制，支持的是“quotient密度 + 解析已知物理”组合当前决策价值；尚不能把全部gain因果归为密度独立校准。原controller还处理任务、report、未来损失等目标；finitefamily当前science/sec不是全赛最高分。

新trial offline前瞻预算900s/model、16GiB CUDA allocation仅存于独立EXECUTION_LOCK；stage2A原MODEL_CONTRACT不修改。已失败的production额外成本median20ms/p9550ms/64MiB不放宽。公开history特征现有平均约85–88ms/state，若将来采用，需另冻结缓存/共享context实现并重新实测；本次未优化或证明生产成本通过。

## 数值证书静态审查边界

数值export fixture尚未执行，不能称已取得动作数值一致性证书。当前冻结`numerical_fixture.py`（SHA `b7df1203d291a9b7701265fa7c0a3c72ea1d60e08bb185e9d9427eb419a152a7`）除rows/assigned fibers/count之外，lines149–155还要求`original_target_indices_by_fiber`并检查每row的fiber→target index一致；只检查fibers/rows的描述不适用于这份冻结源。`decision.prepare_original_rows`从原action与公开target catalog正常构造该映射。证书边界在于helper接受caller构造的target index map，本身没有独立的target_id catalog，不能独立证明target_id→index映射；恢复时应先审查此边界。依收尾要求，本次不修源码、不运行fixture或新增测试。

## 私有归档与恢复映射

完整raw本机目录为`formal_v4/results/cold_physics_quotient_model_20261004/stage2/stage2b/raw_outputs/output/`。`ROOT_RAW_ARCHIVE_REVIEW.json`记录受root委托的只读归档复核，`RAW_RECOVERY_MAP.json`逐5170原路径列出bytes/SHA、Git路径以及与既有fit数据/父source/其他raw的同内容映射。Git暂存raw文件和元数据；290MB压缩运输tar与chunk保留本机，未重复暂存。内容同SHA的raw路径由Git同一blob自然复用；恢复目录内容不依赖重新生成world，压缩tar字节的原hash仍供现有本机archive核验。
