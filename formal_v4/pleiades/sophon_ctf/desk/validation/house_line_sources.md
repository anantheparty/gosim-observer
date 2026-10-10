# House of Leaves 日期定位复核

仅读本地最新提示与公开资料；未调用任何平台、desk、模型或凭证，也未提交答案。没有抄录按位置索取的小说正文。

## 核验结果

**平台提示混淆了两个不同位置。**

| 定位 | Pantheon 2000 版中的内容 | 置信度 |
|---|---|---|
| 导言中间，罗马页码 **xix**；日期 **January 5, 1997** | 这是导言引用的 **Zampanò 手稿注记**。日期后为谈论发现者出版该作品及收益归属的正文，而不是地点署名。其后继续谈到姓名、读者评价和时间检验。 | 高；大学学位论文直接引述并标 xix，作者网站读者年表交叉支持。 |
| **Johnny Truant 导言结尾，xxiii** | 署日期为 **October 31, 1998**，随后是地点 **Hollywood, CA**。日期不是 January 5, 1997。 | 高；研究论文与作者网站年表一致，另一研究著作明确引用 xxiii。 |

因此，不能同时满足提示里的“Johnny 导言末尾”和“January 5, 1997”两个条件。
应向主线报告这一矛盾：若坚持按明确日期找，定位为 xix 页注记；若坚持找 Johnny 最后署名，定位为 xxiii 页，地名如上。
这份核验不判断后台实现想收哪一项，也不把任何文字包装为已验证答案。

## 可访问来源

1. **Eleanor Williams，The Divine and Miss Johanna，Ohio University 博士论文，2006。**
   - 官方大学论文库 PDF：<https://etd.ohiolink.edu/acprod/odb_etd/ws/send_file/send?accession=ohiou1145555978&disposition=inline>
   - **PDF 第 58 页／论文印刷页 58**：在讨论《叶之屋》的段落中查 `January 5, 1997`，有直接引文并标原书 **xix**。
   - **PDF 第 88 页**参考文献：该书版本为 **New York: Pantheon, 2000**。
   - 本轮已实际下载到内存并提取 PDF 文本验证页码，未保存或复制那段小说原文。

2. **Jessica Pressman，House of Leaves: Reading the Networked Novel，Studies in American Fiction 34(1)，2006，107–128。**
   - 作者发布页：<https://www.jessicapressman.com/publications/>
   - 作者公开 PDF：<https://www.jessicapressman.com/wp-content/uploads/2012/07/Pressman-House-of-Leaves.pdf>
   - 讨论日期与 Halloween 的部分明确指出最后一篇日记与导言同署 **October 31, 1998**。
   - 浏览工具及搜索索引可见该 PDF；直接 Python 下载遇到 406，故不声称取得了自己的本地 PDF 副本。

3. **作者网站读者论坛：Key to All Mythologies: The Introduction。**
   - <https://forums.markzdanielewski.com/forum/house-of-leaves/house-of-leaves-aa/3912-key-to-all-mythologies-the-introduction>
   - 前段讨论导言结尾署 1998-10-31；后面的 chronology 把 1997-01-05 归于 Zampanò 注记。
   - 属于读者研究，不是作者官方释义；这里用于交叉核查。

4. **出版社导读**：<https://www.penguinrandomhouse.com/books/36526/house-of-leaves-by-mark-z-danielewski/9780375703768/readers-guide/>
   - 能确认小说叙事层级及导言 xx 页相关讨论；**该网页本身没有给出所问的日期后原文**，不要引用它冒充逐字核验来源。

## 给主线的处理建议

先审查日期/署名冲突，保留用户自己查阅原书的步骤。对于 xix 页正文，我只提供准确定位及概述；它并非仅由日期、地名构成的事实字段。若用户随后自行提供需要核对的那一行，可以再检查其标点、大小写与请求格式。当前没有理由自动把 xxiii 页地名提交到一个明确指向 1997-01-05 的关卡。
