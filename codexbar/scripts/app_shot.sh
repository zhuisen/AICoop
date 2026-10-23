#!/usr/bin/env bash
# 截已装并在运行的 AICoop 主窗口（真 WKWebView，不是 harness 的 Chrome），输出路径打印到 stdout。
#   bash codexbar/scripts/app_shot.sh [输出文件]   默认 ~/Downloads/aicoop_screenshots_<日期>_realwindow/main_<时间>.png
# 前提：运行它的终端有「屏幕录制」权限（Ghostty 2026-10-02 已授权）；Claude Code 里要在沙箱外执行（沙箱拿不到显示器）。
# 只按窗口 id 截这一个窗口，不截全屏。截的是 App 当前停留的页面，脚本不点导航。
# 后台 / 被遮挡的窗口 WebView 不绘制（截出来一片深灰）⇒ 先切到前台（会抢一下焦点）。
set -euo pipefail
OUT="${1:-$HOME/Downloads/aicoop_screenshots_$(date +%Y%m%d)_realwindow/main_$(date +%H%M%S).png}"
mkdir -p "$(dirname "$OUT")"
osascript -e 'tell application "AICoop" to activate' >/dev/null 2>&1 || true
sleep 1.5
ID=$(osascript -l JavaScript -e '
ObjC.import("CoreGraphics");
const list = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(0, 0)));
const main = list.filter((w) => (w.kCGWindowOwnerName || "") === "AICoop" && w.kCGWindowIsOnscreen && w.kCGWindowLayer === 0 && w.kCGWindowBounds.Height > 400)
  .sort((a, b) => b.kCGWindowBounds.Width * b.kCGWindowBounds.Height - a.kCGWindowBounds.Width * a.kCGWindowBounds.Height)[0];
console.log(main ? main.kCGWindowNumber : "");' 2>&1)
[ -n "$ID" ] || { echo "❌ 屏幕上没有 AICoop 主窗口（没开 / 在别的桌面空间 / 已最小化）" >&2; exit 1; }
screencapture -x -o -l "$ID" "$OUT" || { echo "❌ 截图失败：多半是终端没有「屏幕录制」权限，或在沙箱里跑" >&2; exit 1; }
echo "$OUT"
