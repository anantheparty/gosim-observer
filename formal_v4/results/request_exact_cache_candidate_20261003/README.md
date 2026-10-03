# 独立 Request 严格等价缓存候选

**官方公开测试通过，指纹一致；20:09 JST 已确认，20:10 JST 已启动四卡完整评测。公开测试432.668244分，59.384秒，0远端调用；公开卡无REQ，完整分数待结果。**

- ZIP：`/Users/kamico/Downloads/observer_request_exact_cache.zip`
- ZIP SHA256：`e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`
- 官方源码指纹：`7bdc340f6247fc0ce961d68c395eded9d88908db34713493120c231d3ef4b81a`
- 70947 bytes，29 files。

## 来源与行为

来源是冻结的 `observer_request_phase_gpu.zip`，SHA `bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec`，原官方源码指纹 `75fa4058539fbe28fafd0e56d4fab0cc8af0108d7cbb6ec87ee1f268a126c0d5`。

保留其中所有原算法源文件和 `policy_config.json` 的原始字节。仅新增 `research/request_exact_cache.py` 与 `research/agent_request_exact_cache.py`、来源元数据；现有文件仅修改 run入口、禁用可选remote的runtime、重新生成build manifest。αβγδ都使用 Request 路线，没有portfolio分卡选择，也没有新参数。

wrapper先导入冻结的distributed entry，再在first initialize之前绑定 `policy.SpatialPlanner = ExactCachedRequestRemotePlanner`，此类继承 `ExactRequestCacheMixin, RequestRemotePlanner`。Policy构造时断言实际planner类正确。RemotePlanner factory同时改为DisabledRemote，runtime严格要求enabled=false与enable_search=false；health返回disabled/0秒，不创建API会话，不读取注入的OPENAI凭据。不使用socket或token文件。

缓存只复用同一次build/同一start相同中点计算以及scienceprice的同时间geometry/publicquality；不改变候选集、duration、targets、program、切分/累加/比较/tie顺序。每次build前后清空price缓存、中点缓存按build serial及start隔离，数组额外缓存上限16 MiB。原stable policy.py、原两个冻结ZIP、已运行portfolio ZIP都未修改。

## Gates

8个严格JSONL initialize/choose/finish测试全部通过：四卡×缺OPENAI环境或dummy环境。网络 connect/connect_ex/create_connection/getaddrinfo 和OPENAI_API_KEY/OPENAI_BASE_URL读取都用stub禁止，0次尝试。每卡生成有效observe，实际类为 `ExactCachedRequestRemotePlanner`，CPU baseline调用1次、remote0；缺环境与dummy环境动作hash完全一致，进程正确退出。

随后从候选ZIP解包、实例化实际wrapper的 `ExactCachedRequestPolicy`，取得其实际planner，与冻结原 `RequestRemotePlanner` 对照完整published δREQ2。453列的顺序、每列所有字段、完整DP、6条选中的执行动作逐项bitwise相同，pool SHA为 `e06f01083c49e05e70c8b9431c3f99ccf20af743a75b5293063148456f7fc68f`。同机器单次原版13.501s、缓存8.633s；该数据只说明构建计算加速，不是云端整卡成绩。中点缓存峰值6.3168 MB。

所有build manifest SHA、官方ZIP校验、冻结原文件字节一致检查通过。实际私有runtime token匹配0，hidden/server文件0；公开initial由六个public文件重建，ledger/messages来自本队公开下载输出。完整窗口gate使用的REQ/输出只存在测试临时文件，不打入候选ZIP。

详见 `package_gates.json` 与 `exact_cache_provenance.json`。本子任务没有UI、提交、评测、部署或Git index操作。候选可用于后续单次四卡对照，但去掉health耗时会改变剩余wallclock，不能保证重现原分数，更不能把局部加速当整卡加速。

At 20:28 JST, delta completed with **6423.086757** and 587.273 accounted seconds.
All action, decision, message, observation and score-report bytes match the
original Request delta. The three other cards are still running; no full-batch
mean is available yet. See `../cloud_request_cache_delta_20261003/`.

All four scores are now downloaded and verified. The measured mean is
**6735.09250250**. Alpha/beta expired at the global deadline; gamma/delta
completed. Full evidence: `../cloud_request_cache_batch_20261003/`.
