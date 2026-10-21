# ai_talk — 微信 4.x AI 聊天机器人

一个运行在 Windows 上的微信 AI 聊天机器人。  
它不注入、不 Hook 微信，而是读取微信 4.x 本地数据库接收消息，通过 Windows UI Automation + OCR 驱动真实微信客户端发送消息。

> 本项目是**外部机器人**，不是微信官方插件，也不代表微信/腾讯、DeepSeek、B 站等任何平台。

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

- **私聊聊天**：默认人设「鲸鱼女仆」，DeepSeek `deepseek-flash`
- **会话白名单**：`REPLY_WHITELIST` 限制自动回复范围，`PROACTIVE_WHITELIST` 限制主动消息对象
- **上下文**：按会话保存历史，人物默认保留最近 80 条消息 / 24000 字符
- **像人一样发消息**：短句、多气泡、句号自动拆条、偶尔带 emoji /「）」
- **群聊**：
  - 被 @ 时正常回答
  - 没 @ 时只有约 **20%** 概率随口接一句吐槽，不认真回答
  - 群里不主动发消息，也不设置提醒
- **图片**：OCR + 视觉模型，理解截图、题目、聊天图片
- **表情包**：从微信 CDN 下载，GIF 取帧识别；约 **10%** 概率回复
- **PDF**：文字版直接抽取；扫描版渲染后 OCR
- **引用消息**：引用文字、图片、PDF、链接、视频卡片都能解析
- **B 站链接/视频卡片**：解析标题、UP 主、字幕；下载低画质视频并抽帧看画面
- **公众号文章**：抓取标题、公众号、正文后总结/回答
- **联网搜索**：360 / Bing 抓取；明确说「搜一下 / 查一下 / 百度一下」直接搜，时效性问题先规则快筛再由 DeepSeek 判断是否需要搜
- **提醒**：
  - 定时提醒，如「晚上八点提醒我」
  - 条件提醒，如「上海天晴了提醒我」「金价890提醒我」；定期联网检查，满足后通知
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
| 人设聊天、群聊吐槽 | DeepSeek `deepseek-flash` | 是 |
| 主动消息文案 | DeepSeek + 最近上下文 | 是 |
| 图片/视频帧理解 | DeepSeek 视觉能力 | 是 |
| 文章/搜索结果总结 | DeepSeek | 是 |
| 图片文字识别 | RapidOCR / Windows OCR | 否，本地 OCR |
| PDF 文字抽取 | pypdf / PyMuPDF | 否 |
| 网页搜索 | 360 / Bing | 否 |
| 搜索规划（是否搜 + 查询词） | DeepSeek，少量 token（推理模型需预留 token） | 是 |
| 条件提醒判断 | 联网搜索 + DeepSeek | 是 |
| 提醒、定时、安静时段、频率控制 | 本地调度器 | 否 |
| B 站视频筛选与随机 | B 站搜索 + 本地权重/过滤 | 否 |

需要注意：

- AI 生成内容可能出错，尤其是数字、公式、OCR 结果、文章摘要、视频画面推断。
- 搜索、文章、视频、PDF 等内容仅供聊天参考，不构成投资、法律、医疗或其他专业建议。
- 条件提醒依赖搜索结果和 AI 判断，可能延迟或误判；重要事项建议用定时提醒。
- AI 人设为虚构角色，保持全年龄向；不代表真实人物或平台立场。
- 主动消息由 AI 生成，存在说错话、重复、上下文误判的可能。

---

## 版权与许可

Copyright © 2026 canflee

本项目采用 **MIT License** 开源，详见 [LICENSE](LICENSE)。

- 你可以自由使用、修改、分发，但需保留版权声明和许可证文本。
- 第三方组件、接口和内容归其各自所有者：
  - `wechatauto-replica`：Apache-2.0
  - OpenAI Python SDK：Apache-2.0
  - DeepSeek API：遵循 DeepSeek 平台条款
  - 微信 / 腾讯、B 站、360、Bing：遵循各自平台条款
- 本项目与腾讯、DeepSeek、B 站等均无隶属或官方合作关系。

---

## 运行环境

- Windows 10 / 11
- 微信 **4.1.x** 桌面版，已登录小号，保持窗口可被 UI Automation 识别
- Python **3.12**（64 位）
- 使用独立 Python（路径示例，按实际安装位置调整）：
  `%LOCALAPPDATA%\Programs\PyEmbed312\python.exe`
- 依赖见 `requirements.txt`

> `run.bat` 默认使用 `%LOCALAPPDATA%\Programs\PyEmbed312\python.exe`，不存在时回退到 `.venv\Scripts\python.exe`。换机器时按实际路径修改 `PY` 变量。

---

## 快速开始

1. 启动微信 4.x，登录小号，保持窗口打开
2. 复制配置：
   ```powershell
   Copy-Item .env.example .env
   ```
3. 编辑 `.env`，至少填：
   ```ini
   DEEPSEEK_API_KEY=sk-你的key
   ADAPTER=wechatauto
   ADMIN_WXIDS=你的大号wxid
   ```
   - 想限制自动回复范围：填 `REPLY_WHITELIST`；留空表示所有会话都回
   - 想开启主动消息：填 `PROACTIVE_WHITELIST`（留空且 `PROACTIVE_TARGET_WXID` 也为空时不会主动发）
   - 所有可调参数都从 `.env` 读取，代码里不再保留默认值；缺少必填项会提示
     `配置错误: 缺少环境变量 XXX`
4. 双击 `run.bat`
5. 控制台窗口保持打开；按 `Ctrl+C` 或关闭窗口停止

> **只开一个实例。** 多个 `main.py` 会同时监听、重复回复、抢 UI 焦点。

---

## 使用方式

### 私聊

直接发文字、图片、表情包、PDF、B 站链接、公众号链接即可。  
连续发多条消息时，机器人会等约 4 秒，把上下文合并后回复。

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
- 支持直接改提醒：「七点一刻那个取消，改成七点半」会取消旧时间并保留原提醒内容
- 「提醒我一下就行了」这类没有实际条件的话，不会再被误识别成条件提醒
- 「今天七点」如果早上时间已过，会优先理解为今晚七点；如果今晚也过了，才顺延到明天
- 条件提醒会定期联网搜索并判断条件是否成立，满足后通知
- 条件提醒默认每 15 分钟检查一次；说「每5分钟提醒我」「每半小时提醒我」时，这条条件会单独使用对应频率
- 每次检查都会联网搜索并调用模型，频率越高 API 消耗越大；可用 `CONDITION_INTERVAL_MINUTES` 调整
- 条件提醒依赖搜索结果和 AI 判断，可能延迟、误判或查不到；重要事项建议用定时提醒
- 条件提醒的流程：提取条件 → 定期生成搜索词 → 联网搜索 → 模型判断是否满足 → 满足就通知
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
| 去掉括号动作 / 敏感词 | `bot/sending.py` | `_sanitize()`、`_strip_actions()`、`ACTION_WORDS` |
| 去掉回复开头的名字 | `.env` | `REPLY_TARGET_NAME`，留空不处理 |
| 群聊不 @ 的触发概率 | `.env` | `GROUP_BANTER_RATE` |
| 表情包回复概率 | `.env` | `STICKER_REPLY_RATE` |
| 只回复指定会话 | `.env` | `REPLY_WHITELIST`，留空表示全部 |
| 多消息合并等待时间 | `.env` | `REPLY_DEBOUNCE` |
| 合并上限 | `.env` | `BATCH_MAX_MESSAGES`、`BATCH_MAX_CHARS` |
| 联网搜索开关 / 数量 | `.env` | `WEB_SEARCH`、`SEARCH_MAX_RESULTS`、`SEARCH_CACHE_SECONDS` |
| 搜索规划 | `.env` | `SEARCH_INTENT_ENABLED`、`SEARCH_INTENT_MAX_TOKENS`、`SEARCH_QUERY_MAX_TOKENS` |
| 搜索网页抓取 | `.env` | `SEARCH_FETCH_PAGES`、`SEARCH_FETCH_MAX_CHARS`、`SEARCH_FETCH_TIMEOUT_SECONDS` |
| 主动消息开关 / 对象 | `.env` | `PROACTIVE_ENABLED`、`PROACTIVE_WHITELIST`、`PROACTIVE_TARGET_WXID` |
| 主动消息安静时段 | `.env` | `PROACTIVE_QUIET_START`、`PROACTIVE_QUIET_END` |
| 主动消息间隔 | `.env` | `PROACTIVE_MIN_MINUTES`、`PROACTIVE_MAX_MINUTES` |
| 主动消息文案逻辑 | `bot/proactive_flow.py` | `_generate_auto_proactive()` |
| 视频分享语 | `bot/proactive_flow.py` | `_video_share_line()` / `_video_fallback()` |
| 视频分类过滤 | `bot/random_video.py` | `CATEGORY_BAD_WORDS` |
| 追问逻辑 / 间隔 | `.env` | `FOLLOWUP_FIRST_DELAY_MINUTES`、`FOLLOWUP_MIN_INTERVAL_MINUTES`、`FOLLOWUP_MAX_INTERVAL_MINUTES` |
| 主动视频概率 | `.env` | `PROACTIVE_VIDEO_RATE` |
| 视频类型权重 | `.env` | `VIDEO_WEIGHTS` |
| 视频关键词 | `bot/random_video.py` | `CATEGORY_KEYWORDS` |
| 视频新鲜度 / 播放量 | `.env` | `VIDEO_FRESHNESS_DAYS`、`VIDEO_MIN_PLAY`、`VIDEO_FALLBACK_MIN_PLAY`、`VIDEO_TOP_CANDIDATES` |
| 避免重复视频 | `bot/random_video.py` | `data/sent_videos.json`，保留数量见 `VIDEO_HISTORY_LIMIT` |
| 定时提醒检查间隔 | `.env` | `REMINDER_CHECK_SECONDS` |
| 条件提醒 | `.env` | `CONDITION_CHECK_SECONDS`、`CONDITION_INTERVAL_MINUTES`、`CONDITION_RETRY_MINUTES`、`CONDITION_SEARCH_CACHE_SECONDS`、`CONDITION_EXPIRE_DAYS` |
| 图片 / PDF 上限 | `.env` | `OCR_MAX_IMAGES`、`PDF_MAX_FILES`、`PDF_MAX_PAGES`、`PDF_MAX_CHARS` |
| 微信收发适配 | `bot/adapter/wechatauto.py` | 收消息、图片/表情包/PDF/链接解析、UIA 发送 |
| 模型和 Key | `.env` | `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_TIMEOUT_SECONDS`、`DEEPSEEK_MAX_RETRIES` |
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
model: deepseek-flash
temperature: 0.9
max_tokens: 1000
max_history: 80
max_context_chars: 24000
trigger: mention
prefix: ""
```

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

### 视频概率与类型

- 概率：`.env` → `PROACTIVE_VIDEO_RATE`（默认 0.2）
- 权重：`.env` → `VIDEO_WEIGHTS`
  ```ini
  VIDEO_WEIGHTS=photography:0.20,aviation:0.15,anime:0.35,rhythm:0.15,ai:0.03,robotics:0.05,abstract:0.05
  ```
  > 格式是 `类别:权重`，多个用英文逗号分隔；程序会按相对比例自动归一化。
  - `ai`：人工智能
  - `robotics`：机器人 / 具身智能
  - `abstract`：抽象小视频
- 关键词：`CATEGORY_KEYWORDS`
  - `ai`：人工智能 / AI 大模型 / 智能体
  - `robotics`：具身智能 / 人形机器人 / 机器人演示
  - `abstract`：抽象 / 搞笑整活 / 鬼畜
- 播放量：`VIDEO_MIN_PLAY`（默认 5 万）；不足 3 条时放宽到 `VIDEO_FALLBACK_MIN_PLAY`（默认 1 万）；按播放量排序，只在前 `VIDEO_TOP_CANDIDATES` 条里随机
- 新鲜度：搜索当前年份，且发布时间在 `VIDEO_FRESHNESS_DAYS` 天内
- 分类过滤：`CATEGORY_BAD_WORDS`
  - ai：排除ai视频/ai生成
- 去重：已发过的 BVID 记录在 `data/sent_videos.json`
- 分享语：`bot/proactive_flow.py` 的 `_video_share_line()` / `_video_fallback()`
  - 8–15 字，带一点吐槽/期待/评价，不是光秃秃的标签

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
REPLY_DEBOUNCE=4.0
BATCH_MAX_MESSAGES=8
BATCH_MAX_CHARS=2000
```

- 你连续发消息时，机器人等最后一条后 4 秒
- 把多条合并成一次上下文再回

### 拆分条数与句号

`.env`：

```ini
REPLY_BUBBLE_LIMIT=80
REPLY_MAX_BUBBLES=8
```

- 遇到换行、`。！？` 都会拆条
- 每条最多 `REPLY_BUBBLE_LIMIT` 字
- 最多 `REPLY_MAX_BUBBLES` 条
- 句尾句号会去掉
- 想更长/更短，改 `.env` 里的 `REPLY_BUBBLE_LIMIT`、`REPLY_MAX_BUBBLES`

---

## 群聊规则

- 只在被 @ 时正常回答
- 不 @ 时约 20% 概率吐槽，不回答实质问题
- 群里**不会主动发消息**
- 群里**不会设置提醒**；@ 问提醒会回复「私聊里设」
- 旧的群提醒会被自动跳过并标记完成，不会发到群里
- 主动消息目标固定为私聊 wxid，不会发群

---

## 多模态能力说明

### 联网搜索

- 搜索实现是 `requests + BeautifulSoup` 抓 360 / Bing，**不使用 DeepSeek Search/Fetch API**，也不按搜索次数单独计费
- 360 可能触发验证码；失败后自动改用 Bing
- 搜索后会再抓前 1 条网页正文，补足搜索摘要里没有的实时数据，例如天气页面的当前温度和预报
- 明确说「搜一下 / 查一下 / 百度一下」等，会由 LLM 把请求改写成搜索查询词
- 没有明确搜索词时，先用通用规则快筛（疑问词、看看、时间词等），再由 LLM 判断是否需要搜索
- 查询词由 LLM 结合当前时间和上下文生成，**不针对台风/天气等写死关键词**
- 查询词会简化为核心对象 + 地点，去掉日期、当前、实时等冗余词，避免 Bing 返回无关结果
- `SEARCH_INTENT_MAX_TOKENS`、`SEARCH_QUERY_MAX_TOKENS` 默认 256；`deepseek-flash` 是推理模型，设太小会只剩空 content
- 判断失败时，明确搜索请求用清理后的原文兜底；隐式搜索不搜
- `SEARCH_INTENT_ENABLED=false` 时恢复为只认明确搜索词
- 条件提醒是独立机制，会按自己的间隔联网检查

### 图片

- 从微信数据库下载图片，必要时重试 3.5 秒等落盘
- 本地 OCR：RapidOCR，失败回退 Windows OCR
- 图片 + OCR 文字 + 上下文一起给 DeepSeek 视觉模型
- 支持多张图，但会限制数量

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
- 其他普通网页链接暂不抓取

### 引用消息

- 引用文字：读取被引用文字
- 引用图片：按 `svrid` 找回原图再识别
- 引用 PDF：找回原文件再抽取
- 引用 B 站/公众号链接：提取 URL 后走对应处理
- 发送人名字不会再被当成正文术语

---

## 数据、隐私与第三方服务

本地数据：

- `.env`：API Key、模型、管理员、主动消息配置
- `data/bot.db`：聊天记录、提醒
- `data/media/`：图片、表情包、PDF 缓存
- `data/sent_videos.json`：已发送的 B 站视频
- `logs/`：隐藏模式运行时的日志

会发送到第三方的数据：

- 聊天内容 / 图片 / PDF 文字 / 视频帧 / 搜索规划 → DeepSeek API
- 搜索关键词（包括条件提醒的检查关键词）→ 360 / Bing
- 搜索结果的网页正文 → 对应网站（只抓取前几条，用于补足摘要）
- 公众号链接 → 微信公众平台
- B 站链接 → B 站接口

普通网页搜索是抓取 360 / Bing 页面，**不调用 DeepSeek Search/Fetch API**。

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
- 等 4 秒合并消息后再看

**重启后突然回复了旧命令或旧提醒？**

- 旧版本可能把启动前数据库里的消息重新处理一遍
- 现在所有消息都会按 `msg_id` 去重；更新并重启后不会再重复执行
- 同时确认只开了一个 `run.bat`，多个实例也会重复回复

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

- 默认每 `CONDITION_INTERVAL_MINUTES` 分钟检查一次（当前默认 15 分钟），需要等一个周期
- 检查依赖联网搜索，搜不到、结果矛盾或无法确认时不会触发
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
- 网页搜索和抓取均为 `requests` 实现，不使用 DeepSeek Search/Fetch API
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
- 修复 `deepseek-flash` 推理模型在搜索规划/条件判断中因 `max_tokens` 太小只输出 reasoning、content 为空的问题；相关上限默认提高到 256，并自动重试
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
- 上下文：每个会话独立历史，默认保留最近 80 条 / 24000 字符；连续消息 4 秒合并
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
  - 已发 BVID 去重
- 配置：`.env` 增加 `PROACTIVE_*`、`WEB_SEARCH`、`ADMIN_WXIDS` 等说明
- 游戏暂停：新增 `#pause` / `#resume`；UIA 发送会抢焦点，长时间游戏建议虚拟机/二机
- 许可：MIT License，Copyright © 2026 canflee

---

## 项目结构

```text
ai_talk/
├─ run.bat                     # 启动器
├─ main.py                     # 入口
├─ requirements.txt
├─ .env                        # 本地配置（不要提交）
├─ .env.example
├─ config/
│  └─ personas.yaml            # 人设 / 绑定 / 默认人设
├─ bot/
│  ├─ bot.py                   # 消息入口、批次合并、回复编排
│  ├─ commands.py              # 管理 / 公开命令
│  ├─ sending.py               # 清理、拆气泡、发送
│  ├─ media.py                 # 图片 / PDF / 视频 / 文章 / 搜索
│  ├─ proactive_flow.py        # 主动消息与视频分享
│  ├─ reminder_flow.py         # 定时 / 条件提醒设置
│  ├─ conditions.py            # 条件提醒：搜索 + AI 判断
│  ├─ condition_reminders.py   # 条件提醒后台调度
│  ├─ router.py                # 私聊 / 群聊 / 20% 吐槽规则
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
│  ├─ llm/
│  │  └─ deepseek.py           # DeepSeek 客户端
│  └─ adapter/
│     ├─ base.py
│     ├─ wechatauto.py         # 微信 4.x 适配器（数据库 + UIA）
│     └─ console.py            # 控制台调试适配器
├─ data/                       # 运行时数据（不要提交）
└─ logs/                       # 日志
```

---

*最后更新：2026-10-21*
