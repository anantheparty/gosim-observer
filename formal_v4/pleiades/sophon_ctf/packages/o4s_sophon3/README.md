Sophon3 私有探测包，默认最后曝光指向木星。

`probe_config.json` 的 `dive_object` 可设为 `jupiter`、`saturn`、`mars`、`venus`；
同名环境开关 `SOPHON_DIVE_OBJECT` 优先。整个运行只选择一颗最后曝光的行星。

基于 sophon2 的 agent 协议、向量天球几何、光纤分类和超正常上限的字形证据，
改成轻量覆盖规划：900 秒曝光，优先每夜未测清的光纤，明亮目标帮助异常得分越过正常上限。
字形从首次确定异常之后的正分记录投票；天气关闭和零分不计为暗像素。
所有天文输入来自初始化消息；行星公式摘自官方本地练习 checker。
不依赖模型、隐藏文件或固定的练习字母、异常夜历。

末夜选择该行星仍高于地平线 1° 的时刻，发出 60 秒、空 assignments 的合法曝光后 finish。
真实条件未公开；这种曝光已通过四颗行星的官方本地检查器。
平台剩余计费时间低于 45 秒时，跳到最近可用行星曝光窗口，提前收尾。

Johnny：非本地 runner 且提供 SOPHON_RUN_TOKEN 时，以文档约定的 token-only 请求联系，
初始化和收尾各一次，单次 socket timeout 8 秒，daemon 线程；不跟随重定向，不用公共 anon key。
本地 runner 检测到 SAC_LOCAL_RUNNER 后完全禁止联系，即使意外注入 token 也跳过。
日志对 token/Authorization/secret/JWT 脱敏；不输出环境变量值或 JWT claims。

主要 stderr 事件：sophon_init、sophon_flash、sophon_glyph、sophon_dive_plan、sophon_dive、
johnny_response、sophon_message、sophon_snapshot_extra、sophon_finish_message、sophon_summary。
真实 receipt 可能由地面站在运行结束后另行加入产物，因此包内日志无法保证看到。
