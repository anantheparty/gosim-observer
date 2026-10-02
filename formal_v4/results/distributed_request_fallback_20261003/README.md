# 独立distributed入口：完整CPU fallback正控

运行时没有remote_runtime.json，也没有调用生产API。独立入口复用ModelGPUPolicy/ModelRemoteBudget、共享terrain后验，并通过新baseline hook执行CPUphase+本地future REQ。

L1完整6285.945725，REQ2/2、required缺2、report100、0invalid/错误报告，survey_complete，accounted310.453秒/900。相对于已验证CPU future-REQ deadline，actions.jsonl、decisions.csv、observations.csv、messages.jsonl四份文件逐字节SHA256一致。

153个冻结输入源码/引擎/卡文件逐项hash复查零差异；稳定Policy源保持不变。说明默认hook和budget/remote façade没有改变无远端情况下的可行轨迹。

真实API整卡尚未执行；等待云端评测结束，避免争用Phase队列。这是fallback正控，不能称为网络/GPU得分。
