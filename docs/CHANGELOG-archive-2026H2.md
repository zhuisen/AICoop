# CHANGELOG 归档 · 2026 H2（v1.6.0 – v1.8.0）

> 2026-10-17 从 `CHANGELOG.md` **整段搬来，逐字未改**（v1.10.4 发版时主文件到 3006 行，触到 3000 行分卷阀）。
> 主文件保留最近两个大版本（v1.10 / v1.9）。这里唯一不可再生的是**当时的实测数字**，摘要会把它磨掉。
> 同一个 git 仓，`git log -S` 照样搜得到；查 `### B` 编号时两卷一起搜：`grep -n "^### B" CHANGELOG.md docs/CHANGELOG-archive-*.md`。

---

## v1.8.0 — 2026-09-19

**下载安装包就能接入轮换 —— 但必须经你点头。**

v1.7.0 让「没接上轮换」第一次**会变红**；这一版让它**可以被接上**，而且是在 App 里、
由用户逐项决定。用户 2026-09-19 拍板的流程是**两段同意**：总览只提示并跳转，真正动手在设置页。

### 新增 · 账号池 Connector（`设置 → 账号池接入`）

六步，逐项可选，每一步都能**先看将要写入的原文**：准备运行时 · 写入 model provider ·
建 profile overlay · 建命令入口 · 装 launchd 服务 · 让 `codex` 本身也走轮换（**默认不勾**）。

**四条硬边界**（都写进了闸，9 条变异全部被捕获）：

| 边界 | 怎么保证 |
|---|---|
| **不需要管理员密码** | 全部用户级：`~/Library/LaunchAgents`、`~/.local/bin`、`~/.codex` |
| **不重写你的配置** | 只在托管标记之间写 `~/.codex/config.toml`；`apply`→`remove` 往返后**逐字节回到原样** |
| **绝不碰凭证** | 静态闸禁止 `connector.py` 出现 `login` / `logout` / `auth.json` —— 那两条命令会在服务端吊销当前账号 |
| **可撤销** | 只删它自己建的东西；你自己放的同名文件**先备份再让路**，指向别处的 symlink 一律不动 |

★ **`external` 单独一档**：已存在的 provider / profile / 入口标成「你自己装的」，
**不会去覆盖**，也算「已经在工作」。第一版把作者机器上手工配的全报成「待装」，
等于建议用户覆盖自己正在用的配置。

★ **运行时复制到数据目录，不指向 App 内部**：`deploy.sh` 与应用更新会整个替换 bundle，
指向那里的话常驻服务会在替换窗口里消失；用户把 App 拖进废纸篓，`codex` 跟着废掉，
而两件事看起来毫无关系。

### 变更

- **安装包现在带着轮换运行时**（`bundle.resources` +9：`proxy/*`、`daemon/quota_daemon.py`、
  `scripts/install-launchd.sh`、`codex-wrapper-with-logout-guard.sh`、`connector.py`）。
  带着 ≠ 自动装 —— 要改你的 `~/.codex`，那得你点头。
- 总览的「未接入轮换」横幅多了一个 **「去接入 →」** 直达设置页；菜单栏那条也可点。
  `unknown`（判定不了）**不给**这个按钮 —— 我们根本不知道缺什么。
- `codex-rotate integration` 的文案跟着改了：安装包**含**运行时，所以不再说「不含 proxy/」。

### 闸

`tests/test_connector.py`（26 条）· 变异 9/9 被捕获 · 全量 **1432** 条通过 ·
Connector 面板四态（fresh / mixed / blocked / ready）均已像素验证。

---

## v1.7.0 — 2026-09-19

**轮换接入这件事，第一次有了会变红的检查。**

用户报「下载了 CodexBar，敲 `codex` 没走 rotateproxy」。查下来**不是 bug，是这套东西从来
没被完整分发过** —— 而每一处缺口都静默，用户看到的是「一个看起来正常的空池」。

### 新增

- **`codex-rotate integration [--json]`** —— 装机链路总闸。一条命令查完
  profile overlay / provider 块 / `supports_websockets` / 代理在不在听 / 池里有没有号 / 入口是否存在，
  **五态**：`ready` / `not_installed`（中性）/ `broken`（红）/ `no_accounts`（琥珀）/ `unknown`。
  已接进 `codex-rotate health`（排在所有闸之前）。
- **CodexBar 总览页 + 菜单栏直接显示接线状态**（`read_integration` IPC，与 `health` **共用同一个
  判定函数**）。此前 App 把 `run_rotate` 的 stdout 整个丢掉，`health` 里既有的几道闸一个字都到不了界面。

### 修复

- **`codex` PATH wrapper 现在可分发。** 它有两个**作者自己机器上恰好正确**的硬编码默认值：
  仓库根写死 `~/Projects/tools/codex-account-rotator`、官方二进制写死 `~/.local/npm-global/bin/codex`。
  改成自解析（按脚本自身位置上跳两级）+ 在 PATH 上找官方二进制并**跳过自己**（否则无限递归）。
  找不到时**报错退出**，不会静默退回直连。

### 文档

- `docs/INSTALL.md` §2 **第一次把 `codex` wrapper 写进安装步骤**（这是根因）；补上
  `cxd` 单号直连入口与三入口对照表；§3 补上**缺失的 `rotateproxy.config.toml` 创建步骤**
  （此前只在 `SETUP.md` 里，照 INSTALL 装完仍然缺 profile）。
- **服务数 3 → 4**（`install-launchd.sh` 一直 emit `autosync`/`quotad`/`proxy`/`dawnprobe`，
  文档、`CLAUDE.md`、`docs/WINDOWS.md` 三处都写的 3）。
- `docs/TROUBLESHOOTING.md` 新增「敲 `codex` 没有走轮换代理」整节。
- README 明写：**只下载 `.dmg`/`.exe` 不会获得轮换能力**。

### 闸

`tests/test_codex_integration_gate.py`（17 条，**7 条变异全部被捕获**）·
`tests/test_codex_wrapper_portable.py`（9 条，含「不许 exec 回自己」与「INSTALL.md 必须装 wrapper」）。
全量 **1405** 条通过。

---

## v1.6.4 — 2026-09-18

v1.6.3 以来 **2 个 commit**。**Z 级**：两条都是修，没有新能力。

### Fixed
- ★★★ **僵尸进程还有第二条路，而它不在本仓代码里。** 装机版 v1.6.3（**已含** B56 全部修复）
  底下仍抓到一具：点一次「设置 → 关于」的外链，就留一具永久僵尸。链路是
  `tauri-plugin-shell::open` → `open::that_detached`，而后者 spawn 完**直接 drop `Child`、
  从不 `wait()`**。外链改走本仓自己的 `open_url` 命令（走 `spawn_and_reap` 收尸 +
  http(s) scheme 白名单），`tauri-plugin-shell` 连同它的 npm 包与 `shell:default` 权限一并移除。
  详见 **B57**。
- ★★ **重置卡到期横幅不再喧宾夺主，且关得掉**（用户 2026-09-18 实报）。原形态是 60px 三行、
  挂在 352px 弹窗顶部、`CARD_WARN_DAYS=3` 意味着**连挂三天**、**没有任何关闭入口**，
  而那颗「用卡: /usage」大按钮**点了并不用卡**（只弹 toast 说去终端敲命令）。
  现在：常驻那一半收进卡上本就有的 `CardBadge`（零高度成本），横幅只在**这张卡刚进入
  3 天窗口**时弹一次单行、带 `×`。关闭记忆按 `节点:到期日` 存 —— 换新卡会**重新提醒一次**，
  不是「以后都别提醒我」。「怎么用卡」那句搬进角标悬浮，所以关掉不丢信息。

### Improved
- 僵尸闸新增 `TheDetachedSpawningDependencyIsGone`：判据**跨过仓库边界**（依赖声明 / npm 包 /
  前端 import / capability / 替代命令是否真的接上并走收尸），因为这一次泄漏的 spawn
  不在 `src/**` 里，而只扫源码的闸对它是结构性沉默。

---------

## v1.6.3 — 2026-09-17

v1.6.2 以来 **2 个 commit**。**Z 级**：修的是资源泄漏与一条静默故障，没有新能力。

### Fixed
- ★★★ **不再留下僵尸进程。** 真凶是 `bin/agy` 用裸 `Popen` 起采样器、紧接着
  `os.execv` 换进程映像 —— execv 换映像**不换父子关系**，接管 pid 的 agy 真身
  不认识这个孩子、永不 `waitpid`。改双 fork 让孙进程被 init 收养。
  ⚠️ 上一版（v1.6.2 之后那个 commit）修的是 App 侧两条采样器 spawn，
  **那两条当时产出 0 个僵尸** —— 写法对但地方错，详见 **B56**。
- ★★★ **grok 额度消耗序列恢复采集（此前静默停摆 49 小时）。** App 判「要不要补拉采样器」
  只看锁文件在不在，于是一个**陈锁**就让它永久闭锁；而采样器自己本来就能按 PID 接管死锁，
  只是永远等不到被拉起。现在改成探锁里那个 PID 还活不活着。
- **agy 采样器不再自造陈锁**：早退路径原来先取锁后探活，`return 0` 走不到 `finally` 的
  `unlink`。已与 grok 侧对齐（先探活后取锁）。
- **App 退出时清理自己起的子进程**：此前采样器会被孤儿化，最长在后台继续查额度 24 小时。
  用 `SIGTERM`（让采样器有机会删自己的锁），并为两个采样器补了 SIGTERM 处理器 ——
  Python 默认的 SIGTERM 直接终止、**不跑 `finally`**。

### Improved
- 僵尸检测的闸从「只认一种写法」改成覆盖 **7 种**泄漏形状，扫描范围补上
  **7 个无扩展名的 python 脚本**（原覆盖率 0/7，真凶就在其中），
  并新增一条断言**真实 `ps`** 的行为闸。

### 已知未修（发版前如实写出来）
- 本机既有的 17 个僵尸不会消失：7 个挂在还活着的老 agy 进程上、10 个属于另一个 app
  （`Clipsync`，疑似同一形状但不在本仓）。修复只保证不再产生新的。
- 三份 path-scoped 规则的注入仍未验成（判据在 `CLAUDE.md` §5，要新会话跑）。
- `doushutangmu@gmail.com` 仍过不了 Antigravity 的 eligibility 闸。

---

## v1.6.2 — 2026-09-17

v1.6.1 以来 1 个 commit。**Z 级**，只修发版流程本身。

### Fixed
- ★★★ **发版后本地版本不再显示 `+N`。** v1.6.1 发出去之后，本地安装的那份显示
  **`v1.6.1+10`** —— 产物没撒谎，它确实是在 `git tag` **之前 38 秒**、从一个脏工作区
  构建的（距 `v1.6.0` 9 个 commit + 脏 1 = 10）。
  **根因是顺序**：`B` 从 git 派生（§3.7）之后，`$release-cut` 那条通用顺序
  （… → build → commit → tag → push）**结构性地做不到 `B == 0`**，
  因为构建那一刻 tag 还不存在。§3.7 承诺「`B == 0` 就是 release」，
  §3 的顺序却保证它不成立 —— 两条规则从 `B` 变成派生值那一刻起就互相矛盾。
  · 正本已改：`CLAUDE.md` §3 新增 **4.5**「发版时先 tag 再本地 deploy」，并写明理由。
  · 闸：`deploy.sh` 现在**当场打印它烤进产物的版本**，`B != 0` 时告警并给出下一步。
    这个缺陷在部署那一刻完全不可见（构建成功、app 正常启动、只有版本字符串在撒谎），
    **只能靠事后打开界面才发现的东西，就会由用户来发现** —— 所以它需要闸，不是再写一句话。
  · 本次发版**就是按新顺序做的**（commit → tag → deploy → push），本地因此显示 `v1.6.2`。

---

## v1.6.1 — 2026-09-16

v1.6.0 以来 **4 个 commit**。按发版规则是 **Z 级**：修的都是既有功能里的缺陷，没有新能力。
主题是**探针** —— 全 app 仅有的两个花钱控件都在这条路径上。

### Fixed
- ★★★ **codex 探针默认模型钉死 `gpt-5.6-luna` / `low`，不再被 `models_cache.json` 否决。**
  此前清单一刷新，默认就顺位到一个该账号调不了的模型，**每个号 HTTP 400、零计费请求**，
  于是 5h 窗口永远锚定不了 —— 症状就是「点了探针，额度重置时间还是不动」。
  当天双向实证：清单里有的会 400、清单里没有的反而能跑。详见 **B55 ①**。
- ★★★ **agy 探针的归属现在有证据。** 它跑的是「此刻钥匙串里那个号」，而那个槽被
  **7 个**常驻 agy 进程并发写（身份还不同），所以 `probe <非当值号>` 可能
  **实际用 A 在跑，却把 ✓ 和 15k token 记在 B 头上**。
  现在用 agy 自己日志的 `applyAuthResult:` 核对：对不上就不记在本号头上，
  认不出则只标注、不翻转结果。详见 **B55 ②**。
- **`agy-rotate health [label…]` 真的吃 label 了** —— 此前传了名字也静默检查全池；
  未知名字现在直接报错退出，不静默退回全池。
- **探针报错留「有用的那一半」**：改为优先抓结构化 `"message"`、否则取头部。
  此前取 stderr 末尾，于是 eligibility 被拒时只留下一段 Google 登录 URL，
  而真话 `Verify your account to continue.` 在开头、被截掉。

### Improved
- **Gemini 额度自动保鲜**（10 分钟阀，三触发点：进档 / 可见时心跳 / 托盘弹出）。
  此前云端每账号额度**只有手点 ↻ 才更新**，实测本机停在 18 小时前。
  ⚠️ 保鲜判据是池级的 `quota_ran_at`（**尝试过**）而非各号 `quota_at`（**取成过**）——
  后者会让一个坏号把条件锁死成 403 放大器（同 B46 的形状）。
- **Gemini 卡与账号卡对齐**：副标题放账号邮箱、页脚放最紧窗口的重置日（绝对写法）。
  ⚠️ 页脚**刻意不写「到期」** —— 三个独立探针确认 agy 没有订阅到期数据。
- **控件组不再折行**：平台详情页「分模型/总量」在 ≤1200px 下被挤成两行（窗口下限 860px，
  等于日常宽度一直是坏的）。新增 `segRows` 探针把这一类从"只能肉眼发现"变成会红的闸。

### 已知未修（发版前如实写出来）
- `doushutangmu@gmail.com` 仍过不了 Antigravity 的 **eligibility** 闸（`Verify your account`）。
  与凭证无关，上游同症状 issue 至今无解。
- 三份新建的 path-scoped 规则（credentials / verification / rotation-lanes）**注入仍未验成**，
  判别实验在 `CLAUDE.md` §5，**要新会话跑**。
- git 历史重写后旧 commit 在 GitHub GC 前仍可用 SHA 直链访问（用户知情并接受）。

---

## v1.6.0 — 2026-09-15

v1.5.0（2026-09-10）以来 **44 个 commit**。按发版规则是 **Y 级**：③ 是一整块新能力。

### New
- **agy（Gemini）账号池**：`agy-rotate` 13 个子命令（login/list/quota/switch/pick/auto/rename/
  remove/live/health/probe/rotate/auto-switch），总览分 Codex / Gemini / Grok 三档，
  菜单栏 v4 芯片行，自己的探针与「检查 token」，`agy.log` 运行留痕。
- **单天按小时**：选中某一天（昨天 / 具体某一天）横轴改为逐小时。最近 30 天瞬开，
  更早的日子按需 `--hours-day` 现补。
- **AI 用量**年度档与自定义范围（1:1 复刻交接稿），日历弹层含月份选择器。
- **运行日志接上多源**：quotad / agy / dawnprobe / autosync 的行终于能到界面
  （其中 dawnprobe 是全仓唯一会自动花钱的任务，此前完全不可见）。
- **每日清晨探针闸**（`dawn_probe_gate`）：跑没跑、成没成、**可不可以重跑**三件事各自有答案。
- **计费探针记来源** `via`（dawn / ui / cli?）—— 「谁在自动花钱」终于有记录。
- 版本号 `X.Y.Z+B`，`B` 每次本地部署 +1、发版归 0。

### Improved
- agy 额度改走 `retrieveUserQuotaSummary`：**每个号都能直接读到自己的周窗口**，
  并干掉了「按数值对分桶 + 成员最多的那组是 gemini」那套启发式。
- grok 取消 5h 空格（xAI 只有周窗口，那一格永远不会有数）。
- 代理轮换泳道按 **aid** 认身份（改名不再劈成两条泳道）。
- 缺一格额度时行上直接写原因，不再只写在悬浮里。
- grok 周额度实时采样；agy 额度推送通道。

### Fixed
- **quotad 的 `_reset_crossed` 在 403 出现时会变成 403 的放大器** —— 扫描失败 ⇒ 条件恒真
  ⇒ 每 60s 再扫。实测当天 03:00–08:59 打到 22/44/43/43/44/32 次/小时（设计 12）。
- Gemini 档切档「跳来跳去」（陈旧 `live_seen` 覆盖已验证的现读）。
- 主窗与菜单栏对「当前号」给出两个答案（跨 webview 广播）。
- 「一个 USE 一个当前」：排名改用**所有候选都测到的窗口**做共同基准。
- 「今日」被画成 30 天（`p.hours` 契约改了没回头看消费点）。
- 日志源清单与安装脚本双向漂移（多出两份 8 月的退役日志、少了 dawnprobe）。
- 菜单栏点账号跳错页、Gemini 档 ⌘N 角标点了没反应。

### ⚠️ 已知未修（发版前如实写出来）
- **被 `rotate_off` 摘出轮换的号会饿死**：续期只剩代理这一条路（keepalive 2026-08-29 取消），
  代理永不选它 ⇒ token 过期 ⇒ 额度读不到 ⇒ 读数停在作废前那一刻。
  本机 `qq55` 就是实例。用户 2026-09-15 拍板**暂不修**，知情即可。
- 24 格单天布局没有像素证据（harness 驱不动自定义范围选择器）。
- 圆角真机 WKWebView 仍未验（抓屏被 TCC 挡）。

---

### B59

**Connector：第一个主动改用户 `~/.codex` 的东西**（2026-09-19）

v1.7.0 之后用户拍板做 codex 建议的**方案④ Connector**，并指定了流程：
「做在设置端里，新下载在 codex 总览里弹出提示，选择是否安装。如果是的话，就跳到设置端里
让用户自行选择是否动手。」—— 即**两段同意**，总览只提示，动手在设置页。

**这一轮抓到的、自己犯的 5 个错**（每一个都成了闸）：

1. **把「你自己装的」报成「没装」。** 第一版只有 `todo/done/blocked` 三态，于是作者机器上
   手工配好的 provider/profile/wrapper 全被标成「待装」—— 等于建议用户去覆盖自己正在用的
   配置。加了 `external` 第四态。
2. **`ENTRIES` 里有 `agy-rotate`，`RUNTIME_FILES` 里没有** ⇒ 真装机会建出**悬空 symlink**，
   点一下报 `No such file`，而用户完全看不出与 Connector 有关。闸：入口目标必须在运行时清单里。
3. **`blocked` 时复选框仍是勾选态、`apply()` 只挡了 `chosen.length` 与 `busy`** ——
   红条说「装不了」而按钮照样能点。**按钮变灰只是样式。**
4. **harness 桩里的 `\n` 被多一层转义变成真换行**，卡在 JS 单引号字符串里 ⇒ 整个 harness
   脚本解析失败 ⇒ React 从未挂载 ⇒ 截图一片空白。★★ 第二次犯时，被转义掉的正是**那条
   警告本身**（我写的「别写字面换行转义」那句注释被劈成两半，后半截变成代码）。
   现在换行一律 `String.fromCharCode(10)` 拼。
5. **验证探针的假阳性**：我在**整份 HTML**里 grep 组件文案，而那些字正躺在桩的源码里 ⇒
   报「六个步骤都在」而页面其实零渲染。判据改成：剥掉 `<script>` 之后只看 `<body>`，
   并核 `__PROBE__` 的 `mounted` 与 `errors`。

★★★ **第 6 个，也是最严重的一个：我的测试把用户真实的常驻服务全停了。**

`connector.remove()` 会 `launchctl bootout gui/<uid>/com.doushutangmu.codex-rotate.*`。
服务 label 是**固定字符串**，不随任何环境变量改变 —— 而测试只隔离了 plist 路径
（`CODEXBAR_LAUNCH_AGENTS`）。于是跑一次 `tests/test_connector` 就把真机上的
**proxy / quotad / autosync / dawnprobe 四个全 bootout**，轮换当场断掉，
而整套测试**全绿**、没有任何一处会为此变红。发现它纯属偶然：随手跑了一次
`codex-rotate integration`，看见「连不上 127.0.0.1:8011」。

这与 2026-09-06「夹具写进真账本」是**同一个形状**：测试污染生产，且症状安静。
修法也照那次 —— **加一个只影响这一件事的隔离口** `CODEXBAR_LAUNCHCTL=0`
（`connector._launchctl()` 是所有 launchctl 调用的唯一出口），而不是「记得在每个测试里打桩」
（那是"写下来但没有闸"的老路，下一个新测试照样踩）。
两处 bootstrap 都设它，闸在 `test_isolation_bootstrap`：一条断言**变量已设置**，
一条是**行为闸** —— 把 `subprocess.run` 换成探针真跑一次 `remove()`，数它有没有碰 launchctl。
★ 探针**拦下不放行**，否则这条闸自己的变异验证会再杀一次服务 ——
**验证工具本身不许有破坏性副作用。**

⚠️ **另有一句披露当场变成假话**：安装包加上 `proxy/` 之后，`integration` 还在说
「`.dmg` 里不含 `proxy/`」。本仓铁律「换了数据源，页面上的话必须跟着换」——
这次是自己在同一轮里制造并修掉的。

### B58

**「敲 `codex` 没走 rotateproxy」—— 不是 bug，是从没被分发过**（2026-09-19，用户报）

一个下载了 CodexBar 的用户敲 `codex` 没有轮换。逐环节查下来**四处缺口，每一处单独就足以
让轮换失效，而它们全都静默**：

1. `.dmg` 的 `bundle.resources` 里**没有任何 `proxy/` 下的文件**（`proxy.py` / `cxp` /
   `auth-token` 一个都没有），也没有 `install-launchd.sh` ⇒ 下载用户手里根本没有轮换引擎；
2. `docs/INSTALL.md` §2 只建 `codex-rotate` / `cx` / `cxp` / `agy-rotate` 四个 symlink，
   **没有 `codex`**。开发机上裸 `codex` 能轮换，靠的是 `~/.local/bin/codex` 那个 wrapper
   **恒定注入 `--profile rotateproxy`** —— 而它不在任何安装步骤里；
3. profile 缺失时 **codex 不报错**，静默退回 base 配置（直连单号、不轮换、WS 全开）；
4. App 的 `useStore.run()` 丢掉 `run_rotate` 的 stdout ⇒ `health` 里既有的几道闸
   **一个字都到不了 UI**。

★★ **这是「在我机器上是好的」的字面形态**，而且比通常更难发现：`which codex` 对作者和用户
给出的是**不同答案**（作者的 PATH 上第一个 `codex` 是 wrapper，还叠着一个 `alias codex=cxp`），
所以在本机**怎么复现都复现不出来**。同族前车之鉴：LibreSSL 那条、系统代理黑洞那条 ——
「本地环境让请求静默失败，用另一个工具复现不算独立证据」。

★★ **wrapper 自己也不可分发**（查的时候才发现）：`CODEX_ROTATE_STORE` 默认值是作者的 clone
路径、`CODEX_NATIVE_BIN` 默认值是作者的 npm prefix。直接让用户 symlink 它会把他们的 `codex`
弄成 exit 78。已改成自解析 + PATH 发现（并跳过自己，否则 `~/.local/bin` 排前面时无限递归）。

**交付物是一个会变红的检查，不是又一行散文** —— `codex_integration_gate()`，五态，
`unknown` 绝不折叠成 `ok`，红灯放在**默认总览与菜单栏**（眼睛已经在的地方）。

⚠️ **写这道闸的过程里，同一条铁律我自己犯了三次**（全部被它自己的用例抓住）：
「读不到 ≠ 没有」在 `provider`、`ws` 两条检查上各错一次（把「文件不存在」和「存在但读不到」
折成同一个 `None`），导致**一台干净的 .dmg 机器被判成 `broken`（红：你装了但坏了）**
而不是 `not_installed`（中性：你只装了看板那一半）—— 两者的下一步完全相反。
第三次是 `ws` 那条在「读得到的那半里没找到」时判了 `bad`。

⚠️ **像素验证又抓出两个 tsc/测试都看不见的缺陷**：CLI 文案里的 `**粗体**` 是给终端看的
markdown，在 HTML 里原样显示成星号；徽章与正文重复成「接线断了 · 接线断了 ——」。
菜单栏 352px 下整句被省略号从尾部切掉，而**被切掉的恰好是「该做什么」那半** ——
harness 的 overflow 探针报 0（`text-overflow` 只改渲染、DOM 文本仍完整，结构闸抓不到这一类，
本仓已记过）。改成两行结构才解决。

### B57 · 僵尸进程第三幕：**泄漏的那次 spawn 不在我们的代码里** — 2026-09-18 ✅

B56 修完、v1.6.3 发出去之后，我为它写的行为闸（真去数 `ps`）在**装机版上仍然是红的**：

    pid 36012   PPID 14732(CodexBar)   STAT Z   诞生于 09-18 14:47:29

先把最容易混淆的一条钉死：pid 14732 的启动时刻是 `09-17 11:13:10`，产物构建时刻是
`11:13:09`，`CFBundleShortVersionString = 1.6.3` —— **正在跑的这个进程就是含修复的那一版**，
不是没更新。僵尸比修复晚了一天才出生。

#### 真因：依赖替我们 spawn，然后把句柄扔了

    SettingsPage `openExternal()`
      → tauri-plugin-shell 2.3.5   src/open.rs:134   `::open::that_detached(path)`
      → open 5.3.5                 src/lib.rs:267    → `spawn_detached()`
      → open 5.3.5                 src/lib.rs:380    `pre_exec { setsid() }`
                                                     + `self.spawn().map(|_| ())`

最后那行把 `Child` **直接 drop 掉，从不 `wait()`**。Rust 的 `std::process::Child` 没有会
收尸的 `Drop`（刻意的语言设计），所以 drop 句柄 = 定额留一具僵尸。14:47:29 这个时刻正对上
「关于」里那两个外链之一被点开。

★ **它与 B56 的 `bin/agy` 是同一个形状，只是换了语言。** `setsid()` /
`start_new_session=True` 都只脱离控制终端，**不转移收尸责任**。两次都是靠
「它 detach 了所以安全」这个错觉过的关 —— 第一次是我写的，第二次是依赖写的。

#### 忠实复现（`scratch/verify_rust_child_drop_20260918.rs`，两个方向）

    A  丢弃 Child（= open::that_detached，含 setsid）-> 本进程名下僵尸 1
    B  交给线程 wait（= 本仓 spawn_and_reap）        -> 新增僵尸 0

★ 复现**必须带上 `setsid()`**，否则证明不了「setsid 不转移收尸责任」这半 ——
同 B56 那次「漏掉 `execv` 的复现会得出『没有 bug』的相反结论」。

#### 修法：自己起，因为依赖那行改不了

新增 `open_url` 命令：http(s) scheme 白名单（这个字符串最终交给系统 URL 派发器，
macOS 的 `open` 会按 scheme 唤起**任意**已注册应用）+ 三平台启动器 + 走 `spawn_and_reap`。
`tauri-plugin-shell` 连同 npm 包、`shell:default` capability 一并移除 —— 留着等于给
「顺手装回去」留一条无声的路。

#### 这一轮给判据本身上的课

- ★★★ **只扫 `src/**` 的闸对这一类是结构性沉默的。** B56 那套七种形状的 Rust 探测器
  一条都没响，而它们**全都正确**：泄漏确实不在本仓源码里。新闸
  `TheDetachedSpawningDependencyIsGone` 因此把判据下沉到**依赖声明与权限**那一层，
  并配一条反向断言（替代命令存在且真的注册了）—— 否则「把功能删了」也会全绿。
- ⚠️ 写这条闸时当场又踩了两个本仓记过的形态：
  ① **形态④**：`SettingsPage.tsx` 顶上正写着「不要用 plugin-shell」这条规则本身，
     裸搜字符串把**解释规则的那句话**判成违反规则；
  ② `_strip_rs` 的 `//[^\n]*` 不认字符串字面量，把 `starts_with("https://")` 里的 `//`
     当成注释起点，**吃掉半个白名单** ⇒「没有白名单」恒红，而真因与白名单无关。
  两条都是「判据自己坏了，而坏的样子指向别处」。

#### 剩余风险

- 端到端那一下（真点一次外链、再数 `ps`）**需要一次人工点击**，尚未做。机制链由
  「复现证明 `spawn_and_reap` 收尸」+「静态闸证明 `open_url` 走的就是它」闭合。
- 本机 17 具僵尸里 **10 具来自 Clipsync**（另一个仓）。形状很可能相同，**未查**。

### B56 · 僵尸进程：修对了写法，修错了地方 — 2026-09-17 ✅

用户报「CodexBar 会留下僵尸进程」。第一版修复（816f0ad）动的是 `lib.rs` 两处采样器的
`let _ = ….spawn()` —— 写法本身没错，但**那两条路径当时产出 0 个僵尸**。
四方评审（4/4 投票）把这条打回，逐条复核后全部属实。

#### 真凶在 `bin/agy`，不在 App

实测 17 个 `<defunct>` 的父进程分布：

    ×10  /Applications/Clipsync.app          （另一个 app，不在本仓）
    × 7  ~/.local/bin/agy                     ← **本仓 bin/agy 造的**
    × 0  当前 CodexBar                        （两条 spawn 路径正被锁抑制）

`bin/agy` 用裸 `subprocess.Popen` 起采样器，紧接着 `os.execv` 换进程映像 ——
**`execv` 换映像不换父子关系**：采样器仍挂在这个 pid 下，而接管 pid 的 agy 真身
根本不认识它、永不 `waitpid`。
⚠️ `start_new_session=True` 只 `setsid`，**不改 PPID、不转移 reap 责任** ——
当时正是靠它误以为已经安全。改双 fork 让孙进程被 init 收养。
⚠️ 没用 `SIGCHLD=SIG_IGN`：它会**跨 `execv` 保留**，让 agy 自己的 `waitpid` 全拿 `ECHILD`。

★ **第一次复现失败过**：只写 `Popen` 不 `execv`，两边都是 0 —— Python 的 `subprocess`
会顺手收尸，而真实路径里 `execv` 让 Python 运行时整个消失、再没人收。
**漏掉 `execv` 的复现会得出「没有 bug」的相反结论。** 补上之后：

    Popen + execv 成长命进程（原）  -> 该 pid 下僵尸 1
    双 fork   + execv（修后）       -> 该 pid 下僵尸 0

#### 顺带查出一条**正在生效的线上故障**：陈锁让 grok 采样静默 49 小时

App 判「要不要补拉采样器」用的是 `!Path::new(&lock).exists()` —— 只看文件在不在。
而两个采样器自己的 `take_lock()` **都能按 PID 接管死锁**，`agy_quota_sampler.py` 的
docstring 甚至点名了后果：「不接管的话**采集会从此永久静默**」。
**但 App 根本不给它机会** —— 那段自愈逻辑永远走不到。两层各自正确，组合起来是坏的。

实测：`grok-quota-ledger/.sampler.lock` 内容 `884`、进程早已不在，
`samples.jsonl` **冻结 49 小时**。grok 没有 `bin/agy` 那样的 wrapper 兜底，
**App 是它唯一的补拉路径** ⇒ 永久闭锁，而 UI 上只表现为「数据旧了」。
改 `sampler_lock_held()`：读锁里的 PID + `kill(pid, 0)` 探活，一切拿不准 **fail-open 去拉**
（少拉一次 = 永久静默，多拉一次 = 一个瞬时进程，两边不对等）。
⚠️ **没用 mtime 判陈旧**：实测采样器运行期间**不刷新**锁 mtime，按 mtime 判会把活锁误判成死锁。

#### 以及两条同族遗漏

- **agy 采样器先取锁后探活**，早退路径 `return 0` 走不到 `finally` 的 `unlink` ⇒
  **自己给自己造陈锁**。grok 侧早已是「先探活后取锁」并配了行为闸，
  **agy 侧从未同步** —— 典型的「修了症状、类没关」。
- **App 退出不清理子进程**：实测 pid 97371 `PPID=1`，是**上一代 app** 起的孤儿，
  `MAX_LIFETIME 24h` ⇒ 用户关掉 app 后它还能继续查额度一整天。
  而本仓自己写着「最贵的问题是**谁在自动花钱**」，这条链路正好答不上来。
  加 `KIDS` 注册表 + `reap_all_children()`，接进 `quit_app` / `ExitRequested(code=Some)` /
  `RunEvent::Exit` 三处，用 `SIGTERM` 不用 `SIGKILL`。
- ★ **顺带闭环**：选 SIGTERM 的**全部理由**是「让采样器删掉自己的锁」，
  而 Python 默认的 SIGTERM **直接终止、不跑 `finally`** —— 实测 app 退出后两个锁原样留在盘上。
  两个采样器装 `SIGTERM/SIGINT → raise SystemExit`，行为验证锁已自删。

#### 第一版的闸是空守卫，四家一致指出

- Rust 判据只认 `let _ = ….spawn()`。实跑形状表：**7 种里抓到 1 种** ——
  连它自己 docstring 声称能抓的裸 `cmd.spawn();` 都漏。改成反向白名单（必须绑定且有 `wait`），
  现在 7/7 全抓且不误报合法写法。
- Python 侧 `rglob("*.py")`，而本仓有 **7 个无扩展名的 python 脚本** ——
  覆盖率 **0/7**，**真凶 `bin/agy` 从未被扫过一个字节**，测试却报「Python 侧干净」。
- 判据改 AST：文本匹配会撞上解释这条规则的 docstring（修完当场假红一次，形态④第六次）。
- 新增断言**真实 `ps`** 的行为闸 —— 僵尸不占 CPU、几乎不占内存，**永远不会自己报警**。
- 两条既有测试（`test_agy_realtime` / `test_grok_realtime`）钉的是被证伪的旧前提
  「锁文件在就不拉」，判据一并更换 —— **旧判据会把正确的修复判成违规**。

本轮变异 11 个，全部按预期红/绿。

⚠️ **已知残留**：本机那 17 个僵尸不会消失 —— 7 个挂在**还活着的**老 agy 进程上
（要等它们退出），10 个属于 Clipsync。修复只保证不再产生新的。

---

### B55 · 探针三连：默认模型钉死 · 归属要有证据 · 报错留有用的那一半 — 2026-09-16 ✅

用户报「点了探针，额度重置时间没更新」，顺着查出三个缺陷，全在**唯一花钱的那条路径**上。

#### ① codex 探针一次都没跑成 —— 而 2026-09-06 的修复只是把故障开关挪了个地方

链条：codex 16:44 刷新 `models_cache.json` → `gpt-5.6-luna` 从清单里消失 →
`_probe_model_default()` 顺位到 `gpt-5.4-mini` → 每个活号 **HTTP 400
「已不被这个 ChatGPT 账号支持」** → **零计费请求** → `quota_anchor` 停在
`billed=false / floating` → 重置时间一直跟着 `now` 滑 → 用户看到"没更新"。
★ 与 2026-09-06 那次事故**一字不差**，但根因升了一层。

**清单在两个方向都被证伪（同一天、同一台机器）：**

| 模型 | 在 `models_cache.json` 里 | 实际调用 |
|---|---|---|
| `gpt-5.4-mini` | ✅ 在（`visibility=list`） | ❌ HTTP 400 |
| `gpt-5.6-luna` | ❌ 不在 | ✅ 成功（06:00 dawn-probe 4/4、16:50 复测 1/1） |

根因：`models_cache.json` 是 **codex 客户端**按 `client_version`/`etag` 拉的快照，
而「能不能调」是**按 ChatGPT 账号授权**的 —— 两者从来不是同一个集合，
且它**会被 codex 自己随时改写**，于是"探针能不能用"挂在一个隐藏开关上。

修：`PROBE_MODEL_PINNED = "gpt-5.6-luna"` / effort `low`（用户定），提到模块级并
**不经过清单过滤**；设成 `None` 即退回按清单挑的兜底（钉死的那个终会真下架）。
★ 闸的**判据也换了**：旧闸断言「默认模型在清单里」——那条不只失效，它会**主动把能用的
luna 判成非法**。新判据是「**本机有没有成功记录**」（`last_probe.status == "ok"` /
`dawn_probe` 的 `ok == total`），那条信息一直躺在 `state.json` 里，只是没人拿它当判据。

**修复即时可验**：用 luna 探过的号 `billed=True / state=anchored / reset 固定`；
用坏模型探的仍是 `billed=False / floating`。随后 4 个活号全部锚定（3/3 + 1/1）。

#### ② agy 探针：花了 15k token，却不知道花在谁头上

`_probe_one(label)` 的 `label` 形参**在函数体里一次都没被用过**（AST 证实）——
它跑的是「此刻钥匙串里那个号」，结果却被无条件记到「我们打算探的那个号」头上。
而钥匙串是被并发写的**单槽**，本机实证：**7 个**常驻 agy（最老的跑了 8 天 23 小时）、
**身份不同**（日志实证 2 个是 A、1 个是 B）、`agy.log` 里「钥匙串被别的 agy 进程写回过」
**已出现 9 次**（最近一次就在当天）。

修：`_run_identity(started_at)` 按我们自己起的那次的启动时刻定位它的 cli 日志，
读 `applyAuthResult: email=`（与 `agy-quota::pid_identity` **同源**）。三态不合并 ——
对得上→记账 · **对不上**→`ok=False` + `usage=None`（钱花在别号上）· **认不出**→不翻转 `ok`。
证据落 `last_probe.ran_as / attributed / via`。

#### ③ health 不吃 label · 报错只留没用的那一半

- `cmd_health` **完全不读 `args` 里的名字**，`health <label>` 静默检查全部号。
  零消耗所以没烧钱，但「限定了和没限定，在输出上分辨不出来」是本仓最不能容忍的那类
  「参数被静默吃掉」。现在按 label 过滤，**未知名字直接报错退出**。
- 探针报错取 `stderr[-160:]`（**末尾**）。eligibility 被拒时 agy 吐一大段 JSON + 很长的
  Google 登录 URL，于是记录里只剩 `…flowName=GlifWebSignIn&authuser`，而真话
  `Verify your account to continue.` 在开头、被截掉 —— 实测为此多绕一整轮排查。
  改成 `_err_gist()`：优先抓结构化 `"message"`，否则取**头部**。

#### ⚠️ 我在修 ② 的时候原样复刻了本仓记过的另一个坑

第一版 `_run_identity` 用裸 `except Exception`，而 `agy-rotate` **当时没有 `import re`**
⇒ `NameError` 被整个吞掉 ⇒ `ran_as` 恒 `None` ⇒ **归属核对静默地从不工作**，
而探针输出、退出码、日志**全都完全正常**。与 `_quota_anchors_mod()` 那次
（fail-open 吞掉 `Path` 未导入、账本静默从不记账）是**同一个形状**。
现已收窄到 `(OSError, ValueError)`，并上了三条闸，其中一条是**行为闸**
（拿本机真实日志跑一次必须解出 email）—— 静态闸挡不住这一类。

★ 另一处自伤：「优先抓结构化 message」那条变异**第一轮没红** ——
  夹具把 message 放在开头 180 字符内，**头部兜底也能命中**，所以它在验"真话还在"
  而不是"优先抓"。判据档位换成把 message 推到 180 字符之外（只有正则那条能挡住），
  变异立刻变红。**空守卫形态⑩：判据档位挑错会被上游的另一条路径兜住。**

#### 顺带确认（不是缺陷）

`doushutangmu@gmail.com`：额度读取 ✓、`health` ✓，而 `probe` 真跑被
`Verify your account to continue.` 挡住 —— 那是 Antigravity 的 **eligibility** 闸。
★ 而「四桶 100%」也不是"很充裕"：重置时刻恰好 = 快照 + 窗口长度，是**窗口从未启动**的签名。
**「读得到额度」「凭证有效」「能干活」是三件事。** 归属守卫确认 `attributed=true`，
结论关于的是正确对象。

闸：`tests/test_probe_model_is_supported.py`（18 条）·
`tests/test_agy_probe_attribution.py`（15 条）。三轮变异共 14 个，全部按预期红/绿。

---

### B54 · 公开仓库里的身份泄漏：**搬一段文字换了信任边界** — 2026-09-16 ✅

用户问「github 项目有没有暴露 codex 信息、中转站信息，暴露 key/oauth 就很严重」。

#### 结论先说：**没有凭证泄漏**

全历史 1355 个 blob 逐个扫（9 条正则，每条先在已知阳性上自检过）：
`sk-` 命中 4 条**全是夹具**（`sk-AT-REST-DO-NOT-LEAK-…` / `sk-same-prefix-A|B` / `sk-73a1…`）、
JWT 0、`access_token`/`refresh_token` 赋值 0、`GOCSPX-` 0、`auth/` 与 `state.json` 从未入库。
2385 条「hex/base64」命中全是 git SHA。**作者 ident 是 GitHub noreply，不含真实邮箱。**

#### 真问题是身份，而且是**我这一轮亲手造成的**

把 `CLAUDE.md` §8 整段搬进 `.claude/rules/credentials.md` 时，
**`.claude/rules/*.md` 是入库并推到公开仓库的，而 `CLAUDE.md` 是 gitignored 的** ——
搬运保真了，**信任边界没跟着一起想**。搬过去 = 公开。

★ 这是本仓「写下来但没有闸的规则一定会被违反」的又一次实证：
`test_doc_boards.py::TheCommittedRulesCarryNoLocalFacts` **本来就存在**，
它当场红了两条（`plus3/plus4`、`Pro1/plus6`）—— 闸是好的。
**但它看不见 `user-b` / `user-a` 这类用户自起的 Google 账号名**，
因为那条闸按 `plus\d+|Pro\d+` 的**形状**找。
⇒ 探针看不见目标 ⇒「没命中」被读成「没有」，本仓最贵的那类错。

#### 修了两件事

1. **补了一条从真源派生的闸**（`test_no_real_account_identifier_appears_in_the_committed_rules`）：
   不再猜标识符长什么样，**现读本机 `state.json` / `.agy-pool.json` 里真实存在的名字**
   再去 rules 里搜。⚠️ 清单**只能现读，绝不能写进那个入库的测试** —— 写进去它自己就是泄漏。
   已双向变异验证（塞回真名→红；换成不指人的措辞→绿）。
2. **重写了公开 git 历史**（用户 2026-09-16 拍板，我原本建议不做）。

#### 历史重写的执行记录

范围（用户选定）：**只清 Google 账号名 + email + sub ID**；
`tokendun`（中转站厂商名）、`plus3–plus7`（账号标签）、`doushutangmu`**保持原样**。
★ `doushutangmu` 被明确排除是因为它**不是脱敏而是改功能**：
bundle id `com.doushutangmu.codexbar` 与 launchd 标签前缀都含它 ——
改完 macOS 视为另一个 app（TCC 权限重置、Application Support 目录变、已装服务成孤儿）。

- 备份：`git bundle create --all` → `~/archive/codex-account-rotator/pre-filter-repo-20260916/`
  （⚠️ **那份 bundle 里仍是未脱敏的历史**，它就是回滚路径，别当它干净）。
- 重写：`git filter-repo --replace-text --replace-message`，**在干净克隆里跑**
  （本仓 2026-08-31 跑过一次，`.git/filter-repo/already_ran` 会触发续跑确认）。
- 结果：202 个 commit 全保留；**v1.3.0~v1.5.0 的 tag SHA 未变**（泄漏内容首次出现在 v1.5.0 之后），
  只有 `main`（`9a38659` → `0846fb4`）与 `v1.6.0`（`ae8c194` → `932b274`）强推。
- 验收：**从 GitHub 重新克隆**再扫 —— 1353 blob + 全部 commit message **零残留**，
  且正向对照确认替换值真的存在（否则"扫到 0"可能是扫错了历史）。
- 重写后的树跑完整测试：**1284 绿 / 15 skip / 0 失败**。

#### ⚠️ 一个把我卡了 10 分钟的坑（值得记）

第一次跑 `git filter-repo … 2>&1 | tail -12` **十分钟零输出**。
判据不是"等久一点"，是 **`ps` 显示它 10 分钟只烧了 0.07s CPU、`.git` 15 分钟零改动**
⇒ 它在**阻塞**不是在干活。`sample` 抓栈，栈顶是 **`builtin_input`** ——
它在等 `already_ran` 的续跑确认，而**那句提问被 `| tail` 吞掉了**。
★ 正是「六问」里的④**我把失败输出静音了吗**。
交互式提示 + 管道 = 一个看起来像"跑得很慢"的死锁。

#### 已知残留（用户知情并接受）

- 旧 commit 在 GitHub GC 之前**仍可用 SHA 直链访问**。仓库 0 fork / 2 star，
  用户选了「只强制推送，接受短期残留」，没走 Support ticket 也没删库重建。
- 所有 commit SHA 都变了 ⇒ 文档里引用旧 SHA 的地方会对不上号。

---

### B53 · 周额度「非当值号读不到」是**错的** —— 端点一直都在，我没找 — 2026-09-15 ✅

用户第二次追问：「我现在 gemini 第一个号的周额度还是没看到是什么内容」。

#### 我错在哪

B49/B52 里我反复写：「周窗口只有本机 loopback RPC 有，非当值号**结构性**读不到」，
还据此做了 `weekly_seen`（把当值时读到的记下来）、把卡片文案改成「用过才有」。

**那个前提是错的。** 它建立在**一个观测**上 —— `fetchAvailableModels` 每个号只回 2 个桶
（一个 5h、一个 `resetTime=None` 的不限量）—— 而我**从来没去找过第二个端点**。

端点就摆在 `agy` 二进制的 `strings` 里，与本地 RPC 的方法名**并排**：

    本地  /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
    云端  /v1internal:retrieveUserQuotaSummary          ← 按账号，吃 Bearer

实测两个号都 HTTP 200，各自返回自己的完整摘要：

    sam  gemini-weekly 98.78%   gemini-5h 100%
    dbk  gemini-weekly 97.33%   gemini-5h 100%     ← 用户要看的就是这个

这正是 `CLAUDE.md` §6 那条最贵的错：**只看默认响应就断言"接口没有这个能力" = 假阴性。**
上一次是中转站的 `?start_date=`，当时用户说「你多看看」。**这次是用户追问两次才逼出搜索。**

#### 改了什么

- `fetch_quota` 换成 `retrieveUserQuotaSummary`，返回**完整 groups**（与本机 RPC 同形同源）。
- 顺带干掉一个启发式：旧实现按 `(remainingFraction, resetTime)` 分桶、再"成员最多的那组是
  gemini"来猜组名。新端点自带 `displayName` / `bucketId`，**组名不再靠猜**。
- 池里存 `quota_summary`（完整）+ `quota`（旧形状，选号与 CLI 打印仍吃它）。
  后者是前者的**投影**（`quota_by_group`），只算一次 —— 不会分叉成"摘要说 97%、选号按 100% 排"。
- 前端 `toSnapshot` 直译摘要，每个号都有自己的 5h **与周**。
- ★ **`weekly_seen` 整个删除**（活了几小时）。它存在的唯一理由是那个错误前提；
  留着就是「没人渲染的骨架」，而且会变成第二份事实，迟早在某条失败路径上分叉。
  池文件里的残留也一并清掉。
- 卡片文案从「用过才有」退回「这次没读到」——**换了数据源，页面上的话必须跟着换**（§5d）。

#### 闸

`QuotaGroupingKeysOffTheNumbersNotTheNames` 整类重写为 `TheQuotaComesFromTheSummaryEndpoint`，
并**钉住旧启发式不许回来**（两条互相矛盾的分组逻辑并存比只有旧的更糟）。
`test_the_weekly_row_is_never_faked` 的判据也跟着换：窗口现在**全部直译上游**，
所以判据变成"不许写死窗口类型、不许给额度值兜底"——
上游 `remainingFraction` 的缺省恰好是 1.0，「没有」和「满格」仍然只隔一个默认值。

⚠️ `test_fetch_quota_returns_none_not_empty_on_http_error` 用的是**定长切片** `[i:i+1200]`，
换端点后 docstring 变长，真正的 `return` 被切在窗口外 ⇒ 假红。改成切到下一个 `def`。
（§7.-1 第 3 条：定长切片会滑出被测范围 —— 今天又踩一次。）

**测试 1292 → 1294 passed** · `tsc -b` 干净 · `sweep.py` **16**（基线）。

--

### B52 · Gemini「一个 USE，一个当前」—— 排名时拿了两把不同的尺 — 2026-09-15 ✅

用户截图：`USE` 挂在 **dbk** 上，而「当前」是 **sam**。并要求「还存在什么非当值号，一次性根治」。

#### 真因：`min(5h)` 和 `min(5h, 周)` 不是同一个量

    dbk   5h 99.x%   周 **没测到**   ⇒ min = 99.x   ← 拿到 USE
    sam   5h 100%    周 98.78%      ⇒ min = 98.78  ← 而它是当前

`99.x > 98.78`，dbk 胜。**它赢的唯一原因是少测了一个窗口。**

这就是本仓 §8 那条「基准必须用 `tightest`，不能用 `windows[0]` —— 两把不同的尺」
在**账号之间**的形态。拿它们比大小 = **奖励测得少的那个号**。
⚠️ 界面上完全看不出来：两个数都四舍五入成 `99%`，谁也看不见 99.4 和 98.78 的差别。

#### 为什么不能"等数据齐了再比"

周窗口对非当值号是**结构性测不到**的 —— 只有本机 loopback RPC 有，而云端按账号那条
**没有周桶**（2026-09-15 实测：每个号 27 个模型只有 2 个桶，一个 5h、一个不限量）。
所以永远会有号缺窗口，**必须定义清楚在什么基础上比**。

#### 根治：只在所有候选都测到的窗口（交集）上比

本例交集 = `{5h}` ⇒ dbk 99.x vs sam **100** ⇒ sam 胜 ⇒ `最优` 落在当前号上，矛盾消失。

★ **代价是显式的，所以必须说出来**：若 dbk 的周其实只剩 5%，按 5h 比仍会推荐它 ——
  我们**无法知道**。`agyPartial` 因此把"这次少看了哪些窗口"交给 `最优`/`USE` 的 `title`：
  「在各号都读得到的窗口上余量最多。⚠️ 这次比较没算上 周 ——」。
  不说的话 `USE` 会被读成"全面最优"，而事实只是"在都量到的那部分上最优"。
★ 空交集 ⇒ 不给推荐。判据打在 `Number.isFinite` 上：`Math.min()` 空集合返回 `Infinity`，
  不挡会冒出一个"余量 Infinity"的假最优号 —— 比 `null` 更难发现，因为它是个数字，一路不报错。

#### 「非当值号」→「用过才有」

前者说的是**我们的内部状态**，后者说的是**用户能做什么**（§5d：披露要说"做什么"）。
而且它是**会自己消失**的：那个号下次当值时 `agy-quota` 把周额度记进 `weekly_seen`（B49），
此后这一格显示那次的真实读数（带 `~` 标龄）。`title` 里写明了这一点 + 「想立刻看到：切到它、跑一次 agy」。
⇒ 这是一条**有终点**的状态，不是永久免责。

#### 又一条逐字钉实现的闸假红了

`test_unknown_quota_never_gets_recommended` 钉的是字面 `x.pct != null`。
重构成**更强**的两道守卫（`rows.length > 0` + `Number.isFinite`）之后它红了，而语义是变好的。
判据已改成行为。**这是今天第五次栽在同一个形状上** ——
逐字匹配守的是"代码长什么样"，不是"行为对不对"。

#### 同批：§3.7 改正

我把「`B` 只在 `git push` 时 +1」写反了，用户当场纠正「本地更新本地版本就需要 `X.Y.Z+B`」。
已改回全局原意：**`B` 每跑一次 `deploy.sh` +1，发版归 0**，由 `deploy.sh` 自己在 build **之前**做
（放在 build 之后 = 这次装的二进制里还是旧号）。闸另加一条：正本里**不许**留着写错的那版规矩 ——
两句互相矛盾的规矩并存，比只有一句错的更糟。

**测试 1279 → 1290 passed** · `sweep.py` **16**（基线）· 变异验证 4 个全部符合预期。

--

### B51 · 「今日」画成了 30 天 —— **我改了 `p.hours` 的契约，没回头看消费点** — 2026-09-15 ✅

用户截图实报「今日的 token 用量有 bug」：`今日 · **349 格** · 每 2 小时`，
横轴 `00:00 08:00 16:00` 重复了近 30 遍，总 token **21.64B**、较昨日 **↑4130.7%**。

#### 这是 B50 的直接回归，根因一句话

为了「单天按小时」，`p.hours` 从**只有今天**变成**跨 30 天**。
而它的既有消费点全都假设它就是今天：

    bucketsFor 的今日档 → byTwoHours(p.hours)          ⇒ 698 个小时桶两两合并成 349 格
    todayView（菜单栏）  → Object.keys(...hours).sort()  ⇒ 把 30 天当成今天

★★ **改一个字段的含义，等于同时改掉它每一个消费点的正确性** —— 而那些消费点
   一个字都没动，编译也不会报错，因为类型完全没变（都是 `Record<string, Bucket>`）。
   这是本仓「同一个值换了含义、下游全部静默失准」的又一例。

#### 修法：让"哪一天"变成**必填参数**

新增 `hourKeysOf(p, day)`，两个消费点都改成显式传日期。
不是"记得过滤一下"这种口头约定 —— 约定会被忘掉，参数不会。

#### ★ 一条闸在我发现之前就红了

`test_menubar_panel_height::test_heights_match` 当场报「账号 580 vs 今日 587」。
**那条闸是对的**，是我改了契约没回头看。可惜它只覆盖菜单栏，主窗那 349 格没人守 ——
所以这一轮补了 `ChangingTheHoursContractDidNotBreakTheTodayView`（4 条）：
不许整包取用 `p.hours` · `hourKeysOf` 必须收 `day` · 两个消费点都要点名今天。

⚠️ 写闸时自己又踩了两次「探针打偏」：
  ① `Object.keys(p.hours)` 的禁令把 **`hourKeysOf` 自己的实现**判红了 ——
     它正是那个唯一允许整包取键、但当场按 `day` 过滤的地方，得排除；
  ② `.index('if (st.preset === "today")')` 命中的是 **`singleDayOf`** 里那一份，
     不是 `bucketsFor` 里那一份。命中了，但命中错了（§7.-1 ②③）。

**测试 1275 → 1279 passed** · `sweep.py` **16**（基线）· 变异验证 4 个全部符合预期。
像素自证：`今日 · 349 格` → `今日 · 1 格 · 每 2 小时`（当时 01:xx，今天只有 2 个小时桶）。

--

### B50 · 单天（昨天 / 具体某一天）横轴按小时 — 2026-09-15 ✅

用户：「codexbar 的设定，设计单天例如昨天、具体的某一天，横轴按小时进行排序」。

#### 此前为什么做不到

`scan.py` 的逐小时桶**只对今天累积**：`if di == last_di:  # 今日视图按小时,只需当天`。
所以选中昨天只能画出**一根日柱**。这是数据层的限制，不是 UI 的。

#### 为什么不是"所有日期都留小时桶" —— 量过再定

当天实测（7 个平台，单个小时桶 JSON 约 201 B）：

    全部 1095 天 → 快照 1.1 MB 涨到约 **37 MB**，而它**每次扫描都要重写**
    最近 30 天   → 约 +1.0 MB
    最近  7 天   → 约 +0.24 MB

把这三个数摆给用户，他选了**最近 30 天瞬开 + 更早按需重扫**。
⇒ `HOURLY_DAYS = 30`；窗口外那一天走 `scan.py --hours-day YYYY-MM-DD` 现补。

#### ★★★ 正确性判据：小时桶必须加得起来等于日桶

这是唯一能证明"按小时拆"没把量拆丢/拆重的判据 —— 一个把某些行漏进别的小时的 bug，
画出来只是"某根柱子矮一点"，没有任何地方会红。
实测 **5 天 × 7 平台共 35 组，全部逐位相等，0 处不一致**。闸在
`tests/test_single_day_hourly.py::TheHourlyBucketsSumToTheDayBucket`（跑真扫描）。

#### 四处配套

- `hoursOfDay()` 取不到返回 **`null` 而不是空数组** —— 空数组会被画成"这天 24 格全是 0"，
  而真相是"这天没存小时桶"。两者下一步动作完全不同（补扫 vs 什么都不用做）。
- 取不到时**回落到那根真实的日柱**，不画空。
- `run_traffic` 放行 `--hours-day` 并让它**绕过新鲜度合并** —— 它要的正是现有快照里
  没有的东西，命中合并窗口就会静默回一份仍然没有小时桶的快照，
  而"刚点过"和"没点中"在界面上一模一样（本仓在手动 ↻ 上栽过同一形状）。
  日期值单独做**形状校验**（逐位核 `YYYY-MM-DD`），不是"任何字符串都放行"。
- tooltip 判据从「是不是今天」改成「**标签带不带 `T`**」：原来只给今日档特判，
  选中昨天时浮层会印出原始的 `2026-09-14T09`。

#### ⚠️ 未验的那一半（写出来，不装作验过了）

**24 格单天布局没有像素证据。** harness 驱动不了自定义范围选择器（没有「昨天」preset，
只能走日历弹层），所以这一版只验到：数据逐位正确 · 单元闸 + 5 次变异 · `sweep.py` 16（基线）。
我拿"把昨天 24 格搬成今天"的夹具渲染过一次，**那走的是今日档的 2 小时合并路径**
（图上标题自证：「今日 · 12 格 · 每 2 小时」），它证明**整天的轴画得干净**，
**不证明** `hoursOfDay` 的 24 格布局。
★ 要补上这个证据，最省事的做法是加一个「昨天」preset —— 它既是用户点名的场景，
  又让 `?prange=昨天` 这条既有驱动能直接够到。**未做，等用户点头**（那是可见的 UI 改动）。

**测试 1253 → 1263 passed** · `tsc -b` / `cargo check` 干净 · `sweep.py` **16**（基线）·
变异验证 5 个全部符合预期（含"整个删掉"方向与一次防假红）。

--

### B49 · grok 取消 5h 格 + agy 周额度**记得住** — 2026-09-15 ✅

用户两条：「grok 修改，取消 5h 窗口」「agy 明明两个号一个有周额度，一个没有。这就是问题啊」。

#### ① grok 的 5h 格：删掉，不再找体面画法

此前补过**三版**：`visibility:hidden` 空行 → `—  ↻—` → 「无此窗口」。
三版都是在给**一件根本不存在的东西**找一种体面的画法，而每一版都让用户再问一次
「我的 5h 额度呢」。xAI 只回 WEEKLY（`window_minutes = 10080`），那一格永远不会有数。
**最后的答案是不画。** 连 `slotRows` / `winSlots` prop 一起删（不留骨架），菜单栏行同步。

★ 对齐**是像素验的，不是推理的**：条形区由 `flex:1` 留白压在卡片底边 ⇒ 末行对齐，
  所以 grok 的「周」仍与账号卡的「周」在同一条线上。`sweep.py` 36 个总览视图全干净。

#### ② agy 周额度：不是"没有"，是"现在取不到"

先把事实钉死 —— 云端按账号那条**结构上就没有周**（当天实测，`scratch/agy_raw_buckets_*`）：

    sam  27 个模型 → 2 个桶：frac=1 reset=+5.00h (n=23) · frac=1 reset=None 不限量 (n=4)
    dbk  27 个模型 → 2 个桶：同上

**没有任何周桶。** 周窗口只有本机 loopback RPC 有，而那条打的是"第一个应答的 agy 进程"，
那个进程只有一个身份 —— 所以另一个号的周额度**不可能现取**。

但它**当值时读到过**，那个数字是真的。本仓 §7.0b：「这次读不到」不许覆盖「上次读到过」。
把那一格画空，等于把「我们知道，只是现在取不到」降级成「从来不知道」——
两者差着一个真实的数字。这就是用户说的"这就是问题"。

修法：`agy-quota` 在**归属明确**（`pid_email` 在池里唯一命中）时，把这次读到的周桶
记进那个号的 `weekly_seen`；`toSnapshot` 回放它并带上 `seen_at`；
卡片与 **Hero** 都按 `seen_at` **降级显示**（`~93%` + 降不透明度 + title 标龄）。
★ 归属撞了两个或认不出 ⇒ **一个字都不写**。宁可少一格，也不把 A 的数字记到 B 头上。
★ 这不是缓存现值，是**留痕观测**。Hero 那一处是后补的 —— 第一版只改了卡片，
  而 Hero 是整页最显眼的地方，在那里不标龄就是把记忆当现读推给用户。

#### 两条闸被**收窄**（不是放宽）

- `test_the_weekly_row_is_never_faked` 原来是「`toSnapshot` 里不许出现 `weekly`」。
  现在改成三条更强的：周桶只能来自 `weekly_seen` · 必须带 `seen_at` ·
  **数值路径上不许有任何默认值**（`?? 100` / `|| 1`）—— 那正是「没有」变成「满格」的唯一入口。
- `test_agy_schema_contract` 加 `FRONTEND_ONLY = {"seen_at"}`：它是前端合成字段，
  python 侧不产出，不参与 TS↔JSON 契约比对。
- `test_missing_window_says_so` 的 grok 部分整体移到新的 `GrokShowsOnlyItsOwnWindow`，
  并在 docstring 里写明**对齐不靠这条闸保证**（那是 `sweep.py` 的活），
  防止下一个人在这里用静态断言去"证明"像素。

**测试 1251 → 1253 passed** · `tsc -b` 干净 · `sweep.py` **16**（基线）。
像素留档 `~/Downloads/codexbar_{gemini_weekly2,grok_no5h}_20260915.png`。

--

### B48 · 「周额度没刷新、5h 额度丢了」—— 数据一个都没丢，是**同一个 `—` 同时表示三件事** — 2026-09-14 ✅

用户：「为什么我的 gemini 周额度没刷新，我的 grok 五小时额度没刷新？还丢失了？」

#### 实测：什么都没丢

两个 sidecar 当时都是**几秒前**刚写的：

    .agy-quota.json   fetched_at 23:44:56   gemini-weekly = 98.78%   pid_email = user-a@example.com
    .grok-quota.json  fetched_at 23:45:21   period_type = USAGE_PERIOD_TYPE_WEEKLY, window_minutes = 10080

- **gemini 周额度在，98.78%** —— 但它归属于 `pid_email` 指的那个号（本机 loopback RPC
  打的是"第一个应答的 agy 进程"，而这台机器有 4 个常驻 agy 在抢钥匙串）。
  用户看的是**另一张卡**，那张卡结构上拿不到这一格。
- **grok 根本没有 5h 窗口** —— xAI 只回 WEEKLY（`window_minutes = 10080`）。
  那一行之所以存在，只是为了和 codex 卡的两行**对齐**（`winSlots` 来自 codex 池）。

#### 真因：三种完全不同的状态共用一个 `—`

    ① 这个平台结构上没有这个窗口      （grok 的 5h）        → 永远不会有，等也没用
    ② 这个读数属于别的号              （agy 的周）          → 切过去再刷新就能看到
    ③ 这次真的读失败了                                      → 重试/查原因

三者的**下一步动作完全不同**，而界面给的是同一个字符。
★ 更刺眼的是：解释**一直都写着** —— 写在 `title` 里。
  而本仓自己的规矩是「**告警放在眼睛已经在的地方**」，
  只写进悬浮的真话等于没写。用户当然不会去 hover 一个看起来只是"没数"的格子。

修法：把结论写到行上（`无此窗口` / `非当值号` / `这次没读到`），`title` 保留做详情。

★ **条槽必须留着** —— 我一度把它删掉给中文腾地方，`test_missing_window_says_so` 当场红：
  跨卡对齐靠那一行的高度撑着，而 harness 的折行探针对"少了一行"是沉默的。**红得对。**
★ 那条闸本身也改了判据：它原来钉的是字面 `↻—`，于是把 `—` 换成更清楚的中文时**自己红了**，
  而语义是变好的。逐字匹配守的是"代码长什么样"，不是"用户看不看得懂"——
  今天第三次栽在同一个形状上（前两次：`test_the_ui_reads_it`、`test_a_failed_probe_...`）。

#### 同批：`read_logs` 接进日志页（用户点名要）

B46 查出它是孤儿（前端零调用方）。现在 `LogsPage` 的「运行日志」区消费它，
quotad / agy / dawnprobe / autosync 的行终于能到界面上 —— 其中 **dawnprobe 是全仓唯一
会自动花钱的任务**，它的成败此前完全不可见。三处配套：

- **来源由 Rust 侧以 `<job>\t` 前缀给出，不让前端猜**：`dawnprobe.log` 的行既没有
  `[dawnprobe …]` 也没有时间戳，靠猜只会得到「其它」。
- **`quotad.log` 只有 `HH:MM:SS` 没有日期**：按"倒序里时间变大 ⇒ 跨日"往回推，
  逐行标 `inferred`，界面上给 `~` 前缀 —— **推断不许伪装成实测**。
  真的没时间的行（dawnprobe）写 `null`、显示 `—`、排在最后，**不编一个时间**。
- `@unwired(read_logs)` 标记随之摘掉；那条异或闸正是为"接线那天会变红逼人删标记"设的。

#### 两次自己抓自己

1. **`LOGS_TXT` 是个从未定义过的名字** —— 那条 stub 一旦被调用就 `ReferenceError`。
   此前没人发现，因为**前端根本没有调用方**。接线的同一轮补上，否则症状会是：
   stub 抛异常 → 调用方 `.catch` 吞掉 → 服务日志恒空 → 页面照常渲染、零报错 → sweep 报"干净"。
2. **`join('\n')` 写在一个非 raw 的 Python 三引号字符串里** ⇒ Python 先把它变成真换行 ⇒
   JS 字符串字面量当场断行 ⇒ 整个打桩块语法错 ⇒ **所有视图**一起「探针缺失」，
   sweep 从 16 炸到 79。转义在那里被解释两次。改用 `String.fromCharCode(10)`。
   ★ 而我在修好之前做过一次"DOM 确认"，`grep` 到了 quotad/agy/dawnprobe **全部命中** ——
     那是打桩块**自己的源码**就内联在页面里，`--dump-dom` 把它一起 dump 了。
     正确做法是先 `re.sub` 掉 `<script>…</script>` 再数。**断言打在被测的那个东西上了吗**（§7.-1 ③）。

#### 顺带：CHANGELOG 分卷

主文件触到 3000 行阀。「构建里程碑」**整段逐字**移到
`docs/CHANGELOG-archive-2026H1.md`（1778 行）—— 本仓规矩是「不压，分卷」。
主文件 3034 → 1261 行。

**测试 1251 passed** · `tsc -b` / `cargo check` 干净 · `sweep.py` **16**（回到基线）。

--

### B47 · 菜单栏与总览对「当前号」给出两个答案 —— 而 B45 把这个分歧从瞬态变成了永久 — 2026-09-14 ✅

用户截图：同一屏上**菜单栏说当前是 `sam`、主窗总览说当前是 `dbk`**。

#### 谁对

实测 `agy-rotate live --json` → `sam`（`drifted: true`），池里 `live_seen` = `dbk`。
⇒ **菜单栏对，总览错** —— 总览停在池文件里那个已知会撒谎的种子上。

★ 用户当时跑的是 **09:01 的装机版**，而 B45 是 11:59 提交的 ⇒ 那台机器上跑的是修复前的代码。
  所以这张截图本身是 B45 要修的那个 bug 的现场。**但下面这条 B45 修不了，而且是 B45 造成的。**

#### 真正的缺口：两个 webview 各探各的，从不互通

`useAgyPool` 在 `App.tsx` 与 `MenuBar.tsx` **各挂一份**，`enabled` 条件还不一样
（主窗要「总览 + Gemini 档」，菜单栏要「账号 Tab + Gemini 芯片」）。于是两边在
**不同时刻**各跑一次 `agy-rotate live --json` —— 而本机有 **4 个常驻 agy 进程**
在抢同一个钥匙串槽（实测最久的 6 天 23 小时）。两次探测落在不同时刻，本来就会得到不同的号。

`grep -c "listen\|emit" useAgyPool.ts` = **0**，而同仓的 `usePrivacy` / `usePlatformPrefs` /
两个额度 sidecar **全都**走 Tauri 事件广播 —— 因为「两个 webview 的 localStorage 不互通」
这条本仓早就写过。这个 hook 是唯一的例外。

★★★ **而 B45 加的 `verified` 位让分歧从瞬态变成永久**：在那之前两边每次进档都会重读、
  有机会收敛；之后各自锁死在自己那次探测的结果上，永不改口。
  **这是我今天上午亲手引入的回归**，在它随 v1.6.0 发出去之前抓到。
  ⇒ 跨 webview 广播不是锦上添花，是 `verified` 的**必要配套**。

#### 修法

照抄 `usePrivacy` 的范式（事件广播）+ `useQuotaSidecar.adopt` 的采纳规则（按时间戳**单调**）：
任一 webview 现读成功就 `emit("agy-live-changed", {sub, drifted, at})`，另一侧收下并采纳。
★ 收听**不受 `enabled` 约束** —— 那是别人已经取好的数据，收下零成本；受约束就退回
「只有正在看这一档时才收敛」，而用户报的正是"菜单栏在看、总览没在看，于是两边不一样"。
★ 严格 `at >` 采纳，所以自己 emit 又被自己收到是空操作，旧的在途结果也盖不掉新的。

#### 验证

harness 新增 `?agylive=<sub>` 投递一条兄弟 webview 会发的事件。实测 hero 序列：

    qq55(种子) → Asen(本 webview 现读) → **Huo(兄弟广播)**   ← 收敛

⚠️ **局限写在闸里**：harness 只渲染**一个** webview，真正的双 webview 分歧
  **结构上模拟不出来**；能验的是「收到兄弟广播会不会收敛」，即修法本身。
  别把这条闸读成「两个 webview 一致已被自动化覆盖」。

**测试 1245 → 1251 passed** · `tsc -b` 干净 · `sweep.py` 16（基线）·
变异验证 4 个符合预期（只收不发 / 采纳不比时间戳 / 收了不采纳 → 红；`!!`→`Boolean()` → 绿）。
⚠️ 第一版的"良性"变异选错了：改事件名**不是**良性的（harness 那侧把名字写死了，
  改名会真把收发两端断开），红得有理 —— 是我给变异贴错了标签，不是闸假红。

---

### B46 · 一次运行日志体检：查出 4 件，其中最大的一件**四条原始判断里没有一条提到** — 2026-09-14 ✅

---

### 从现况板搬来（2026-09-21，逐字未改）—— 两块已经不是「进行时」的

> `memory.md` 只写进行时。下面两块都不是：前者是**等复现再跑的判别实验**（没人在推进它），
> 后者已发版且闸已做变异验证。按「已发布的整段挪进 CHANGELOG，板上留一行指针」搬过来 ——
> **搬运保真，摘要不保真**，所以一个字没改。

### 0a-bis. `Selected model is at capacity` —— **未复现，根因未定**（2026-09-08）

用户报此错并问「是不是我改完配置导致的」。**排除**：本轮只改了 `proxy/cxp` 的 argv 路由
（diff 里 model / service_tier 一个都没碰），两个 config 的 mtime（11:39 / 12:03）都早于第一次编辑；
额度链正常（plus4/6/7 今天 429 六次全部被代理正确接住换号，现跑 Pro1 持续 200）。
**当场用现状配置真跑 `codex exec` —— 成功**，所以是间歇性的。

两个都能解释同样证据的假说，**别当已知**：
- H1 **fast 通道容量** —— `rotateproxy.config.toml:7` 有 `service_tier = "fast"`（base 是 `"default"`），
  而 `gpt-6-astra` 的 tier 定义只有 `{"id":"priority","name":"Fast","description":"2x speed, increased usage"}`。
  ⚠️ 这行**不在 09-06 备份里**（那份只有 provider/model/effort=high），是之后被加的，非本轮所为。
- H2 **gpt-6-astra 整体容量** —— 模型刚发布。

**判别实验（下次复现时，同一时刻跑）**：
`codex exec -c service_tier='"default"' --skip-git-repo-check 'reply with exactly OK'`
成功 ⇒ H1（改 `rotateproxy.config.toml:7` 为 `"default"`）；也失败 ⇒ H2（换 `gpt-5.6-sol`/`gpt-5.5`）。
**未替用户改** —— `fast` 是「2x 速度 + 更高用量」，关掉是有代价的取舍。

