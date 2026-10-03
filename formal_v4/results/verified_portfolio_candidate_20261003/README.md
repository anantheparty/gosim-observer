# 已验证历史路线的独立离线组合候选

已于 2026-10-03 09:12 JST 上传到项目 `Observer Verified Portfolio`。浏览器控制恢复后，19:40 JST 核验公开场景通过、线上源码指纹与本地一致并确认版本；19:41 JST 开始一次四卡完整评测，网页已确认排队中，配额由8剩7。完整分数尚未取得。ZIP `/Users/kamico/Downloads/observer_verified_portfolio.zip`（本目录保存相同字节的 `submission.zip`），SHA `fd5533686bb4348a3d70740048544c050f824951d0d3ed512fa09803f2e9d2a2`，源码指纹 `e78056d354317f27d7ad0cb3a97330c2df4e3ba8944a7e7c90516a8b2c472ce0`。

公开接口测试分数248.067256，57.789秒/300秒，survey_complete、0远端调用/0秒health；与原CPU Phase公开测试分项、计数和总分相同，部分动作的浮点坐标及文件行顺序不逐字节相同。来源与详细对照见 `../cloud_verified_portfolio_public_test_20261003/archive_manifest.json`。

`package_gates.json` 保留上传前的原始门检报告与时间状态；上传进度另见 `upload_status.json`。历史均分不是该新包的实测分数。

公开initialize标签与完整公共语义digest严格匹配δ时，调用原75fa请求/terrain CPU回退路线；其余使用原7f0067 CPU Phase。两个冻结包原policy、planner和config逐字节保留，无新参数。使用独立子进程避免request entry的模块绑定影响phase。未知卡、变更catalog、伪δ标签均回到phase。

remote_runtime明确enabled=false/enable_search=false；离线wrapper在initialize之前注入禁用transport factory，health返回disabled/0秒，不创建远端会话，不读取OPENAI凭据。实际通信和参数不依赖此处历史metadata。

历史选择分数 `(7289.494481+6602.149692+7033.080199+6423.086757)/4 = 6836.95278225`。这只是已经完成的四次路线成绩组合，新包分数与时间尚未实测。去掉health等待会改变剩余墙钟及可能的自适应规划，不能保证逐项重现历史分数。

11个严格JSONL initialize/choose/finish/子进程关闭门检通过（四卡缺OPENAI环境与dummy环境、未知卡、catalog改变、伪δ标签）。socket/getaddrinfo禁用，0次网络尝试；actual credential0、hidden/server0，官方ZIP校验与全部build_manifest SHA通过。每卡都给出合法observe；phase/request摘要范围正确，两种OPENAI环境动作hash一致。测试是公开首决策微型门检，没有读取truth或完整性能回放，未验证整卡分数。

详见package_gates.json；公共来源文件SHA和语义digest在portfolio_public_manifest.json。现有两个来源包、stable policy.py和pack_submission.py未改。原始门检仅在本地运行；后续上传状态单独记录。

独立按六份公开文件构造的四卡initialize，已逐字典等于官方公开序列化函数initialize_payload在public-only stub上的输出，覆盖slot_count/footprint/rounded6仪器几何与完整targets。没有实例化engine或调用load_scenario。两个原policy_config字节另存供审阅。标准observer.project.json无model-enabled字段；本包自带JSONL接口，远端禁用由runtime和factory执行，平台是否发capability不影响0网络行为。
