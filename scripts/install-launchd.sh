#!/usr/bin/env bash
# Generate + (re)load the seven codex-rotate launchd agents.
#
# Generated rather than committed as files because every plist embeds absolute paths ($HOME, the repo
# location, the interpreter) — a committed copy would be wrong on any other machine and would drift
# silently on this one.
#
# ★ The interpreter is resolved and PINNED, never left to a shebang. launchd's default PATH is only
# /usr/bin:/bin:/usr/sbin:/sbin, so `#!/usr/bin/env python3` lands on macOS's /usr/bin/python3, which
# links LibreSSL 2.8.3 — and Cloudflare fingerprints that TLS ClientHello and answers 403 to
# GET /backend-api/codex/usage. Measured 2026-08-01, single variable, 3 trials each, identical token /
# headers / IP / minute:
#     /usr/bin/python3        LibreSSL 2.8.3   -> 403 403 403
#     /opt/homebrew/bin/py3   OpenSSL  3.6.3   -> 200 200 200
# Every agent was silently failing that way, so the pool's quota only ever came from stale rollout
# telemetry (observed: UI showed 100% for an account really at 16%).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# `--render DIR`：只把 plist 写进 DIR，不碰 launchctl、不动 ~/Library/LaunchAgents。
#   给 `connector.py` 比对「装着的」与「本脚本会生成的」是否一致（samchen #4 ②：keepalive 还是旧的 04:30 版、
#   agydawn / otel 没装、已退役的 refreshquota 还在）。判据是内容，不是「有没有加载」。
RENDER=""
if [ "${1:-}" = "--render" ]; then
    RENDER="${2:?--render 需要一个目录}"
fi

# ★★★ **数据目录必须显式写进每一份 plist**（2026-09-10 四方评审抓到 critical）。
#
#    launchd 起的进程**不继承你的 shell 环境**,所以"用户 export 一下"在这里是无效的 ——
#    plist 里没写,子进程就只能按 `__file__` 去猜,猜出来的是**安装目录**。
#    从 `deploy.sh` 装的 macOS 机器上看不出问题:那条路径会把仓库路径烧进
#    `CODEXBAR_STORE_DEFAULT`,于是 app 的 `data_dir()` 恰好也等于仓库 —— 两边碰巧相同。
#    CI 出的安装包没有这个烧录值,app 落到 `app_data_dir()`,而 launchd 起的代理仍在
#    安装目录 ⇒ **route.local.json / state.json / auth/ 全部分叉**,
#    并且 `.refresh.lock` / `.state.lock` 落在两个不同路径上 = **等于没有锁**,
#    `codex-rotate` 与代理会同时刷同一个号的 refresh_token(一次性凭证)。
#
#    优先级与 Rust `store_dir()` **逐条对齐**(lib.rs:85)。顺序不一致就是换个地方分叉。
STORE="${CODEX_ROTATE_STORE:-${CODEXBAR_STORE:-$REPO}}"
# ★ app 通过 `spawn_cmd` 给每个子进程都设了 `CODEX_ROTATE_STORE`,所以由 app 调起本脚本时
#   上面第一条就命中;手动跑则退回仓库目录 —— 与改动前逐字相同。
if [ ! -d "$STORE" ]; then
    echo "⛔ 数据目录不存在:$STORE" >&2
    echo "   （从 app 里装会自动带上正确的目录;手动装请先建好,或 CODEX_ROTATE_STORE=<dir> 重跑）" >&2
    exit 78
fi
echo "==> 数据目录: $STORE"

AGENTS="${RENDER:-$HOME/Library/LaunchAgents}"
PREFIX="com.doushutangmu.codex-rotate"
UID_NUM="$(id -u)"

# --- resolve an interpreter with a modern TLS stack -------------------------------------------------
PY="${CODEX_ROTATE_PYTHON:-}"
if [ -z "$PY" ]; then
    for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
        [ -x "$cand" ] || continue
        if ! "$cand" -c 'import ssl,sys; sys.exit(0 if ssl.OPENSSL_VERSION.startswith("OpenSSL") else 1)' 2>/dev/null; then
            continue
        fi
        PY="$cand"; break
    done
fi
if [ -z "$PY" ]; then
    echo "✗ no python3 with an OpenSSL build found — LibreSSL gets 403 from the usage API." >&2
    echo "  install one (brew install python3) or set CODEX_ROTATE_PYTHON=/path/to/python3" >&2
    exit 1
fi
echo "==> interpreter: $PY  ($("$PY" -c 'import ssl;print(ssl.OPENSSL_VERSION)'))"

mkdir -p "$AGENTS"

# Log paths are NOT uniformly "$REPO/<name>.log": the proxy writes beside its own source, and CodexBar's
# log page reads these exact literals (src-tauri/src/lib.rs read_logs). Keep the two in sync.
log_path() {
    case "$1" in
        proxy) echo "$REPO/proxy/proxy.log" ;;
        *)     echo "$REPO/$1.log" ;;
    esac
}

# ★ 每个任务额外的环境变量(XML 片段)。`emit` 用完即清 —— 忘了清会把上一个任务的
#   变量带给下一个,而那种串味不会报错。
ENV_EXTRA=""

# ★ 一个服务装不上**不许挡住其余的**（`set -e` 会让脚本停在第一个失败上，后面的连 plist 都不写）。
#   每个 `emit … || FAILED=…` 收集失败，最后统一报错并以非 0 退出 —— 既不装一半，也不假装成功。
FAILED=""

emit() {  # emit <name> <body-xml> <arg…>
    local name="$1" body="$2"; shift 2
    local out="$AGENTS/$PREFIX.$name.plist"
    local logf; logf="$(log_path "$name")"
    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        echo '<plist version="1.0"><dict>'
        echo "  <key>Label</key><string>$PREFIX.$name</string>"
        echo '  <key>ProgramArguments</key><array>'
        printf '    <string>%s</string>\n' "$PY" "$@"
        echo '  </array>'
        # ★★ **每个任务都带,一个不漏。** 以前只有 proxy 有 EnvironmentVariables,
        #    而 quotad / autosync / dawnprobe 同样会写 state.json 和 auth/ ——
        #    漏掉任何一个,它就在另一个目录上单干。
        echo '  <key>EnvironmentVariables</key><dict>'
        echo "    <key>CODEX_ROTATE_STORE</key><string>$STORE</string>"
        [ -n "$ENV_EXTRA" ] && echo "$ENV_EXTRA"
        echo '  </dict>'
        ENV_EXTRA=""
        echo "$body"
        echo "  <key>StandardOutPath</key><string>$logf</string>"
        echo "  <key>StandardErrorPath</key><string>$logf</string>"
        echo '</dict></plist>'
    } > "$out" || return 1
    plutil -lint "$out" >/dev/null || return 1
    [ -n "$RENDER" ] && return 0

    # ★★ **`bootout` 是异步的** —— 它返回时任务往往还挂在 domain 里，紧跟的
    #    `bootstrap` 就撞上 `Bootstrap failed: 5: Input/output error`。
    #    2026-09-10 实测:quotad 这样失败，而 `set -e` 让脚本**停在那一行** ——
    #    该任务已经 bootout、还没 bootstrap 回来，于是**服务就那么停着**，
    #    后面的 proxy / dawnprobe 连 plist 都没重写。
    #    「装了一半」和「装好了」在终端上只差最后几行输出，而守护进程是真的没了。
    launchctl bootout "gui/$UID_NUM/$PREFIX.$name" 2>/dev/null || true
    local i=0
    while [ "$i" -lt 50 ] && launchctl print "gui/$UID_NUM/$PREFIX.$name" >/dev/null 2>&1; do
        sleep 0.1; i=$((i + 1))
    done
    # ★ 服务被 `launchctl disable` 过就会 `Bootstrap failed: 5: Input/output error`，而 `disable`
    #   **持久化**（重启也不消）。2026-09-23 一次清理对 ~79 个 LaunchAgent 做过。先 `enable`：
    #   只动我们自己这一个 label，且是可逆的；本来就 enabled 时是空操作。
    launchctl enable "gui/$UID_NUM/$PREFIX.$name" 2>/dev/null || true
    local tries=0 rc=1
    while [ "$tries" -lt 5 ]; do
        if launchctl bootstrap "gui/$UID_NUM" "$out" 2>/dev/null; then rc=0; break; fi
        tries=$((tries + 1)); sleep 0.3
    done
    # ★ 判据是**真的加载上了**，不是 bootstrap 的退出码 —— 后者在这条路径上不可靠。
    if ! launchctl print "gui/$UID_NUM/$PREFIX.$name" >/dev/null 2>&1; then
        # ★ `${rc}` 不是 `$rc` —— 后面紧跟全角逗号。bash 3.2 在 UTF-8 下把 `，` 的首字节吞进变量名，
        #   `set -u` 报 `rc\xef: unbound variable`，真错误被换成乱码，stderr 里的非法字节还会让
        #   connector.py 抛 UnicodeDecodeError（2026-09-26）。闸：tests/test_shell_var_before_multibyte.py。
        echo "  ⛔ $name 装不上（bootstrap rc=${rc}，重试 ${tries} 次后仍未加载）" >&2
        echo "     手动:launchctl bootstrap gui/$UID_NUM $out" >&2
        return 1
    fi
    echo "  ✓ $name$([ "$tries" -gt 0 ] && echo "（重试 $tries 次）")"
}

ROT="$REPO/codex-rotate"

emit autosync \
    "  <key>RunAtLoad</key><true/>
  <key>WatchPaths</key><array><string>$HOME/.codex/auth.json</string></array>" \
    "$ROT" sync || FAILED="$FAILED autosync"

# ★★ refreshquota(07:00) 2026-08-29 取消后不再生成：quotad 已经定时全池扫（`tick_usage` → `refresh-all`），是真冗余。
# ★★ keepalive 2026-08-29 取消、**2026-10-22 按用户要求恢复**（「#5 也去处理」）。取消时把续期交给 proxy 的
#    `_slot_token`，但它只续**挑得中**的号：长期不被挑中的号（停了轮换的、排在后面的）token 到期后**不会自愈**
#    （2026-08-29 一个 Plus 号就这样断了 11 天，额度扫描每 300s 静默失败）。
#    · 形态：**每小时拉起一次**，`--idle-window` 让它只在本机 22:00–08:00 干活（白天一拉起就退出，不读 state、不联网）。
#      上一轮已过 20h（合盖过夜，夜里的触发合并到醒来那一次）⇒ 窗口外也补跑一轮（samchen #4 ①）。
#      ★ 不用 `StartCalendarInterval` 写死 04:30：这个任务上次就是被本脚本以外的东西改写 plist、丢掉日历键、
#      `runs = 0` 一次没跑过；按小时拉 + 命令自己判，丢一次也只是晚一小时（同 dawnprobe 的形态）。
#    · 动的凭证：只刷**非活跃**号里 access token 48h 内到期的（`_refresh_slot`，持 `.refresh.lock`，refresh_token 一次性轮换）；
#      活跃号**永不刷**（codex 自己的刷新器持有它）；已判死的号跳过。刷完按 07-16 选项② 检查 `~/.codex/auth.json` 那个号
#      还活着没有，死了 / 快过期且 codex 没在跑才换一个健康号进去（`_ensure_live_healthy`）。
emit keepalive \
    '  <key>StartInterval</key><integer>3600</integer>' \
    "$ROT" keepalive 48 --idle-window || FAILED="$FAILED keepalive"

emit quotad \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>' \
    "$REPO/daemon/quota_daemon.py" || FAILED="$FAILED quotad"

# ★ `CRP_PORT` 现在走 `ENV_EXTRA` —— `emit` 统一生成唯一的一个 EnvironmentVariables 字典。
#   在 body 里再写一个同名 key 会得到重复键的 plist,`plutil -lint` 未必拦得住。
ENV_EXTRA='    <key>CRP_PORT</key><string>8011</string>'
emit proxy \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>' \
    "$REPO/proxy/proxy.py" || FAILED="$FAILED proxy"

# ★★ 每日清晨探针(06:00)。给 **Plus 号**各发一次最小计费补全,把 5h 窗口**锚定**上 ——
#    没被用过的 5h 窗口服务端每轮都回「此刻 + 整窗」,倒计时永远停在 ~4h55m,那 5 小时等于没在走。
#
#    ⚠️ **这是本仓唯一一个会自动花钱的定时器**,所以命令侧有三条护栏(见 `cmd_dawn_probe`):
#      ① `enabled` 默认**假** —— 装了这个 plist 也不会自己跑,要 `dawn-probe --enable`;
#      ② **当天幂等** —— app 内还有一条补跑路径,两条都调它,没有幂等就是双重计费;
#      ③ 每次运行落痕到 `state.json` 的 `dawn_probe`,UI 读它。
#
#    ★★ **为什么还要 app 内补跑**:本项目的日历定时有前科 —— keepalive/refreshquota 的
#      `StartCalendarInterval` 曾被本脚本以外的东西改写掉,`runs = 0`、**从未运行过**,
#      而没有任何一处会为此报红(改写者至今未查明)。所以这个 plist**不能是唯一的触发路径**。
#      发现定时不跑时先比对 plist 形态(单行 vs 逐行美化 + 空 EnvironmentVariables),别先怀疑脚本。
#    ★★ 2026-10-15 起**每 60s 拉起一次**，不再是固定的 06:00 日历时刻：用户要能在界面上选时间、
#      且在所选时刻起 3 分钟内随机。时刻写死在 plist 里就得在界面上改 plist —— 本脚本是 plist 的唯一生成者。
#      所以由命令自己判断到没到点（`dawn_sched.py`），空转一次约 60ms，同 `autosync` 的形态。
emit dawnprobe \
    '  <key>StartInterval</key><integer>60</integer>' \
    "$ROT" dawn-probe --tick || FAILED="$FAILED dawnprobe"

# ★★ Gemini（agy）定时探针。与上面同一套护栏（默认关、先占天再探、落痕），见 `agy-rotate::cmd_dawn_probe`。
#    ★ 必须喂 `AGY_POOL_STORE`：agy 池按 `__file__` 推目录，不吃 `CODEX_ROTATE_STORE`（credentials.md）。
ENV_EXTRA="    <key>AGY_POOL_STORE</key><string>$STORE</string>"
emit agydawn \
    '  <key>StartInterval</key><integer>60</integer>' \
    "$REPO/agy-rotate" dawn-probe --tick || FAILED="$FAILED agydawn"

# ★ Claude Code OTel 接收端（「Claude 实测速度」开关的另一半，2026-10-19 起正式服务）。
#    只听 127.0.0.1:4318、只写 `<store>/traffic/otel-ledger/`；不联网、不读凭证。
#    ★ `--dir` 显式给 store 下的目录：`.dmg` 布局里 `$REPO` 是运行时副本，按 `__file__` 推会写进副本。
#    ★ 端口被占时它写明原因进 `.status.json` 并退出非 0；`ThrottleInterval` 让 KeepAlive 别每 10s 拉一次。
#    ⚠️ 2026-10-18 试运行时手写过 `com.doushutangmu.claude-otel`（同一端口）。两份同时在 ⇒ 后起的那份起不来。
emit otel \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>' \
    "$REPO/traffic/otel_receiver.py" --port 4318 --dir "$STORE/traffic/otel-ledger" || FAILED="$FAILED otel"

[ -n "$RENDER" ] && exit 0

# ★ 已退役的任务（不再生成）若还装着，卸掉 —— 只认这份清单里的 label。
#   refreshquota 2026-08-29 取消（见上）；老机器上它还在每天 07:00 跑（samchen #4 ②）。
#   清单与 `connector.py::RETIRED_SERVICES` 一致（闸 tests/test_launchd_drift.py）。
for n in refreshquota; do
    if launchctl print "gui/$UID_NUM/$PREFIX.$n" >/dev/null 2>&1 || [ -f "$AGENTS/$PREFIX.$n.plist" ]; then
        launchctl bootout "gui/$UID_NUM/$PREFIX.$n" 2>/dev/null || true
        rm -f "$AGENTS/$PREFIX.$n.plist"
        echo "  ✗ 已卸掉退役的 $n"
    fi
done

echo
echo "==> loaded:"
for n in autosync keepalive quotad proxy dawnprobe agydawn otel; do
    printf '  %-13s %s\n' "$n" \
        "$(launchctl print "gui/$UID_NUM/$PREFIX.$n" 2>/dev/null | awk '/^\tstate = /&&!f{print $3; f=1}' || echo '?')"
done

if [ -n "$FAILED" ]; then
    echo >&2
    echo "⛔ 这些服务没装上:${FAILED}（其余已装好）。原因见上面各条 ⛔ 输出。" >&2
    exit 1
fi
