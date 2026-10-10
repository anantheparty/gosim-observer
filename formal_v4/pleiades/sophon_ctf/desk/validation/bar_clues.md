# 酒吧候选声明验证表

输入 78 行，45 次 POST bar；共 110 条声明，其中普通 53、237 担保 57。
输入 SHA-256：`abd61433d20940ca758d5416398c6233c6fb9d6ab8cb05da28af1eb9c4dee92e`。

频次只描述观察结果，不构成正确答案。未发起任何端点调用。

## 去掉 237 担保的词频

| 槽位 | 词 | 声明数 | 不同响应数 | 模板计数 | 原日志行 |
|---:|---|---:|---:|---|---|
| 1 | ATTIC | 3 | 3 | {'everyone_knows': 1, 'room_bet': 2} | [29, 44, 61] |
| 1 | ULLMAN | 3 | 3 | {'everyone_knows': 1, 'room_bet': 2} | [43, 56, 61] |
| 1 | CARETAKER | 1 | 1 | {'everyone_knows': 1} | [65] |
| 1 | CARPET | 1 | 1 | {'room_bet': 1} | [40] |
| 1 | CHAPEL | 1 | 1 | {'room_bet': 1} | [22] |
| 1 | GRADY | 1 | 1 | {'everyone_knows': 1} | [76] |
| 1 | PANTRY | 1 | 1 | {'everyone_knows': 1} | [26] |
| 1 | ROOM | 1 | 1 | {'trust_me': 1} | [62] |
| 1 | SKYLIGHT | 1 | 1 | {'everyone_knows': 1} | [54] |
| 1 | TRICYCLE | 1 | 1 | {'room_bet': 1} | [30] |
| 2 | PANTRY | 2 | 2 | {'everyone_knows': 1, 'room_bet': 1} | [58, 77] |
| 2 | TONY | 2 | 2 | {'everyone_knows': 1, 'room_bet': 1} | [43, 59] |
| 2 | CARETAKER | 1 | 1 | {'everyone_knows': 1} | [55] |
| 2 | CHAPEL | 1 | 1 | {'trust_me': 1} | [33] |
| 2 | GRADY | 1 | 1 | {'room_bet': 1} | [23] |
| 2 | ROOM | 1 | 1 | {'trust_me': 1} | [58] |
| 2 | SKYLIGHT | 1 | 1 | {'everyone_knows': 1} | [63] |
| 2 | TRICYCLE | 1 | 1 | {'everyone_knows': 1} | [60] |
| 3 | TONY | 4 | 4 | {'room_bet': 2, 'trust_me': 2} | [17, 25, 30, 42] |
| 3 | SKYLIGHT | 3 | 3 | {'everyone_knows': 1, 'room_bet': 2} | [28, 32, 44] |
| 3 | TRICYCLE | 3 | 3 | {'everyone_knows': 1, 'trust_me': 2} | [17, 26, 66] |
| 3 | BOILER | 2 | 2 | {'everyone_knows': 1, 'trust_me': 1} | [21, 54] |
| 3 | ATTIC | 1 | 1 | {'trust_me': 1} | [77] |
| 3 | CARETAKER | 1 | 1 | {'everyone_knows': 1} | [45] |
| 3 | PANTRY | 1 | 1 | {'everyone_knows': 1} | [36] |
| 3 | ROOM | 1 | 1 | {'room_bet': 1} | [78] |
| 3 | ULLMAN | 1 | 1 | {'trust_me': 1} | [58] |
| 4 | BOILER | 3 | 3 | {'room_bet': 1, 'trust_me': 2} | [25, 40, 41] |
| 4 | CARETAKER | 2 | 2 | {'everyone_knows': 1, 'trust_me': 1} | [35, 78] |
| 4 | ULLMAN | 2 | 2 | {'room_bet': 1, 'trust_me': 1} | [59, 61] |
| 4 | CARPET | 1 | 1 | {'everyone_knows': 1} | [22] |
| 4 | CHAPEL | 1 | 1 | {'trust_me': 1} | [34] |
| 4 | ROOM | 1 | 1 | {'everyone_knows': 1} | [36] |
| 4 | TONY | 1 | 1 | {'everyone_knows': 1} | [63] |
| 4 | TRICYCLE | 1 | 1 | {'room_bet': 1} | [57] |

## 固定担保词与普通词是否分离

237 按槽位：`{"1": {"MIRROR": 12}, "2": {"TOPIARY": 16}, "3": {"ELEVATOR": 15}, "4": {"BASEMENT": 14}}`。
与所有普通模板词汇的交集：`[]`。

## 原话证据

| 原日志行 | 时间 | 组 | 模板 | 槽位 | 词 | 房号 | 原话 |
|---:|---|---|---|---:|---|---:|---|
| 17 | 2026-10-06T18:55:35Z | ordinary | trust_me | 3 | TRICYCLE |  | Word 3 is TRICYCLE, kid. Trust me. |
| 17 | 2026-10-06T18:55:35Z | ordinary | room_bet | 3 | TONY | 234 | The third word? TONY. I'd bet room 234 on it. |
| 21 | 2026-10-06T19:02:50Z | ordinary | everyone_knows | 3 | BOILER |  | Everyone knows the third word is BOILER. |
| 21 | 2026-10-06T19:02:50Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 22 | 2026-10-06T19:03:43Z | ordinary | room_bet | 1 | CHAPEL | 203 | The first word? CHAPEL. I'd bet room 203 on it. |
| 22 | 2026-10-06T19:03:43Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
| 22 | 2026-10-06T19:03:43Z | ordinary | everyone_knows | 4 | CARPET |  | Everyone knows the fourth word is CARPET. |
| 23 | 2026-10-06T19:04:20Z | ordinary | room_bet | 2 | GRADY | 236 | The second word? GRADY. I'd bet room 236 on it. |
| 23 | 2026-10-06T19:04:20Z | 237 | 237_sworn | 3 | ELEVATOR |  | I'd swear it on 237: word number 3 is ELEVATOR. |
| 23 | 2026-10-06T19:04:20Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 25 | 2026-10-06T19:05:04Z | 237 | 237_sworn | 2 | TOPIARY |  | I'd swear it on 237: word number 2 is TOPIARY. |
| 25 | 2026-10-06T19:05:04Z | ordinary | room_bet | 4 | BOILER | 231 | The fourth word? BOILER. I'd bet room 231 on it. |
| 25 | 2026-10-06T19:05:04Z | ordinary | room_bet | 3 | TONY | 214 | The third word? TONY. I'd bet room 214 on it. |
| 26 | 2026-10-06T19:05:50Z | 237 | 237_sworn | 4 | BASEMENT |  | I'd swear it on 237: word number 4 is BASEMENT. |
| 26 | 2026-10-06T19:05:50Z | ordinary | everyone_knows | 1 | PANTRY |  | Everyone knows the first word is PANTRY. |
| 26 | 2026-10-06T19:05:50Z | ordinary | everyone_knows | 3 | TRICYCLE |  | Everyone knows the third word is TRICYCLE. |
| 28 | 2026-10-06T19:06:48Z | ordinary | room_bet | 3 | SKYLIGHT | 229 | The third word? SKYLIGHT. I'd bet room 229 on it. |
| 28 | 2026-10-06T19:06:48Z | 237 | 237_locked | 1 | MIRROR |  | As sure as room 237 is locked, the first word is MIRROR. |
| 29 | 2026-10-06T19:07:34Z | 237 | 237_never_lies | 4 | BASEMENT |  | Room 237 never lies, and neither do I about this - the fourth one is BASEMENT. |
| 29 | 2026-10-06T19:07:34Z | ordinary | room_bet | 1 | ATTIC | 200 | The first word? ATTIC. I'd bet room 200 on it. |
| 29 | 2026-10-06T19:07:34Z | 237 | 237_locked | 3 | ELEVATOR |  | As sure as room 237 is locked, the third word is ELEVATOR. |
| 30 | 2026-10-06T19:07:35Z | ordinary | trust_me | 3 | TONY |  | Word 3 is TONY, kid. Trust me. |
| 30 | 2026-10-06T19:07:35Z | ordinary | room_bet | 1 | TRICYCLE | 223 | The first word? TRICYCLE. I'd bet room 223 on it. |
| 31 | 2026-10-06T19:07:37Z | 237 | 237_locked | 3 | ELEVATOR |  | As sure as room 237 is locked, the third word is ELEVATOR. |
| 31 | 2026-10-06T19:07:37Z | 237 | 237_never_lies | 2 | TOPIARY |  | Room 237 never lies, and neither do I about this - the second one is TOPIARY. |
| 31 | 2026-10-06T19:07:37Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 32 | 2026-10-06T19:09:23Z | 237 | 237_never_lies | 2 | TOPIARY |  | Room 237 never lies, and neither do I about this - the second one is TOPIARY. |
| 32 | 2026-10-06T19:09:23Z | ordinary | room_bet | 3 | SKYLIGHT | 239 | The third word? SKYLIGHT. I'd bet room 239 on it. |
| 32 | 2026-10-06T19:09:23Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
| 33 | 2026-10-06T19:09:25Z | ordinary | trust_me | 2 | CHAPEL |  | Word 2 is CHAPEL, kid. Trust me. |
| 33 | 2026-10-06T19:09:25Z | 237 | 237_sworn | 2 | TOPIARY |  | I'd swear it on 237: word number 2 is TOPIARY. |
| 34 | 2026-10-06T19:10:24Z | 237 | 237_never_lies | 1 | MIRROR |  | Room 237 never lies, and neither do I about this - the first one is MIRROR. |
| 34 | 2026-10-06T19:10:24Z | ordinary | trust_me | 4 | CHAPEL |  | Word 4 is CHAPEL, kid. Trust me. |
| 35 | 2026-10-06T19:10:26Z | ordinary | everyone_knows | 4 | CARETAKER |  | Everyone knows the fourth word is CARETAKER. |
| 35 | 2026-10-06T19:10:26Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 36 | 2026-10-06T19:10:28Z | ordinary | everyone_knows | 4 | ROOM |  | Everyone knows the fourth word is ROOM. |
| 36 | 2026-10-06T19:10:28Z | ordinary | everyone_knows | 3 | PANTRY |  | Everyone knows the third word is PANTRY. |
| 37 | 2026-10-06T19:10:29Z | 237 | 237_never_lies | 1 | MIRROR |  | Room 237 never lies, and neither do I about this - the first one is MIRROR. |
| 37 | 2026-10-06T19:10:29Z | 237 | 237_sworn | 1 | MIRROR |  | I'd swear it on 237: word number 1 is MIRROR. |
| 37 | 2026-10-06T19:10:29Z | 237 | 237_locked | 1 | MIRROR |  | As sure as room 237 is locked, the first word is MIRROR. |
| 40 | 2026-10-06T19:11:36Z | ordinary | trust_me | 4 | BOILER |  | Word 4 is BOILER, kid. Trust me. |
| 40 | 2026-10-06T19:11:36Z | ordinary | room_bet | 1 | CARPET | 200 | The first word? CARPET. I'd bet room 200 on it. |
| 41 | 2026-10-06T19:11:37Z | 237 | 237_never_lies | 1 | MIRROR |  | Room 237 never lies, and neither do I about this - the first one is MIRROR. |
| 41 | 2026-10-06T19:11:37Z | ordinary | trust_me | 4 | BOILER |  | Word 4 is BOILER, kid. Trust me. |
| 41 | 2026-10-06T19:11:37Z | 237 | 237_sworn | 4 | BASEMENT |  | I'd swear it on 237: word number 4 is BASEMENT. |
| 42 | 2026-10-06T19:12:42Z | 237 | 237_locked | 3 | ELEVATOR |  | As sure as room 237 is locked, the third word is ELEVATOR. |
| 42 | 2026-10-06T19:12:42Z | ordinary | trust_me | 3 | TONY |  | Word 3 is TONY, kid. Trust me. |
| 43 | 2026-10-06T19:13:16Z | ordinary | room_bet | 2 | TONY | 211 | The second word? TONY. I'd bet room 211 on it. |
| 43 | 2026-10-06T19:13:16Z | ordinary | everyone_knows | 1 | ULLMAN |  | Everyone knows the first word is ULLMAN. |
| 44 | 2026-10-06T19:13:17Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 44 | 2026-10-06T19:13:17Z | ordinary | everyone_knows | 1 | ATTIC |  | Everyone knows the first word is ATTIC. |
| 44 | 2026-10-06T19:13:17Z | ordinary | everyone_knows | 3 | SKYLIGHT |  | Everyone knows the third word is SKYLIGHT. |
| 45 | 2026-10-06T19:13:19Z | 237 | 237_never_lies | 2 | TOPIARY |  | Room 237 never lies, and neither do I about this - the second one is TOPIARY. |
| 45 | 2026-10-06T19:13:19Z | ordinary | everyone_knows | 3 | CARETAKER |  | Everyone knows the third word is CARETAKER. |
| 53 | 2026-10-06T19:20:51Z | 237 | 237_locked | 1 | MIRROR |  | As sure as room 237 is locked, the first word is MIRROR. |
| 53 | 2026-10-06T19:20:51Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
| 54 | 2026-10-06T19:29:48Z | ordinary | trust_me | 3 | BOILER |  | Word 3 is BOILER, kid. Trust me. |
| 54 | 2026-10-06T19:29:48Z | 237 | 237_sworn | 2 | TOPIARY |  | I'd swear it on 237: word number 2 is TOPIARY. |
| 54 | 2026-10-06T19:29:48Z | ordinary | everyone_knows | 1 | SKYLIGHT |  | Everyone knows the first word is SKYLIGHT. |
| 55 | 2026-10-06T19:29:49Z | ordinary | everyone_knows | 2 | CARETAKER |  | Everyone knows the second word is CARETAKER. |
| 55 | 2026-10-06T19:29:49Z | 237 | 237_sworn | 3 | ELEVATOR |  | I'd swear it on 237: word number 3 is ELEVATOR. |
| 56 | 2026-10-06T19:29:51Z | ordinary | room_bet | 1 | ULLMAN | 235 | The first word? ULLMAN. I'd bet room 235 on it. |
| 56 | 2026-10-06T19:29:51Z | 237 | 237_never_lies | 4 | BASEMENT |  | Room 237 never lies, and neither do I about this - the fourth one is BASEMENT. |
| 57 | 2026-10-06T19:29:53Z | ordinary | room_bet | 4 | TRICYCLE | 229 | The fourth word? TRICYCLE. I'd bet room 229 on it. |
| 57 | 2026-10-06T19:29:53Z | 237 | 237_never_lies | 2 | TOPIARY |  | Room 237 never lies, and neither do I about this - the second one is TOPIARY. |
| 58 | 2026-10-06T19:29:54Z | ordinary | trust_me | 3 | ULLMAN |  | Word 3 is ULLMAN, kid. Trust me. |
| 58 | 2026-10-06T19:29:54Z | ordinary | trust_me | 2 | ROOM |  | Word 2 is ROOM, kid. Trust me. |
| 58 | 2026-10-06T19:29:54Z | ordinary | everyone_knows | 2 | PANTRY |  | Everyone knows the second word is PANTRY. |
| 59 | 2026-10-06T19:30:15Z | 237 | 237_never_lies | 4 | BASEMENT |  | Room 237 never lies, and neither do I about this - the fourth one is BASEMENT. |
| 59 | 2026-10-06T19:30:15Z | ordinary | everyone_knows | 2 | TONY |  | Everyone knows the second word is TONY. |
| 59 | 2026-10-06T19:30:15Z | ordinary | trust_me | 4 | ULLMAN |  | Word 4 is ULLMAN, kid. Trust me. |
| 60 | 2026-10-06T19:30:16Z | 237 | 237_never_lies | 1 | MIRROR |  | Room 237 never lies, and neither do I about this - the first one is MIRROR. |
| 60 | 2026-10-06T19:30:16Z | 237 | 237_never_lies | 2 | TOPIARY |  | Room 237 never lies, and neither do I about this - the second one is TOPIARY. |
| 60 | 2026-10-06T19:30:16Z | ordinary | everyone_knows | 2 | TRICYCLE |  | Everyone knows the second word is TRICYCLE. |
| 61 | 2026-10-06T19:30:18Z | ordinary | room_bet | 1 | ULLMAN | 239 | The first word? ULLMAN. I'd bet room 239 on it. |
| 61 | 2026-10-06T19:30:18Z | ordinary | room_bet | 4 | ULLMAN | 217 | The fourth word? ULLMAN. I'd bet room 217 on it. |
| 61 | 2026-10-06T19:30:18Z | ordinary | room_bet | 1 | ATTIC | 203 | The first word? ATTIC. I'd bet room 203 on it. |
| 62 | 2026-10-06T19:30:20Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 62 | 2026-10-06T19:30:20Z | ordinary | trust_me | 1 | ROOM |  | Word 1 is ROOM, kid. Trust me. |
| 63 | 2026-10-06T19:30:22Z | ordinary | everyone_knows | 2 | SKYLIGHT |  | Everyone knows the second word is SKYLIGHT. |
| 63 | 2026-10-06T19:30:22Z | ordinary | everyone_knows | 4 | TONY |  | Everyone knows the fourth word is TONY. |
| 64 | 2026-10-06T19:30:53Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
| 64 | 2026-10-06T19:30:53Z | 237 | 237_sworn | 2 | TOPIARY |  | I'd swear it on 237: word number 2 is TOPIARY. |
| 65 | 2026-10-06T19:30:55Z | 237 | 237_never_lies | 4 | BASEMENT |  | Room 237 never lies, and neither do I about this - the fourth one is BASEMENT. |
| 65 | 2026-10-06T19:30:55Z | ordinary | everyone_knows | 1 | CARETAKER |  | Everyone knows the first word is CARETAKER. |
| 66 | 2026-10-06T19:30:57Z | ordinary | trust_me | 3 | TRICYCLE |  | Word 3 is TRICYCLE, kid. Trust me. |
| 66 | 2026-10-06T19:30:57Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
| 67 | 2026-10-06T19:30:59Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 67 | 2026-10-06T19:30:59Z | 237 | 237_locked | 3 | ELEVATOR |  | As sure as room 237 is locked, the third word is ELEVATOR. |
| 68 | 2026-10-06T19:31:01Z | 237 | 237_never_lies | 4 | BASEMENT |  | Room 237 never lies, and neither do I about this - the fourth one is BASEMENT. |
| 68 | 2026-10-06T19:31:01Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 68 | 2026-10-06T19:31:01Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 72 | 2026-10-06T19:32:02Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 72 | 2026-10-06T19:32:02Z | 237 | 237_sworn | 3 | ELEVATOR |  | I'd swear it on 237: word number 3 is ELEVATOR. |
| 73 | 2026-10-06T19:32:03Z | 237 | 237_locked | 1 | MIRROR |  | As sure as room 237 is locked, the first word is MIRROR. |
| 73 | 2026-10-06T19:32:03Z | 237 | 237_sworn | 1 | MIRROR |  | I'd swear it on 237: word number 1 is MIRROR. |
| 73 | 2026-10-06T19:32:03Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 74 | 2026-10-06T19:32:05Z | 237 | 237_never_lies | 1 | MIRROR |  | Room 237 never lies, and neither do I about this - the first one is MIRROR. |
| 74 | 2026-10-06T19:32:05Z | 237 | 237_sworn | 2 | TOPIARY |  | I'd swear it on 237: word number 2 is TOPIARY. |
| 74 | 2026-10-06T19:32:05Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 75 | 2026-10-06T19:32:07Z | 237 | 237_sworn | 1 | MIRROR |  | I'd swear it on 237: word number 1 is MIRROR. |
| 75 | 2026-10-06T19:32:07Z | 237 | 237_never_lies | 3 | ELEVATOR |  | Room 237 never lies, and neither do I about this - the third one is ELEVATOR. |
| 76 | 2026-10-06T19:32:09Z | 237 | 237_locked | 4 | BASEMENT |  | As sure as room 237 is locked, the fourth word is BASEMENT. |
| 76 | 2026-10-06T19:32:09Z | ordinary | everyone_knows | 1 | GRADY |  | Everyone knows the first word is GRADY. |
| 77 | 2026-10-06T19:33:04Z | ordinary | trust_me | 3 | ATTIC |  | Word 3 is ATTIC, kid. Trust me. |
| 77 | 2026-10-06T19:33:04Z | ordinary | room_bet | 2 | PANTRY | 216 | The second word? PANTRY. I'd bet room 216 on it. |
| 77 | 2026-10-06T19:33:04Z | 237 | 237_sworn | 4 | BASEMENT |  | I'd swear it on 237: word number 4 is BASEMENT. |
| 78 | 2026-10-06T19:33:06Z | ordinary | trust_me | 4 | CARETAKER |  | Word 4 is CARETAKER, kid. Trust me. |
| 78 | 2026-10-06T19:33:06Z | ordinary | room_bet | 3 | ROOM | 239 | The third word? ROOM. I'd bet room 239 on it. |
| 78 | 2026-10-06T19:33:06Z | 237 | 237_locked | 2 | TOPIARY |  | As sure as room 237 is locked, the second word is TOPIARY. |
