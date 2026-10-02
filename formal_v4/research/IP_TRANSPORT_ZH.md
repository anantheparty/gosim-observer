# CD2 IP 直连与平台出网验证

2026-10-03 JST。IP直连用于区分DNS故障与无外部路由；不会改变评测容器网络配置，不使用模型代理转发GPU请求。

## 客户端实现

`remote_planner.py` 可接受私有配置 `connect_ip`。TCP socket直接连接字面IPv4/IPv6，不调用DNS。URL原始hostname仍用于TLS SNI、证书主机名校验及HTTP Host，因此不需要关闭证书校验或为IP签证书。

本机正控禁用服务hostname的DNS查询，GPU health仍成功，耗时.144秒；`getaddrinfo_calls=[]`。把TLS hostname改为不匹配名字时，连接抛出`SSLCertVerificationError`。结果见 `results/cd2_literal_ip_health_20261003.json`。

测试私有包 `observer_cd2_ip.zip` SHA256：`31f5b84f34dc99c76878e848d0dfc8a048b9b291f8c7f286d66399f2354a84f2`。保持算法和决策配置，仅修改IP客户端、私有连接配置及构建指纹。已通过电脑控制上传，先用免费准备/接口检查验证，不启动第二次四卡评测。

## 官方实现的限制

官方仓库commit `f2205aaffcc923bdc1abb91b2c131bb7b82df7b2`：

- [job_runner.py](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/project_platform/job_runner.py#L151) 接受主办方 `restricted_egress` 开关，启用时项目只能访问模型代理。
- [egress.py](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/project_platform/egress.py#L246) 建立Docker `--internal` 网络，没有外部路由、gateway或masquerade；唯一可达的sidecar只能转发到固定模型端点。

源文件SHA256分别为`81cda2488ac3305ebdbb9741a25e0b90e3d2cf081c49c0a304a91c89b63b0748`和`ae4b44578f751174ca8a5ce799688e3fb72d5e974c48e71f28141d7250f4f38f`。代码说明“若该开关已启用，IP也无法连接”，尚不能仅由此前DNS失败断言实际开关值；免费IP检查用于得到运行证据。

## 平台实测结论

IP私有包免费公开接口检查正常结束，未确认该版本或启动第二次正式评测，日配额仍4次。原始代码指纹`b2feb261b658a0ec04751228d2e2c3f049df5096c46e15aeeebd7d98070bdf34`。

云端agent.log：

```json
{"remote_check":"failed","exception":"OSError","errno":101,"seconds":0.009}
```

Linux errno101为`ENETUNREACH`（Network is unreachable）。这次没有DNS查询，直接连接IP仍立即失败。运行环境确实缺少可用外网路由，与官方internal-network实现一致；但项目无法直接读取主办方开关值，所以不声称已读到该布尔配置。

程序CPU fallback完成公开场景，`remote_calls=0`，总分336.142734、计时35.262秒。这个分数只用于接口检查，不能与α–δ成绩比较。公开场景也因CPU墙钟候选截断等因素与前次检查产生不同轨迹；不是IP客户端带来的科学收益。完整结果和原始/规范化哈希在 `results/cloud_cd2_ip_public_test_20261003/`。

## 全季收益判断

GPU应比较完整四卡得分，包含通信和900秒预算。单步候选更丰富不能证明全季分数单调增加；但已验证的同源GPU相位扩充四卡全部提高，平均+132.981588。在线连接成立时可以优先采用这套更强搜索；在线网络不成立时，GPU仍用于离线算法验证，CPU迁移保留几何候选结构。
