# No.4 本地 Git 历史与对象审计

**未发现 No.4 的题名、bar/pass 判定、room214 线索或额外 Sophon 路由泄露。** 本轮只读本地对象，没有 fetch、网络/平台请求、凭证处理或仓库修改。

## 覆盖范围

| 项目 | 结果 |
|---|---:|
| HEAD | `373d94f32598073b4eff31c15794fcd3474722ae` |
| 本地 refs | 1 个 head、2 个 remote refs、55 个 tags |
| 全部 refs 可达提交 | 377；HEAD 单独可达 59 |
| 全部唯一 Git 对象 | 6,438 = 3,341 blobs + 2,720 trees + 377 commits |
| 文本扫描 | 3,275 text blobs + 全部 377 commit 对象 |
| 二进制原始字符串扫描 | 66 blobs，包括 18,470,751 字节视频 |
| `git fsck --full --unreachable --no-reflogs` | exit 0，无不可达对象输出 |
| 仓库边界 | 仍是 shallow；覆盖所有本地对象，不代表远端曾存在的全部历史 |

`cat-file --batch-all-objects` 的对象集合与 `rev-list --objects --all` 数量一致，没有发现只存在于对象库、未被 refs 覆盖的额外对象。tags 均未增加独立 annotated-tag 对象；提交消息也纳入了扫描。历史路径与文件名作了单独枚举。

扫描关键词包括 `Sophon`、`Johnny`、`Overlook`、`room214`（含空格/连字符变体）、`No.4`、`/desk/bar`、`/desk/pass`、`Take this pass`、`signed it myself`、`skip the rest of the house`、`THE SHINING`、`酒吧`、`通行证`。仅保存对象 ID、路径、匹配词类别与固定路由，未复制任意原始匹配行。

## 有内容的发现

| 证据 | 含义 |
|---|---|
| 文本对象：Sophon 56 次、Johnny 36 次、Overlook 15 次（按对象计数，可交叉） | 都落在已知 CLI 联系说明、引擎/测试、榜单 SQL/UI、相关提交消息；不是独立谜面 |
| `17d68bb` | 新增 contact-johnny 的旧 token 请求体说明；没有 bar/pass/房间服务实现 |
| `cd0ce1d` | 新增多 flag 表和提交 UI；明示写入方是私有 sophon function |
| 全部文本对象提取的路由 | 仅 `/functions/v1/sophon/contact-johnny`、`sophon/desk/flag`、`sophon/desk/files` |
| 新版 desk 的 bar、door、pass | 未发现公开实现、构建代码、路由名或题名映射 |

这里的词计数是对象版本计数，不是不同功能数量。同一文档多个历史版本会重复命中。

## 构建与二进制产物

唯一可见压缩 Web 示例为 `web/public/demo/baseline-dev-reference.html.gz`，对象 `b44e81548544a6eab026d1ad033b328d46b27da8`。已完整解压 **6,476,922 字节**并扫描，目标词无命中。未发现另一个打包后的 Sophon JS、source map 或部署 ZIP。

二进制原始字符串出现了两个文件中的短 `no4/no-4` 偶然匹配：

- `docs/assets/home-replay/desktop-dense.jpg`：1 处在 JPEG SOS 之后的压缩图像数据；附近只有约 41% 可打印字节。
- `web/public/media/survey-film.mp4`：4 处全部在 `mdat` 媒体数据区，附近约 29%–57% 可打印字节。

这些不是完整文本、元数据题名或路由，不能当作 No.4 线索。未做视频解码/OCR、隐写或密码穷举，符合本轮轻量源码/产物审计范围。

## 对下一步的影响

没有足够源码证据改变当前假设：bar 的动态 pass 可能与 No.4 有关，但公开仓库不能证明其验收时机、真假条件或副作用。也没有发现值得据此新增的路由。因此本审计不提出端点猜测；继续依赖已授权的基础路由与可验证运行内时序设计。

可复核清单：[no4_git_object_scan.json](/home/shu/kamico/observer/work/sophon_desk/validation/no4_git_object_scan.json)。其中保留各命中的对象 ID/路径、gzip 扫描结果和二进制匹配位置，不含凭证值。
