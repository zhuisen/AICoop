#!/usr/bin/env bash
# Build, sign, deploy AICoop (formerly CodexBar) to /Applications.
# Auto-uses "CodexBar Self-Signed" if available (run setup-signing.sh once first).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="CodexBar Self-Signed"
APP="/Applications/AICoop.app"
BUILD="$ROOT/src-tauri/target/release/bundle/macos/AICoop.app"
# 改名前的安装位置（2026-10-21 CodexBar → AICoop）。同 bundle id，留着会和新包抢单实例锁。
LEGACY_APP="/Applications/CodexBar.app"

cd "$ROOT"

# ★ 把仓库根烧进二进制。GUI app 不继承 shell 环境,不能指望运行期 env(见 lib.rs 的 store_dir)。
#   别人 clone 到任何路径,跑一次这个脚本就能用。
export CODEXBAR_STORE_DEFAULT="$(cd "$ROOT/.." && pwd)"
echo "==> store dir: $CODEXBAR_STORE_DEFAULT"

# 全新 clone 没有 node_modules,直接 tauri build 会挂。有 lockfile 用 ci(可复现),否则 install。
if [ ! -d "$ROOT/node_modules" ]; then
    echo "==> installing npm deps (first run)…"
    if [ -f "$ROOT/package-lock.json" ]; then npm ci; else npm install; fi
fi

# ★ 构建号 `B` 不在这里维护了 —— `src-tauri/build.rs` 从 git 现算
#   （发版后本地就是 release ⇒ B=0 ⇒ 显示纯 `vX.Y.Z`；改过才有 `+B`）。
#   见 CLAUDE.md §3.7。这里刻意什么都不做，别把计数器加回来。

echo "==> building…"
# ★ 每次部署都让 build.rs 重跑（全方面评审 §11）：它原来只在 `.git/HEAD` / `refs` 变时重跑 ——
#   干净时构建过一次（B=0 进了缓存），之后改文件再构建，cargo 只重编 crate、不重跑 build.rs，产物照样报 B=0。
export CODEXBAR_BUILD_STAMP="$(date +%s)-$$"
# ★ 完整日志落盘，失败时打最后 40 行 + 路径（原来 `| tail -3` 把编译报错截得只剩「error: could not compile」）。
_buildlog="$ROOT/../scratch/deploy-build.log"
mkdir -p "$(dirname "$_buildlog")"
if ! npx tauri build --bundles app > "$_buildlog" 2>&1; then
    tail -40 "$_buildlog"
    echo "🛑 构建失败 —— 完整日志：$_buildlog"
    exit 1
fi
tail -3 "$_buildlog"

# ★ 必须**优雅**退出,不能直接 SIGKILL。窗口尺寸/位置由 tauri-plugin-window-state 保存,而它只在
#   `CloseRequested` / `RunEvent::Exit` 时写盘 —— `pkill -9` 不给退出处理任何机会,于是
#   「调好高度 → 跑一次更新 → 尺寸又回默认」,正是这个持久化要解决的问题本身。
# ★ 预检放在停旧实例**之前**（四方评审 2026-10-21 Opus M8）：等到装完才发现旧包移不走，旧实例已被杀、新包没签名也没启动。
if [ -d "$LEGACY_APP" ]; then
    _arch="$HOME/archive/codex-account-rotator/legacy-codexbar-app-$(date +%Y%m%d)"
    if ! mkdir -p "$_arch" || [ ! -w "$(dirname "$LEGACY_APP")" ] || [ ! -w "$_arch" ]; then
        echo "🛑 旧的 $LEGACY_APP 移不走（${_arch} 建不了或没有写权限）—— 它和新包同 bundle id，会抢单实例锁。什么都没动，处理后重跑。"
        exit 1
    fi
fi

echo "==> stopping old instance (graceful)"
# ★ 按**可执行文件路径**找进程（新旧两个安装位置），强杀也只杀这些 PID —— 不用宽泛的 `pkill -f`。
_ours() { ps -Ao pid=,comm= | awk -v a="$APP/Contents/MacOS/codexbar" -v b="$LEGACY_APP/Contents/MacOS/codexbar" '$2 == a || $2 == b {print $1}'; }
# ★ 只在真有进程时才发 quit，且按 bundle id 发、带超时（四方评审 Opus M4）：
#   按 app 名发时，第一次部署（/Applications 里还没有 AICoop）会弹「AICoop 在哪里？」对话框把脚本卡住；
#   app 卡死时 Apple Event 默认要等 2 分钟。新旧两个名字共用同一个 bundle id，发一次就够。
if [ -n "$(_ours)" ]; then
    osascript -e 'with timeout of 5 seconds' -e 'tell application id "com.doushutangmu.codexbar" to quit' -e 'end timeout' 2>/dev/null || true
fi
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -z "$(_ours)" ] && break
    sleep 0.3
done
# 兜底:优雅退出没成功(比如 app 卡住)才强杀,此时状态确实会丢,但总比装不上强。
_left="$(_ours)"
if [ -n "$_left" ]; then
    echo "    (graceful quit timed out — force killing pid $_left; window geometry may reset)"
    kill -9 $_left 2>/dev/null || true
    sleep 1
fi

echo "==> deploying to $APP"
rm -rf "$APP"
cp -R "$BUILD" "$APP"
# 改名后旧包移进归档（不删：它是回滚点）。不移走的话旧的开机自启项会先把它拉起来、抢走单实例锁。
# ★ 同一天跑两次时目标已存在：`mv` 会失败（或把它塞进已有的包里）—— 换一个不撞的名字，失败就停（四方评审 Opus M3）。
# ★ 归档后从 LaunchServices 注销：同 bundle id 的另一份留在登记里，`open -b` / 开机恢复可能拉起它。
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
if [ -d "$LEGACY_APP" ]; then
    _dst="$_arch/CodexBar.app"
    [ -e "$_dst" ] && _dst="$_arch/CodexBar-$(date +%H%M%S).app"
    if mv "$LEGACY_APP" "$_dst"; then
        echo "==> moved old $LEGACY_APP → $_dst"
        "$LSREG" -u "$_dst" 2>/dev/null || true
    else
        echo "🛑 没能把旧的 $LEGACY_APP 移走 —— 它和新包同 bundle id，会抢单实例锁。请手动移走后重跑。"
        exit 1
    fi
fi
# 构建树里改名前的那份旧产物（同 bundle id，可重建）：删掉，免得被 LaunchServices 当成可启动的副本
_old_build="$ROOT/src-tauri/target/release/bundle/macos/CodexBar.app"
if [ -d "$_old_build" ]; then
    "$LSREG" -u "$_old_build" 2>/dev/null || true
    rm -rf "$_old_build"
fi

# ⚠️ 不用 `grep -q`：它匹配到就退出，`security` 若还在写会吃 SIGPIPE，pipefail 让整个条件
#   变成**假** —— 静默落到下面 ad-hoc 那一支，下次启动重新弹 TCC 授权（同 `_running` 那条竞态）。
if security find-identity -p codesigning 2>/dev/null | grep -F "$IDENTITY" >/dev/null; then
    echo "==> signing with '$IDENTITY'"
    codesign --force --deep --sign "$IDENTITY" "$APP"
    codesign --verify --strict "$APP"
else
    echo "⚠️  '$IDENTITY' not found — using ad-hoc (run setup-signing.sh once to fix)"
fi

echo "==> launching"
open "$APP"

# ★★★ **核实跑起来的真的是刚装的这一份**（2026-09-21 补，事故驱动）。
#
#   本机有 **3 个 bundle 共用 `com.doushutangmu.codexbar`**：/Applications、构建树
#   `src-tauri/target/release/bundle/macos/`、以及 `~/archive/...` 里的快照备份。
#   单实例闸是 flock（CLAUDE.md §5 / .claude/rules/ui.md），谁先抢到锁谁活，
#   **后来者判 `HeldByOther` 后静默退出** —— 那是设计，不是缺陷。
#
#   ⚠️ 但两件事叠在一起就成了陷阱：archive 里那份 **v1.4.1（2026-09-08）** 抢着锁，
#   于是 `open /Applications/CodexBar.app` **每次都无声无息地什么都没发生**，
#   用户对着一个 13 天前的构建看了很久，症状是「菜单栏 AI 用量变成全量展示」
#   ——那恰好是 v1.4.1 之后三个 commit 才修的东西。
#   deploy 全程报「✓ deployed」，因为它只管装、从不看**谁在跑**。
#
#   ★ 同族判据：本仓已有的「常驻服务代码 ✓ 均为最新」比的是进程启动时刻 vs 源码 mtime。
#     这里比的是**可执行文件路径** —— 同一个问题的另一面：装好了 ≠ 跑起来了。
sleep 3
# ⚠️ **awk 里不许 `exit`，管道尾巴上也不许 `head`**（2026-09-23 实测）。本脚本开着
#   `set -euo pipefail`：awk 读到第一行就退出会关掉管道，`ps` 还在写就吃 SIGPIPE（exit 141），
#   pipefail 把它算成整条管道失败，`set -e` 随即**静默杀掉整个 deploy.sh** ——
#   后面的版本号与 B≠0 告警一行都不打，而看上去和成功一模一样（新包其实已经装好并启动了）。
#   是竞态：`ps` 写得比 awk 退出快就不触发，所以时好时坏。闸：tests/test_deploy_script_sigpipe.py。
_running="$(ps -Ao pid=,comm= | awk '$2 ~ /codexbar$/ && !f {print $1; f=1}')"
# ★ 后验失败要以非 0 退出（全方面评审 §11）：原来只打一行警告、照样 exit 0，调用方（与我）读到的是「部署成功」。
#   放到最后才退：版本号与 B≠0 告警照常打完。
_verify_fail=0
if [ -z "$_running" ]; then
    _verify_fail=1
    echo "⚠️  启动后没看到 codexbar 进程 —— 它可能被单实例闸挡住了，或者崩了。"
elif [ "$(ps -o comm= -p "$_running")" != "$APP/Contents/MacOS/codexbar" ]; then
    _verify_fail=1
    echo "🛑 **跑起来的不是刚装的那一份！**"
    echo "   期望: $APP/Contents/MacOS/codexbar"
    echo "   实际: $(ps -o comm= -p "$_running")  (pid $_running)"
    echo "   原因：同 bundle id 的另一个副本先抢到了单实例锁，新装的这份静默退出了。"
    echo "   处理：先退掉上面那个进程（kill ${_running}），"
    echo "        再重新 open '$APP'；并考虑把那个陈旧副本移走/改名。"
fi

# ★★★ 把这次烤进产物的版本号**当场打出来**（2026-09-17 补）。
#
#   起因：v1.6.1 发版后用户在界面上看到 `v1.6.1+10`。产物没错 —— 它确实是在
#   `git tag` **之前 38 秒**、从一个脏工作区构建的，`B` 从 git 现算就是 10。
#   错的是顺序（见 CLAUDE.md §3）。但真正让它难发现的是：
#   **deploy 全程不说自己烤了什么版本**，于是"版本对不对"要等用户打开界面才知道。
#   ★ 一个在动作发生那一刻就能看见的事实，不该留到事后由人去界面上发现。
# ★ 用脚本开头就算好的 `$ROOT`（绝对路径）—— 此处已经 `cd "$ROOT"` 过，
#   再拿 `$0` 推相对路径会解析失败，实测当场把版本打成 `?`。
VER=$(node -p "require('$ROOT/src-tauri/tauri.conf.json').version" 2>/dev/null || echo "?")
TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
# ★ 最近的 tag 是这个版本的预发布 ⇒ 版本带上预发布段（同 build.rs::prerelease），别说成「就是 release vX.Y.Z」
case "$TAG" in "v${VER}-"*) VER="${TAG#v}" ;; esac
if [ -n "$TAG" ]; then
    B=$(git rev-list --count "$TAG..HEAD" 2>/dev/null || echo 0)
    [ -n "$(git status --porcelain 2>/dev/null)" ] && B=$((B + 1))
else
    B=0
fi
# ★ 核二进制里实际烤进去的 B（build.rs 写在 OUT_DIR/build_number，取最新那份）。对不上 = build.rs 没重跑、
#   产物报的版本与工作区不符 —— 界面会说假话，所以算部署失败。
_baked_f=""
for _f in "$ROOT"/src-tauri/target/release/build/codexbar-*/out/build_number; do   # 取最新的一份（不走管道：pipefail 下提前退出的管道尾会 SIGPIPE）
    [ -f "$_f" ] || continue
    if [ -z "$_baked_f" ] || [ "$_f" -nt "$_baked_f" ]; then _baked_f="$_f"; fi
done
if [ -z "$_baked_f" ]; then
    echo "⚠️  找不到 build.rs 写的 build_number，核不了二进制里的 B"
elif [ "$(cat "$_baked_f")" != "$B" ]; then
    echo "🛑 二进制里烤的 B=$(cat "$_baked_f")，工作区现算 B=${B} —— build.rs 没重跑（界面上的版本是旧的），或构建途中改了文件（常见：\`Cargo.lock\`）"
    _verify_fail=1
fi
if [ "$B" = "0" ]; then
    echo "✓ deployed — v${VER}（B=0：你跑的这份**就是** release）"
else
    echo "✓ deployed — v${VER}+${B}"
    echo "   ⚠️  B=${B} ≠ 0：这份产物**不是** release。距 ${TAG:-?} 有 $((B)) 个改动。"
    # ★★ 把 B 拆成「commit 数」与「脏文件」两项分别报（2026-09-19 加）。
    #    此前只笼统说「发版时请在 git tag 之后再跑」—— 而 v1.7.0 那次 tag 顺序**是对的**，
    #    真因是 `Cargo.lock` 被构建改了却没进 commit（版本号写进它自己的 package 条目，
    #    而它只在**构建之后**才变）。一条指向错误原因的告警比没有告警更糟：
    #    它让人去检查一个本来就对的东西。所以这里必须说**是哪一项**、脏的是**哪些文件**。
    _ahead="$(git -C "$ROOT" rev-list --count "${TAG:-HEAD}"..HEAD 2>/dev/null || echo '?')"
    _dirty="$(git -C "$ROOT" status --porcelain 2>/dev/null)"
    echo "      · 距 tag 的 commit 数：${_ahead}"
    if [ -n "$_dirty" ]; then
        echo "      · 脏工作区（+1）——以下文件未提交："
        printf '%s\n' "$_dirty" | sed 's/^/          /'
        echo "        ↳ 常见元凶：\`Cargo.lock\`（版本号改完、**构建之后**才会变）。"
        echo "          把它并进 release commit 再 \`git tag -f\`，然后重跑本脚本。"
    else
        echo "      · 工作区干净 ⇒ B 全部来自 commit 数：在 \`git tag\` **之后**再跑本脚本（CLAUDE.md §3 4.5）。"
    fi
fi
if [ "$_verify_fail" != "0" ]; then
    echo "🛑 部署后验失败（见上）—— 新包已装好，但跑起来的不是它。"
    exit 1
fi
