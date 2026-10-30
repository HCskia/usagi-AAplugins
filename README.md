# Yumi`s usagi

适用于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 QQ 群管插件，核心能力是**把支付宝 AA 收款截图自动 OCR 识别成「该成员已付款」**，另外附带车群记录、群名片编号、召唤/点兵等日常群务。

> 平台：`aiocqhttp`（OneBot v11，即 go-cqhttp / LLOneBot / NapCat 等协议端）

---

## 功能一览

### AA 收款截图 OCR 登记已付

群成员在群里发一张支付宝收款截图，插件自动完成：

1. 取图（URL / base64 / 本地路径，单条消息只接受 1 张）
2. 调 OCR 接口（可配多个，按顺序失败自动切下一个）
3. 从识别文本里解析出 **付款 QQ** 与 **金额**
4. 校验金额是否等于该群配置的金额，校验 QQ 是否为发送者本人
5. 通过后把该成员群名片（或群头衔）打上「已付」标记

支持的账单形态：

| 账单类型 | 识别依据 | 语言 |
| :-- | :-- | :-- |
| 支付宝 AA 收款 | `AA收款` / `Dutch` / `Go Dutch` / `我` / `Me` / `已付` / `paid` | 简体、繁体、英文 |
| 支付宝小荷包 | `小荷包` / `转账备注` / `轉賬備註` / `Transfer notes` | 简体、繁体、英文 |
| 经营小店交易记录 | 配置的店名 / `备注QQ` / `支付记录` | 简体 |

容错设计：

- **QQ 容错**：OCR 识别的 QQ 与发送者 QQ 编辑距离 ≤ 1（错 1 位、多 1 位、少 1 位）时自动校准为发送者真实 QQ
- **双通路重试**：原图直传识别 → 解析不出 QQ/金额时，自动降级到 OpenCV 预处理（灰度 → 2 倍放大 → 高斯模糊 → 自适应二值化 → 闭运算）再识别一次

### 车群记录

`/停车` 把当前群所有非管理员成员的「入群月份 + QQ + 群号 + 群名 + 车名」写入 sqlite；`/上车` 按月/按人查；`/下车` 按车名模糊删除；`/查车` 列出所有车名。

### 群名片与群务

群成员顺序编号（`01`、`02`…）、清空编号、召唤未付成员、按关键词艾特全群、邀请入群自动同意、加群申请按白名单自动批准（可设人数上限）、退群、动态增删 OCR 群、共同群聊链接。

### 日常娱乐

`/娶群友` 每日随机群友（种子 = 日期 + QQ + 群号，同日同群结果固定）；`吃啥` 从数据库随机推荐菜名。

---

## 运行环境

| 项 | 要求 |
| :-- | :-- |
| AstrBot | ≥ v4.5.0（`display_name` 需要，低版本能跑但显示异常） |
| 平台 | `aiocqhttp`（OneBot v11） |
| Python 依赖 | 见 `requirements.txt`：`opencv-python`、`numpy`（`aiohttp` 由 AstrBot 自带） |
| OCR 服务 | 需自备，见下方「OCR 服务对接」 |

---

## 安装

```bash
# 方式一：插件市场搜索 Yumi`s usagi 安装
# 方式二：手动克隆到 AstrBot 插件目录
cd AstrBot/data/plugins
git clone https://github.com/HCskia/usagi-AAplugins.git astrbot_plugin_Yumis_usagi
pip install -r astrbot_plugin_Yumis_usagi/requirements.txt
```

装好后在 AstrBot 面板重载插件，再到插件配置页填写下面的配置项。

---

## 配置说明

| 配置项 | 类型 | 默认 | 说明 |
| :-- | :-- | :-- | :-- |
| 测试模式开关 | bool | 关 | 开启后**所有功能**只在「测试群组ID」对应的群生效，建议先开着调试 |
| 测试群组ID | string | 空 | 测试群号 |
| 管理员列表 | template_list | 空 | 管理员 QQ 号，涉及改名/删库/退群等敏感操作都要校验 |
| 仅管理员查询上车 | bool | 关 | 开启后 `/上车` 只有管理员能用（关闭时普通成员只能查自己） |
| 非娶群友群组 | template_list | 空 | 这些群不触发 `/娶群友` |
| 非吃啥群组 | template_list | 空 | 这些群不触发「吃啥」 |
| 自动同意入群申请群组 | template_list | 空 | 每项含「群号」+「自动批准人数上限」（0 = 不限）。bot 需在该群为管理/群主 |
| 群成员编号等待时间 | float | 0.5 | 每次改名片之间的间隔（秒），编号有遗漏时上调 |
| 召唤未付成员等待时间 | float | 0.2 | 仅 `/召唤未付成员 -n` 生效，每次拉取成员详情之间的间隔（秒） |
| OCR服务器API列表 | template_list | 空 | 每项含「API地址」「API验证Token」「模型名称」，按添加顺序依次尝试，前面的失败自动切下一个 |
| OCR已付标注-群称号模式 | bool | 关 | 开启后改用**群头衔**标注已付（`set_group_special_title`），要求 bot 是群主；关闭时改群名片，要求 bot 是管理员 |
| OCR已付标注文本 | string | 已付 | 打上的标记文本 |
| OCR群组 | template_list | 空 | 每项含「群号」+「识别金额」。只有这里的群会处理图片消息，且金额必须与该群配置完全一致 |
| 经营小店列表 | template_list | 空 | 小店名称，用于识别「经营小店」类交易记录 |

### OCR 服务器 API 地址填什么

插件按地址自动判断接口类型：

- **局域网 PaddleX 风格同步服务**：填 `http://<OCR服务器IP>:8900/ocr`（推荐，通常免 Token）
- **PaddleOCR AI Studio 异步任务接口**：填 `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`（需 Token，`model` 默认 `PP-OCRv6`）

判别规则：域名含 `aistudio-app.com`，或路径以 `/jobs` 结尾 → 走异步任务接口；否则走同步接口。

- 同步接口请求体与 PaddleX 一致：`{"file": "<图片base64>", "fileType": 1}`，Token 通过请求头 `Authorization: token <token>` 传递；响应需包含 `result.ocrResults[].prunedResult.rec_texts`
- 异步接口：multipart 上传 → 轮询任务状态 → 下载 JSONL 结果 → 提取文本；单任务最长等待 120 秒

---

## 命令一览

权限列的「管理员」指在配置项**管理员列表**里的 QQ 号。

| 命令 | 别名 | 参数 | 说明 | 权限 |
| :-- | :-- | :-- | :-- | :-- |
| （发图片） | — | 无 | 在 OCR 群里发收款截图，自动识别并标记已付 | 群成员 |
| `/娶群友` | 文本含 `qqy` 即触发 | 无 | 每日随机娶一位群友 | 群成员 |
| `吃啥` | `吃什么` | 无 | 随机推荐菜名 | 群成员 |
| `/撤回` | — | `[群号] [小时数]` | 撤回该群最近 N 小时内所有图片消息，默认当前群、24 小时 | 管理员 |
| `/群成员编号` | `/yumi`、`/YUMI` | 无 | 按成员列表顺序把非管理员名片改成 `01`、`02`… | 管理员 |
| `/清空群成员编号` | `/hc`、`/HC` | 无 | 清空所有非管理员群名片 | 管理员 |
| `/召唤未付成员` | `/召唤未付`、`/callnonepaymem` | `[-n]` | 艾特名片/头衔里不含「付」的成员；`-n` 表示逐个拉取最新成员信息（更准但更慢） | 管理员 |
| `/乌拉大点兵` | — | `关键词` | 艾特所有群名片包含该关键词的成员 | 管理员 |
| `/共同群聊` | `/u共群`、`/usagi共群` | `QQ号` | 返回共同群聊查询链接 | 无 |
| `/设为ocr群` | `/设为ocr`、`/setocr` | `金额` | 把当前群加入 OCR 群列表并设置识别金额 | 管理员 |
| `/取消ocr` | `/移除ocr`、`/cancelocr` | 无 | 把当前群移出 OCR 群列表 | 管理员 |
| `/停车` | `/tc` | `车名` | 记录当前群全部非管理员成员的入群月份与车名 | 管理员 |
| `/上车` | `/sc` | `[月份] [QQ号]` | 查询某人某月上的车；不填 QQ 查自己，查他人需管理员 | 见左 |
| `/下车` | `/xc` | `车名` | 按车名模糊删除车记录 | 管理员 |
| `/查车` | `/cc` | 无 | 列出所有车名（含群号与月份） | 管理员 |
| `/离开` | `/走走`、`/润`、`/bye` | 无 | bot 退群，同时把自己从 OCR 群列表移除 | 管理员 |
| （群邀请） | — | 无 | 管理员邀请 bot 入群时自动同意 | 事件 |
| （加群申请） | — | 无 | 配置了「自动同意入群申请群组」的群，达到条件自动批准 | 事件 |

---

## 数据文件

数据写在 AstrBot 的插件数据目录（`StarTools.get_data_dir(<插件名>)`，通常是 `AstrBot/data/plugin_data/<插件名>/`）下的 `db/` 里：

```text
db/
├── cars.db    # 车群记录
└── eat.db     # 吃啥的菜名库
```

插件只会创建 `db/` 目录，**不会自动建表**，首次使用前请先手工建好：

```sql
-- cars.db
CREATE TABLE IF NOT EXISTS oncars (
    date       TEXT,  -- 入群月份，格式 YYYY-MM
    user_id    TEXT,
    group_id   TEXT,
    group_name TEXT,
    car_name   TEXT
);
-- 插件用 INSERT OR IGNORE 写入，建议加唯一索引避免重复停车重复入库
CREATE UNIQUE INDEX IF NOT EXISTS idx_oncars_uniq ON oncars (date, user_id, group_id, car_name);

-- eat.db
CREATE TABLE IF NOT EXISTS foods (food TEXT);
INSERT INTO foods (food) VALUES ('火锅'), ('麻辣烫'), ('猪脚饭');
```

---

## OCR 已付登记流程

```text
群成员发收款截图
   ↓
是否在 OCR 群列表？测试模式是否命中？——否→ 忽略
   ↓ 是
bot 在当前群是否管理员/群主？——否→ 提示权限不足
   ↓ 是
取图（URL / base64 / 本地，单张，≤ 15MB 下载 / 20MB base64）
   ↓
OCR 识别（原图直传 → 解析；失败则 OpenCV 预处理后重试；多个 API 依次降级）
   ↓
解析账单（小荷包 / AA 收款 / 经营小店 / 兜底）→ 得到 QQ + 金额
   ↓
QQ 容错比对发送者（编辑距离 ≤ 1）——不符→ 「QQ号不符合」
   ↓
金额与群配置金额比对——不符→ 「检测到您的金额与设置的识别金额不符哦！」
   ↓
群称号模式？→ 设群头衔 : 设群名片前缀
   ↓
回复「【x.xx元】本兔子大王亲自为你登记完成！」
```

---

## 注意事项

- **只支持 aiocqhttp**：依赖 OneBot v11 的 `get_group_member_list`、`set_group_card`、`get_group_msg_history` 等接口，其他平台适配器不生效
- **改群名片要求 bot 是管理员**；**改群头衔（群称号模式）要求 bot 是群主**
- 一条消息只处理 1 张图片，多图会返回「ocr图片数量大于1」
- OCR 金额必须与群配置金额**完全相等**（浮点比较），设错会一直提示金额不符
- `/撤回` 依赖协议端的 `get_group_msg_history`，部分协议端实现不完整时会翻页异常
- 所有功能都受「测试模式」总开关约束，调试完记得关掉
- 插件注销时不会自动清理数据库，删插件前自行备份 `db/`

---

## 目录结构

```text
.
├── main.py              # 插件入口：事件监听、命令注册、群务逻辑
├── functions/
│   ├── AAocr.py         # OCR 取图、请求、账单解析、QQ 容错
│   ├── tool.py          # sqlite 封装、图片消息解析、base64、格式检测、配置读写
│   └── __init__.py
├── _conf_schema.json    # AstrBot 配置面板 schema
├── metadata.yaml        # 插件元信息
├── requirements.txt
├── LICENSE
└── README.md
```

---

## 许可

[AGPL-3.0](./LICENSE)

## 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件框架
- [PaddleOCR / PaddleX](https://github.com/PaddlePaddle/PaddleOCR) 提供的 OCR 能力
