# 真实GPU与NumPy导出检查

2026-10-04 JST：`source_manifest.json`描述源码冻结时GPU尚待检查；当前检查已经完成，以`cuda_export_audit.json`和`ROOT_GPU_VERIFICATION.json`为准。五份模块和三份公共输入与GPU主机字节一致。

真实rank64公开状态：7800目标×44维、252全局维、17指派维、17动作维；结构模型6598参数，flat控制6507参数。PRO6000上随机未训练权重的前向/反向通过；NumPy导出最大差8.58e-6，置换最大差7.45e-8。Windows特征构造18.61ms，NumPy推理3.94ms，不能当训练或整季搜索速度。

未读取teacher标签，未执行optimizer，未改变参赛程序或得到NN分数。导出不能开启calibrated标志，默认返回原native动作。原始公共ledger被压成近似统计，不能称为精确Markov状态或一般失效窗口的无损压缩。
