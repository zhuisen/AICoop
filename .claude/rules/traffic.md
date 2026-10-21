---
paths:
  - "traffic/**"
  - "**/src/traffic.ts"
  - "**/src/rates.ts"
  - "**/useTraffic.ts"
  - "**/TrafficPage.tsx"
  - "**/PlatformPage.tsx"
  - "**/RequestsPage.tsx"
  - "**/src/requests.ts"
---

# 流量总览 / 多 AI 用量口径（path-scoped）

> 2026-09-10 从项目 `CLAUDE.md` §5 整段搬来，**逐字未改**。
> 搬的理由：它 43 KB、占 §5 的 62%，而**内容是 `traffic/scan.py` 的口径不是 UI** ——
> 四家 token 归一、去重键、增量解析、缓存签名、时区分桶、PARSER_V、以及几条弃案。
> 留在总是加载的正文里，每次碰这个项目都要吃掉它；塞进 UI 那份规则里更糟 ——
> 编辑 `scan.py` 时它**正好不会加载**。
>
> ★ **这里是正本**。`CLAUDE.md` §5 只留一行路由。

- **流量总览（v0.7.0 起唯一的消耗视图）**：`traffic/scan.py [--days N] [--json] [--no-cache]` + 主界面「AI用量信息」页（`TrafficPage`）→ 点平台进「详情」（`PlatformPage`）。走独立 tauri 命令 `run_traffic`（**刻意不挂进 `run_rotate` 的白名单**：那条通道守的是账号池命令，两套语义混一个白名单迟早加错）。**八个数据源**全是本机 CLI 自己落的盘，零额度消耗、不联网、不碰凭证（后三个是宿主源，见下）。⚠️ **这句话的范围是 `traffic/`，不是整个仓库**（2026-08-24 起）：`grok-quota` 会读 `~/.grok/auth.json` 并打 xAI 的账单接口，它**刻意不在 `traffic/` 里**、也不挂进 `run_traffic` 的白名单，正是为了让这条安全线仍然可以按目录一眼判定。别把它挪进来。数据源本身仍是：Claude `~/.claude/projects/**/*.jsonl`（并入 OTel 账本 `traffic/otel-ledger/` 里 transcript 没有的调用，2026-10-19）· Codex `~/.codex/sessions/**/rollout-*.jsonl` 与 `rollout-*.jsonl.zst`（2026-10-16 起，见下面 codex `.zst` 那条）· Grok `~/.grok/**/updates.jsonl` · Kimi `~/.kimi-code/sessions/**/wire.jsonl`。
  - 2026-08-09 取代了原来的「Token 消耗」+「Claude 消耗」两页（`TokensPage.tsx` / `ClaudeTokensPage.tsx` / `AreaChart.tsx` 已删）。**别再按平台各写一份扫描器**——四家的 token 语义不同（下条），分头实现必然在边界上互相矛盾。
  - ★ **四家的 `total` 口径不一样，必须先归一化再比**（2026-08-09 实测）：codex `total = input + output` 且 `cached_input ⊆ input`；Grok `totalTokens = input + output` 且 `cachedRead ⊆ input`；**Claude 与 Kimi 的输入各字段互不相交**（Claude `input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`；Kimi 见下面 kimi 口径那条）。`scan.py` 统一折成四个**互不相交**的类：`uncached_in | cache_read | cache_write | output`，相加才是 total。直接把四家的 `total` 摞在一张图上就是拿四把不同的尺量同一根线。
  - ★ **去重口径按家写死，不是一条通则**：Claude 按 `message.id` **全局**去重（虚高 2.23x）；**codex 按累计值 `total_token_usage.total_tokens`**（同一 `token_count` 事件会成对重复写入——旧注释「codex 实测均无重复」已作废）；OpenClaw 按 `responseId`（虚高 4.08x）。**不按内容哈希**，两轮恰好用掉一样多 token 是常事；取不到累计值时**保留该条**（fail-open）。`SOURCES` 里 codex 的 `dedup: False` 只指**跨文件**不合并，不代表文件内没重复——两个概念共用一个词，旧注释就是这么写偏的。时区口径见下面几条，`PARSER_V` 是它们的版本闸。
  - ★ **窗口按自然日切，不是"最近 N 个有数据的日期"**。旧写法（取有数据的日期排序后 `[-N:]`）让 `--days 90` 的合计随时区浮动 **3.2%**，因为不同 TZ 下"有数据的日期"集合本身就不同。现在用 `date` 算术生成连续 N 天再补零，空白天显式为 0。
  - ★★ **取数一律走 `useTraffic`,不要直接 `invoke("run_traffic")`**。`run_traffic` 每次成功都会**原子落一份成品** `.traffic-latest.json`(先写 `.tmp<pid>` 再 `rename`;直接覆写会让并发读者读到半截 JSON —— 主窗口在扫描、用户同时点开菜单栏，是每天都会发生的时序)。`useTraffic` 先读快照,只有快照过期才后台补扫。实测 **快照 1.1ms(0.25ms 读盘 + 0.86ms 解析)vs 全量热路径 1350~2785ms**,用户报的「token 页面新打开有几秒停顿」就是后者。
  - ★★ **两个 webview 共用数据、共用新鲜度规则,但各自决定何时要新数据**（用户 2026-08-11 定稿）。主窗口曾是"进页面无条件重扫"(旧的 `revalidate:true`)，菜单栏是"超过 10 分钟才补扫"——**同一份数据两套新鲜度标准**，于是「菜单栏刚自动刷新 → 点进主界面又刷一次」。两边渲染的是同一个 `.traffic-latest.json`，独立只可能产生分歧。三层，缺一层还会重复：
    - ① **同一条 `FRESH_MS`** —— `revalidate` 参数已删除，两边都按岁数判。挡的是"对方**刚扫完**"。
    - ② **`emit("traffic-updated")` 广播** —— 扫完通知对方**读盘**(~1ms)而不是重扫(~1.4s)。两个 webview 是独立 JS 上下文，localStorage 都不互通，只能走 Tauri 事件（同 `usePrivacy` 范式）。`adopt()` 只接受 `generated_at` 更新的数据，所以自己发的那条不会造成回环。
    - ③ **Rust 侧 `SCAN_LOCK` + 新鲜度双检**（`SCAN_COALESCE_SECS = 90`）—— 拿到锁后再看一眼快照岁数，已新鲜就直接返回不起 python。**前端只能挡住"对方已扫完"，挡不住两边同时判定要扫**，所以这一层必须在 Rust。
      - ★★ **④ 进行态也必须广播**（`hooks/useBusyMirror.ts`，用户 2026-09-06：「菜单栏点了刷新，进主界面没显示正在刷新」）。前三层同步的是**数据**和**完成信号**，而 `loadingAction` / `busy` 一直是各自的 React state ⇒ 对方只在动作**结束**时才知情，整个执行期间（刷新全池逐号 GET + 1.5s 节流；冷路径扫描 ~23s）显示得像什么都没发生。
      - **熄灯必须有三条互相独立的路径**，因为镜像态是"别人告诉我的"、我无法确认它还成立，而长亮又灭不掉的灯是本仓判过死刑的形态：① 对方的结束事件（`announce(null)`，**必须在 `finally`**）；② Rust/扫描器发的 `state-changed` / `traffic-updated` —— **不经过发起方**，对方 webview 崩溃或重载时只有这条能救；③ 硬超时 `STUCK_SEC=180`。
      - ★★ **绝不能回放自己的事件**：Tauri 的 `emit` 广播给**包括自己在内**的所有窗口，不按 `getCurrentWindow().label` 过滤的话，发起方 `finally` 清了本地态而镜像还亮着 ⇒ **按钮转圈停不下来**，比原缺陷更糟。
      - 两个 hook 共用同一条 `action-busy` 通道，所以 `useStore` 要把 `traffic-scan` 筛掉 —— 眼下没有按钮匹配它所以"碰巧无害"，下一个按钮 id 撞上就乱转圈。
      - ⚠️ **harness 一次只渲染一个 webview**，「跨窗口」只能靠注入事件验：`?busyfrom=<action>`（`from: 'other-window'`）+ 反向对照 `?busyself=<action>`（必须被忽略）。**没有这对开关，这次改动在 harness 里一个像素都验不到，而截图会正常渲染、探针会报干净。** 闸在 `tests/test_busy_mirror.py`（3 次变异全红）。
  - ⚠️ 因此「新鲜度判断只在展示层」这句**已作废**（那是 `revalidate` 时代的说法）：策略仍在展示层，但**并发合并在 Rust**，两者不冲突。
  - ★ **自动保鲜:三个触发点共用一个 `FRESH_MS`(2 分钟)**。① 挂载;② 30s 心跳(**仅 `document.visibilityState === "visible"` 时**);③ 托盘弹出的 `menubar-shown` 事件(阈值收紧到 30s —— 主动点开就是想看现在的数)。心跳只是"到点看一眼岁数",不到期不扫,所以 30s 节拍 ≠ 30s 扫一次。
    - **为什么非要事件+心跳**:菜单栏 webview **只在 app 启动时挂载一次**(托盘 show/hide 不重建 webview),初始化 effect 被 `primed` 锁住后再不会跑 —— 不补这两条,今日 Tab 的数字会冻在开机那一刻(用户 2026-08-09 报「过了几十分钟还没刷新」)。
    - **可见性门已实测有效**(2026-08-09):弹窗关闭状态下盯快照 mtime 3 分钟,零重扫;若门失效,按 2 分钟阈值至少还会再写一次。所以没人看时是零开销 —— 一次扫描要 ~0.8s CPU + stat 10300 个文件,后台空转纯属浪费。★ 用户 2026-08-22 可在设置页关掉这条心跳（「后台自动刷新」），关掉后只在**进入用量页 / 弹出托盘 / 点 ↻** 时更新。
    - ⚠️ **别给挂载单独设更宽松的阈值**。曾经挂载用 10 分钟、心跳用 2 分钟,结果启动 30s 后必定多扫一次(实测)。同一个"新鲜"只能有一套标准。
  - 菜单栏 webview 启动即创建(隐藏),所以 app 一起来就预取了一次。**这意味着改 `useTraffic` 会影响冷启动开销**,别在它里面加重活。
  - ★★ **加一家平台 = 写一个 `_scan_*` + 在 `SOURCES` 加一行,前端不用动**。平台名/配色/可用性随扫描结果一起下发（`platforms[k].color`），UI 照着渲染；`theme.ts` 的 `PLATFORM_COLORS` 降级为兜底。★ **三个宿主源**（`SOURCES` 里 `host: True`）：OpenClaw / Reasonix / DeepSeek Harness 自己都不是平台，解析器给每条 row 加**第 7 位平台键**，聚合层据此路由；归属**按模型名判、不按 provider 判** —— 本机 provider 是 `xiaomi`/`huohuo` 这类账号昵称，按它归会造出假平台，认不出才回落 provider 名。⚠️ **只有 openclaw 走 `_openclaw_platform`**：reasonix / dsh 是 1:1 采纳外部贡献者补丁（用户 2026-08-15 指示全量采纳），各自行内路由，跑了非 deepseek 模型会造出名叫 `gpt-5.5` 的假平台；它们的模型名也**不归一**（保留 `deepseek-pro/` 前缀），所以 `rates.ts` 要按前缀各收一条。dsh 还依赖外部 `zstd`，取不到时抛 `ScanReadError`、进 `read_failed`（2026-10-16 前是**静默返回 0 行**，B84 顺带修）。**停用有两条路，语义不同**：`--exclude k` / `traffic/sources.local.json` 的 `{"disabled":[…]}`（gitignored）＝**扫描层**，压根不解析，且只认**源** key（传路由出来的 `deepseek`/`mimo` 会报「未知平台」）；设置页开关＝**展示层**，数据仍在缓存里，开回来不用重扫。扫描结果里带 `scan.enabled` / `scan.registered` —— **少了一家时靠它区分"被停用"还是"解析器坏了"**（2026-08-09 吃过一次哑巴亏，快照里没这个字段就事后无法诊断），但它列的是**源**不是平台：宿主源恒在 `registered` 却不作为平台出现，`deepseek`/`mimo` 恰好相反，**别拿这两个集合与 `platforms` 直接作差当诊断**。
  - ⚠️ **解析器必须一家一写,不要做"通用适配器"**。实测四家四种形状，猜字段名正是会静默算错数的做法。
  - ★★ **codex 会把旧会话压成 `rollout-*.jsonl.zst`，必须计入**（2026-10-16，外部用户实报，CHANGELOG B84）。他的机器 1,675 个 `.zst` 对 37 个 `.jsonl`，90 天漏算 96%（143.4M vs 4.03B）。口径：
    - 只收 `.jsonl` 与 `.jsonl.zst`（`_codex_keep`）；`.jsonl.bak-namespace*` 等旁支**不收**（SQLite 里查不到对应会话，收了凭空多 841M）。同名并存只收 `.jsonl`（压缩中途 `.zst` 可能没写完，codex 源 `dedup: False`）。
    - 解压走 `_zstd_text`（先 Python 3.14 `compression.zstd`，再 `zstd` 命令行），**失败抛 `ScanReadError`**，绝不返回空 —— 空会连同签名进缓存，把会话钉成 0 token。
    - 压缩保留原 mtime，`cut` 预筛照常成立；不升 `PARSER_V`（row 不变，`.zst` 是新缓存键）。
    - ⚠️ **SQLite `threads.tokens_used` 加总不能当真值**：分叉会话（`forked_from_id` 非空）第一条累计值就带着父会话的全部消耗，他那份 56 个分叉会话重复了 6.44B。扫描器累加的是每次请求的 `last_token_usage`，不受影响。别拿 SQLite 校准扫描结果。
    - `~/.codex/archived_sessions`（Codex 里归档的会话）目前**不在**扫描根下，要不要计入未拍板。
  - ★ **每个已注册源都有一条状态 `scan.sources`**（2026-10-16，B85）：六态 `not_found/empty/ok/partial/read_failed/disabled`，
    外加 `no_decoder`（没有解压器，不是文件坏了）与 `unparsed`（压缩过却没解析，按后缀计）。普查**只认压缩后缀**
    （grok 根下 127 个 `.lock`），同名 `.jsonl` 已收的不算漏。给人看的话只走 `scanHealth.ts::sourceNotes`；
    没找到 / 空是 info 不是告警。UI = 设置页「数据源状态」块（用户 2026-10-16 选 A，**不进用量卡**）；
    旧快照没有 `sources` 时整块不画，绝不说「全部正常」。
  - ★ **kimi 口径（2026-08-09 实测，75 个 wire.jsonl / 1745 条）**：只认 `type == "usage.record"` 且 `usageScope == "turn"`。三个坑：① 同一笔账记了两遍——`usage.record`(1746) 与 `event.type=="step.end"` 的 `event.usage`(1745) 四类逐项零差，两个都加就翻倍（选前者因为它带 `model`）；② `usageScope` 里混着 **1 条 `session`** 累计记录，不滤掉就重复计一整个会话；③ 四个字段 `inputOther|inputCacheRead|inputCacheCreation|output` **本来就互不相交**（与 Claude 同族，与 codex/Grok 相反）——**别在这里做减法**。另：`main` 与 `agent-N` 的 wire 日志 uuid 零交集，所有文件直接相加不会重复；`time` 是 epoch **毫秒**。
  - ★★★ **Antigravity(agy)：2026-09-09 起主源是 agy 自己的 SQLite，覆盖 ~91%（不再是 print-only 的 16%）。**
    - **「本地零落盘」这半被彻底推翻，而且是我自己写错的**：原话「扫遍 261 个 db，结构化 `promptTokenCount` 零命中」——
      `gen_metadata.data` 是 **protobuf wire format，里面根本没有字段名**，`grep promptTokenCount` **永远** 0 命中。
      用一个看不见目标的探针得出"目标不存在"，与本仓记过两次的 grep 假阴性同族。**下面那些"零命中"的旧论据一律作废。**
    - 字段（盲解 + 与 wrapper 账本逐会话核对 69 个）：`gen_metadata.data → f1.f4.{f2=input, f3=output, f5=cache_read, f9=thinking}`、
      `f1.f19` = 模型 id。★ **`f9` 是 `f3` 的子项，绝不能加**（`f3` 单独命中 63/69，`f3+f9` 只有 1/69）。
      时间戳：第 k 条 gen ↔ 第 k 个 `step_type=15` 的 `metadata → f1.f1`（epoch 秒）。
    - ★★ **这些库是 `journal_mode=wal`**：写入落在 `-wal`，**主库 mtime 原地不动** ⇒ 缓存签名与 `cut` 都必须看 `-wal`
      （`_agy_db_sig`）。不看的症状是**数字停在旧值、零报错**。
    - 账本（`bin/agy` wrapper，print-only）降级为**并集兜底**，只补 db 已消失的会话；共有会话一律以 db 为准，**绝不双计**。
    - 实测接入前后：覆盖率 `37/101 (36.6%) → 277/303 (91.4%)`，90 天合计 `9M → 317M`。
      闸：`tests/test_agy_sqlite.py`（14 条，4 个变异全红）。
    - ★★ **字段表已由 agy 自己的 protobuf descriptor 实证（2026-10-19，agy 1.4.2），不再是盲解**。
      做法：在二进制里找 `\x0a<len><消息名>`，回读长度前缀，解析 `DescriptorProto` → 精确字段号（脚本思路见 kb「agy 会话库 protobuf 完整字段表」）。
      · `gen_metadata.data → f1` = `ChatModelMetadata`：`4` usage · `11` time_to_first_token · `12` streaming_duration（都是 `Duration`）· `13` credit_cost · `14` retries · `17` retry_infos · `19` response_model。
      · usage = `ModelUsageStats`：`2` input · `3` output（**含 thinking**）· `4` cache_write · `5` cache_read · `9` thinking · `10` response_output（可见输出）· `11` response_id。
        实测 `f10 == f3 − f9` **1802/1802**；`cache_write` 本机恒 0（没漏算）；`credit_cost` 本机 0。
      · `steps.metadata` **本身**就是 `CortexStepMetadata`：`1` created_at · `6` viewable_at · `7` finished_generating_at · `8` completed_at · `22` last_completed_chunk_at · `32` started_at · `4` tool_call（`2` = 工具名；`3` = 参数 = **正文，别读**）· `9` model_usage · `23` tool_call_output_tokens。
      · `step_type`：15 模型回复 · 132 工具调用 · 14 用户输入 · 101 系统消息 · 23 checkpoint · 17 错误。`steps.status`：3 完成 · 5 清除 · 6 取消 · 7 出错 · 8 **生成中** · 2 运行中 · 9 等待。
      · ★ **模型时间不含工具时间**：模型回复步的 `finished_generating_at − created_at` 与 gen 的 `ttft + streaming` 差值 <1s **1804/1804**（最近 120 库）。所以 agy 的 t/s 是**实测**，「含工具时间所以只能估」那个说法作废。工具耗时 = 工具步 `completed_at − started_at`（`run_command` 中位 3.0s / p90 17.7s，`view_file` 0.16s）。
      · 本机 agy 没有子 agent 会话（`trajectory_metadata_blob` 无 parent id）；`cli.log` 里没有模型计时（`latency_breakdown` 只是本地发送几毫秒）。
    - ⚠️ 下面这段是 2026-08-19 的旧结论，**只保留仍然成立的部分**（口径、模型名、云端 API、弃案）；
      凡涉及"拿不到 / 零落盘 / 只覆盖 print 模式"的表述都已被上面推翻：
    - **「本地零落盘」这半仍然成立**，且已用更大样本复验：123 个会话 SQLite + `transcript.jsonl` + `transcript_full.jsonl` + `cli.log`，结构化 token 字段**零命中**；CLI 无 usage 子命令。⚠️ **朴素 grep `usageMetadata` 会假阳性** —— 唯一命中的是「我问 agy 这个问题、它自己答案里那段 JSON 示例」，自指。与 Claude 额度那次同款，**别被 grep 的命中数骗到**。
    - **推翻的是「完全拿不到」**：`agy -p --output-format json` 的 stdout **直接返回五类用量**。故做 `bin/agy` wrapper（PATH 前置 → 截获 print 模式记账 → 把 `response` 原样吐回，调用方零感知）。`omc ask antigravity` 与 `omc team N:antigravity` **都走 `-p`**（`runtime-cli.cjs` 的 `getPromptModeArgs`），两条都覆盖；**交互式会话永远拿不到**，靠 `coverage` 字段显式标注（覆盖率是**上界**，分母来自 agy 自己的 transcript）。
    - ★★ **口径与 codex/Grok 族相反,改之前必读**：usage 是**会话内累计**（三轮实测 out 113→190→245 单调递增），且 `input_tokens` **已扣掉 cache_read**（Claude/Kimi 族，各项互不相交）——**绝不能再做 `input - cache_read`**。与线上 wire 逐项精确吻合（误差 0）：`input=Σ(prompt−cached)` · `output=Σ(cand+thoughts)` · `total=input+output`，**agy 自报的 total 不含 cache_read，因此少算 36%**，别直接用。
    - **云端只有额度、没有 token**：`POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` 实测 200，回的是**每模型剩余请求数**（`tokenType` 恒 `REQUESTS`）+ 重置时间，**无 token 明细**；`retrieveUserQuotaSummary` 裸调 403。按 token 查历史，Google 没有这种 API。`countTokens` 是**重新推导不是记录**（分不出 cache_read），同 Claude 额度那条一并否掉。
    - **弃案：常驻 MITM 全覆盖。** 技术上可行且不难 —— 协议是 **HTTP/1.1 + JSON 不是 gRPC**（全部 `POST /v1internal:*`，`streamGenerateContent?alt=sse` 的响应里带 `usageMetadata`），agy 认 `HTTPS_PROXY`/`SSL_CERT_FILE`、**无证书固定**。不做的理由：要解密 Google OAuth 凭证，与「流量扫描器不碰凭证」的定位冲突，且补不回历史。⚠️ `SSL_CERT_FILE` 是**替换**根池不是追加，只指自签 CA 会让没被劫持的主机验不过。
    - ★ **模型名要从 agy 自己的日志回填,别记成 `unknown`**：`omc ask` 不传 `--model`，而 JSON 输出 / 会话 SQLite / transcript 里**都没有模型名**（全查过）。唯一有的地方是 `~/.gemini/antigravity-cli/log/cli-*.log`：`printmode.go] Print mode: starting (..., model="…")` 只回显命令行参数（不传就是空），**`model_config_manager.go] Propagating selected model override to backend: label="Gemini 3.7 Flash (High)"` 才是真正生效的那个**。wrapper 按**会话 id** 定位本次运行的日志（**不是按 mtime 取最新** —— `omc team` 并行起 N 个 agy 各写各的日志，按时间取必然张冠李戴），再交给 `_agy_model` 归一。
    - ★★ **由此纠正一个错的兜底价**：本机默认是 **Gemini 3.7 Flash**（$0.75/$3.75）不是 3.1 Pro（$2.00/$12.00）。我最初按「3.1 Pro 是 omc 内置默认且最贵，取上界」兜底，**费用高估 2.7 倍**。教训：兜底价要贴**真实默认**，「取最坏情况当上界」在这里是错的直觉。
    - ★ **模型名归一各家惯例不同**：Google 版本号带**点**（`gemini-3.7-flash-high`），Anthropic/OpenAI 一律**横线**（`claude-opus-4-6-thinking`/`gpt-oss-120b-medium`）；且 agy **自己命名不一致** —— Opus 的 id 保留 `-thinking`、Sonnet 却丢掉（`claude-sonnet-4-6`），只能列例外。归错**不报错**，只是悄悄换一档价（Opus 按 Flash 计差 6.7 倍），所以有回归闸 `tests/test_agy_model_names.py`（14 条真值来自 `agy models` 两列；已做变异测试，3/3 真变异变红）。
    - **注意 agy ≠ gemini CLI**，本机两个都装，是两个不同的东西。
  - ○ **官方 Gemini CLI 可接但数据已停**（`~/.gemini/tmp/*/chats/*.json`，97 会话 / 435 条）：`{input,output,cached,thoughts,tool,total}` + `model`，实测 435 条零反例 —— `total = input+output+thoughts+tool` 且 **`cached ⊆ input`**（codex/Grok 那一族）。多一个 `thoughts` 类，接的时候要定它并进 `output` 还是单列。最后更新 **2026-06-18**，接进来是历史数据。
  - ★★ **Claude 没有额度油表,是拿不到不是没做 —— 定稿 2026-08-10,别再查第三遍**。用户看到第三方软件能显示 Claude 的 5h/周额度后问过一次,重查结论不变,且这次证据更硬(Claude Code **2.1.224**、5648 个 transcript):
    - ⚠️ **朴素 grep 会给出假阳性,别被它骗到**:直接搜 `rate_limit|resets_at|remaining|quota` 命中 552 / 1513 / 1526 / 8592 次,看着像"有"。按**结构化字段 vs 正文里的字**重扫后,真字段只有两个 —— `attachment.remaining = 1.5`(与额度无关)和 **`error.rateLimits`(85 次,非空 0 次**,槽位存在但从未被填)。其余全是**文件路径里带 quota**(本仓库自己的 `quota_daemon.py`、`weekly-quota-demo.html`…)和我们讨论额度的对话正文。
    - `stats-cache.json` 只有 token 统计(`dailyModelTokens`/`modelUsage`);`~/.claude.json` 的 `remaining_passes` 是别的东西;`claude --help` 无任何可脚本化的 usage/quota 子命令。
    - **第三方是走钥匙串**:`security find-generic-password -s "Claude Code-credentials"` 存在,它们拿订阅凭证调服务端(`/usage` 的额度条本来就是实时拉的),不是读日志。**Anthropic Consumer Terms §3 禁止「非 API key 的自动化访问」**,codex 那边没有等价禁令,所以只有 codex 有油表 —— 两边没有对等物。
    - **用户 2026-08-10 决定:不走这条路。** 也**不做本地估算** —— `total` 里 96% 是缓存重读,而 Anthropic 按不按缓存折价计量至今未定,估出来可能差几倍;**给一个看起来精确、实际可能错 3 倍的百分比,比坦白拿不到更糟**(同「不用 `+N` 藏数据」一条原则)。
  - ★★★ **定稿 2026-10-19（用户）：Claude 与 agy 的实时额度走「状态栏转写落盘」**。上面 08-10「Claude 没有油表」那条的**结论被补上了**（那时 statusline 还没有 `rate_limits`，v2.1.80 才加），它否掉的两条路（读钥匙串 / 本地估算）**仍然否**。
    - **做法**：CLI 每次刷新状态栏，把一段 JSON 交给用户配置的命令（两家官方文档写明的功能）。在用户**自己的**脚本里加一步，把额度字段原子写盘：
      Claude = `~/.claude/settings.json` 的 `statusLine` 命令，取 `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}`；
      agy = `~/Projects/tools/agy-status/statusline.sh`，取 `quota.<桶>.{remaining_fraction,reset_time}`（桶名 `gemini-5h`/`gemini-weekly`/`3p-5h`/`3p-weekly` **只有 `gemini-weekly` 见于官方文档，其余待真实 payload 核**）。
    - **为什么选它**：不读 token/cookie/钥匙串、不多发一个请求（不会撞 `/api/oauth/usage` 那种 429，anthropics/claude-code #30930）。Codex 有「CLI 自己把 `rate_limits` 写进 rollout」，这三家都没有，这是最接近的替代。
    - **只写白名单字段**：payload 里还有 cwd、transcript 路径、模型名，一律不落盘。脚本失败必须静默跳过，**不能影响状态栏本身**。
    - **四个已知局限**（社区踩过）：① CLI 不在跑就没有新数（Claude 退回 Claude.app 的 `plan-usage-history.json`，只有已用%、无重置时间）；② 会滞后（agy-hud 实测 agy 一轮内不动、闲置 5h 值滞后 25 分钟）⇒ 每条带时间戳，UI 写「截至 HH:MM」；③ Claude 没有按模型的周额度；④ ★★ **payload 不带账号身份**（CodexBar PR #2769 当天回滚的理由之一）—— Claude 单号无碍，**agy 多号池必须做归属核对**（同 B55：对不上当值号就丢，不记到别的号头上）。
    - 社区同法：stablyai/orca（叠在 OAuth 上）、franksde/agy-hud（首选 statusline quota）、用户自己的 clawd。调研全文在 kb「Claude / agy / grok 实时额度抓取方法、社区评价与风控」。
    - ⚠️ **agy 风控另案**：Google FAQ 把「第三方软件访问 Antigravity」写成违反 ToS，问题标题点名「automate account switching」，答案是包装 agy「not supported under consumer plans」。转写本身不在其列，但本仓的 `agy-rotate` 自动切号 / 云端读额度在 —— **要不要收紧，未拍板**。
  - ★★★ **请求账本 / 实时 t/s**（2026-10-19 重构，`traffic/requests.py`；契约 `scratch/redesign_20261019/PLAN.md` §2.1，公式正本在模块 docstring）。
    与 `scan.py` 同一条安全线：stdlib、不联网、不读凭证、**不读正文**（落盘只经 `_whitelist`，会话标题只取 cwd 的 basename）。`--json` 给请求页（最近 2 个本地自然日），`--live` 给托盘胶囊 / 悬停面板 / 刘海（同时原子写 `requests-ledger/.live.json`）。
    - **每条 t/s 的分子分母**（`MIN_GEN_S = 0.3`）：
      · Codex = 可见输出（`output − reasoning`）÷（响应结束 − 首个输出项写盘时刻）。首字取**第一个推理项**的写盘时刻；第一个输出项不是推理项（工具调用整项写盘）就没有首字。推理 token 产生在首字之前，留在分子里会虚高（实测中位 157 vs 102 t/s）。
      · Claude = OTel span 的 `output ÷ (duration_ms − ttft_ms)`；分子**含 thinking**（实测 thinking 在首字之后流式产出：thinking > 50% 的 88 条中位 98 t/s，与无 thinking 的 93 条 131 同量级，扣掉只剩 28）。没有 span 的退回 transcript `output ÷ (末行 − 触发行)`。
      · Gemini（agy）= usage `f3`（输出，**含 thinking**）÷ `f1.f12` streaming；Grok = `outputTokens ÷ apiDurationMs`。
        ✗ 已被 2026-10-21 实测取代：分子用 `f10`（可见输出）。用户看到「Gemini 3 t/s」（95 可见 ÷ 31.4 s，thinking 2854）。
        439 条 est=false 按模型 × thinking 占比（<20% / 20–50% / >50%）分组：`f3÷streaming` argon 138 / 230 / 157、flash 426 / 474 / 625，组间一致；
        `f10÷streaming` 在 >50% 组掉到 33 / 26 ⇒ thinking 在 streaming 段里生成（与 Claude 同、与 Codex 相反）。⚠️ 单机两天数据、两个模型。
        ⚠️ 改公式要 +1 `CUR_V`（全量重解覆盖旧数），且**必须部署**：app 跑的是安装包里那份 `requests.py`，旧版会把游标版本写回去。
      · **退估值**：生成段 < 0.3 s（或可见输出为 0）⇒ 退回 `output ÷ 整条时长`，`est=true`。实测 528 条 Claude span 里 118 条 `duration − ttft` ≤ 300 ms，直接除最高 75,875 t/s。
      · **给 null**：任何分母 < 0.3 s 或分子 ≤ 0 ⇒ `tps = null`，**不写 0**（0 会把均速拉低，而那条请求根本没生成）。下限对所有分母生效（实测 28 ms / 516 token ⇒ 18,429 t/s）。
      · `est` 只在数据里；界面上 t/s **不加「≈」「估」**（交接包全局规则）。
    - **`avg_tps` 取逐条 t/s 的中位数**（null 不计），不是算术平均、也不按 token 加权：重尾分布下一条短响应就能把均值拉偏几倍；按 token 加权要四家同一个分母，而四家口径本来就不同。
    - **`--live` 的合计**：`tps` = 在跑会话「最近一条已完成响应」t/s 之和，**只在同一 AI 内相加**；全部为 null 时为 null；在跑但还没完成第一条的会话 `tps: null`。**任何界面不出现跨 AI 合计**。
    - 实测分布（2026-10-19 08:30 一次 `--json --days 2`，n=3985，**单次观测**；「实测」= `est=false` 的那部分）：

      | 平台 | 条数 | 全部 p10 / 中位 / p90 | 实测条数 | 实测 p10 / 中位 / p90 | 估值条数 |
      |---|---|---|---|---|---|
      | Codex | 124 | 15.0 / 78.8 / 197.2 | 95 | 49.0 / 95.1 / 202.4 | 29 |
      | Claude | 3780 | 7.3 / 70.0 / 131.4 | 1494 | 82.8 / 111.8 / 149.7 | 2286 |
      | Gemini | 80 | 5.9 / 33.7 / 147.9 | 33 | 7.1 / 29.0 / 143.8 | 47 |
      | Grok | 1 | 54.1 | 1 | 54.1 | 0 |

      今天 / 昨天 `avg_tps` 99.5 / 53.0，首字中位 3.11 s / 4.95 s。⚠️ Claude 估值占 60%（OTel 试运行 10-18 22:40 才开始，之前的请求只有 transcript）；两天的均速差是混合比例变了还是真变慢，**这次分不出来** —— 等 OTel 覆盖满两天再比。
    - **账号对上率**（同一次）：Codex 124/124 按 `response_id` 对上号（`rotation.py::scan_proxy_log` + `make_resolver`），0 条「直连」；Gemini 77/80（经 `agy_rotation` 的 conv id 对上，3 条 null）；Claude 恒「本机」、Grok 恒「单号」。⚠️ 直连为 0 只说明这两天没有绕开代理的请求，**不说明对不上的路径不存在**（泳道那条 77~93% 是另一个窗口、另一个口径）。
    - **OTel 已产品化（2026-10-19，v1.12.0 beta，待外部用户验证）**：接收端 `traffic/otel_receiver.py` 是正式服务 `com.doushutangmu.codex-rotate.otel`（**只在 `install-launchd.sh`**；Windows 版已取消，`test_installers_agree.py::MACOS_ONLY`），进了 `RUNTIME_FILES` 与 `bundle.resources`，账本 `--dir <store>/traffic/otel-ledger`。改 `~/.claude/settings.json` 那半拆成设置页开关「Claude 实测速度」（默认关，`claude_otel_env.py`：只碰 12 个键、冲突不写、先备份、关只删自己写的）—— 装服务 ≠ 改用户配置这条分界保留。端口被占时接收端把原因写进 `.status.json`（`listening:false`）并退出非 0。`requests.py` 与 `scan.py` 只**读** `traffic/otel-ledger/`，没有它时 Claude 全走 transcript。
      ✗ 已被取代：「试运行，常驻 `com.doushutangmu.claude-otel`，刻意不在安装脚本 / `RUNTIME_FILES`，转正未拍板」（10-18）。
    - 闸 `tests/test_requests_ledger.py`（四家夹具、增量游标、去重、失败保留旧值、白名单、`--live` 合计规则）。
    - ★★★ **判停 = 各家自己写的轮次结束标记，不是「N 秒没写」**（用户 2026-10-19 拍板「改用轮次结束标记」；表在 `requests.py` 模块 docstring「判停」）。
      · **为什么**：旧判据「45 s 内写过会话文件」停手后要等 45 s + 托盘 3 s ≈ 48 s 才熄；而 Claude transcript 一轮之内相邻两次写入的静默间隔
        （2026-10-19 实测，n=95684）**p50 0.1 s · p90 10 s · p99 99 s · p99.9 600 s**（长工具调用 / 子 agent / 等权限）⇒ 同一个 45 s 既慢、又会在
        长工具调用中途误判停。轮次结束是 CLI 自己落盘的事实，拿「多久没写」去归纳它就是 `CLAUDE.md` §7.1「先演绎后归纳」那一类。
      · **口径**：在跑 = 这个文件最后一个轮次事件是「开始」（`state.open`，随游标保存，缓存命中不重读也知道）**且** `FALLBACK_SECS`（600 s）内写过。
        兜底窗口只管「没写结束标记」：崩溃 / 被杀 / 旧版本不写标记。写了结束标记 ⇒ 立刻停，文件刚写过也停。
      · **各家标记**（只看 type / subtype / 键是否存在 / 状态码，不读正文；本机近 7–10 天实测）：
        Codex 开 `task_started`、收 `task_complete` · `turn_aborted`（Esc，44/44 `reason: interrupted`，紧跟自己那一轮的 `task_started`），turn_id 对不上不收。
        Claude 开 = 提示行（user、非 meta、有 `promptSource` 键，子 agent 的提示行没有这个键、靠 `isSidechain: true`）· 工具结果行 · 非终止 assistant；
        收 = `system/turn_duration`（2135 轮）· 中断行（Esc 写一行带 `interruptedMessageId` 键的 user，**不写** turn_duration；44 次里 39 次有这个键，
        另 5 次是旧版、靠兜底）· assistant `stop_reason ∈ {end_turn, stop_sequence, max_tokens}`（子 agent 不写 system 行，只有这一条；61/71 个子 agent 文件以 end_turn 收尾）。
        agy 看会话库最后一步：`(step_type 15, status 3)` 或 status 5 / 6 = 收，其余（生成中 8、工具 132、错误 17 后面跟重试的 15）= 开；近 150 库 139 个以 (15,3) 收尾。
        grok 开 `user_message_chunk`、收 `turn_completed`（end_turn 122 / cancelled 5 / error 4，都收）。
      · ⚠️ **不收的三样，别「补」回来**：`stop_hook_summary`（2140 次里 32 次后面还跟着工具调用 —— 子 agent 的 Stop 钩子也写它）·
        `refusal`（实测拒答后 `model_refusal_fallback` 换模型接着答）· 压缩摘要行 `isCompactSummary`（手动 /compact 之后没有回复；自动压缩时轮次本来就开着）。
        本地命令回显行（没有 `promptSource`）也不开新一轮，否则 `/model` 一下就亮 10 分钟。
      · 提示行一写下就算开（不等第一条回复）：实测提示 → 第一条 assistant 行 n=2254，p50 12 s · p90 49 s · max 431 s。
      · Rust 侧（`activity.rs`）：FSEvents 只当「叫醒」；光晕跟 live（`glow`），live 失败 / 卡住 > 10 s 才退回 FSEvents。见 `.claude/rules/ui.md` 刘海「在跑的判据」。
      · 闸 `tests/test_requests_ledger.py::TurnEndMarkers`（四家：进行中 / 结束标记立刻停 / 兜底窗口 / 增量与缓存命中 / 旧游标重解）。
  - ★★ **grok 与 agy 都有额度油表，都已接入**（grok 2026-08-24 / agy 2026-09-04）。⚠️ 这条曾写作「agy 没有且拿不到」，**2026-09-04 被实测推翻**，详见本节末尾那条。
    - **grok 端点 = `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits`**。它**压在 HPACK 里**，grok TUI 走 HTTP/2，所以 `strings` 抓包和裸看抓包文件都找不到路径——四个凭直觉猜的 URL 全 404。**解 HPACK 才拿到**（`scratch/grok-probe/decode_h2.py`，`pip install hpack` 即可）。同批解出的完整面貌：`/v1/settings` `/v1/user` `/v1/models` `/v1/responses` `/v1/sessions/{id}/signals` `/v1/traces` `/oauth2/token`。**不是官方公开 API**，升级可能改。
    - 鉴权取 `~/.grok/auth.json` 顶层条目的 **`key`** 字段（不是 `access_token`），配 `x-xai-token-auth: xai-grok-cli` + `x-userid`。返回周期/已用百分比/按产品拆分。**只有周窗口（实测正好 10080 分钟），没有 5 小时窗口** —— 别照账号池那套画两个环。
    - ★ **这个域名不吃 TLS 指纹那一套**（LibreSSL 3/3、OpenSSL 3/3 全 200，单一变量各 3 次）。**与 `chatgpt.com/backend-api/codex/usage` 不同族** —— 那条是 LibreSSL 恒 403。仍走 `python_bin()` 只是为了口径一致，不是因为这里必须。
    - ★★ **绝不刷 grok 的 refresh_token。** `~/.grok/auth.json` 是 grok CLI 自己的活文件，我们和它**共用同一份凭证**；它单次有效，我们一刷，grok CLI 手里那份立刻作废 —— 与 §8「绝不刷 active 号的 token（B7/B8/B14 连环杀号）」完全同族。access token 只活 ~6 小时，**过期就短路不发请求**，把续期交还给 grok CLI。也**绝不取 `~/.grok/auth.json.lock`**（取了会阻塞它自己的刷新，把"只读展示"变成"干扰凭证轮换"）。闸在 `tests/test_grok_readonly.py`（AST，11 条，已做 13 次变异验证全部变红）。
    - ★ **续期条件实测过**：`grok --version` **不续期**（指纹不变）；**起一次 TUI 会话才续**（实测 `expires_at` 前推 6 小时、key 指纹变）。UI 文案照这个写，说成"跑一次 grok"会让人用 `--version` 试完以为提示是错的。
    - ★★ **方向坑：`quotaColor()` 吃的是「剩余」，grok 接口给的是「已用」。** 设计阶段就写明了这条，**我照样犯了一次**：细条填剩余(65%)、旁边数字写 35% 已用，同一行两个方向，而 tsc/cargo/单测**全绿**，是截图看出来的。现在的口径是**用户看得见的三处（条、数字、productUsage）全是「已用」，只有颜色按剩余算**。闸在 `tests/test_grok_direction.py`（4 次变异全红，含我犯的那个原错）。
    - 落点：**不进 `state.json` 的 `slots`**（那是轮换池，每个 key 都会被 `_pick`/`cmd_keepalive` 遍历，进池即进刷新器射程），走独立 sidecar `<store>/.grok-quota.json`（含 email + user_id，已 gitignore）。Rust 侧 `read_grok_quota`/`run_grok_quota` + `GROK_LOCK`（**独立于 `SCAN_LOCK`** —— 联网取额度和读本机盘是两种成本，共用一把锁会互相阻塞）。前端 `useGrokQuota` **只在钻进 grok 详情页时 enabled**，这是全 app 唯一一条主动联网的数据路径。
    - ★★ **降级契约：失败态 `quota` 恒 `None`，绝不写 0。** `0%` 是"这周一点没用"的合法值，一旦某条失败路径悄悄写出 0，UI 会画一条正常的绿条，用户没有第二个办法分辨。8 个 reason 的闭集两边各一份（`grok-quota` 的 `REASONS` ↔ `grok.ts` 的 `grokReasonNote`），闸在 `tests/test_grok_reason_copy.py`：**两边都从源解析**，只改一边就红；并强制每条文案「明说这不是额度为 0」+「给下一步动作」（后者当场抓出 `network_error` 漏写）。**退出码恒 0** —— 非 0 会让 Rust 走 `Err(String)`，而 `Err` 在前端三条消费路径上都被读成"没数据"，等于把降级又折叠回去。
    - ★★ **agy 额度已接入（2026-09-04）。端点无鉴权、不联网、不消耗配额：**

          POST http://127.0.0.1:<高位端口>/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
          Content-Type: application/json    body: {}    无 token、无 csrf

      返回 **2 组 × 2 窗口 = 4 个桶**（Gemini / Claude+GPT × 5h / weekly），带 `remainingFraction` + `resetTime`。
      本机实测环境**没装 Antigravity IDE**，纯 agy CLI（1.1.26）—— 所以「必须有 IDE 在跑」那半也不成立。
      落点同 grok：独立 sidecar `<store>/.agy-quota.json`（**不含凭证**，接口无鉴权，忽略它只因为它是运行时产物），
      Rust 侧 `read_agy_quota`/`run_agy_quota` + 独立 `AGY_LOCK`，前端 `useAgyQuota`（2min 新鲜度，因为 5h 窗口每 1% ≈ 3 分钟）。
    - ★★ **上面那条推翻了 2026-08-24 的「agy 的额度结构性不可达，别再试」。这个判断错在哪，比结论本身更值得记：**
      - 当时的证据是真的：本地 RPC 返回 500 `error getting token source: You are not logged into Antigravity`，
        且 agy 自己的 `Login` RPC 说「interactive auth is only supported in **antigravity-hub** mode」。
      - **错的是外推。** 2026-09-04 的判别实验（同一个 print 模式进程，按时间多次采样）：

            起后  0s  →  500  error getting token source…
            起后 10s  →  200  {"response":{"groups":[…]}}     ← 同一进程、同一端口

        那个 500 是**启动预热窗口**。我在端口一出现就立刻调，撞进窗口里，然后把
        **「这一枪没打中」外推成了「确实没有」** —— 本仓反复吃亏的同一类错，而且这次还写成了带「别再试」的定稿，
        等于给后来的人上了一道锁。★ **区分变量是「时间」，不是「模式」**：我当时把它归因到 CLI/hub 模式差异，
        因为那个归因手边就有一句 agy 自己的报错佐证，看着严丝合缝。
      - 教训落到代码里，不只落在文档里：`agy-quota` 把这个 500 落成 `not_ready`（**还没就绪**）而不是「读不到」，
        闸在 `tests/test_agy_degrade_contract.py::test_warmup_500_is_not_ready_not_unavailable`。
      - 云端那半（`retrieveUserQuota` 403 no valid license）**至今仍然成立**，只是不再重要 —— 本地 RPC 就够了。
    - ★★ **agy 的假绿形态与 grok 方向相反，两边文案不可互抄。** grok 接口给**已用**（怕假的 `0%` = 没用过），
      agy 给**剩余**（怕假的 `100%` = 满格），而上游 `remainingFraction` 的**缺省值就是 1.0** ——
      任何一处 `?? 1` 或「把空响应当成功往下传」都会直接渲染成满额，且看上去完全正常。
      所以失败态 `quota` 恒 `None`，且断言**整个响应序列化后不得出现 `remaining_percent`**。
    - ★★ **`not_installed` 与 `no_process` 必须分开** —— agy **不常驻**，「没在跑」是常态不是故障：
      - 全按隐藏处理 ⇒ 装了 agy 的人几乎**永远看不到卡**；
      - 全按显示处理 ⇒ 没装的人得到一盏**永远亮着又无从消除的灯**（本仓判过死刑的形态）。
      所以 `not_installed` 整卡隐藏（确定的否定），`no_process` 照常显示上次读数 + 一个 `!`，且**不染警告色**。
      闸在 `tests/test_agy_not_in_pool_ui.py::test_no_process_does_NOT_hide_the_card`（反向断言）。
    - ★ 三个实测坑：① `lsof` 必须带 `-a`（`lsof -nP -a -p <pid> -iTCP -sTCP:LISTEN`），漏了会列出该进程所有 fd；
      ② 低位端口是 HTTPS、高位是明文 HTTP，实测连号但**那是 5 次观测的归纳不是保证**，两个都探别硬编 N+1；
      ③ 找进程用 `ps` + 精确匹配可执行名，**不用 `pgrep -f agy`**（自匹配恒真）。
    - ★★ **agy 的额度是滚动窗口,不是固定窗口 —— 2026-09-05 实测推翻了我自己前一天的假设。**
      两处 `remaining` 在 `resetTime` **完全没变**时上涨:`gemini-5h` 98.740→98.870(+0.13%)、
      `gemini-周` 97.600→98.400(+0.80%,跨 7.7 小时)。固定窗口下这不可能;滚动窗口下这是常态
      (旧消耗老化退出 trailing 5h / 7d)。接口自己的措辞也一致:"will **fully refresh** in 6 days"。
      · **后果**:第一版把「上升」报成异常,在真机 5 个样本里就误报 2 次,而那 2 次都是正常恢复。
      · **现行口径只累加下降**,上升进独立的 `recovered_pct`(**不与消耗相抵**,相抵会让"用了多少"变小)。
        这个算法在「滚动窗口」和「服务端回补」两种假说下都成立 —— 证据还不能完全区分两者,
        所以刻意不押注。判别实验:连续采一整个 5h 窗口,看恢复是平滑的还是集中在某一刻。
      · ★ 这一路上 reset 分类换过三版(看 reset 变没变 / 看额度变多没 / 看 Δreset≈Δt),**全部作废** ——
        换成滚动窗口模型后根本不需要分类。三版的错法都记在 `agy_quota_series.py` 头部。
    - ★★ **额度消耗序列是第二本账,与 token 账本不可相加。** `scan.py` 输出里它是**独立顶层键**
      `agy_quota`,不进 `platforms` —— 进去就会被下游 30+ 处读 `b.total` 的地方当 token 加进总数。
      单位是**额度百分比**,不能乘单价、不能折算成钱。
      · 存在的理由:token 账本只覆盖 print 模式(近 90 天 34/214 = 15.9%),交互式会话一个字都进不来;
        额度是服务端真值,交互态照样会掉 ⇒ **覆盖 100%,代价是换了量纲**。
      · ⚠️ 它是**水位计不是流量计**:采样间隔超过窗口的一半就标 `lower_bound`,因为滚动窗口下
        一笔消耗若在两次采样之间完全老化退出,水位差永远看不见它。UI 用「≥」标注,不用脚注。
      · ⚠️ 已知前提:额度是**账号级**的,同账号在别处(另一台机器 / IDE)消耗也会算到本机头上,
        而**无法从本机数据判断这件事有没有发生**。
    - ★★ **事故:附加功能把主用量扫描整个搞挂(2026-09-05,当天修)。** 用户报「点刷新没反应」。
      两层叠加:① `agy_quota_series.py` **没进 `tauri.conf.json` 的 `resources`**,安装包里
      `scripts/traffic/` 只有 `scan.py`;② `_agy_quota_series` **不是 fail-open**,import 一抛就冒泡 ⇒
      `scan.py --json` **退出码 1、stdout 零字节** ⇒ `run_traffic` 失败 ⇒ 整页刷不出来。
      ★ **症状里没有任何东西指向 agy** —— 坏掉的是与 agy 毫无关系的 token 统计。
      **一个纯附加的次要功能,绝不能有能力搞挂主路径。**
      现在:整个 `_agy_quota_series` 包在 try/except 里返回 None;两个模块都进了 resources;
      闸在 `tests/test_scan_optional_extras.py`(藏掉模块 / 模块存在但一 import 就抛 / 打包清单核对)。
      ★ **新增运行时按路径加载的模块时,必须同步加进 `resources`** —— 那条断言会自动核对
      `scan.py` 里所有 `parent / "xxx.py"` 的写法,漏一个就红。
    - ★★ **采样器挂在 `bin/agy` 而不是 launchd。** 交互态走 `os.execv`,wrapper 进程会被真身
      整个替换掉 —— 没有"之后"可言,所以只能在拉起 agy **之前**启动一个独立进程。
      它自我终结(单实例锁 + 连续 180s 无 agy 即退出 + 24h 硬上限),实测 140s 退出、无孤儿、锁自动清理。
      不做常驻的理由:额度只在 agy 活着时才动,24×7 盯一个大部分时间不动的数是浪费。
    - ★ 「回环被代理黑洞」那条潜伏型规则**对本脚本不成立**：`http.client` 不做代理解析（实测三个 proxy 全指黑洞仍 200），
      所以不需要 `NO_PROXY`。但这份免疫来自实现选择 —— **换成 `urllib`/`requests`/reqwest 系，黑洞立刻回来**。
  - ★★ **锚点账本有两类记录，别合并**（2026-09-12）：`record()` 记的是一次 `/usage` **采样**
    （进时间序列，`first_seen`/`last_seen` 是滑动判据的坐标）；`mark_billed()` 记的是一条**事实**
    —— 我们在这个窗口里亲手发过一次计费请求。后者命中已有行时**只加 `billed_at` 一个键**，
    时间轴字段一个不碰，所以「只在 `/usage` 这条路径上记」那条规矩仍然成立。
    `verdict()` 里 `billed_at` **必须排在 `slides` 之前**：计费探针刚跑完时尾部的滑动串仍然成立
    （锚定后的 reset 会合并进探针**前**那次免费 GET 的行，`first_seen` 还留在闲置期），
    让 `slides` 先判就会得出「我们刚花钱启动的窗口没启动」。
    ★ 实测未修时该误报持续 **897–1197s**、每次探针必现、与相位无关；
    UI 侧 `used_max < 2` 的守卫接不住（low-effort 探针对 5h 窗口的消耗取整后是 0~1%）。
    标记**按行不按桶** —— 按桶会把闲置期的旧行一起标掉，让一串确实在漂的窗口集体自称已锚定。
  - ★★ **代理侧补读的 `x-codex-*` 头(2026-09-05,起因是读 `router-for-me/CLIProxyAPI` 的白名单)。**
    原来只取 primary/secondary 三件套 + `plan-type`,而服务端**一直在发 17 个**。
    ★ **实测清单**(靠新加的"头集合变化"日志量出来的,不是猜的):
    - **真的在发、现已采集**:`active-limit`(=`premium`) · `credits-{balance,has-credits,unlimited}`
      (本机实测 balance=0 ⇒ 无购买额度) · `primary/secondary-reset-after-seconds` ·
      `primary-over-secondary-limit-percent`
    - **真的在发、与额度无关**:`safety-buffering-{enabled,faster-model}` · `turn-state`
    - **根本没发**:`allowed` / `limit-reached` / `x-codex-<短名>-*`(bengalfox 族) / `code-review-*`
      ⇒ 解析器留着但恒 `None`。**这是"确实没有"不是"没打中"** —— 靠日志判定的,别再猜一遍。
  - ★★ **`codex_headers` 是 `slot` 的独立兄弟键,不在 `quota` 里 —— 这是实测逼出来的。**
    第一版塞进 `quota`,真机上活不过几分钟:`quota_daemon` 走 `/backend-api/codex/usage`
    **整体替换** `slot["quota"]`(`codex-rotate:1321`),那条路径拿不到响应头,于是每轮都抹掉。
    ★ 测试全绿、字段也确实写进去了 —— **只是转瞬即逝**,单测根本看不到这个。
    两条来源就该是两个对象各带时间戳(与 agy「两本账不可相加」同一条理由);
    合并则 `captured_at` 混源,陈旧值会蹭到新时间戳被认成现值。已验:两者并存,相差 1 秒互不覆盖。
    ⚠️ **命名避让**:`slot["credits"]` 早被 usage-api 占用(存 `rate_limit_reset_credits`,
    是"重置限流用的额度数");头里的是**付费余额**,所以叫 `credits_balance`。**两者不是一回事。**
  - ★ **`reset_after_seconds` 与 `resets_at` 要并存**:后者是绝对纪元、依赖两边对"现在"的共识,
    时钟一偏就错;前者是相对秒数、免疫。本仓在"窗口是否已重置"上栽过(v0.12.9)。
    实测两者差 **1 秒** ⇒ 当前时钟一致。**目前只采集不判定** —— 没有跨时钟样本前,
    不拿一个未验证的量去替换一个已验证的量。
  - ★★ **`proxy.log` 现在记"x-codex 头集合变化"**(集合变了才记一行,不是每请求一行)。
    它同时还掉一笔旧债:此前 proxy 对额度写入**零留痕**,导致某字段读不到时
    **分不清「服务端没发」还是「我解析没打中」**。上面那份实测清单就是它第一次运行的产出。
  - 费率与费用口径在 `codexbar/src/rates.ts`（四类 token 分别乘单价，**不用**交接稿 §8 的构成假设）。
    ★ **Claude 缓存写分两档**（2026-10-15，`PARSER_V` 12）：transcript 的 `usage.cache_creation.ephemeral_1h_input_tokens` 是 1h 档（**2× 输入价**），其余按 5m 档（1.25×）。scan row 第 9 位 = 1h 份额（钳到 ≤ `cache_creation_input_tokens`：实测 18 条总数 0 而明细有数），桶里 `cache_write_1h` 是 `cache_write` 的**子集**不是第五类。实测本机近 60 个 transcript 1h 档 625.9M、5m 档 0；30 天 Claude 等效费用 $5,815 → $6,564（+12.9%）。闸 `tests/test_claude_cache_write_1h.py`。费用是**等效 API 成本**，订阅制下不是实付，UI 各处必须标注。
  - ★★ **缓存计入口径三档**（设置页 › 缓存计入口径；用户 2026-08-11 定稿）。`full` 含缓存 / `noRead` 不含缓存读 / `none` 不含缓存。本机 90 天实测量级：**36.71B/$31,229 · 1.54B/$12,132 · 0.58B/$5,876**（2026-08-16 实测，当时的费率表；⚠️ 2026-09-29 牌价更新后 Codex/Claude 费用有变，这组量级已过期，需重测）。
    - **`noRead` 与 `none` 差 3 倍，分界全在 `cache_write`**：它是**首次发送并写入缓存的新内容**，没有缓存机制这些 token 照样要发（只是按普通输入价计费）。所以 `noRead` 回答「不靠缓存我实际消耗多少」，`none` 回答「完全不沾缓存的那部分」——后者会丢掉 0.9B 真实新内容（是 `uncached_in + output` 的两倍）。
    - ★ **重塑只在 `useTraffic` 出口做一次**，现在是**两层**：`applyCacheMode`（缓存口径）+ `applyPlatformPrefs`（平台偏好——**停用＝整家从 `data.platforms` 移除，总 token 与总费用跟着扣**，用户 2026-08-12 定稿；排序只影响列表与图例，堆叠图仍按占比大的贴基线）。下游 30+ 处读 `b.total` / `costOfBucket` 的地方自动跟上。**逐处去改必然漏，而漏掉的那处会显示另一个口径的数字。** 费用同步跟着变——`costOf` 就是拿这四类分别乘单价的，类被清零费用自然不含它。`full` 返回原引用，默认口径零开销零行为变化。
    - ★ **缓存占比 / 构成行必须走 `raw`**（未重塑）：重塑后 `cache_read` 恒为 0，拿它算会输出「缓存 0.0%」——那会被读成"没用到缓存"，与事实相反。`useTraffic` 因此同时返回 `data`(已重塑) 与 `raw`。⚠️ **`raw` 只跳过缓存口径这一层，平台偏好照样过** —— 否则已停用的平台会混进缓存占比的分母。唯一直读未过滤快照的地方是设置页那份平台清单（否则停用后就再也开不回来）。
    - ★★ **不同口径 = 不同页面**：不计入的类，其指标要**从页面上整个删掉**，不是显示 0%、也不是改说「已排除 X」（后者等于换个说法把它请回来）。已删：总览 KPI「缓存」整格 · 详情页费率卡「缓存读」整列（`gridTemplateColumns` 同步收）· 构成行里未计入的类 · 脚注里对应的折扣率说明。构成行的**分母也换成计入的那几类之和**，否则 `none` 档四项加起来只有 4%。
    - 判定单一真源 = `countsCacheRead` / `countsCacheWrite` / `countedClasses` / `mixParts`（都在 `traffic.ts`）。**页面别各写一份 `mode === "full"`**，那是迟早在某个边界上互相矛盾的写法。开关状态走 `useCacheMode`（localStorage + Tauri 广播，同 `usePrivacy`），所以菜单栏「今日」即时同步。
    - ⚠️ **删列会静默染错色**：`FragRow` 原来按下标染色（`i===1` 青＝缓存读、`i===3` 琥珀＝费用），缓存读整列消失后下标左移，青色会跑到「输出」头上。已改成单元格自带颜色——**任何"某一列可能消失"的表格都不许按下标做样式**。
    - 回归脚本 `scratch/verify_cache_mode_20260811.ts`（`jiti` 直接跑**前端真代码**，非 Python 重写——重写过一次，正则漏了 `FALLBACK` 未加引号的键，把费用算低了 7%）。
  - ★★★ **Claude 按「实际 API 调用」算 = transcript ∪ OTel 账本**（用户 2026-10-19 定稿：「都按实际 api 调用算……这个口径在 codexbar 上不做提示和说明」）。
    - 起因（2026-10-19 当天实测，n=1）：`requests.py` Claude 2057 次 / 539.85M，`scan.py` 1513 次 / 398.46M。多出的 547 次**不在任何 transcript 里**，只在 `traffic/otel-ledger/`：`query_source_safe` = `agent_summary` 511 次（139.6M）· `web_fetch_apply` 17 · `web_search_tool` 14 · `compact` 5（2.4M）—— Claude Code 的后台调用，真花额度、不写对话记录。两边都有的 1510 条 token 逐条相等。
    - 做法：Claude 源的 `extra` 钩子 `_claude_otel_rows`，在全局 `message.id` 去重**之后**跑；`request_id` 不在 transcript 里的 span 进桶（`uncached_in/cache_read/cache_write/output` = `input/cache_read/cache_creation/output_tokens`，时刻 `t_end`）。**两边都有的以 transcript 为准**（它带 1h 拆分）。
    - ★ 去重键是 **`requestId`**，不是 `message.id`：OTel 的 `gen_ai.response.id` 也是 `req_…`，与 message.id 零交集（实测 0/1591）。transcript row 第 10 位带 `requestId`、**随缓存走** —— 缓存命中的文件不重读，集合只能从缓存里拿（`PARSER_V` 13）。
    - 账本走同一套缓存规矩（`sig` / 增量 / 读失败保留旧值连旧签名）。目录不存在 = 没开 OTel，静默等于旧口径。路径与 `requests.py::roots()["otel"]` 同一个环境变量 `REQUESTS_OTEL_DIR`、同一个 `<store>`（scan.py 不能 `import requests`：它反过来 import scan）。
    - 不按 `success` 筛：当天账本 2164 行 `success` 全 true、`attempt` 全 1；失败而带 token 的照计，四项全 0 的跳过。重试各有 request_id，各算一次。
    - ⚠️ 已知偏差：OTel 无 1h 缓存写拆分 ⇒ 这部分按 5m 价（偏低）；OTel 试运行 10-18 22:40 起，之前的历史就是少这部分（不补、不写说明）。3 条 transcript 的 `output_tokens` 停在流式中途值（5 vs span 511），按口径仍以 transcript 为准，对账差 −987 token。
    - 对账 `python3 -I scratch/claude_api_parity_20261019.py`（当天两边都是 2138 次）。闸 `tests/test_scan_claude_otel.py`（17 个变异如期）；**跑 Claude 源的测试必须把 `scan.OTEL_ROOT` 指到夹具**，同 AGY_ROOT 那次，有 AST 闸。
  - ★ **去重键是 `message.id`，且必须全局去重**。朴素求和虚高 **2.23x**（实测 2026-08-09，5090 文件 / 1.97GB / 94,807 唯一响应）。两种重复成因不同：一次响应按 content block 拆成多行、每行带同一份 usage（文件内 115,413 条）；会话 resume/fork 复制历史（跨文件 1,497 条 / 1.6%）。**per-file 去重挡不住第二种**——这也是缓存里存 `{msg_id: 明细}` 而不是聚合值的原因：聚合值算出来就没法再减掉跨文件那份。
  - ★ 跨文件重复里有 **16 条两边 usage 不一致**，形态全是「一份四项全 0 / 一份真实值」。合并时**显式取 token 总量大者**，不靠字典序覆盖——零值过滤本是为 `<synthetic>` 写的，靠它挡属于碰巧对。
  - ★ transcript 时间戳是 **UTC**，本机 +0800，必须转本地日期再分桶，否则 00:00–08:00 的活记到前一天。**缓存里只存 epoch，日期一律在聚合层现算**——缓存键只有 `(mtime,size)` 不含时区，存派生日期的话，以别的 TZ 跑过一次（launchd 默认环境 / CI / `export TZ`）就会让 5000+ 个此生不再变 mtime 的文件永久保留旧时区日期，两种口径混进同一张图且不自愈。同理**日期不能按 UTC 小时记忆化**：+05:30 这类半小时偏移的本地午夜落在整点小时的中间（Kolkata=18:30Z），会把两天折叠成一天，且结果依赖遍历顺序。缓存带 `v`+`pv` 双版本号，**改任何 `_scan_*` 的解析逻辑（含去重键、口径归一）必须 +1 `PARSER_V`**（`_parse_file` 这个名字早已不存在，别照旧文去找）。
  - ★ `total` 含 `cache_read`，而它**占 96%**（每轮重发完整历史）。这是**吞吐量不是等价成本**，别乘单价——缓存读**按平台、按模型各算折扣**（Claude/Codex/Kimi 多数 10% · Grok 15~25% · DeepSeek 3.3% · MiMo 0.8%；⚠️ 2026-09-29 起 Claude **Fable 5.1 / Mythos 5.1 是 2.5%、Opus 5.5 是 5%**，同一平台内也不统一；详情页脚注按当前模型实算，**别再按统一 10% 心算**）。★ 牌价表 `rates.ts` 2026-09-29 按四家官方页重取（B73），`tests/test_rates_cover_live_models.py` 守「CLI 自己列出的可用模型都得有价」。subagent 按响应数占 46%、按 token 只占 10%，两个口径都别混。
  - ★★ **Claude 走增量解析**（2026-08-22，`PARSER_V` 8）。此前每次扫描都把变动过的活跃 transcript **整个重解析**——实测一次 **624MB / 3 个文件**，而连跑三次输出**内容指纹完全相同**：那 624MB 全是早就解析过、一字未变的历史。现在只解析追加的那一段，实测 **1049MB → 2.6KB**，热路径 **3.7s → 1.4s**。
    - **只对 claude 启用**（占近 24h 热数据 **94%**：744MB/795MB）。`SOURCES` 的 `lines` 是**逐源显式登记**，不是默认能力：`_scan_codex_file` 带跨行状态（`cur` 模型来自更早的 `turn_context` 行、`seen_cum` 是文件内去重集），reasonix/dsh 要整文件解压 —— 这三个喂尾部会算错。grok/kimi/openclaw/agy 逐行无状态、技术上可加，但只占 3%，不值得再改四个解析器。
    - ★ **增量是纯优化，不承担正确性**：守卫不过一律退回全量重解析，**最坏等于改动前**。这是它敢上线的唯一理由。
    - ★★ **锚点必须限制在 `[0, off)` 之内**（只覆盖已消费区间，追加改不到它）。原本头部读固定 64KB，文件小于 64KB 时会把**新追加的内容也读进"头部"** ⇒ 哈希必变 ⇒ 增量永远不生效。**真机上完全看不出来**（活跃文件都 100MB+），是小夹具单元测试逼出来的 —— **用真数据测这个改动会一路绿灯**。
    - ★ **半行绝不能算进 `off`**：JSONL 边写边读，把写了一半的行算进去，下次就从它后面开始 ⇒ **那条记录永久丢失**，而总量只小一点点，看不出来。只消费到最后一个 `\n`。
    - ⚠️ **「三道独立守卫」的说法已被变异测试推翻**：拆掉「文件变短」那道，截断用例照样红 —— 文件变短时 `[off-64KB, off)` 读不满、哈希必然对不上。**真正起作用的只有锚点比对**；「文件变短」是快速路径 + 防 `read(size-off)` 退化成 `read(-1)` 读到 EOF，别当第二重保险。
    - 回归闸 `tests/test_incremental_parse.py`（9 例，合成夹具**不碰真实 `~/.claude`**）。**未覆盖 `/compact` 与 resume/fork 是否原地重写** —— 那正是锚点要挡的场景，本轮没触发到，所以守卫不能省。
    - 冷路径仍 ~23s（10118 个文件首次全解析）。已加「无变更则不写缓存」（曾是热路径最大单项，8.6MB 白写）。
  - ★★ **写缓存用 `json.dumps()` + 单次 `write()`，绝不用 `json.dump(obj, fh)`**（2026-08-24）。实测这份 16MB 缓存：`json.dump` 到文件 **474ms**，`dumps` + 单次 write **91ms**（5.2×），含真落盘+rename 才 95ms ⇒ **磁盘只占 ~4ms，那 474ms 几乎全是 `json.dump` 逐块 `iterencode`/`write` 的调用开销**。⚠️ 这条极其反直觉：我先入为主认定是磁盘 I/O，还据此设计过「缓存分成 16 片」——codex 实测指出真因，grok 又用体积分布证伪分片（脏的恰是最肥的会话文件，top3 占 19%，分片反而写 40%）。**别再往分片/SQLite 那边走。**
  - ★ **日期分桶用「预算本地午夜边界 + `bisect`」，但小时桶必须留 `strftime`**（2026-08-24）。日桶 148ms → 63ms；边界逐日 `mktime` 算、只活在本次进程内，**不沾**那条「派生日期进缓存」的禁令。⚠️ **小时桶不能同样处理**：整点边界表达不了非整点 DST，`Pacific/Chatham` 02:45 切换实测把 02:45–02:59 判进 `T03`（我干过，codex 复核发现）。
  - ★★ **`_sig()` 必须用 `st_mtime_ns`**（2026-08-24）。秒级 `int(st_mtime)` 下**同一秒内、长度不变的改写会被判成未变动**，缓存沿用旧结果且**没有任何症状**——数字只是悄悄停在旧值。实测两次写入相隔 0.09ms、长度都是 227、内容 `output 111→222`，秒级签名完全相同。换格式**不需要** +`CACHE_V`：老条目 sig 与新格式必然不等 ⇒ 逐条自然失效（claude 走增量、其余整解析一次），比整份作废便宜。
  - ★ **弃案（三家一致否决，别再提）：per-file 日桶缓存**。硬伤**不是时区**（我一开始以为是），是**跨文件全局去重** —— Claude 按 `message.id` 跨文件合并、agy 的 `_agy_deltas` 必须看完全部文件才能差分，按文件存桶再相加这两条会**静默算错**。同批否掉的还有缓存分片与 SQLite（要 10121 次 `json.loads` 拼回数据，比一次 `json.load` 更慢）。
  - ★ **`scan()` 的接线有专门的闸** `tests/test_scan_wiring.py`：AST 断言打在 **`scan()` 函数体**上（不是 helper、更不是测试自己的副本），覆盖「日桶必须由 `_day_bounds()` 绑定」「小时桶必须 `strftime`」「签名必须走 `_sig()`」「`acc.setdefault` 必须在窗口判断之前」，外加真跑 `scan()` 的隔离夹具。**`SOURCES` 要收成单元素并去掉 coverage 钩子** —— 靠 `only=[...]` 过滤不算隔离（实测那样会打开 165 个真实 brain 文件，去掉 `only=` 还会扫 10133 个真文件而断言照过）。
