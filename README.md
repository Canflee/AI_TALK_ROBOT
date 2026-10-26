# ai_talk — 微信 4.x AI 聊天机器人

一个运行在 Windows 上的微信 AI 聊天机器人。  
它不注入、不 Hook 微信，而是读取微信 4.x 本地数据库接收消息，通过 Windows UI Automation + OCR 驱动真实微信客户端发送消息。

> 本项目是**外部机器人**，不是微信官方插件，也不代表微信/腾讯、模型服务商、B 站等任何平台。

> 作者：canflee · 许可证：MIT

---

## 目录

- [功能概览](#功能概览)
- [AI 部分说明](#ai-部分说明)
- [版权与许可](#版权与许可)
- [运行环境](#运行环境)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [常用修改位置](#常用修改位置)
- [人物形象怎么改](#人物形象怎么改)
- [主动消息 / 自动行为怎么改](#主动消息--自动行为怎么改)
- [群聊规则](#群聊规则)
- [多模态能力说明](#多模态能力说明)
- [数据、隐私与第三方服务](#数据隐私与第三方服务)
- [风险与免责声明](#风险与免责声明)
- [常见问题](#常见问题)
- [项目结构](#项目结构)

---

## 功能概览

- **私聊聊天**：默认人设「鲸鱼女仆」，本地 AIModel `qwen/qwen3.5-9b`
- **意图判断**：私聊/群 @ 消息先由模型判断普通聊天、联网搜索、设置提醒、解答问题
- **任务完成检查**：回复只承诺“正在找/等一下”时，模型会继续执行；B 站/网页补发链接，并先自查可用性
- **图片识别**：本地视觉模型先生成特征词（如白发少女），再文本搜索；不保证准确角色名
- **文件发送**：数据库确认 + 3 次重试；全屏/窗口遮挡导致失败会提示，不再误报成功
- **稳定性**：单实例锁、微信数据库 PermissionError 重试、失效/CSDN 521 链接过滤
- **会话白名单**：`REPLY_WHITELIST` 限制自动回复范围，`PROACTIVE_WHITELIST` 限制主动消息对象
- **上下文**：按会话保存历史，人物默认保留最近 80 条消息 / 24000 字符
- **像人一样发消息**：默认 1-2 条、尽量短；复杂问题由模型决定长度和分段；偶尔带 emoji /「）」
- **群聊**：
  - 被 @ 时正常回答
  - 没 @ 时只有约 **20%** 概率随口接一句吐槽，不认真回答
  - 群里不主动发消息，也不设置提醒
- **图片**：OCR + 视觉模型，理解截图、题目、聊天图片；可生成特征搜索词
- **表情包**：从微信 CDN 下载，GIF 取帧识别；约 **10%** 概率回复
- **PDF**：文字版直接抽取；扫描版渲染后 OCR
- **文档处理**：接收 PDF/Word，读取后询问要求，处理后可生成 Word/PDF 到 `data/processed` 并回传
- **图片作业**：图片 + 做题要求 + “整理成 Word/PDF” 会生成解答文件，不再误导出聊天记录
- **引用消息**：引用文字、图片、PDF、链接、视频卡片都能解析
- **B 站链接/视频卡片**：解析标题、UP 主、字幕；下载低画质视频并抽帧看画面
- **公众号文章**：抓取标题、公众号、正文后总结/回答
- **普通网页链接**：最多抓 8 页、每页 5000 字；实际访问检查后再使用
- **联网搜索**：360 / Bing 抓取；最多 10 条结果、抓 6 页正文；失效链接会过滤
- **提醒**：
  - 定时提醒，如「晚上八点提醒我」
  - 条件提醒，如「上海天晴了提醒我」「金价890提醒我」；定期联网检查，满足后通知
  - 天亮 / 天黑类条件直接按城市日出日落时间判断，不额外搜索、不耗模型，如「上海天黑了提醒我」
  - 提醒时间、内容和条件由模型提取，本地校验；不再靠写死关键词猜
- **主动消息**：
  - 默认开启，只发给主动发送白名单里的私聊
  - 从最近一条聊天（你或机器人）算起：20 分钟前不发；20–90 分钟内随机，越往后概率越高，90 分钟必发（安静时段顺延）
  - 安静时段 09:00–22:30
  - 你 10 分钟内刚聊过就跳过，并从最后一条消息重新计时
  - 会结合上下文追问，或开启新话题
  - 约 20% 概率分享一个较新的 B 站视频
  - 主动消息发出后 5 分钟没回，会追问一句；之后每约一小时一次，直到你回复；追问同样遵守安静时段，且不重置 20–90 分钟主动计时
- **管理命令**：`#persona`、`#personas`、`#reset`、`#id`、`#reminders`、`#proactive`、`#cancel`、`#help`

---

## AI 部分说明

本项目的 AI 能力与确定性逻辑分开，具体如下：

| 功能 | 实现 | AI？ |
|---|---|---|
| 人设聊天、群聊吐槽 | AIModel `qwen/qwen3.5-9b` | 是 |
| 主动消息文案 | AIModel + 最近上下文 | 是 |
| 图片/视频帧理解 | AIModel 视觉能力 | 是 |
| 图片特征词生成 | AIModel 视觉能力，不猜角色名 | 是 |
| 文章/搜索结果总结 | AIModel | 是 |
| 图片文字识别 | RapidOCR / Windows OCR | 否，本地 OCR |
| PDF 文字抽取 | pypdf / PyMuPDF | 否 |
| 网页搜索 | 360 / Bing | 否 |
| 链接可用性自查 | B 站 `view` API + 实际访问网页 | 否，规则检查 |
| 搜索规划（是否搜 + 查询词） | AIModel，少量 token（推理模型需预留 token） | 是 |
| 条件提醒判断 | 联网搜索 + AIModel | 是 |
| 天亮 / 天黑判断 | Open-Meteo 日出日落 + 本地时间 | 否，规则判断 |
| 意图判断（聊天 / 搜索 / 提醒 / 答题） | AIModel，每轮一次 | 是 |
| 任务完成检查 | AIModel，每轮回复后 | 是 |
| 提醒、定时、安静时段、频率控制 | 本地调度器 | 否 |
| B 站视频筛选与随机 | B 站搜索 + 本地权重/过滤 | 否 |

需要注意：

- AI 生成内容可能出错，尤其是数字、公式、OCR 结果、文章摘要、视频画面推断。
- 搜索、文章、视频、PDF 等内容仅供聊天参考，不构成投资、法律、医疗或其他专业建议。
- 普通条件提醒依赖搜索结果和 AI 判断，可能延迟或误判；天亮 / 天黑按日出日落时间判断，不受搜索结果影响；重要事项建议用定时提醒。
- AI 人设为虚构角色，保持全年龄向；不代表真实人物或平台立场。
- 主动消息由 AI 生成，存在说错话、重复、上下文误判的可能。

### 意图判断

- 私聊和群里被 @ 的消息，会先交给本地模型判断：普通聊天、联网搜索、设置提醒、解答问题
- 抱怨「你怎么不提醒我」「为啥不提醒我」会被判为普通聊天，不会再误设条件提醒
- 判为搜索：直接使用模型给出的查询词
- 判为提醒：模型同时返回提醒类型、内容、时间或条件；本地做校验
- 时间已过会尽量顺延到明天；字段不完整或仍无法确定时会先问清楚
- 模型没返回完整提醒字段时才回退本地解析
- 判为答题：使用完整答案模式，允许比普通聊天更长
- 图片是否需要联网识别也由模型判断，不再写死“是谁 / 搜一下”等触发词
- 分类失败会自动回退到原来的规则

### 任务完成检查

- 每次正常回复后，模型会判断用户的任务有没有完成
- 如果只说了“正在搜 / 等一下 / 马上发链接”但还没给出结果，会继续执行
- 找 B 站视频/动画/番剧：用 B 站搜索，补发最多 3 条链接
- 找其他信息：用 360/Bing 搜索，补发最多 3 条链接
- 普通聊天、已经给出结果、无法确定时视为完成，不会乱发
- 补发前如果用户已经继续发消息，会跳过，避免打扰
- 补发使用模型判断的动作和查询词，不写死触发词
- 补发前会自查链接：B 站视频查 `view` 接口，网页会先跟随 360 跳转拿到最终地址
- 网页会实际访问并检查状态码、登录/验证页、404/已删除/正文过短；CSDN 返回 521 也会过滤
- 自查后只发可用链接，并发送最终直链，不发 360 跳转链接；全都失效会直接说没找到可用的

---

## 版权与许可

Copyright © 2026 canflee

本项目采用 **MIT License** 开源，详见 [LICENSE](LICENSE)。

- 你可以自由使用、修改、分发，但需保留版权声明和许可证文本。
- 第三方组件、接口和内容归其各自所有者：
  - `wechatauto-replica`：Apache-2.0
  - OpenAI Python SDK：Apache-2.0
  - AIModel / 本地模型服务：遵循所用模型和推理框架的许可条款
  - 微信 / 腾讯、B 站、360、Bing：遵循各自平台条款
- 本项目与腾讯、模型服务商、B 站等均无隶属或官方合作关系。

---

## 运行环境

- Windows 10 / 11
- 微信 **4.1.x** 桌面版，已登录小号，保持窗口可被 UI Automation 识别
- Python **3.12**（64 位）
- 本地 OpenAI 兼容模型服务（默认 `qwen/qwen3.5-9b`，`http://127.0.0.1:8080/v1`）
- 使用独立 Python（路径示例，按实际安装位置调整）：
  `%LOCALAPPDATA%\Programs\PyEmbed312\python.exe`
- 依赖见 `requirements.txt`

> `run.bat` 默认使用 `%LOCALAPPDATA%\Programs\PyEmbed312\python.exe`，不存在时回退到 `.venv\Scripts\python.exe`。换机器时按实际路径修改 `PY` 变量。

---

## 本地模型

当前默认使用独立 `llama-server` + Qwen3.5-9B，不依赖 Bionic/LM Studio 界面：

- 启动：双击 `start-model.bat`
- 停止：双击 `stop-model.bat`
- API：`http://127.0.0.1:8080/v1`
- 模型：`qwen/qwen3.5-9b`
- Key：`local`
- 上下文：默认 `-c 32768`，`n_ctx_train=262144` 只是模型理论上限
- 8GB 显存下不要设置 262144；建议保持 32768，不稳定时降到 16384

查看当前实际加载上下文：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/v1/models -Headers @{Authorization="Bearer local"} |
  ForEach-Object { $_.data[0].meta | Select-Object n_ctx, n_ctx_train }
```

> `.env` 和 `.env.example` 的键名、顺序、注释结构已经对齐；两者都使用 UTF-8 BOM + CRLF。

---

## 快速开始

1. 双击 `start-model.bat`，等窗口出现 `listening on http://127.0.0.1:8080`
2. 启动微信 4.x，登录小号，保持窗口打开
3. 复制配置：
   ```powershell
   Copy-Item .env.example .env
   ```
4. 编辑 `.env`，至少填：
   ```ini
   AIMODEL_API_KEY=local
   AIMODEL_BASE_URL=http://127.0.0.1:8080/v1
   AIMODEL_MODEL=qwen/qwen3.5-9b
   ADAPTER=wechatauto
   ADMIN_WXIDS=你的大号wxid
   ```
   - 默认走本地 OpenAI 兼容接口；先启动本地模型服务，再运行 `run.bat`
   - 本地服务不校验 Key 时，`AIMODEL_API_KEY` 填 `local` 即可
   - 想限制自动回复范围：填 `REPLY_WHITELIST`；留空表示所有会话都回
   - 想开启主动消息：填 `PROACTIVE_WHITELIST`（留空且 `PROACTIVE_TARGET_WXID` 也为空时不会主动发）
   - 所有可调参数都从 `.env` 读取，代码里不再保留默认值；缺少必填项会提示
     `配置错误: 缺少环境变量 XXX`
5. 双击 `run.bat`
6. 控制台窗口保持打开；按 `Ctrl+C` 或关闭窗口停止

> **只开一个实例。** 程序启动时用命名互斥量检测，重复运行会提示「已有 ai_talk 实例在运行」并退出，避免重复监听、重复回复和抢 UI 焦点。

---

## 使用方式

### 私聊

直接发文字、图片、表情包、PDF、B 站链接、公众号链接即可。  
连续发多条消息时，机器人会等约 10 秒，把上下文合并后回复。

### 文档处理

发 PDF 或 Word 后，机器人会先读取文件，然后问你想要做什么。直接回复要求即可：
> 文件读取收到后立即开始；如果 10 秒内你继续发了消息，会跳过“你想让我做什么”，直接结合文件内容回复。

```text
总结成一页
翻译成英文
改写成正式邮件
```

也可以继续用 `#doc` 命令：

```text
#doc 总结成一页
#doc 翻译成英文
#doc status
#doc cancel
```

- 收到的文件保存在 `data/media`
- 处理结果按你要求的格式生成；没说格式时才默认 Word + PDF
- 结果保存在 `data/processed/<任务ID>/`，然后发回私聊
- 最近发过 PDF/Word 时，说「写成 Word 给我」会处理那份文档，不会导出聊天记录
- 发过图片/题目时，说「整理成 Word/PDF」会生成作业解答文件，不会导出聊天记录
- 没有发文档、图片时，说「整理成 Word」不会自动导出聊天记录；要导出请明确说「导出聊天记录」
- 暂不支持旧版 `.doc`，请另存为 `.docx`
- 当前按新排版生成结果，不保证还原原文档版式

### 图片作业

- 发图片并说「把这题做了」，再说「整理成 Word/PDF 给我」
- 机器人会立即解析图片，完整解答后生成 Word/PDF
- 支持多张图片；生成的是解答文件，不是聊天记录
- 解析和作答较慢时会等待，不会先回半截
- 只有明确说「导出聊天记录」才会整理最近聊天

### 群聊

- `@机器人 问题`：正常回答
- 不 @：约 20% 概率接一句吐槽/客套，不回答实质问题
- 群里不主动发消息
- 群里不设置提醒

### 命令

在私聊或群聊中发送：

```text
#help
#persona whale_maid
#personas
#reset
#id
#reminders
#proactive
#doc
#pause
#resume
#cancel 3
#cancel all
```

- 管理命令仅 `ADMIN_WXIDS` 里的账号可用
- `#id`、`#help`、`#reminders`、`#proactive` 等公开命令不要求管理员
- `#pause` / `#resume` 也是管理命令

### 会话白名单

```ini
# 只自动回复这些会话，留空表示全部
REPLY_WHITELIST=wxid_xxx,12345678901@chatroom
# 主动消息和追问只发给这些私聊，留空回退到 PROACTIVE_TARGET_WXID
PROACTIVE_WHITELIST=wxid_xxx,wxid_yyy
```

- 私聊填 wxid，群聊填 `xxx@chatroom`
- 被 `REPLY_WHITELIST` 挡掉的普通消息不会自动回复、不会设置提醒，也不进入上下文
- 公开命令和管理命令不受回复白名单限制

### 提醒示例

```text
晚上八点提醒我
明天早上8点提醒我开会
1分钟后提醒我
今天七点一刻叫我一声
上海天晴了提醒我
下雨了每五分钟提醒我
每5分钟提醒我下雨了
上海天黑了提醒我
北京天亮了提醒我
金价890提醒我
金价跌到880提醒我
不要提醒我任何事情了
取消所有提醒
算了所有提醒都关了吧
把提醒全关了
七点一刻那个取消，改成七点半
算了，七点一刻别叫我了，改成七点半
七点一刻那个取消
算了别叫我了
取消吧
```

- 定时提醒按时间触发
- 隐含提醒也会识别：如「明天下午三点开会」「后天记得交报告」，不一定要说「提醒我」
- 支持直接改提醒：「七点一刻那个取消，改成七点半」会取消旧时间并保留原提醒内容
- 「提醒我一下就行了」这类没有实际条件的话，不会再被误识别成条件提醒
- 「今天七点」如果早上时间已过，会优先理解为今晚七点；如果今晚也过了，才顺延到明天
- 条件提醒会定期联网搜索并判断条件是否成立，满足后通知
- 条件提醒默认每 5 分钟检查一次；说「每10分钟提醒我」「每半小时提醒我」时，这条条件会单独使用对应频率
- 其他条件每次检查都会联网搜索并调用模型，频率越高 API 消耗越大；可用 `CONDITION_INTERVAL_MINUTES` 调整
- 普通条件提醒依赖搜索结果和 AI 判断，可能延迟、误判或查不到；重要事项建议用定时提醒
- 条件提醒的流程：提取条件 → 定期生成搜索词 → 联网搜索 → 模型判断是否满足 → 满足就通知
- 「天亮 / 天黑 / 日出 / 日落」这类条件会走本地判断：解析城市 → Open-Meteo 查经纬度和当天日出日落 → 对比当前时间，不搜索、不调用模型
- 只发送城市名和坐标到 Open-Meteo；识别不出城市时回退为普通条件提醒
- 其他条件会保留「现在 / 实时」等判断词，避免搜索词被简化成宽泛话题；网页正文并行抓取（最多 5 个）后再交给模型判断
- 发送 `#reminders` 可以查看定时和条件提醒，用 `#cancel 编号` 取消单条，`#cancel all` 取消全部
- 自然语言也可以取消全部，例如「不要提醒我任何事情了」「取消所有提醒」「以后别提醒我」

### 主动消息

默认启用，但需要先配置 `PROACTIVE_WHITELIST`（或单个 `PROACTIVE_TARGET_WXID`）：

- 只发给 `PROACTIVE_WHITELIST` 里的私聊（未设置时回退到 `PROACTIVE_TARGET_WXID`）
- 从最近一条聊天（你或机器人）算起：20 分钟前不发；20–90 分钟内随机，越往后概率越高，90 分钟必发（安静时段顺延）
- 09:00–22:30 之外不发
- 你 10 分钟内活跃过就跳过，并从最后一条消息重新计时
- 如果启动时上次聊天已经超过这个窗口，会很快补发一次
- 会看最近聊天：没聊完就追问，聊完了就开新话题
- 约 20% 概率分享一个较新的 B 站视频

### 打游戏 / 不想被抢焦点

当前非 Hook 方案的收发原理：

- **收消息**：读取微信 4.x 本地数据库，不碰窗口
- **发消息**：Windows UI Automation + 剪贴板 + 键盘，必须让微信窗口可见并获得焦点
- 微信最小化、缩到托盘、被全屏游戏盖住时，程序会尝试恢复窗口；可能抢焦点，也可能发送失败
- 所以无法像 Hook 一样在后台静默发送；正常回复、主动消息、追问都会受影响

当前非 Hook 方案发送时**必须把微信切到前台**，会抢焦点，游戏可能被切出去，发送也可能失败。

- 临时：`#pause` 暂停自动回复、主动消息和追问；`#resume` 恢复
- 暂停期间收到的普通消息不自动回、不入队、不写入聊天记忆；恢复后需要重发
- 暂停/恢复各会有一次切到微信确认
- 定时提醒仍会按你设的时间发；不想被打扰就先取消提醒
- 最稳：把微信 + 机器人放到虚拟机或第二台电脑，主机游戏不受影响
- 真正的后台发送需要 Hook/协议；微信 4.x 目前没有稳定开源方案

---

## 常用修改位置

| 想改什么 | 文件 | 具体位置 |
|---|---|---|
| 人物名字 / 性格 / 说话方式 | `config/personas.yaml` | `personas.whale_maid.display_name`、`system_prompt` |
| 默认用哪个人设 | `config/personas.yaml` | `default` |
| 给某个联系人绑定人设 | `config/personas.yaml` | `bindings` |
| 人设模型 / 温度 / 最大长度 | `config/personas.yaml` | `model`、`temperature`、`max_tokens` |
| 上下文长度 | `config/personas.yaml` | `max_history`、`max_context_chars` |
| 回复拆成几条 / 每段多长 | `.env` | `REPLY_BUBBLE_LIMIT`、`REPLY_MAX_BUBBLES`、`REPLY_SPLIT_LIMIT` |
| 两条消息间停顿 | `.env` | `REPLY_SEND_DELAY_MIN`、`REPLY_SEND_DELAY_MAX` |
| 每收到 N 条后暂停回复 | `.env` | `INCOMING_PAUSE_EVERY`、`INCOMING_PAUSE_MIN_SECONDS`、`INCOMING_PAUSE_MAX_SECONDS` |
| 去掉括号动作 / 敏感词 | `bot/sending.py` | `_sanitize()`、`_strip_actions()`、`ACTION_WORDS` |
| 去掉回复开头的名字 | `.env` | `REPLY_TARGET_NAME`，留空不处理 |
| 群聊不 @ 的触发概率 | `.env` | `GROUP_BANTER_RATE` |
| 表情包回复概率 | `.env` | `STICKER_REPLY_RATE` |
| 点击随机化 / 拟人节奏 | `.env` | `WECHATAUTO_RHYTHM`（`natural` / `calm` / `fast` / `off`） |
| 微信数据库监听间隔 | `.env` | `WECHAT4_INTERVAL`（默认 2 秒） |
| 意图判断 | `bot/intent.py` | 聊天 / 搜索 / 提醒 / 答题；图片是否联网识别 |
| 任务完成检查 / 补发 | `bot/task_check.py`、`bot/bot.py` | `_run_task_check()`、`_send_bilibili_task()`、`_send_web_task()` |
| 链接可用性自查 | `bot/link_check.py` | B 站 `view`、网页实际访问、360 跳转解析、失效过滤 |
| 图片特征搜索词 | `bot/image_search.py` | `generate_image_search_query()` |
| 图片/视频/链接预解析 | `bot/media_parser.py` | 收到即后台解析，回复时合并 |
| 文件发送确认 / 重试 | `bot/adapter/wechatauto.py` | `send_file()` |
| 输入框点击位置 | `bot/adapter/wechatauto.py` | `_patch_focus_input()`，35%–62% 高度 |
| 微信数据库访问重试 | `bot/wechatauto_patch.py` | PermissionError 重试、临时文件清理 |
| 只回复指定会话 | `.env` | `REPLY_WHITELIST`，留空表示全部 |
| 多消息合并等待时间 | `.env` | `REPLY_DEBOUNCE` |
| 合并安全上限 | `.env` | `BATCH_MAX_MESSAGES`、`BATCH_MAX_CHARS`（极端情况才触发，实际阈值为 4 倍） |
| 联网搜索开关 / 数量 | `.env` | `WEB_SEARCH`、`SEARCH_MAX_RESULTS`、`SEARCH_CACHE_SECONDS` |
| 搜索规划 | `.env` | `SEARCH_INTENT_ENABLED`、`SEARCH_INTENT_MAX_TOKENS`、`SEARCH_QUERY_MAX_TOKENS` |
| 搜索网页抓取 | `.env` | `SEARCH_FETCH_PAGES`、`SEARCH_FETCH_MAX_CHARS`、`SEARCH_FETCH_TIMEOUT_SECONDS` |
| 条件提醒判断上下文 | `.env` | `CONDITION_CONTEXT_CHARS` |
| 公众号文章长度 | `.env` | `ARTICLE_MAX_CHARS` |
| 普通网页链接抓取 | `.env` | `WEB_LINK_ENABLED`、`WEB_LINK_MAX_PAGES`、`WEB_LINK_MAX_CHARS`、`WEB_LINK_TIMEOUT_SECONDS` |
| 文档生成 token | `.env` | `DOC_MAX_OUTPUT_TOKENS`、`DOC_RETRY_OUTPUT_TOKENS` |
| 图片提示词上限 | `.env` | `PROMPT_MAX_IMAGES`、`PROMPT_MAX_IMAGE_SIDE`、`PROMPT_IMAGE_QUALITY` |
| 主动消息开关 / 对象 | `.env` | `PROACTIVE_ENABLED`、`PROACTIVE_WHITELIST`、`PROACTIVE_TARGET_WXID` |
| 主动消息安静时段 | `.env` | `PROACTIVE_QUIET_START`、`PROACTIVE_QUIET_END` |
| 主动消息间隔 | `.env` | `PROACTIVE_MIN_MINUTES`、`PROACTIVE_MAX_MINUTES` |
| 主动消息调度 / 重试 | `.env` | `PROACTIVE_CHECK_SECONDS`、`PROACTIVE_START_DELAY_SECONDS`、`PROACTIVE_RETRY_MIN_MINUTES`、`PROACTIVE_RETRY_MAX_MINUTES` |
| 主动消息文案逻辑 | `bot/proactive_flow.py` | `_generate_auto_proactive()` |
| 视频分享语 | `bot/proactive_flow.py` | `_video_share_line()` / `_video_fallback()` |
| 视频分享概率 | `.env` | `PROACTIVE_VIDEO_RATE` |
| 视频分类与权重 | `.env` | `VIDEO_WEIGHTS`、`VIDEO_CATEGORY_KEYWORDS`、`VIDEO_CATEGORY_TERMS`、`VIDEO_CATEGORY_BAD_WORDS` |
| 视频话题与分享语 | `.env` | `VIDEO_CATEGORY_TOPICS`、`VIDEO_TOPIC_RULES`、`VIDEO_TOPIC_FALLBACKS`、`VIDEO_DEFAULT_FALLBACK`、`VIDEO_SHARE_EXTRA_HINT` |
| 视频筛选 / 去重 | `.env` | `VIDEO_MIN_PLAY`、`VIDEO_FALLBACK_MIN_PLAY`、`VIDEO_MIN_DURATION`、`VIDEO_MAX_DURATION`、`VIDEO_FRESHNESS_DAYS`、`VIDEO_TOP_CANDIDATES`、`VIDEO_HISTORY_LIMIT` |
| 视频搜索与缓存 | `.env` | `VIDEO_SEARCH_LIMIT`、`VIDEO_CACHE_SECONDS`、`VIDEO_INFO_CACHE_SECONDS`、`VIDEO_FRAME_CACHE_SECONDS`、`VIDEO_FRAME_MIN_INTERVAL`、`VIDEO_FRAME_COUNT`、`VIDEO_DOWNLOAD_MAX_MB`、`VIDEO_POPULAR_FRESHNESS_DAYS` |
| 追问检查间隔 | `.env` | `FOLLOWUP_CHECK_SECONDS`（首问时间和追问间隔见 `FOLLOWUP_FIRST_DELAY_MINUTES`、`FOLLOWUP_MIN_INTERVAL_MINUTES`、`FOLLOWUP_MAX_INTERVAL_MINUTES`） |
| 定时提醒检查间隔 | `.env` | `REMINDER_CHECK_SECONDS` |
| 条件提醒 | `.env` | `CONDITION_CHECK_SECONDS`、`CONDITION_INTERVAL_MINUTES`、`CONDITION_RETRY_MINUTES`、`CONDITION_SEARCH_CACHE_SECONDS`、`CONDITION_EXPIRE_DAYS` |
| 条件提醒 token | `.env` | `CONDITION_QUERY_MAX_TOKENS`、`CONDITION_JUDGE_MAX_TOKENS` |
| 图片 / PDF 上限 | `.env` | `OCR_MAX_IMAGES`、`PDF_MAX_FILES`、`PDF_MAX_PAGES`、`PDF_MAX_OCR_PAGES`、`PDF_MAX_CHARS` |
| 机器人名字 / 并发 / 报错提示 | `.env` | `BOT_NAME`、`BOT_WORKERS`、`SEND_ERROR_NOTICE` |
| 配置文件与日志 | `.env` | `DB_PATH`、`PERSONAS_PATH`、`LOG_LEVEL` |
| 启动检查 / 微信文件上限 | `.env` | `SKIP_WECHAT_CHECK`、`WECHAT_MAX_FILE_MB`、`WECHAT_MAX_STICKER_MB` |
| 微信收发适配 | `bot/adapter/wechatauto.py` | 收消息、图片/表情包/PDF/链接解析、UIA 发送 |
| 模型和 Key | `.env` | `AIMODEL_API_KEY`、`AIMODEL_MODEL`、`AIMODEL_BASE_URL`、`AIMODEL_TIMEOUT_SECONDS`、`AIMODEL_MAX_RETRIES`、`AIMODEL_EXTRA_BODY` |
| 管理员 | `.env` | `ADMIN_WXIDS` |

> 改 `.py` 或 `config/personas.yaml` 后必须重启 `run.bat` 才能生效。

---

## 人物形象怎么改

人物完全由 `config/personas.yaml` 控制，不需要改代码。

### 1. 改名字

```yaml
whale_maid:
  display_name: 鲸鱼女仆
```

### 2. 改性格、外貌、说话方式

编辑 `personas.whale_maid.system_prompt`：

```yaml
system_prompt: |
  你是「鲸鱼女仆」，一只蓝发蓝瞳的鲸鱼少女……
  平时一句到两句，25 字内，可以带一点自己的反应、吐槽或情绪……
  不要用括号描写动作……
```

建议保留这些行为约束，否则会退回“AI 助手腔”：

- 平时一句到两句，25 字内，口语化，可以带一点反应/吐槽
- 复杂问题才展开，分条说
- 不要括号动作
- 不要每句加句号
- 不要每句加 emoji，一条最多一个
- 只输出最终要发出去的消息，不要输出分析、计划、搜索过程或“我搜一下…”这类话
- 别像播报，也别像客服
- 保持全年龄向

### 3. 换默认人设

```yaml
default: whale_maid
```

### 4. 给某个联系人单独绑定人设

```yaml
bindings:
  wxid_xxxxxxxx: companion
  12345678901@chatroom: assistant
```

### 5. 人设的高级参数

```yaml
model: qwen/qwen3.5-9b
temperature: 0.9
max_tokens: 1000
max_history: 80
max_context_chars: 24000
trigger: mention
prefix: ""
```

- 不写 `model` 时使用 `.env` 的 `AIMODEL_MODEL`；示例里写的是当前本地模型 ID
- `trigger: mention`：群里必须 @；私聊照常回
- `trigger: prefix`：必须带前缀，如「翻译 」
- `trigger: off`：不自动回
- `whitelist: [...]`：只在这些会话生效

### 6. 改「小明，」这种开头

发送前会去掉回复开头的目标名字，例如「小明，」。在 `.env` 里配置：

```ini
REPLY_TARGET_NAME=小明
```

留空表示不处理。名字中间有空格、特殊字符也可以直接填，程序会自动转义。

---

## 主动消息 / 自动行为怎么改

### 开关与目标

`.env`：

```ini
PROACTIVE_ENABLED=true
PROACTIVE_WHITELIST=wxid_xxx,wxid_yyy
# 兼容旧配置：未设置 PROACTIVE_WHITELIST 时使用
PROACTIVE_TARGET_WXID=
```

- **只给白名单里的私聊发**，不会发给群或其他联系人
- 多个 wxid 用英文逗号分隔；群聊（`xxx@chatroom`）会被自动忽略
- 两个都留空时不启用主动消息和追问

### 时间与频率

```ini
PROACTIVE_QUIET_START=9
PROACTIVE_QUIET_END=22.5
PROACTIVE_MIN_MINUTES=20
PROACTIVE_MAX_MINUTES=90
```

- 安静时段外不发，顺延到 09:00 后
- 从最近一条聊天（你或机器人）算起：20 分钟前不发；20–90 分钟内随机，越往后概率越高，90 分钟必发
- 如果启动时上次聊天已经超过 90 分钟，会很快补发一次
- 你 `PROACTIVE_ACTIVE_SKIP_MINUTES` 分钟内刚聊过，会跳过这一轮，并从你最后一条消息重新计时

### 内容逻辑

位置：`bot/proactive_flow.py` → `_generate_auto_proactive()`

当前提示词会要求：

- 看最近聊天
- 没聊完就追问进展，例如「那个 xx 怎么样了」
- 聊完了就换轻松的新话题
- 只发一两句
- 不提“主动任务/系统”
- 不复读上一条
- 不出现目标名字开头

想改主动消息的风格，改这段 `instruction` 即可。

### 追问

主动消息发出后，会进入“等回复”状态：

- 5 分钟内没收到你的消息 → 追问一句（怎么不回我 / 干嘛不回消息 / 人呢，咋不理我）
- 之后每 55–70 分钟追问一次（你是不是把我忘了 / 咋还不回我）
- 只发追问，不再发其他主动内容
- 追问不参与 20–90 分钟主动计时，也不写入聊天记忆
- 安静时段不追问；你一回复就立刻停止
- 只对主动发送白名单里的私聊生效

代码：`bot/followup.py`。想改首问时间或间隔，改 `.env` 里的 `FOLLOWUP_FIRST_DELAY_MINUTES`、`FOLLOWUP_MIN_INTERVAL_MINUTES`、`FOLLOWUP_MAX_INTERVAL_MINUTES`。

### 视频分享配置

主动消息里可以按概率分享一个较新的 B 站视频。视频分类不写死在代码里，全部由 `.env` 的 `VIDEO_*` 控制；`.env.example` 里的 `default` 只是通用示例，开源使用时可改成自己的兴趣分类。

- 概率：`.env` → `PROACTIVE_VIDEO_RATE`（默认 0.2）
- 默认示例：
  ```ini
  VIDEO_WEIGHTS=default:1.0
  VIDEO_CATEGORY_KEYWORDS=default=视频 分享|视频 合集|热门 视频
  VIDEO_CATEGORY_TERMS=default=视频|分享|合集
  VIDEO_CATEGORY_TOPICS=default=视频
  VIDEO_TOPIC_FALLBACKS=视频=这个视频有点东西
  VIDEO_DEFAULT_FALLBACK=这个有点意思
  ```
- 自定义多个分类时，分类名建议用小写英文，并在各组配置里保持一致：
  ```ini
  VIDEO_WEIGHTS=tech:0.6,music:0.4
  VIDEO_CATEGORY_KEYWORDS=tech=科技 数码|电脑 评测;music=音乐 现场|翻唱
  VIDEO_CATEGORY_TERMS=tech=科技|数码|评测;music=音乐|现场|翻唱
  VIDEO_CATEGORY_BAD_WORDS=tech=广告;music=广告
  VIDEO_CATEGORY_TOPICS=tech=科技;music=音乐
  VIDEO_TOPIC_RULES=tech.手机=新机,tech.AI=AI,music.现场=现场
  VIDEO_TOPIC_FALLBACKS=科技=这个科技视频有点东西,音乐=这个现场不错
  VIDEO_DEFAULT_FALLBACK=这个有点意思
  VIDEO_SHARE_EXTRA_HINT=
  ```
- 权重格式为 `分类:权重`，多个用英文逗号分隔；程序按相对比例自动归一化
- `VIDEO_CATEGORY_KEYWORDS`：每个分类的搜索词，格式 `分类=词1|词2;分类=词1|词2`
- `VIDEO_CATEGORY_TERMS`：标题里至少命中一个才算该分类；留空表示不按标题过滤
- `VIDEO_CATEGORY_BAD_WORDS`：每个分类的额外屏蔽词，格式同上，可留空
- `VIDEO_BAD_WORDS`：全局屏蔽词，所有分类和热门兜底都会过滤
- `VIDEO_CATEGORY_TOPICS`：分类默认话题标签
- `VIDEO_TOPIC_RULES`：标题命中关键词后使用的话题标签，格式 `分类.关键词=标签`，多个用英文逗号分隔
- `VIDEO_TOPIC_FALLBACKS`：按话题标签配置分享语兜底，格式 `标签=句子`
- `VIDEO_DEFAULT_FALLBACK`：没有匹配到话题时的兜底分享语（必填）
- `VIDEO_SHARE_EXTRA_HINT`：给模型生成分享语的额外要求，可留空
- 筛选：`VIDEO_MIN_PLAY`（默认 5 万）；不足 3 条时放宽到 `VIDEO_FALLBACK_MIN_PLAY`（默认 1 万）；按时长、新鲜度和播放量过滤；只在前 `VIDEO_TOP_CANDIDATES` 条里随机
- 时长与新鲜度：`VIDEO_MIN_DURATION`、`VIDEO_MAX_DURATION`、`VIDEO_FRESHNESS_DAYS`
- 搜索与缓存：`VIDEO_SEARCH_LIMIT`、`VIDEO_CACHE_SECONDS`、`VIDEO_INFO_CACHE_SECONDS`、`VIDEO_FRAME_CACHE_SECONDS`
- 去重：已发过的 BVID 记录在 `data/sent_videos.json`，保留数量见 `VIDEO_HISTORY_LIMIT`
- 兜底：所有分类都没有合适结果时，从 B 站热门视频里按全局屏蔽词、时长、新鲜度、播放量再筛一次（`VIDEO_POPULAR_FRESHNESS_DAYS`）
- 分享语：由人设和视频标题生成一句 8–15 字的短句；生成失败时用 `VIDEO_TOPIC_FALLBACKS` / `VIDEO_DEFAULT_FALLBACK`
- 如果 `VIDEO_WEIGHTS` 里出现没有配置关键词的分类，程序会记录警告并忽略该分类

### 群聊吐槽

`.env`：

```ini
GROUP_BANTER_RATE=0.2
```

- 只对群里**没 @** 的纯文字生效
- 默认 20% 概率接一句吐槽
- 不认真回答，不提供信息/建议
- @ 了仍然正常回答

### 表情包

`.env`：

```ini
STICKER_REPLY_RATE=0.1
```

- 默认 90% 忽略，10% 回复
- 想更少回复，把 `STICKER_REPLY_RATE` 调小

### 多消息合并

`.env`：

```ini
REPLY_DEBOUNCE=10.0
BATCH_MAX_MESSAGES=10
BATCH_MAX_CHARS=2000
```

- 你连续发消息时，机器人等最后一条后 10 秒
- 10 秒内又来消息就重新计时，保证一轮对话完整
- 图片、公众号链接、视频转发收到后立即后台解析，解析完再等齐后续文字一起回复
- `BATCH_MAX_*` 只是极端情况的安全上限，实际阈值是 4 倍

### 媒体解析顺序

- 图片、视频、链接收到后立即开始后台解析
- 解析和 10 秒静默等待同时进行
- 解析完成后，把 10 秒内后续消息合并成一次回复
- 文件读取完成后，10 秒内没有后续消息才询问「你想让我做什么」

### 收消息暂停

`.env`：

```ini
INCOMING_PAUSE_EVERY=10
INCOMING_PAUSE_MIN_SECONDS=20
INCOMING_PAUSE_MAX_SECONDS=40
```

- 按会话统计，每收到 10 条消息，回复前随机停 20–40 秒
- 只影响回复时机；发送侧不设频率限制，回复会按拆条规则一次发完
- 点击位置、光标轨迹仍保留随机化

### 拆分条数与句号

`.env`：

```ini
REPLY_BUBBLE_LIMIT=60
REPLY_MAX_BUBBLES=12
REPLY_SPLIT_LIMIT=1500
```

- 默认回复尽量短，通常 1-2 条；问题复杂时由模型决定多答、多分段
- 先按 `|||` / 换行分段；模型觉得需要换条才分，不再按句号强制拆
- 正常分段由模型决定，不再硬性限制“最多对方消息数的 3 倍”
- 只有单段超过 `REPLY_SPLIT_LIMIT` 才做安全拆分
- `REPLY_BUBBLE_LIMIT` 只用于超长段落的兜底，不是每段硬上限
- `REPLY_MAX_BUBBLES` 只是防失控的安全上限，不是目标条数
- 句尾句号会去掉

---

## 群聊规则

- 只在被 @ 时正常回答
- 回复时不 @ 发送者，直接发到群里
- 不 @ 时约 20% 概率吐槽，不回答实质问题
- 群里**不会主动发消息**
- 群里**不会设置提醒**；@ 问提醒会回复「私聊里设」
- 旧的群提醒会被自动跳过并标记完成，不会发到群里
- 主动消息目标固定为私聊 wxid，不会发群

---

## 多模态能力说明

### 联网搜索

- 搜索实现是 `requests + BeautifulSoup` 抓 360 / Bing，**不使用外部 Search/Fetch API**，也不按搜索次数单独计费
- 360 可能触发验证码；失败后自动改用 Bing
- 搜索后会再抓前 1 条网页正文，补足搜索摘要里没有的实时数据，例如天气页面的当前温度和预报
- 搜索结果正文改为并行抓取（最多 5 个），超时或非 HTML 页面会跳过
- 条件提醒会保留「现在 / 实时」等判断词，不会把「上海天黑了」简化成「上海天气」
- 明确说「搜一下 / 查一下 / 百度一下」等，会由 LLM 把请求改写成搜索查询词
- 没有明确搜索词时，先用通用规则快筛（疑问词、看看、时间词等），再由 LLM 判断是否需要搜索
- 查询词由 LLM 结合当前时间和上下文生成，**不针对台风/天气等写死关键词**
- 查询词会简化为核心对象 + 地点，去掉日期、当前、实时等冗余词，避免 Bing 返回无关结果
- `SEARCH_INTENT_MAX_TOKENS`、`SEARCH_QUERY_MAX_TOKENS` 默认 256；`qwen/qwen3.5-9b` 是推理模型，设太小会只剩空 content
- 判断失败时，明确搜索请求用清理后的原文兜底；隐式搜索不搜
- `SEARCH_INTENT_ENABLED=false` 时恢复为只认明确搜索词
- 条件提醒是独立机制，会按自己的间隔联网检查

### 图片

- 从微信数据库下载图片，必要时重试 3.5 秒等落盘
- 本地 OCR：RapidOCR，失败回退 Windows OCR
- 图片 + OCR 文字 + 上下文一起给 AIModel 视觉模型
- 支持多张图，但会限制数量
- 问「这是谁 / 什么角色 / 识别一下」时，是否需要联网识别也由模型判断，不写死触发词
- 需要联网时：本地视觉模型先生成特征词，再用 360/Bing 做文本搜索
- 不保证精准身份，能描述「白发少女」这类特征；搜索结果不可靠时只描述图片特征，不编造名字
- 不做反向图搜，图片本身不上传；只把生成的关键词发给搜索引擎
- 重复句会自动去重，Markdown 粗体星号会清理

### 表情包

- 从微信 CDN 下载 GIF/PNG/WebP
- 按 md5 缓存到 `data/media`
- GIF 取一帧做视觉理解
- 默认 90% 不回复

### PDF

- 文字版：pypdf 直接抽取
- 扫描版：PyMuPDF 渲染页面 + OCR
- 默认最多 8 页 / 6000 字

### B 站视频

- 支持 `bilibili.com/video/BV...`、`b23.tv` 短链、微信 B 站视频卡片
- 解析标题、UP 主、时长、字幕
- yt-dlp 下载最低画质，ffmpeg 抽 4 帧
- **没有音频转写**；没有字幕时只能看画面和画面文字
- 微信原生视频文件暂不支持，只支持 B 站链接/卡片

### 公众号文章

- 支持 `mp.weixin.qq.com/s...` 链接和转发卡片
- 抓取标题、公众号、发布时间、正文
- 遇到验证/风控会回复「没打开」，不会硬编内容

### 普通网页链接

- 支持任意 `http/https` 链接
- 默认最多抓前 `WEB_LINK_MAX_PAGES` 页（8 页），每页最多 `WEB_LINK_MAX_CHARS` 字（5000 字）
- 多个链接并行抓取；验证码、超时、非 HTML 页面会跳过
- 抓取失败不会编造页面内容
- `WEB_LINK_ENABLED=false` 可关闭

### 引用消息

- 引用文字：读取被引用文字
- 引用图片：按 `svrid` 找回原图再识别
- 引用 PDF：找回原文件再抽取
- 引用 B 站/公众号链接：提取 URL 后走对应处理
- 发送人名字不会再被当成正文术语

---

## 数据、隐私与第三方服务

本地数据：

- `.env`：API Key、模型、管理员、主动消息配置；键名/顺序与 `.env.example` 对齐
- `data/bot.db`：聊天记录、提醒
- `data/media/`：图片、表情包、PDF 缓存
- `data/processed/`：文档处理生成的 Word/PDF
- `data/sent_videos.json`：已发送的 B 站视频
- `logs/`：隐藏模式运行时的日志

会发送到外部服务或本地模型的数据：

- 聊天内容 / 图片 / PDF 文字 / 视频帧 / 搜索规划 / 意图判断 / 任务完成检查 → 本地 AIModel 接口（默认不上传云端）
- 图片特征搜索词 → 360 / Bing（图片本身不上传，只发文字关键词）
- 链接自查 → 目标网站 / B 站接口
- 条件提醒检查关键词（包括城市名）→ 360 / Bing
- 天亮 / 天黑条件 → Open-Meteo（只发送城市名和经纬度，不发送聊天内容）
- 搜索结果的网页正文 → 对应网站（只抓取前几条，用于补足摘要）
- 用户发送的网页链接 → 对应网站（最多前 `WEB_LINK_MAX_PAGES` 页）
- 公众号链接 → 微信公众平台
- B 站链接 → B 站接口

普通网页搜索是抓取 360 / Bing 页面，**不调用外部 Search/Fetch API**。

请勿把 `.env`、`data/`、聊天记录提交到公开仓库。`.gitignore` 已默认排除。

---

## 风险与免责声明

- 本项目使用非官方自动化方式操作微信，可能违反微信软件许可及服务协议。
- **有封号风险。请务必使用小号，不要在主号上运行。**
- 发送消息会短暂抢占鼠标/键盘焦点；挂机时不要同时操作微信。
- 微信客户端升级可能导致适配失效。
- 主动消息、提醒、群聊吐槽都可能说错话或打扰别人，请自行控制频率与对象。
- 作者不对因使用本项目造成的账号封禁、数据丢失、消息误发、内容错误等承担责任。
- 使用即表示你已理解并自行承担相关风险。

---

## 常见问题

**机器人没反应？**

- 微信是否已登录、窗口是否打开
- 是否只开了一个 `run.bat`
- 私聊才默认回；群里要 @
- 表情包默认 90% 不回
- 等 10 秒合并消息后再看

**重启后突然回复了旧命令或旧提醒？**

- 旧版本可能把启动前数据库里的消息重新处理一遍
- 现在所有消息都会按 `msg_id` 去重；更新并重启后不会再重复执行
- 同时确认只开了一个 `run.bat`，多个实例也会重复回复

**日志一直刷 `listener poll error: PermissionError(13, '拒绝访问。')`？**

- 这是微信 4.x 临时解密库被 Windows 短时占用，不是模型/API 问题
- 已内置数据库访问重试和启动时清理 1 小时前的临时文件
- 监听间隔默认 2 秒，可用 `WECHAT4_INTERVAL` 调大
- 仍持续时：关闭 `run.bat` 后删除 `%TEMP%\wechatauto_db`，再启动
- 微信和机器人用同一权限运行；杀毒软件排除该临时目录

**文件显示已发送但没收到？**

- 旧版本只验证了 UI 动作，可能误报“已发送”
- 现在文件发送会查数据库确认，并自动重试 3 次；失败会提示结果保存在 `data/processed`
- 微信全屏、被其他窗口遮挡、焦点被抢时，点击可能落空；尽量让微信以普通窗口可见
- 输入框点击位置已下移到输入框高度的 35%–62%，避免点到上方消息区或工具栏
- 如果还是失败，重新发一次文件或要求再发

**说“等一下/正在找”后没下文？**

- 现在每次回复后都会做任务完成检查
- 如果只承诺、没给结果，会继续搜索并补发链接
- 普通聊天、已经给出结果时不会乱补发
- 补发前如果你已经继续发消息，会跳过

**发来的链接都是下架/打不开的？**

- B 站链接会查 `view` 接口和 `state`
- 网页会跟随 360 跳转后实际访问，检查状态码、登录/验证页、404、已删除、正文过短
- CSDN 521、登录验证页会过滤
- 全都没通过时直接说没找到可用的，不会发死链

**图片读不出来？**

- 微信图片可能比消息晚落盘，程序会重试 3.5 秒
- 仍失败就重发一次
- 图片太糊或只有缩略图时 OCR/视觉也会失败

**B 站视频看不了？**

- 目前只支持 B 站链接/卡片
- 微信原生视频文件暂不支持
- 无字幕时没有音频内容，只能看画面
- 会员/高画质视频会用最低画质

**公众号文章打不开？**

- 微信可能有验证/风控
- 程序会直说没打开，不会伪造正文

**为什么问天气、金价没有联网搜索？**

- 明确说「网上查一下上海天气」「搜一下今天的金价」会直接搜索
- 只说「上海明天天气怎么样」时，会先规则快筛，再由模型判断是否需要搜索
- 如果模型判断不需要，就不会搜；想强制搜索就明确说「搜一下 / 查一下」
- 条件提醒是独立机制，仍然会按间隔自动联网检查

**条件提醒怎么没来？**

- 默认每 `CONDITION_INTERVAL_MINUTES` 分钟检查一次（当前默认 5 分钟），需要等一个周期
- 天亮 / 天黑条件按城市日出日落判断，通常很快就会触发；识别不出城市时会回退为搜索判断
- 其他条件依赖联网搜索，搜不到、结果矛盾或无法确认时不会触发
- 搜索引擎结果可能过时，AI 判断也可能出错
- 超过 `CONDITION_EXPIRE_DAYS` 天未满足会自动取消
- `WEB_SEARCH=false` 时不会检查条件
- 用 `#reminders` 查看是否还在等待，用 `#cancel 编号` 或 `#cancel all` 取消

**主动消息怎么没来？**

- 只在 09:00–22:30
- 从上一次聊天时间算：20 分钟前不发，20–90 分钟随机，越往后概率越高，90 分钟必发（安静时段顺延）
- 如果启动时上次聊天已经超过 90 分钟，会很快补发一次
- 你 10 分钟内聊过会跳过，并从最后一条消息重新计时
- 目标必须在 `PROACTIVE_WHITELIST` 里，且是私聊 wxid
- 群里永远不会主动发

**日志在哪？**

- 用 `run.bat` 启动：日志在控制台窗口
- 隐藏模式：`logs/bot.log`、`logs/bot.err.log`
- 旧日志文件可能来自旧实例，注意进程启动时间

---

## 更新记录

### 2026-10-26

**意图与提醒**
- 条件提醒默认检查间隔改为 5 分钟（`CONDITION_INTERVAL_MINUTES=5`、`CONDITION_RETRY_MINUTES=5`）
- 支持隐含提醒：「明天下午三点开会」「后天记得交报告」这类没有明说「提醒我」的消息也会被识别
- 新增天亮 / 天黑类条件：解析城市后，用 Open-Meteo 查经纬度和当天日出日落，再按当前时间直接判断
- 这类条件不再联网搜索、不调用模型；识别不出城市时才回退为普通条件提醒
- 条件搜索词会保留「现在 / 实时」等判断词，避免被简化成「上海天气」这类宽泛话题
- 条件判断允许结合搜索结果里的今日日出日落、实时天气或实时报价推算，不再只看文字结论
- 搜索结果和条件提醒的网页正文改为并行抓取（最多 5 个并发）

**B 站视频配置**
- 视频分类、权重、关键词、标题匹配词、分类屏蔽词、话题标签、话题兜底和分享语提示全部改为 `.env` 的 `VIDEO_*` 控制
- 默认只保留通用 `default` 示例，不再内置个人兴趣分类；开源使用时按自己的类别配置
- README 补充完整的视频配置格式、筛选规则、缓存、去重和热门兜底说明

**文档与配置**
- 补齐 README 中缺失的 `.env` 配置说明，包括日志、数据库路径、并发、微信文件上限、条件提醒 token、主动消息调度和视频解析参数

### 2026-10-25

**本地模型**
- 默认独立 `llama-server` + `qwen/qwen3.5-9b`，API `http://127.0.0.1:8080/v1`
- 新增 `start-model.bat` / `stop-model.bat`
- 上下文默认 32768，超时 600 秒；`.env` 与 `.env.example` 键名、顺序、格式已对齐

**意图与提醒**
- 私聊/群 @ 消息先交给本地模型判断：普通聊天、联网搜索、设置提醒、解答问题
- 抱怨「怎么不提醒我」归为聊天，不再误设条件提醒
- 提醒的时间、内容和条件由模型一起提取；本地只做校验和兜底
- 模型字段不完整时才回退本地解析；仍不完整会先问清楚
- 判为搜索直接使用模型查询词；答题使用完整答案模式
- 图片是否需要联网识别由模型决定，不再写死触发词

**任务与链接**
- 新增任务完成检查：回复只承诺「正在找/等一下」时，模型继续执行并补发结果
- B 站/网页链接补发前自查：B 站查 `view` 状态，网页跟随 360 跳转后实际访问
- CSDN 521、登录/验证页、404、已删除、正文过短都会过滤；只发可用直链
- 全都失效时直接说没找到可用的

**媒体与文档**
- 图片/视频/链接收到后立即后台解析，10 秒内后续消息合并后回复
- 图片作业可生成 Word/PDF 解答；普通「整理成 Word」不再导出聊天记录
- 只有明确说「导出聊天记录」才导出聊天记录

**稳定性与抓取**
- 微信数据库 PermissionError 自动重试；监听间隔默认 2 秒
- 文件发送改为数据库确认 + 3 次重试；输入框点击下移到 35%–62% 高度
- 回复默认 1-2 条、尽量短；复杂问题由模型决定长度和分段；不再按 3 倍/固定条数硬限制
- 搜索最多 10 条结果、抓 6 页正文；普通网页链接最多 8 页、每页 5000 字
- 条件提醒判断上下文提高到 16000 字；公众号文章最多 10000 字

### 2026-10-23

**本地模型**
- 默认模型改为本地 OpenAI 兼容服务：`qwen/qwen3.5-9b`
- 环境变量前缀统一改为 `AIMODEL_*`
- 模型客户端命名统一为 `AIModelClient` / `AIModelError`
- 本地上下文默认 32768，超时 600 秒
- 群聊发送遇到 UIA `COMError` 时自动刷新 UIA / 重建界面并重试
- 默认启用拟人节奏 `WECHATAUTO_RHYTHM=natural`，随机化点击落点和光标轨迹
- 新增按会话的收消息节奏：每 10 条暂停 20–40 秒再回复；发送侧关闭频率限制，保留点击随机化
- 群聊回复不再 @ 发送者，直接发到群里
- 新增单实例锁：重复启动 `run.bat` 会提示已有实例并退出
- 所有消息统一 10 秒静默合并；图片、公众号链接、视频转发收到后立即后台解析，解析完等齐后续文字再回
- 满 10 条立即进入回复流程；`BATCH_MAX_MESSAGES` 可在 `.env` 调整
- 文件解析完成后的询问延迟 10 秒；期间有后续消息时跳过询问，直接结合文件内容回复
- 回复默认 1-2 条、尽量短；复杂问题由模型决定长度和分段；不再按 3 倍/固定条数硬限制
- 分段由模型决定，不再每个句号都强制拆条，也不会为了凑满条数硬拆
- 图片识别请求不再误走纯文本搜索；本地 Qwen 先生成图片特征词，再联网搜文字
- 图片是否需要联网识别由模型判断，不再写死触发词
- 新增任务完成检查：回复只承诺“正在找/等一下”时，模型会继续搜索并补发链接
- 补发前加链接自查：B 站查视频状态，网页跟随 360 跳转后实际访问，过滤 521/登录验证/404/失效链接
- 图片识别只要求描述特征（如白发少女），不保证准确角色名；不确定不编造
- 文件发送改为数据库确认 + 3 次重试；全屏/窗口遮挡导致点击落空时会报失败，不再误报已发送
- 输入框点击位置下移到 35%–62% 高度，减少点到消息区/工具栏
- 重复回复自动去重，清理 Markdown 粗体
- 图片/搜索/链接回复降低温度，并加入 frequency/presence penalty，减少复读
- 图片/作业可以直接生成 Word/PDF 解答文件；“整理成 Word”不再误导出聊天记录
- 支持普通网页链接抓取：最多并行抓前 8 页、每页最多 5000 字；本地模型上下文保持 32768
- 搜索结果正文抓取提高到 6 页、每页最多 4000 字，并行抓取
- 本地上下文 32768 tokens：网页正文最多约 3 万字，搜索约 2 万字，条件判断约 1.6 万字，超出会截断

### 2026-10-22

**表情包**
- 被问「看看这个表情包 / 这是什么」时强制识别并回复，不再按 `STICKER_REPLY_RATE` 跳过
- 新增 `bot/sticker_intent.py`，结合当前消息和最近上下文判断是否在问表情包
- 表情包下载支持 `cdnurl` / `thumburl` / `externurl` / `url`，放宽 CDN 域名
- CDN 取不到时用 UIA 截图兜底；发送和截图复用同一个 GUI/DB，减少数据库缓存冲突
- 修正人设提示词：明确被问时要结合图片回答

**文档处理**
- 新增 `bot/documents/`：接收、解析、任务存储、LLM 处理、Word/PDF 生成、文件回传
- 支持 `.pdf`、`.docx`；`.doc` 提示先另存为 `.docx`
- 收到的文件保存到 `data/media`，读取后自动询问要做什么
- 支持自然语言指令和 `#doc`；结果保存到 `data/processed/<任务ID>/`
- 按用户要求只生成/发送 Word 或 PDF；未指定格式时才两个都给
- 没有待处理文档时，支持「写成 Word」「导出聊天记录」导出最近聊天
- 文档问答会把最近文档内容注入上下文，方便继续问题目
- 文档处理 token 额度可用 `DOC_MAX_OUTPUT_TOKENS`、`DOC_RETRY_OUTPUT_TOKENS` 调整

**提醒与稳定性**
- 定时/条件提醒发送后写入聊天记忆，避免机器人否认自己发过提醒
- 新增 `python-docx`、`reportlab` 依赖

**验证**
- 已通过编译、表情包意图、文档读取、Word/PDF 生成、格式选择、导出流程测试

### 2026-10-21（本次改动摘要）

**架构与配置**
- `.env` 成为唯一配置源，新增 `REPLY_WHITELIST`、`PROACTIVE_WHITELIST`、`REPLY_TARGET_NAME`
- 删除 3.9 `wcferry` 遗留适配器、未启用的手动主动任务模块；`ADAPTER` 只支持 `wechatauto` / `console`
- 拆分 `bot/bot.py`：命令、发送、媒体、主动消息、提醒分别独立
- B 站视频分类、关键词、话题、分享语全部由 `VIDEO_*` 控制

**搜索**
- 明确搜索词直接搜；其他时效问题先规则快筛，再由 LLM 判断是否需要搜索
- 查询词自动简化，去掉日期、当前、实时等冗余词，避免搜索跑偏
- 360 被验证码拦截时自动改用 Bing
- 搜索后抓取第一条网页正文，补足摘要里没有的实时数据（如天气温度）
- 网页搜索和抓取均为 `requests` 实现，不使用外部 Search/Fetch API
- 修复推理模型 `max_tokens` 太小导致 content 为空的问题

**提醒**
- 条件提醒默认 15 分钟；说「每5分钟提醒我」时该条件单独使用 5 分钟
- 支持「七点一刻 / 七点半 / 七点三刻」；「今天七点」早上已过时优先理解为今晚
- 支持改时间、取消单条、取消最近一条、取消全部提醒
- 「提醒我一下就行了」「顺便」「也」「我是说…不是明天早上」等填充内容不再误建提醒
- `#reminders`、`#help`、`#personas` 等命令输出单条发送，不再拆气泡
- 条件提醒也复用网页正文抓取，提高天气等条件判断准确率

**稳定性**
- 所有消息按 `msg_id` 去重，重启不再重复执行旧命令/旧提醒
- 过滤模型泄露的分析、计划和搜索过程，清理旧历史中的此类内容
- 修复换行不拆气泡、提醒内容混入填充词、取消全部提醒漏匹配等问题

**验证**
- 已通过编译、消息去重、条件提醒、搜索规划、天气端到端、时间解析、提醒修改/取消等回归测试

### 2026-10-21（详细记录）

- 重构 `bot/bot.py`：消息编排、命令、发送、媒体处理、主动消息、提醒分别拆到独立模块，`bot.py` 从约 1100 行降到约 370 行
- 删除未启用的手动主动任务模块和 3.9 `wcferry` 遗留适配器；`ADAPTER` 现在只支持 `wechatauto` / `console`
- B 站视频分类、关键词、屏蔽词、话题规则和分享语全部由 `VIDEO_*` 环境变量控制
- 修复重启后监听器回放旧消息、导致命令或提醒重复执行的问题；现在所有消息按 `msg_id` 去重
- 过滤模型泄露的分析、计划、搜索过程和「用户想… / 我搜一下…」这类内容，不再发到微信；同时清理了旧历史里的这类消息
- 搜索查询词改由 LLM 结合当前时间生成，不再按台风/天气等关键词硬编码补时间；同时修复「搜索一下」被拆成「一下」的问题
- 360 被验证码拦截时自动用 Bing；搜索后抓取前 1 条网页正文，补足摘要里没有的实时数据（例如天气温度）
- 搜索规划会压缩查询词，去掉日期/当前/实时等冗余词，避免「上海天气」被搜成无关结果
- 修复 `qwen/qwen3.5-9b` 推理模型在搜索规划/条件判断中因 `max_tokens` 太小只输出 reasoning、content 为空的问题；相关上限默认提高到 256，并自动重试
- 条件提醒默认检查间隔为 15 分钟，扫描间隔 30 秒；用户说「每5分钟提醒我」时只对该条条件使用 5 分钟
- 新增取消全部提醒：`#cancel all`，以及「不要提醒我任何事情了」「取消所有提醒」这类自然语言；避免再被误识别成条件提醒
- 修复时间解析：「七点一刻」不再变成 07:01，支持半 / 一刻 / 三刻；「提醒我一下」「叫我一声」不会再把「一下 / 一声」留进提醒内容或条件里
- 写「今天七点」但早上时间已过时，会优先理解为今晚七点；如果今晚也过了才顺延到明天
- 「我是说…不是明天早上」这类纠正会清理掉填充词，不会把「我是说 / 一声 / 不是明天早上」写进提醒内容
- `#reminders`、`#help`、`#personas` 这类命令输出改为单条消息发送，不再按长度拆成多个气泡
- 支持按时间修改提醒：「七点一刻那个取消，改成七点半」；「提醒我一下就行了」「行了」这类填充词不会再创建条件提醒
- 扩展取消全部提醒的说法：「算了所有提醒都关了吧」「所有提醒都关了」「把提醒全关了」「全关了吧」
- 支持取消最近一条定时提醒：「算了别叫我了」「别叫我了」「取消吧」「删掉这个提醒」；「顺便」「也」这类开头词不会再被当成提醒内容
- 回复里的换行现在也会拆成独立气泡，避免多行内容挤在一条消息里
- 普通联网搜索改为「规则快筛 + LLM 意图判断」：明确搜索词直接搜，时效性问题交给模型判断是否需要搜
- 新增通用条件提醒：例如「上海天晴了提醒我」「金价890提醒我」，定期联网搜索 + AI 判断，满足后通知
- 移除专用金价查询；金价、汇率等时效问题统一走联网搜索
- 配置集中到 `.env`：回复概率、表情包概率、视频分享概率、视频权重、追问间隔、安静时段、各类数量/字数上限等都可以通过环境变量调整
- `.env` 成为唯一配置来源：删除代码里的 `DEFAULT_VIDEO_WEIGHTS` 等默认值，缺少必填项会直接报配置错误；默认值只保留在 `.env.example`
- 新增 `REPLY_WHITELIST`：只自动回复白名单里的会话；留空表示全部
- 新增 `PROACTIVE_WHITELIST`：主动消息和追问只发给白名单里的私聊；支持多个 wxid
- `PROACTIVE_TARGET_WXID` 保留为单对象兼容配置，`PROACTIVE_WHITELIST` 优先
- 默认不再写死作者本人的 wxid；未配置主动发送对象时自动跳过主动消息和追问
- 新增 `REPLY_TARGET_NAME`，不再写死回复开头要去掉的名字
- 更新 `.env.example`，补充全部可调参数和说明

### 2026-10-20

- 接入方式：微信 4.x 本地数据库 + UIA/OCR，非注入
- 人设：默认「鲸鱼女仆」，全年龄向；短、口语化、有反应/吐槽；不使用括号动作；
- 上下文：每个会话独立历史，默认保留最近 80 条 / 24000 字符；连续消息 10 秒合并
- 发送：自动拆条，遇到句号也会拆；每条句尾句号去掉；多条之间 0.6–1.6 秒；偶尔 emoji /「）」
- 群聊：被 @ 正常回答；没 @ 只有 20% 概率吐槽；不主动发、不设提醒
- 表情包：下载微信 CDN，按 md5 缓存，GIF 取帧识别；约 10% 概率回复
- 媒体：图片 OCR + 视觉、PDF 抽取/扫描 OCR、B 站视频解析 + 抽帧、公众号文章正文、引用消息
- 搜索：360 为主，Bing 兜底
- 提醒：定时提醒；只在私聊生效，群里拒绝设置
- 主动消息：
  - 从最近一条聊天算，20 分钟前不发，20–90 分钟随机目标，越往后概率越高，90 分钟必发
  - 不是从启动时间算
  - 安静时段 09:00–22:30，夜里不主动发
  - 你 10 分钟内活跃过就跳过并重新计时
  - 文本主动消息最多一句，20 字内，可以有点自己的反应
- 追问：
  - 主动消息后 5 分钟没回 → 问一句「怎么不回我 / 干嘛不回消息」
  - 之后每 55–70 分钟一次「你是不是把我忘了 / 咋还不回我」
  - 只发追问，不发其他主动内容
  - 不参与 20–90 分钟计时，不写入聊天记忆
  - 安静时段不追问；你一回复就停止
- 主动视频：
  - 约 20% 概率
  - 分类、权重、搜索词、屏蔽词、话题和分享语全部由 `VIDEO_*` 配置；默认只提供通用示例
  - 当前年份 + 365 天内；播放优先 ≥ 5 万，不足放宽到 1 万；按播放排序取前 2
  - 已发 BVID 去重
  - 分享语 8–15 字，带一点吐槽或评价；生成失败时使用配置的兜底句子
- 配置：`.env` 增加 `PROACTIVE_*`、`WEB_SEARCH`、`ADMIN_WXIDS` 等说明
- 游戏暂停：新增 `#pause` / `#resume`；UIA 发送会抢焦点，长时间游戏建议虚拟机/二机
- 许可：MIT License，Copyright © 2026 参数分离
- `run.bat` 只是启动器，业务更新不需要改它；改代码/人设后重启 `run.bat` 即可

---

## 项目结构

```text
ai_talk/
├─ run.bat                     # 机器人启动器
├─ start-model.bat             # 启动本地 llama-server
├─ stop-model.bat              # 停止本地 llama-server
├─ main.py                     # 入口
├─ requirements.txt
├─ .env                        # 本地配置（不要提交）
├─ .env.example
├─ config/
│  └─ personas.yaml            # 人设 / 绑定 / 默认人设
├─ bot/
│  ├─ bot.py                   # 消息入口、批次合并、回复编排
│  ├─ pacing.py                # 收消息暂停与回复节奏
│  ├─ intent.py                # 聊天 / 搜索 / 提醒 / 答题意图判断
│  ├─ task_check.py            # 任务完成检查与补发
│  ├─ link_check.py            # B 站/网页链接可用性自查
│  ├─ wechatauto_patch.py      # 微信数据库访问重试
│  ├─ commands.py              # 管理 / 公开命令
│  ├─ sending.py               # 清理、拆气泡、发送
│  ├─ media.py                 # 图片 / PDF / 视频 / 文章 / 搜索
│  ├─ media_parser.py          # 图片/视频/链接收到即预解析
│  ├─ image_search.py          # 图片特征搜索词生成
│  ├─ proactive_flow.py        # 主动消息与视频分享
│  ├─ reminder_flow.py         # 定时 / 条件提醒设置
│  ├─ conditions.py            # 条件提醒：搜索 + AI 判断
│  ├─ condition_reminders.py   # 条件提醒后台调度
│  ├─ router.py                # 私聊 / 群聊 / 20% 吐槽规则
│  ├─ sticker_intent.py        # 表情包追问意图判断
│  ├─ config.py                # 环境变量
│  ├─ memory.py                # SQLite 聊天记录
│  ├─ prompt.py                # 上下文 / 图片 / PDF / 搜索 / 视频 / 文章拼装
│  ├─ personas.py              # 人设加载与匹配
│  ├─ ocr.py                   # RapidOCR + Windows OCR
│  ├─ pdf.py                   # pypdf + PyMuPDF
│  ├─ search.py                # 360 / Bing 搜索
│  ├─ search_intent.py         # 规则快筛 + LLM 搜索规划
│  ├─ reminders.py             # 提醒存储与定时调度
│  ├─ auto_proactive.py        # 主动消息调度
│  ├─ random_video.py          # 随机 B 站视频（分类 / 新鲜度 / 去重）
│  ├─ video.py                 # B 站解析 / 下载 / 抽帧
│  ├─ article.py               # 公众号文章抓取
│  ├─ documents/               # 文档接收、解析、处理、回传
│  ├─ llm/
│  │  └─ aimodel.py           # AIModel 客户端
│  └─ adapter/
│     ├─ base.py
│     ├─ wechatauto.py         # 微信 4.x 适配器（数据库 + UIA）
│     └─ console.py            # 控制台调试适配器
├─ data/                       # 运行时数据（不要提交）
│  ├─ media/                   # 收到的图片/表情包/文档
│  └─ processed/               # 文档处理结果
└─ logs/                       # 日志
```

---

*最后更新：2026-10-26*
