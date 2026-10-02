# GPU Phase + terrain + published-future REQ：L1同源整季

2026-10-02 22:27:04 UTC开始。PRO6000 WindowsCUDA进程、WSL官方runner、每路900秒、无HTTP/代理网络。224个输入文件远端SHA256复查零差异。

冻结目录 `C:/Users/hedge/gosim-formal-v4-gpu-request-future-pair-20261003`。两路相同代码，config只有request_dp_mode=bypass/deadline不同；GPU固定1024anchors/max32768/exact256/refine32，Phase16seed/24边界/64精解。

共同源码：Policy e7ab68、GPU be40d5、Phase832e11、REQcommon517f9a、futurefield5a9531。后续新增distributed hook不会改变本次已冻结模块。

| 模式 | 总分 | 官方科学分 | REQ | required缺失 | accounted墙钟 |
|---|---:|---:|---:|---:|---:|
| bypass | 6303.779794 | 6203.856324 | 1/2 | 2 | 624.818秒 |
| deadline | 6417.474127 | 6217.652264 | 2/2 | 2 | 794.375秒 |

增分113.694333=科学13.795940+REQ100−均匀度0.101609。两路report100、survey_complete、0失效/错误报告。日志返回choose累计baseline/phase emergency均0；crop内早期baseline子调用没有独立计数，不能从该累计日志证明全部内部探测未截断。

deadline累计：6次建列165.0096秒，79次DP1.0254秒，6次请求曝光/6次裁剪/4次等待、0预测不可行/执行失败。请求调度的计算主要在建列，256状态DP本身很轻。

该语义修正对CPU和GPU同源整季均有实际收益。历史旧self-contained GPU REQ L1曾有6429.708723，仍比本次高12.234596；本次没有超越所有历史最好，也没有全局最优证明。实际网络版本还需额外延迟预算与独立门检。

完整报告、轨迹、配置原字节、pair_summary、input manifest均保留于本目录。
