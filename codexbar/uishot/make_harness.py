#!/usr/bin/env python3
"""
生成 UI 验证 harness(CLAUDE.md §4 的方法固化版)。

思路:**加载和 app 完全同一份 bundle**,只在它之前注入一个 `window.__TAURI_INTERNALS__` 打桩,
所以量到的是真实构建产物的像素,而不是另写一遍组件的近似。

两条安全线:
- `read_state` 只返回**脱敏空桩**。真实 `state.json` 含 OAuth token,**绝不放进 HTTP 伺服目录**。
- 流量快照是 token 计数、无凭证,内联进 HTML(不是 fetch)——fetch 是异步的,
  app 挂载时就会调 `read_traffic_snapshot`,竞态会让首屏画成空。

用法:python3 make_harness.py  → 生成 app/harness.html
      然后 ?mode=full|noRead|none&nav=traffic|settings|platform:claude
"""
import json
import os
import pathlib
import re
import time

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE / "app"
# 快照可覆盖:`CODEXBAR_SNAPSHOT=<path>` 用来渲染**退化态**(只有 1 个小时桶、空数据…)。
# 真实快照是 app 在写的活文件,**只读不改** —— 要造夹具就另写一份再用这个变量指过去。
REPO = HERE.parent.parent                       # 仓库根:state.json 夹具的来源,**与快照路径解耦**
SNAP = pathlib.Path(os.environ.get("CODEXBAR_SNAPSHOT") or (REPO / ".traffic-latest.json"))

# ★★ **陈旧产物闸。** 2026-09-05 实测踩到:`uishot/app/` 的 bundle 停在 5 天前,
#    而我以为 `npm run build` 会喂给它 —— 那个命令只写 `dist/`,harness 读的是 `app/`。
#    后果不是报错,是**假绿**:sweep 把 8 个新视图全判成"干净",而那些页面里
#    新组件一个都没渲染。页面照常渲染、零报错,看着完全像通过。
#    正确姿势:`vite build --outDir uishot/app` 然后跑本脚本(顺序不能反,build 会清空 outDir)。
def _assert_fresh_bundle():
    src = HERE.parent / "src"
    if not src.is_dir() or not APP.is_dir():
        return
    newest_src = max((f.stat().st_mtime for f in src.rglob("*")
                      if f.is_file() and f.suffix in (".ts", ".tsx", ".css")), default=0)
    newest_app = max((f.stat().st_mtime for f in (APP / "assets").glob("*.js")), default=0)
    if newest_app and newest_src > newest_app + 1:
        import datetime
        fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
        raise SystemExit(
            "✗ uishot/app 的 bundle 比源码旧（bundle {} < 源码 {}）。\n"
            "  直接生成 harness 会得到**假绿**：sweep 测的是旧代码，新组件根本没渲染。\n"
            "  先跑：cd codexbar && ./node_modules/.bin/vite build --outDir uishot/app"
            .format(fmt(newest_app), fmt(newest_src)))


_assert_fresh_bundle()
index = (APP / "index.html").read_text()
snapshot = SNAP.read_text()          # 只传递,不打印

STUB = """
<script>
(function () {
  var p = new URLSearchParams(location.search);
  try {
    localStorage.setItem('codexbar_cache_mode', p.get('mode') || 'full');
    // `?intro=off` 关掉入场动效(设置页那个开关)。默认开 —— 与真实默认值一致。
    localStorage.setItem('codexbar_settings', JSON.stringify({
      dockVisible: false, intro: p.get('intro') !== 'off',
      // `?autorefresh=off` 关掉后台心跳(设置页那个开关)。默认开 —— 与真实默认值一致。
      autoRefresh: p.get('autorefresh') !== 'off',
      // ★ `?autoswitch=on` 打开「额度低自动切号」—— **阈值那一行只在它开着时才渲染**,
      //   不给这个开关的话新加的可输入数字框在 harness 里一个像素都验不到,
      //   而截图会正常渲染、探针会报干净(本仓反复踩的那种假绿)。
      autoSwitchEnabled: p.get('autoswitch') === 'on',
    }));
    // ★ `?privacy=1` 打开打码模式(`usePrivacy` + `maskId`)。默认 0 —— 与真实默认值一致。
    //   给对外截图用:夹具已把邮箱/姓名/account_id 换成假的,打码是**第二层**,
    //   两层都要 —— 夹具保证"截到的不是真人",打码保证"版式就是用户分享时看到的那个"。
    localStorage.setItem('codexbar_privacy', p.get('privacy') === '1' ? '1' : '0');
    // 菜单栏停留页:`?tab=today` 直接渲染今日 Tab(默认账号页)
    localStorage.setItem('codexbar_mb_tab', p.get('tab') === 'today' ? 'today' : 'acc');
    // ★ 菜单栏停留在哪个平台档（v4 芯片行）。**必须能打桩** —— 芯片只有 logo 没有文字，
    //   `click=` 那条路匹配不到它，不给这个开关的话 gemini/grok 两档一个像素都验不到。
    if (p.get('mbplat')) localStorage.setItem('codexbar_mb_plat', p.get('mbplat'));
    // ★ 菜单栏弹窗 4f（交接包 2026-10-19）的几个开关 —— 不给的话这些态一个像素都截不到：
    //   `?mbstrip=1` 在跑条展开（默认折叠，与真实默认一致）· `?mbtheme=light` 浅色（日夜切换已移出弹窗，
    //   弹窗只读 `codexbar_theme`）。（`?probehold` 随「按住 0.6 s」一起删了：探针 2026-10-21 起点一下就执行。）
    localStorage.setItem('codexbar_mb_strip', p.get('mbstrip') === '1' ? '1' : '0');
    // ★ `?theme=light`（主窗口）与 `?mbtheme=light`（菜单栏）现在写同一个键：日夜切换 2026-10-19 移进设置页，
    //   所有 webview 共读 `codexbar_theme`（`SettingsPage.tsx::loadTheme`）。在 bundle 之前写，App 首帧就是浅色。
    var themeQ = p.get('mbtheme') || p.get('theme');
    if (themeQ) localStorage.setItem('codexbar_theme', themeQ);
    else localStorage.removeItem('codexbar_theme');
    // ★ 总览（交接包 page5，2026-10-19）的几个开关 —— 不给的话这些态一个像素都截不到：
    //   `?ovplat=codex|claude|gemini|grok` 停在哪一档（真源是 localStorage `codexbar_provider`）·
    //   `?ovhover=<序号|aid>` 把那张卡钉在悬停态（headless 里 JS 事件不激活 `:hover`，见 verification.md）·
    //   `?ovoff=1` 已停用 / 失效那两条折叠条默认展开。
    if (p.get('ovplat')) localStorage.setItem('codexbar_provider', p.get('ovplat'));
    // 代理轮换页的时间档 / 平台（`?rotwin=168` 直开账号 × 时段；`?rotplat=agy` 直开 Gemini）。不给就清掉，默认 24h / Codex 恒定。
    if (p.get('rotwin')) localStorage.setItem('codexbar_rot_win', p.get('rotwin')); else localStorage.removeItem('codexbar_rot_win');
    if (p.get('rotplat')) localStorage.setItem('codexbar_rot_plat', p.get('rotplat')); else localStorage.removeItem('codexbar_rot_plat');
    if (p.get('ovhover') != null) localStorage.setItem('codexbar_ov_hover', p.get('ovhover'));
    else localStorage.removeItem('codexbar_ov_hover');
    if (p.get('ovoff') === '1') localStorage.setItem('codexbar_ov_stripopen', '1');
    else localStorage.removeItem('codexbar_ov_stripopen');
    localStorage.removeItem('codexbar_ov_sort');
    // ★★ `?h=<n>` 预置**记住的弹窗高度**。账号 Tab 用的就是这个数(今日页没渲染,量不到),
    //    所以「两个 Tab 等高」这条闸**必须能预置它** —— 否则每次加载 localStorage 都是空的,
    //    账号页永远落到兜底值,验出来的"相等"只是两个兜底值相等,与真实行为无关。
    if (p.get('h')) localStorage.setItem('codexbar_mb_h', p.get('h'));
    else localStorage.removeItem('codexbar_mb_h');
    // 平台偏好:`?plat=demo` 套一组示范偏好(停用一家 + 改名改色 + 换顺序),用来验设置面板与总览
    if (p.get('plat') === 'demo') {
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: ['grok', 'claude', 'codex', 'kimi'],
        by: { kimi: { off: true }, grok: { name: 'DeepSeek', color: '#7fd1ff' } },
      }));
    } else if (p.get('plat') === 'agyoff') {
      // 验「设置页停用 agy ⇒ 额度卡零像素」。与 grokoff 分开:两个开关各管各的,
      // 合成一个就验不出"关了 grok 顺手把 agy 也关了"这类串台。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { agy: { off: true } },
      }));
    } else if (p.get('plat') === 'few') {
      // ★★ **今日 Tab 只剩 4 家平台** —— 复现用户 2026-09-06 报的「菜单栏下方大片空白」。
      //    今日页的高度 ≈ 固定头部 + 图例行数 × 35px,而图例只列**今天有流量**的平台。
      //    本机快照有 7 家,所以默认夹具下今日页恰好填满 580 —— 那个"恰好"正是
      //    `PANEL_H_MAX = 580` 这个常量的来源,它把一个**随数据变化的量**写死成了常量。
      //    停掉 kimi/mimo/deepseek 得到 claude+codex+grok+agy = 4 家,与用户截图一致。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { kimi: { off: true }, mimo: { off: true }, deepseek: { off: true } },
      }));
    } else if (p.get('plat') === 'grokoff') {
      // ★ 专门用来验「设置页停用 grok ⇒ 额度卡零像素」。`plat=demo` 停的是 kimi 不是 grok,
      //   拿它验会得到假绿(我第一次就是这么验的)。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { grok: { off: true } },
      }));
    } else {
      localStorage.removeItem('codexbar_platform_prefs');
    }
  } catch (e) { /* 无痕模式:本次渲染仍走默认值 */ }

  var SNAPSHOT = __SNAPSHOT__;
  var STATE = __STATE__;
  window.__HSTATE = STATE;   // ★ 让测试能就地改夹具（如打乱明细顺序）再触发刷新
  // ★ 总览夹具（交接包 page5）。全部在**脱敏夹具**上改，不碰任何真文件：
  //   `?anon=1`     号名一律换成 号A / 号B …（按原名排序），轮换夹具里的同名一并换 —— 对外截图用；
  //   `?ovcool=1`   第 2 个活号 429 冷却 41 分钟（`cooling_until`，板子 `cool_min` 跟着它算）；
  //   `?ovunprobed=1` 最后一个活号没有任何窗口（「未探测」）；`?ovlow=1` 第 3 个活号 5h 剩 6%（「额度低」）；
  //   `?relay=long` 一整窗连续用 48 分钟（真机是 4.0）—— 让接力条在 4h 轴上画得出多段 + 断档 + 回来的号，
  //   用来与交接包的示意对照；默认夹具（真机配速）下几乎整条都是断档，那是真话。
  var ANON = {}, AGY_ANON = ['号W', '号X', '号Y', '号Z'];
  (function () {
    var ids = Object.keys(STATE.slots || {}).filter(function (a) { return !STATE.slots[a].auth_dead && !STATE.slots[a].rotate_off; });
    var now = Date.now() / 1000;
    if (p.get('ovcool') === '1' && ids.length > 1) STATE.slots[ids[1]].cooling_until = now + 41 * 60 + 30;
    // ★ 「未探测」那个不能撞上在用 / 冷却（含真夹具里本来就在冷却的）/ 额度低那几个：撞上时卡片显示的是另一种状态，闸就失去判别力（2026-10-21 实测撞上在用号）
    if (p.get('ovunprobed') === '1' && ids.length) {
      var unp = ids.slice().reverse().filter(function (a) { return a !== STATE.active && a !== STATE.last_aid && a !== ids[1] && a !== ids[2]; })[0];
      // 真夹具里它本身可能正在冷却（冷却先于未探测判）⇒ 一并清掉，否则卡片照样显示「冷却」
      if (unp) { STATE.slots[unp].quota = {}; STATE.slots[unp].cooling_until = 0; }
    }
    if (p.get('ovlow') === '1' && ids.length > 2) {
      var q3 = STATE.slots[ids[2]].quota || {};
      if (q3.primary) q3.primary.used_percent = 94; else if (q3.secondary) q3.secondary.used_percent = 94;
    }
    // `?ovdead=1` 一个不在用的活号凭证失效（`auth_dead`）—— P5 起「失效」折叠条是总览唯一的折叠条，真夹具里常常一个失效号都没有
    if (p.get('ovdead') === '1' && ids.length > 3) {
      var dd = ids.slice().reverse().filter(function (a) { return a !== STATE.active && a !== STATE.last_aid; })[0];
      if (dd) { STATE.slots[dd].auth_dead = true; STATE.slots[dd].auth_dead_at = now - 3600; }
    }
    if (p.get('anon') === '1') {
      var labels = Object.keys(STATE.slots || {}).map(function (a) { return STATE.slots[a].label || a; }).sort();
      labels.forEach(function (l, i) { ANON[l] = '号' + String.fromCharCode(65 + i); });
      Object.keys(STATE.slots || {}).forEach(function (a) { var sl = STATE.slots[a]; sl.label = ANON[sl.label] || sl.label; });
      // 轮换夹具自己的假号名（plus1…plus9 / pro1…）也映射过去，截图里「今天的切换」与卡片同一套名字。
      for (var k = 1; k <= 9; k++) { ANON['plus' + k] = '号' + String.fromCharCode(64 + k); ANON['pro' + k] = '号P' + k; }
    }
  })();
  // `?rotname=<名>`：把轮换夹具里的 Pro1 换成一个长名字 —— 名字列最坏情况（长名 + 当前 + PRO）要能复现。
  function rotNamed(v) {
    var nm = p.get('rotname');
    return nm && v ? JSON.parse(JSON.stringify(v).split('"Pro1"').join(JSON.stringify(nm))) : v;
  }
  function anonDeep(v, map) {
    if (p.get('anon') !== '1' || v == null) return v;
    var txt = JSON.stringify(v);
    Object.keys(map).sort(function (a, b) { return b.length - a.length; }).forEach(function (k) {
      txt = txt.split('"' + k + '"').join('"' + map[k] + '"').split(k + ' →').join(map[k] + ' →').split('→ ' + k).join('→ ' + map[k]);
    });
    return JSON.parse(txt);
  }
  // ★ 菜单栏 4f 的两条通知夹具（真 state.json 恰好没有时，通知条那几种说法一句都截不到）：
  //   `?mblow=1`  最后一个活号 5h 剩 6%（低额度行 + 「只剩 N%」通知）；
  //   `?mbsub=1`  第一个活号订阅 5 天后到期（「订阅 N 天后到期」通知）。
  (function () {
    var ids = Object.keys(STATE.slots || {}).filter(function (a) { return !STATE.slots[a].auth_dead; });
    if (p.get('mblow') === '1' && ids.length) {
      var sl = STATE.slots[ids[ids.length - 1]];
      if (sl.quota && sl.quota.primary) sl.quota.primary.used_percent = 94;
      else if (sl.quota && sl.quota.secondary) sl.quota.secondary.used_percent = 94;
    }
    if (p.get('mbsub') === '1' && ids.length) {
      STATE.slots[ids[0]].sub_until = new Date(Date.now() + 5.5 * 86400000).toISOString();
    }
  })();

  // ★ 菜单栏宽 412,而 **Chrome 最小窗宽是 500** —— 直接传 --window-size=412 会按 500 布局、
  //   按 412 裁图,伪装成"横向溢出"(CLAUDE.md §4 记过这个坑)。所以窗口开 500,用 CSS 把
  //   文档钉死在 412,量到的才是真实的紧凑布局。
  if (p.get('w')) {
    var st = document.createElement('style');
    st.textContent = 'html,body{width:' + p.get('w') + 'px;overflow-x:hidden;margin:0}';
    document.head.appendChild(st);
  }
  // hover 态无法在 headless 里靠鼠标触发,用 CSS 强制展开来量**几何与遮挡**。
  // 注意:这只验证按钮的排版,不验证 `:hover` 这条触发本身。
  if (p.get('hover')) {
    var sh = document.createElement('style');
    // ★ `.cb-hoverpop` 也要强开（2026-09-21 补）。在这之前它够不到，于是**整个
    //   悬浮浮层族（路由分账 / 每号每天在岗）在 harness 里一个像素都验不到** ——
    //   而截图会正常渲染、缺陷探针报干净，正是本仓最怕的那种"沉默"。
    //   ⚠️ 溢出探针已单独排除 `:scope > .cb-hoverpop`（绝对定位层本来就在盒子外），
    //     所以强开它不会造出假的横向溢出。
    sh.textContent = '.mb-row-switch-wrap{opacity:1 !important;pointer-events:auto !important}'
      + '.cb-hoverpop{opacity:1 !important;visibility:visible !important}';
    document.head.appendChild(sh);
  }
  // ★ 总览「快到期」堆叠警告展开态（`?ovxs=1`）：headless 下 JS 事件不激活 `:hover`，给它加 `ov-xs-on`
  //   （与 `.ov-xs:hover` 同一条规则），截的是展开后的排版与遮挡，不验悬停触发本身。
  if (p.get('ovxs') === '1') {
    new MutationObserver(function () {
      document.querySelectorAll('.ov-xs:not(.ov-xs-on)').forEach(function (e) { e.classList.add('ov-xs-on'); });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  // ★ 菜单栏 4f 账号行悬停（`?mbhover=<n>`：第 n 个可切换的行，从 1 数）。headless 下 JS 事件不激活
  //   `:hover`，所以给那一行加 `qhov` 并注入与 `.qrow:not(.qro):hover` 同值的样式 ——
  //   **只验排版与遮挡（最右列 0→46、条跟着缩、「切换」出现），不验 :hover 触发本身。**
  //   `?mbnotice=1` 点开通知条（展开「还有 N 条」）。
  if (p.get('mbhover') || p.get('mbnotice')) {
    var sq = document.createElement('style');
    sq.textContent = '.qrow.qhov:not(.qro){grid-template-columns:16px var(--nameW,46px) minmax(0,1fr) minmax(0,1fr) 46px !important;'
      + 'background:var(--hov2) !important;transition:none !important}.qrow.qhov .sw2{opacity:1 !important;transform:none !important;transition:none !important}';
    document.head.appendChild(sq);
    setTimeout(function () {
      if (p.get('mbhover')) {
        var rs = document.querySelectorAll('.qrow:not(.qro)'), k = parseInt(p.get('mbhover'), 10) - 1;
        if (rs[k]) rs[k].classList.add('qhov');
        clicks.push('mbhover=' + p.get('mbhover') + ' →命中 ' + (rs[k] ? 1 : 0) + '/' + rs.length);
      }
      if (p.get('mbnotice') === '1') {
        var nh = document.querySelector('[data-mb-notice] > div');
        if (nh) nh.click();
        clicks.push('mbnotice →命中 ' + (nh ? 1 : 0));
      }
    }, 900);
  }
  // ★★★ `read_logs` 的夹具。**在 2026-09-14 之前 `LOGS_TXT` 是个从未定义过的名字** ——
  //   那条 case 一旦被调用就 `ReferenceError`。此前没人发现，因为**前端根本没有调用方**
  //   （那条命令是孤儿）。接线的同一轮把它补上，否则症状会是：stub 抛异常 → 调用方
  //   `.catch` 吞掉 → 服务日志恒空 → 页面照常渲染、零报错 → sweep 报"干净"。
  //   这正是本仓反复记的「打桩缺口 ⇒ 零渲染看着像通过」。
  // ★ 三种时间形态必须都在，否则 `parseServiceLogs` 的三条分支只验到一条：
  //   ① `[quotad HH:MM:SS]` 只有时分秒 —— **且刻意造一次跨日**（倒序往下走时间变大）
  //   ② `[agy MM-DD HH:MM:SS]` 带日期
  //   ③ dawnprobe **一个时间戳都没有**
  //   另含一行 `✗`：日志页给失败行染红的规则以前是死代码（agy 的行到不了这一页）。
  var LOGS_TXT = [
    // ★ 契约：每行 `<job>` + TAB + 原文（Rust 侧 read_logs 就是这么给的）。
    //   来源**不由前端猜** —— dawnprobe 的行没有任何自我标识。
    'quotad\t[quotad 20:10:05] activity → Asen:HTTP 200',
    'quotad\t[quotad 08:44:17] window reset crossed → sweep now',
    'quotad\t[quotad 23:58:02] activity → wing:HTTP 200',   // ← 时间变大 ⇒ 属于**前一天**
    'agy\t[agy 09-14 13:41:34] auto 恢复成你选的 [dbk]（钥匙串被别的 agy 进程写回过）',
    'agy\t[agy 09-14 01:06:57] health [sam] ✗ 取不到额度',
    'dawnprobe\t每日清晨探针 · 5 个 Plus 号:qq55 Asen Egan Huo wing',
    'dawnprobe\tprobe 0/5 可用',
  // ⚠️ **不能写 `join('\\n')`** —— 这整段 JS 住在 make_harness.py 的一个**非 raw** 三引号
  //   字符串里，Python 会先把 `\\n` 变成真正的换行，于是 JS 那个字符串字面量当场断行、
  //   整个打桩块语法错误 ⇒ **所有视图**一起「探针缺失」。转义在这里被解释两次。
  ].join(String.fromCharCode(10));

  var cbid = 0, cbs = {}, listeners = {}, unknown = [], errors = [], clicks = [];

  // ★ 没有这个,渲染失败会表现为"一张空白页 + 零溢出",而零溢出看起来像通过 ——
  //   那是假阴性,比没测更糟(2026-08-11 已经中过一次)。
  window.addEventListener('error', function (e) {
    errors.push(String(e.message) + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    errors.push('reject: ' + String(e.reason && (e.reason.stack || e.reason.message || e.reason)).slice(0, 200));
  });

  // ★★ 「请求」页夹具（`read_requests`，契约 PLAN §2.1）。**全部脱敏**：账号名只用 号A…，
  //   没有邮箱、没有会话正文。时间相对 `_NOW` 现算 —— 钉死时间戳会让「今天 / 昨天」随日子腐烂成全空。
  //   覆盖：四家平台 · 今天 + 昨天 · codex 直连行 · 首字读不到的 claude / agy 行 · 首字 > 30 s 的行 ·
  //   t/s 读不到的行 · 1M 以上输入。生成器照抄交接包 RequestsV2.html 的 `gen()`（同一组示意分布）。
  //   `?req=ok|empty|stale|error|errfirst`：
  //     empty    今天 0 条（昨天照常）—— 空列表态；
  //     stale    后端自己报 ok:false + 旧行 + stale_since —— 读失败态（后端保留旧值那条路）；
  //     error    第 1 次成功、之后 IPC 一律失败 —— 读失败态（前端保留上次列表那条路，需拉长虚拟时间 >10 s）；
  //     errfirst 一次都没读到 —— 红条 + 空列表。
  var reqCalls = 0;
  function REQ_FIXTURE(mode) {
    var pad = function (v) { return String(v).padStart(2, '0'); };
    var dkey = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
    var now = new Date(_NOW * 1000);
    var mid = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    var P = [
      { k: 'codex', model: 'gpt-6-sol', srcs: ['交互', 'exec'], accs: ['号A', '号B', '号D', '直连'], ttft: 1, tps: [45, 180] },
      { k: 'claude', model: 'claude-opus-5.5', srcs: ['Claude Code'], accs: ['本机'], ttft: 0.5, tps: [8, 100] },
      { k: 'agy', model: 'gemini-4-argon', srcs: ['agy -p', 'agy 交互'], accs: ['号C', null], ttft: 0, tps: [60, 150] },
      { k: 'grok', model: 'grok-4.7', srcs: ['grok CLI'], accs: ['单号'], ttft: 1, tps: [40, 95] }
    ];
    function gen(seed, n, tEndMax, tEndMin, tag) {
      var x = seed, rnd = function () { return (x = (x * 16807) % 2147483647) / 2147483647; };
      var out = [], sessCount = {}, step = Math.max(20, Math.min(600, (tEndMax - tEndMin) / (n + 1)));
      var t = tEndMax;
      for (var i = 0; i < n; i++) {
        var p0 = P[Math.floor(rnd() * 10) % 10 < 5 ? 0 : (rnd() < .6 ? 1 : (rnd() < .5 ? 2 : 3))];
        t -= Math.round(step * (0.6 + rnd() * 0.8)); if (t <= tEndMin) t = tEndMin + 1 + i;
        var inp = Math.round(20 + rnd() * 190) * 1000, cache = rnd() < .12 ? 0 : Math.round(60 + rnd() * 39);
        var o = Math.round(80 + rnd() * 3400), tps = +(p0.tps[0] + rnd() * (p0.tps[1] - p0.tps[0])).toFixed(1);
        var g = o / tps, hasT = rnd() < p0.ttft, ttft = hasT ? +(rnd() < .1 ? 30 + rnd() * 15 : 1 + rnd() * 6).toFixed(1) : null;
        var sess = p0.k + Math.floor(rnd() * 3); sessCount[sess] = (sessCount[sess] || 0) + 1;
        var total = (ttft || 0) + g;
        out.push({ key: p0.k + ':' + tag + i, platform: p0.k, t_start: t - total, t_end: t, model: p0.model,
          source: p0.srcs[Math.floor(rnd() * p0.srcs.length)], session: tag + sess, session_title: 'demo-project',
          account: p0.accs[Math.floor(rnd() * p0.accs.length)], input: inp, cached: Math.round(inp * cache / 100),
          output: o, reasoning: null, ttft_ms: ttft == null ? null : Math.round(ttft * 1000),
          gen_ms: Math.round(g * 1000), total_ms: Math.round(total * 1000), tool_ms: null, tps: tps,
          est: p0.k === 'claude' && !hasT, _sess: sess });
      }
      out.forEach(function (r) { r.session_req_n = sessCount[r._sess]; delete r._sess; });
      return out;
    }
    var today = mode === 'empty' ? [] : gen(42, 64, _NOW - 60, mid, 't');
    // 固定前五条，保证每个要验的形态**一定在首屏**（随机分布不保证）。
    var fix = [
      { platform: 'codex', model: 'gpt-6-sol', source: '交互', account: '直连', ttft_ms: 4200, tps: 176.7, est: false },
      { platform: 'claude', model: 'claude-opus-5.5', source: 'Claude Code', account: '本机', ttft_ms: null, tps: 82.3, est: true },
      { platform: 'codex', model: 'gpt-6-sol', source: 'exec', account: '号A', ttft_ms: 39500, tps: 113.7, est: false },
      { platform: 'agy', model: 'gemini-4-argon', source: 'agy 交互', account: '号C', ttft_ms: null, tps: null, est: false, input: 1234567 },
      { platform: 'grok', model: 'grok-4.7', source: 'grok CLI', account: '单号', ttft_ms: 4900, tps: 64.6, est: false }
    ];
    fix.forEach(function (f, i) {
      if (!today[i]) return;
      var r = today[i];
      Object.keys(f).forEach(function (k) { r[k] = f[k]; });
      r.key = r.platform + ':tfix' + i;
      if (r.ttft_ms != null) r.total_ms = r.ttft_ms + r.gen_ms; else r.total_ms = r.gen_ms;
      if (r.input != null) r.cached = Math.round(r.input * 0.75);
    });
    var yest = gen(7, 78, mid - 60, mid - 86400, 'y');
    var y0 = new Date((mid - 3600) * 1000);
    return { v: 1, generated_at: _NOW, ok: mode !== 'stale', error: mode === 'stale' ? 'requests-ledger/2026-10.jsonl 被占用' : null,
      stale_since: mode === 'stale' ? _NOW - 140 : null, requests: today.concat(yest),
      days: { today: { date: dkey(now), n: today.length, avg_tps: null, ttft_median_s: null, tokens: 0 },
              yesterday: { date: dkey(y0), n: yest.length, avg_tps: null, ttft_median_s: null, tokens: 0 } } };
  }

  function fire(event, payload) {
    (listeners[event] || []).forEach(function (id) {
      var c = cbs[id]; if (c) c.cb({ event: event, id: id, payload: payload });
    });
  }
  // 测试用：模拟别的 webview / Rust 发来的事件（例：设置页广播 `idle-tray-settings`）
  window.__harnessFire = fire;

  // ★ IPC 调用计数。用来回答「这个操作到底有没有触发扫描」——`run_traffic` 是唯一会真起
  //   python 的那条,页面上完全看不出来,只能数。配 `--virtual-time-budget` 拉长虚拟时间,
  //   可以把 30s 的心跳压缩到秒级验证。
  // grok 额度的六个夹具。**全部脱敏**(邮箱/user_id 都是假的) —— 真 sidecar 含 email + user_id,
  // 与 state.json 同级敏感,绝不进 HTTP 伺服目录。
  // `_NOW` 由 python 侧现算,否则 `↻重置` 与「N 分钟前」会随夹具一起腐烂成"已重置"。
  var _NOW = __NOW__;
  // 定时探针 `--status` 的形状（codex `read_dawn_status` / agy `dawn-probe --status` 共用）。
  // `?dawn=off|on|ran`：off = 默认关；on = 开了但还没跑过；ran = 今天 06:01 跑过。
  function DAWN_STATUS(kind) {
    var mode = p.get('dawn') || 'off';
    var r = { enabled: mode !== 'off', time: '06:00', window: '06:00–06:03', due_at: _NOW + 3600,
              targets_today: kind === 'codex' ? ['qq55', 'Asen', 'Egan', 'Huo'] : ['qq55', 'Asen'] };
    if (mode === 'ran') {
      r.date = new Date(_NOW * 1000).toISOString().slice(0, 10); r.at = _NOW - 3 * 3600;
      r.state = 'done'; r.ok = r.targets_today.length; r.total = r.targets_today.length;
      if (kind === 'agy') r.started = 2;
    }
    return r;
  }
  function _acc(o) {
    var base = { account_key: 'https://auth.x.ai::demo', user_id: 'u-demo',
                 email: 'grok@example.com', token_expires_at: _NOW + 3600,
                 available: false, reason: null, detail: null, http_status: null,
                 quota: null, last_good: null };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var _Q = { used_percent: 35.0, period_type: 'USAGE_PERIOD_TYPE_WEEKLY',
             period_start: _NOW - 345600, period_end: _NOW + 259200,
             window_minutes: 10080.0,
             products: [{ product: 'GrokBuild', used_percent: 27.0 },
                        { product: 'GrokAppBuilder', used_percent: 4.0 },
                        { product: 'GrokImagine', used_percent: 4.0 }],
             on_demand_cap: 0.0, on_demand_used: 0.0, prepaid_balance: 0.0 };
  var GROK = {
    ok:      { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ available: true, http_status: 200, quota: _Q })] },
    expired: { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'token_expired', token_expires_at: _NOW - 600,
                                 detail: '本地 expires_at 已过,未发请求' })] },
    '401':   { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'unauthorized', http_status: 401, detail: 'HTTP 401' })] },
    missing: { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ account_key: null, email: null, token_expires_at: null,
                                 reason: 'auth_file_missing' })] },
    // 降级 + 保留陈旧读数:细条要变琥珀并写明是几时的,横幅在上。两者必须同时出现。
    stale:   { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'network_error', detail: 'TimeoutError: 超过 20s 整体上限',
                                 last_good: { used_percent: 35.0, fetched_at: _NOW - 10800,
                                              period_end: _NOW + 259200 } })] },
  };
  // agy 额度夹具。★ 与 grok 不同,agy 的响应里**没有任何身份信息**(接口无鉴权),
  // 所以这里无需脱敏 —— 但形状必须真实:2 组 × 2 窗口,`remaining_percent` 是**剩余**。
  // ★★ `rem === 100` 的桶**一定**是浮动锚点:一次都没用过 ⇒ 服务端每轮回「此刻 + 整窗」,
  //    倒计时永远停在 4h5xm。这里按剩余量**推导**判定,不另加开关。
  //    用过的桶不带 anchor ⇒ 前端回落到既有行为,与改动前逐像素相同。
  //
  // ⚠️ **`?agy=ok` 走不到「未启动」分支,别以为它覆盖了。** 我一开始就是这么以为的,
  //    `--dump-dom` 当场证伪:卡上与菜单栏行都只取**每个窗口最紧**的那个桶
  //    (`agyWinRows` / `agyTightest`),而 100% 的桶按定义永远不是最紧的 ⇒ 带 anchor 的桶
  //    一个都渲染不到。要验那条分支必须用 `?agy=idle`(四个桶全 100%,即"装了但一直没用")。
  //    ★ 这正是本仓那条「报干净之前先正面证明它渲染了」的又一个实例 ——
  //      推理说覆盖到了,DOM 说没有。
  function _bkt(id, win, rem, dt) {
    var b = { bucket_id: id, window: win, remaining_percent: rem, reset_at: _NOW + dt };
    if (rem >= 100) {
      b.anchor = { state: 'floating', held_secs: 0, samples: 1, slides: 3,
                   used_max: 0.0, reset: b.reset_at };
    }
    return b;
  }
  function _groups(gw, g5, tw, t5) {
    return { groups: [
      { name: 'Gemini Models', buckets: [_bkt('gemini-weekly', 'weekly', gw, 604800),
                                         _bkt('gemini-5h', '5h', g5, 18000)] },
      { name: 'Claude and GPT models', buckets: [_bkt('3p-weekly', 'weekly', tw, 604800),
                                                 _bkt('3p-5h', '5h', t5, 18000)] } ] };
  }
  function _agy(o) {
    var base = { schema: 1, fetched_at: _NOW - 30, available: false, reason: null,
                 detail: null, pid: 45366, quota: null, last_good: null };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var AGY = {
    // 实测形状(2026-09-04,本机 agy 1.1.26)。
    ok:      _agy({ available: true, quota: _groups(99.56, 97.34, 100, 100) }),
    // 低水位:验数字的阈值色与 glow。最紧的是 3p-5h = 7% ⇒ 环上应显示 7、数字红。
    tight:   _agy({ available: true, quota: _groups(62.0, 41.0, 88.0, 7.0) }),
    // ★★ **装了 agy 但一直没用** —— 四个桶全满,于是最紧的那个也是浮动锚点,
    //    卡与菜单栏行都应渲染「↻未启动」而不是一个永远停在 4h5xm 的假倒计时。
    //    这是**唯一能证明那条分支真的渲染出来**的 agy 夹具(`ok` 证不了:100% 的桶
    //    永远不是最紧的,带 anchor 的桶一个都进不了渲染 —— `--dump-dom` 实测)。
    idle:    _agy({ available: true, quota: _groups(100, 100, 100, 100) }),
    // ★★ agy 没在跑 —— **常态,不是故障**。必须仍然显示(带上次读数 + 一个 `!`),
    //    且不得染成警告色。这条夹具就是为了截出"藏了"或"染红了"这两种回归。
    noproc:  _agy({ reason: 'no_process', detail: 'agy 没在运行',
                    last_good: { quota: _groups(99.56, 97.34, 100, 100),
                                 fetched_at: _NOW - 10800 } }),
    // 预热窗口(起后 ~10s 内),会自愈 ⇒ 琥珀。
    warm:    _agy({ reason: 'not_ready', detail: 'agy 刚起,额度服务还在预热' }),
    // ★ 本机没装 agy ⇒ **零像素**。截出来若还有卡就是回归。
    notinst: _agy({ reason: 'not_installed', detail: '本机没有 agy' }),
  };
  // ── 代理轮换泳道夹具(2026-09-07 交接稿)───────────────────────────
  // ★ 形状**逐字取自 `traffic/rotation.py` 的真实输出**,不是照着稿子想象编的 ——
  //   字段名编错的话页面照样渲染(全是 undefined),而 undefined 渲染出来是空白,
  //   看着就像"这段时间没数据"。
  function _seg(acc, sMin, eMin, reqs, tok, models, why, cur) {
    var st = _NOW - 24 * 3600 + sMin * 60;
    return { acc: acc, start: st, end: _NOW - 24 * 3600 + eMin * 60, requests: reqs,
             tokens: tok, by_model: models, enter_reason: why, current: !!cur };
  }
  function _M(a, b, c) {
    var m = [{ model: 'gpt-6-astra', tokens: a }];
    if (b) m.push({ model: 'gpt-5.6-luna', tokens: b });
    if (c) m.push({ model: 'gpt-5-codex', tokens: c });
    return m;
  }
  var ROT_SEGS = [
    _seg('plus5', 0, 200, 38, 61e6, _M(43e6, 13e6, 5e6), 'window_start'),
    _seg('plus4', 200, 330, 22, 31e6, _M(19e6, 9e6, 3e6), 'stream_err'),
    _seg('plus5', 330, 520, 41, 78e6, _M(58e6, 14e6, 6e6), 'quota_rotate'),
    _seg('Pro1', 520, 660, 30, 69e6, _M(56e6, 8e6, 5e6), 'pro_fallback'),
    _seg('plus6', 660, 780, 24, 36e6, _M(24e6, 9e6, 3e6), 'quota_rotate'),
    _seg('plus5', 780, 930, 41, 70e6, _M(48e6, 15e6, 7e6), 'quota_rotate'),
    _seg('plus7', 930, 1040, 31, 62e6, _M(45e6, 12e6, 5e6), 'stream_err'),
    _seg('plus4', 1040, 1160, 28, 42e6, _M(27e6, 12e6, 3e6), 'quota_rotate'),
    _seg('Pro1', 1160, 1280, 37, 89e6, _M(74e6, 9e6, 6e6), 'pro_fallback'),
    _seg('plus6', 1280, 1360, 26, 42e6, _M(28e6, 10e6, 4e6), 'quota_rotate'),
    _seg('plus7', 1360, 1388, 21, 44e6, _M(32e6, 8e6, 4e6), 'stream_err'),
    // ★ 极短段(4 分钟)+ **零 token**:验 `min-width:3px` 与"该时段无归属到的 token"分支。
    //   零 token 不是编的 —— 真机上 429 掉的请求就是有请求、无响应、无 token 记录。
    _seg('plus3', 1388, 1392, 2, 0, [], 'cool_429'),
    _seg('plus4', 1392, 1440, 30, 57e6, _M(40e6, 13e6, 4e6), 'cool_429', true),
  ];
  function _mk(acc, mins, kind) { return mins.map(function (m) {
    return { acc: acc, t: _NOW - 24 * 3600 + m * 60, kind: kind }; }); }
  var ROT_MARKERS = [].concat(
    _mk('plus5', [40, 95, 150, 360, 410, 470, 800, 840, 880, 910], 'stream_err'),
    _mk('plus4', [230, 270, 300, 1080, 1120, 1400, 1430], 'stream_err'),
    _mk('Pro1', [560, 620, 1200], 'stream_err'),
    _mk('plus7', [980, 1375], 'stream_err'),
    _mk('plus7', [1388], 'cool_429'), _mk('plus3', [1390, 1392], 'cool_429'));
  function _rotAccounts() {
    var by = {};
    ROT_SEGS.forEach(function (s) {
      var a = by[s.acc] || (by[s.acc] = { acc: s.acc, tokens: 0, requests: 0, models: {} });
      a.tokens += s.tokens; a.requests += s.requests;
      s.by_model.forEach(function (m) { a.models[m.model] = (a.models[m.model] || 0) + m.tokens; });
    });
    // 配色与线性探测口径同 rotation.py::assign_colors(此处直接给结果,夹具不复算)
    var C = { plus5: '#4d9fff', plus4: '#2dd4bf', Pro1: '#8b7cf6', plus7: '#27B26B',
              plus6: '#E0A21C', plus3: '#E0784F' };
    var Q = { plus5: 100, plus4: 100, Pro1: 100, plus7: 98, plus6: 100, plus3: 0 };
    // ★ P7 右列是 **5h 窗口**剩余（不是最紧窗口）：Pro 没有 5h ⇒ null，画「—」不画满。三档色各出现一次（<10 / <50 / ≥50）。
    var Q5 = { plus5: 82, plus4: 44, Pro1: null, plus7: 96, plus6: 61, plus3: 7 };
    return Object.keys(by).map(function (k) {
      var a = by[k], top = null;
      Object.keys(a.models).forEach(function (m) {
        if (!top || a.models[m] > top[1]) top = [m, a.models[m]]; });
      return { acc: k, plan: k.toLowerCase().indexOf('pro') === 0 ? 'pro' : 'plus',
               color: C[k], tokens: a.tokens, requests: a.requests,
               top_model: top ? { model: top[0], share: top[1] / a.tokens } : null,
               quota_pct: Q[k] === undefined ? null : Q[k],
               quota_5h: Q5[k] === undefined ? null : Q5[k],
               // ★ plus3 此刻仍在冷却（`冷却中` 标签 + 斜纹块的终点用真的 `cooling_until`）。
               cooling_until: k === 'plus3' ? _NOW + 40 * 60 : null };
    }).sort(function (x, y) { return y.tokens - x.tokens; });
  }
  function _rotEvents() {
    var out = [], R = { cool_429: '429 冷却 → 故障转移', stream_err: '断流 → 轮换',
                        quota_rotate: '额度轮换', window_start: '窗口起点',
                        pro_fallback: 'Plus 全部不可用 → Pro 保底接管' };
    for (var i = 1; i < ROT_SEGS.length; i++) {
      var s = ROT_SEGS[i], p = ROT_SEGS[i - 1], is429 = s.enter_reason === 'cool_429';
      // ★ 形状同 `rotation.py::_events`：Pro 保底是换号的**原因**，`type` 仍是 switch；同号重入不算换号。
      if (p.acc === s.acc) continue;
      var ty = is429 ? 'failover' : 'switch';
      out.push({ t: s.start, type: ty, from: p.acc, to: s.acc,
                 reason: s.enter_reason, accs: [p.acc, s.acc],
                 text: p.acc + ' → ' + s.acc + ' · ' + R[s.enter_reason] + ' · 上号 ' +
                       Math.round((p.end - p.start) / 60) + 'm / ' +
                       (p.tokens / 1e6).toFixed(1) + 'M / ' + p.requests + ' 次' });
    }
    ROT_MARKERS.forEach(function (m) {
      out.push({ t: m.t, type: m.kind, from: m.acc, to: null, reason: m.kind, accs: [m.acc],
                 text: m.kind === 'cool_429' ? '429 → cooled [' + m.acc + '], failing over'
                                             : 'stream err [' + m.acc + ']' });
    });
    return out.sort(function (a, b) { return b.t - a.t; });
  }
  var ROT_LOG = [
    { t: _NOW - 60, text: '[quotad] activity → plus4:HTTP 200 · 1.9M tok' },
    // ★ 最新一条记录（plus3 → plus4，48 分钟前）前后 90 s 内的原文 —— 展开日志默认展开它，没有这几行就验不到「对应那一行用平台色」。
    { t: _NOW - 48 * 60 + 3, text: '429 → cooled [plus3], failing over' },
    { t: _NOW - 48 * 60 - 40, text: 'stream err [plus3]: IncompleteRead(2280 bytes read)' },
    { t: _NOW - 2600, text: "headers x-codex 头集合变化 -['x-codex-turn-state']" },
    { t: _NOW - 3100, text: 'cooled 429 → cooled [plus7], failing over' },
    { t: _NOW - 3300, text: '[quotad] window reset crossed → sweep now' },
    { t: _NOW - 3600, text: 'stream err [plus5]: IncompleteRead(2280 bytes read)' },
    { t: _NOW - 4000, text: 'switch plus6 → plus7 (stream-err x1)' },
    { t: _NOW - 4600, text: '[quotad] refresh plus5 ok' },
  ];
  function _rot(o) {
    var base = {
      ok: true, generated_at: _NOW,
      window: { start: _NOW - 24 * 3600, end: _NOW, hours: 24 },
      accounts: _rotAccounts(), segments: ROT_SEGS, markers: ROT_MARKERS,
      events: _rotEvents(), log: ROT_LOG,
      kpi: { tokens: 682e6, requests: 371, avg_tokens: 1.84e6, rotations: 12,
             avg_dwell: 6660, cool_429: 3, stream_err: 22,
             // ★ 保底接管:两段共 260 分钟。夹具必须**真的有**,否则那格 KPI 与 PRO 徽章
             //   一个像素都验不到,而截图会正常渲染、探针报干净。
             pro_segs: 2, pro_secs: 260 * 60 },
      coverage: { responses_seen: 371, responses_with_tokens: 346, responses_unplaced: 0,
                  attributed_pct: 0.933, undated_lines: 0, in_window_lines: 4200,
                  tail_truncated: false, window_covered: true, tail_bytes: 540672,
                  covers_from: _NOW - 30 * 3600,
                  log_begins_at: null, log_begins_reason: 'undated_head' },
      // ★★ 「每号 · 每天在岗」表。夹具必须**每一种格子都真的出现过**，否则那一态
      //    一个像素都验不到，而截图会正常渲染、缺陷探针报干净（本仓记过多次）：
      //      · 数字   —— 真用了
      //      · null   —— 这天没选中它（确实是 0）
      //      · 'unknown' —— 这天没读到（在 covers_from 之前）
      //      · rotate_off 的行（排第一却一次没跑）—— 这张表存在的理由本身
      //      · relay 那一行 —— 整列 `—` 却其实有流量的那种日子
      daily: {
        days: ['09-15', '09-16', '09-17', '09-18', '09-19', '09-20', '09-21'],
        rows: [
          { acc: 'plus5', rank: 1, rotate_off: true,
            cells: ['unknown', null, null, null, null, null, null] },
          { acc: 'plus4', rank: 2, rotate_off: false,
            cells: ['unknown', { secs: 5400, requests: 61, tokens: 92e6 },
                    { secs: 2160, requests: 24, tokens: 31e6 }, null,
                    { secs: 900, requests: 9, tokens: 12e6 },
                    { secs: 7200, requests: 80, tokens: 130e6 },
                    { secs: 1800, requests: 20, tokens: 26e6 }] },
          { acc: 'plus7', rank: 3, rotate_off: false,
            cells: ['unknown', { secs: 1800, requests: 20, tokens: 28e6 }, null, null, null,
                    { secs: 3600, requests: 52, tokens: 106e6 },
                    { secs: 600, requests: 7, tokens: 9e6 }] },
          { acc: 'Pro1', rank: null, rotate_off: false,
            cells: ['unknown', null, null, { secs: 15600, requests: 67, tokens: 158e6 },
                    null, null, null] },
        ],
        relay: [0, 0, 486, 42, 39, 0, 0],
      },
    };
    for (var k in o) base[k] = o[k];
    return base;
  }
  // ★ 7d / 14d / 30d 夹具（账号 × 时段）：每天固定几段，晚上 20–23 点最密 —— 「常用时段」与结论行要算得出确定值。
  function _rotLong(hours) {
    var days = Math.round(hours / 24), segs = [], marks = [], st0 = _NOW - hours * 3600;
    var day0 = new Date(st0 * 1000); day0.setHours(0, 0, 0, 0);
    var PLAN = [['plus5', 9, 11], ['plus4', 14, 15.5], ['plus7', 20.5, 23.5], ['plus6', 1, 2], ['Pro1', 16, 16.5]];
    for (var d = 0; d <= days; d++) {
      PLAN.forEach(function (q, j) {
        if (q[0] === 'Pro1' && d % 3) return;
        if (q[0] === 'plus6' && d % 2) return;
        var b = day0.getTime() / 1000 + d * 86400, s0 = b + q[1] * 3600, e0 = b + q[2] * 3600;
        if (e0 <= st0 || s0 >= _NOW) return;
        segs.push({ acc: q[0], start: Math.max(s0, st0), end: Math.min(e0, _NOW), requests: 20 + j, tokens: (30 + j * 7) * 1e6,
                    by_model: _M(20e6, 8e6, 2e6), enter_reason: 'quota_rotate', current: false });
        if (q[0] === 'plus7' && s0 + 3600 < _NOW && s0 + 3600 > st0) marks.push({ acc: 'plus7', t: s0 + 3600, kind: 'stream_err' });
        if (q[0] === 'plus4' && d % 2 === 0 && s0 + 1200 < _NOW && s0 + 1200 > st0) marks.push({ acc: 'plus4', t: s0 + 1200, kind: 'stream_err' });
      });
    }
    segs.sort(function (a, b) { return a.start - b.start; });
    if (segs.length) segs[segs.length - 1].current = true;
    var evs = [];
    for (var i = 1; i < segs.length; i++) {
      if (segs[i].acc === segs[i - 1].acc) continue;
      evs.push({ t: segs[i].start, type: 'switch', from: segs[i - 1].acc, to: segs[i].acc, reason: 'quota_rotate',
                 accs: [segs[i - 1].acc, segs[i].acc],
                 text: segs[i - 1].acc + ' → ' + segs[i].acc + ' · 额度轮换 · 上号 ' + Math.round((segs[i - 1].end - segs[i - 1].start) / 60) + 'm / 30.0M / 20 次' });
    }
    marks.forEach(function (m) { evs.push({ t: m.t, type: 'stream_err', from: m.acc, to: null, reason: 'stream_err', accs: [m.acc],
                                            text: 'stream err [' + m.acc + '] · 已 200 后断流,**已计费**' }); });
    evs.sort(function (a, b) { return b.t - a.t; });
    var by = {};
    segs.forEach(function (x) { var a = by[x.acc] || (by[x.acc] = { t: 0, r: 0 }); a.t += x.tokens; a.r += x.requests; });
    var accs = _rotAccounts().filter(function (a) { return by[a.acc]; }).map(function (a) {
      var y = {}; for (var k in a) y[k] = a[k]; y.tokens = by[a.acc].t; y.requests = by[a.acc].r; y.cooling_until = null; return y; });
    var tok = segs.reduce(function (s1, x) { return s1 + x.tokens; }, 0), req = segs.reduce(function (s1, x) { return s1 + x.requests; }, 0);
    return _rot({ window: { start: st0, end: _NOW, hours: hours }, segments: segs, markers: marks, events: evs, accounts: accs,
                  kpi: { tokens: tok, requests: req, avg_tokens: tok / Math.max(1, req), rotations: evs.filter(function (e) { return e.type === 'switch'; }).length,
                         avg_dwell: segs.reduce(function (s1, x) { return s1 + x.end - x.start; }, 0) / Math.max(1, segs.length),
                         cool_429: 0, stream_err: marks.length, pro_segs: 0, pro_secs: 0 } });
  }
  var ROT = {
    ok: _rot({}),
    // ★★ `?rot=procur` —— **Pro 号正在当班**:同一条泳道上同时挂 `PRO` 和 `当前` 两个徽章。
    //    这是名字列的**最坏情况**,也正是用户 2026-09-07 截图里被截成 `Pr…` 的那一种。
    //    默认夹具的「当前」在 plus4 上 ⇒ 这个组合**一次都没被渲染过**,
    //    所以那次截断在 harness 里完全看不见(缺陷探针对"没渲染"是沉默的)。
    procur: (function () {
      var segs = ROT_SEGS.map(function (x) {
        var y = {}; for (var k in x) y[k] = x[k];
        y.current = (x.acc === 'Pro1' && x.start === ROT_SEGS[8].start);
        return y;
      });
      return _rot({ segments: segs });
    })(),
    // ★ 旧格式无时间戳 + 尾读截断 —— 专门截那行覆盖率脚注。没有它,诚实度提示一次都验不到。
    undated: _rot({ coverage: { responses_seen: 371, responses_with_tokens: 214,
                                responses_unplaced: 3, attributed_pct: 0.577,
                                undated_lines: 21078, in_window_lines: 1372,
                                tail_truncated: true } }),
    // ★「这段时间代理没干活」——**不是**「读不到」。两者必须显示成不同的话。
    empty: _rot({ accounts: [], segments: [], markers: [], events: [], log: [],
                  kpi: { tokens: 0, requests: 0, avg_tokens: 0, rotations: 0,
                         avg_dwell: 0, cool_429: 0, stream_err: 0, pro_segs: 0, pro_secs: 0 },
                  coverage: { responses_seen: 0, responses_with_tokens: 0, responses_unplaced: 0,
                              attributed_pct: null, undated_lines: 0, in_window_lines: 0,
                              tail_truncated: false } }),
  };

  var ipc = {}, sizes = [], emitted = [], idleTray = null;
  // 悬停面板（harness-tpshover.html）：emit 的完整 payload（JSON）+ 它调的三条命令。
  var emittedJ = [], hvCalls = [];
  // 刘海卡片（harness-notch.html）：`notch_card_resize` 每次报的高度。
  var ntCalls = [];
  // ★★ **路由分账夹具必须自己注入,不能指望活快照。**
  //   `.traffic-latest.json` 会被**正在运行的 app** 用它自己打包的（旧）`scan.py` 覆盖 ——
  //   实测过一次:harness 刚生成好，app 一扫就把 `by_provider` 抹没了，
  //   于是 DOM 闸变红，而根因和"代码写错了"完全无关。
  //   数值取自真实 `scan.py --days 90` 的输出（含 `openai-nows` 这个**未登记** provider,
  //   它是 09-07 WS 实验的临时产物,专门用来验证三分类不会把它误判成中转站）。
  //   ⚠️ `SNAPSHOT` 是**字符串**不是对象（`read_traffic_snapshot` 的 Rust 签名是
  //     `Option<String>`）。我第一版直接读 `SNAPSHOT.platforms` —— `undefined`,
  //     被 try/catch 吞掉,注入静默没生效,而 DOM 闸红得像是组件写错了。
  (function () {
    try {
      var _o = JSON.parse(SNAPSHOT);
      var c = _o && _o.platforms && _o.platforms.codex;
      // ★ 无条件覆盖（2026-10-16）：原来是 `!c.by_provider` 才注入 —— 活快照自己带了 by_provider
      //   （当天没走中转站）就不注入，`TokenDun` 消失，路由分账闸跟着日期红。夹具就该恒定。
      if (c) {
        // ★★ 形状是 **provider → 日期 → 桶**（2026-09-10 起）。前端按当前档位求和，
        //    所以路由分账与同页的 KPI/图必然同窗口。
        // ★ 各 provider 落在**不同的日子**上 —— 全放同一天的话，「跟随档位」那条闸
        //   换任何档位都得到同一批 provider，又是个空守卫。
        var _days = Object.keys(c.days || {}).sort();
        var _last = _days[_days.length - 1], _first = _days[0];
        var _bk = function (n) {
          return { total: n, uncached_in: 0, cache_read: 0, cache_write: 0,
                   output: 0, rounds: 0, models: {} };
        };
        c.by_provider = {};
        if (_last) {
          // 今天/最近：账号池 + 中转站 + 那个未登记的临时 provider
          c.by_provider.rotateproxy = {}; c.by_provider.rotateproxy[_last] = _bk(3529396103);
          c.by_provider.tokendun = {};    c.by_provider.tokendun[_last] = _bk(39513);
          c.by_provider['openai-nows'] = {}; c.by_provider['openai-nows'][_last] = _bk(38627);
          // 最早那天只有单号直连 —— 短档位里它必须消失
          c.by_provider.openai = {};      c.by_provider.openai[_first || _last] = _bk(4651131297);
        }
        c.provider_labels = { tokendun: 'TokenDun' };
        SNAPSHOT = JSON.stringify(_o);
      }
    } catch (e) { /* 快照形状变了就让 DOM 闸去发现 */ }
  })();

  var relayCalls = [];
  window.__relayCalls = relayCalls;   // 渲染闸要数「真发了几次 remove」（只有 sub+arg，没有 payload）
  var agyPushed = false;

// ── 中转站（relay）夹具 ──────────────────────────────────────────────────────
// ★ 形状**照抄 `relay-ctl status` / `usage` 的真实输出**（2026-09-09 实测键集），
//   不是我凭印象编的。夹具与真实响应对不上时,页面在 harness 里绿、真机上空 ——
//   本仓已经栽过三次「不打桩 ⇒ 落 default 返 null ⇒ 页面画空 ⇒ 假绿」。
// ★ `cost` 与 `actual_cost` 用**真实的两个数**（0.36 / 0.0863,差 4.2 倍）——
//   夹具里让它们相等的话,"两列合并成一列"的实现也能绿。
// ★ 中转站的 `daily.date` 是**本机自然日**（`monitor.py` 用 localtime 判今天，前端 `todayOf` 同口径）。
//   夹具原来用 `toISOString()`（UTC）：新加坡 00:00–08:00 之间「今天」那一行变成昨天，
//   默认夹具就画出「今天的按模型明细没取到」（评审 gemini 阶段 5）。
function localYmd(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
var RELAY_USAGE_OK = {
  balance: 69.88, unit: 'USD', plan: '钱包余额', valid: true, mode: 'unrestricted',
  today: { cost: 0.36, actual_cost: 0.0863, requests: 1, total_tokens: 39513 },
  total: { cost: 82.82, actual_cost: 26.39, requests: 513, total_tokens: 37700219,
           cache_read_tokens: 29405179 },
  rpm: 0, tpm: 0, avg_ms: 30274.9,
  // ★ 每天两个分解维度都有：四类 token（上游 daily_usage 直接给）+ 按模型
  //   （后端逐日查 `?start_date=D&end_date=D` 拿到）。夹具必须两个都带，
  //   否则图一层都画不出来、而"画不出来"和"这段时间没用过"长得一样。
  // ★★ **20 天**，且模型构成**随时间变化**：`gpt-5.6-luna` 只出现在第 0~4 天。
  //    这不是为了好看 —— 夹具若各天相同，「模型表跟随档位」那条闸换任何档位都得到
  //    同一张表，是个**空守卫**。有了这条，7d 里必须查不到 luna、30d 里必须查得到。
  daily: (function () {
    var out = [];
    for (var k = 19; k >= 0; k--) {
      var d = new Date(Date.now() - k * 86400000);
      var date = localYmd(d);
      var old = k >= 15;                       // 最早 5 天
      // ★★ **每天必须不一样。** 各天相同的话走势线画出来是一条直线,
      //    而"画的是这条序列"与"画的是一个常数"**在图上完全一样** —— 那条闸是空的。
      //    用 k 的确定性函数,不用随机:截图与 DOM 闸要可复现。
      var w = 0.55 + 0.45 * Math.sin(k * 1.1) + 0.25 * ((k % 3) / 2);
      var sc = function (v) { return Math.round(v * w); };
      var ms = old
        ? [{ model: 'gpt-5.6-luna', requests: sc(12), total_tokens: sc(480000),
             input_tokens: sc(90000), output_tokens: sc(6000),
             cache_read_tokens: sc(384000), cache_write_tokens: 0,
             cost: 2.4 * w, actual_cost: 0.6 * w }]
        : [{ model: 'gpt-5.5', requests: sc(40), total_tokens: sc(1600000),
             input_tokens: sc(280000), output_tokens: sc(17000),
             cache_read_tokens: sc(1303000), cache_write_tokens: 0,
             cost: 8.2 * w, actual_cost: 2.05 * w },
           { model: 'gpt-6-astra', requests: sc(9), total_tokens: sc(320000),
             input_tokens: sc(60000), output_tokens: sc(4000),
             cache_read_tokens: sc(256000), cache_write_tokens: 0,
             cost: 1.6 * w, actual_cost: 0.42 * w }];
      var agg = { requests: 0, total_tokens: 0, input_tokens: 0, output_tokens: 0,
                  cache_read_tokens: 0, cache_write_tokens: 0, cost: 0, actual_cost: 0 };
      for (var i = 0; i < ms.length; i++) {
        for (var f in agg) agg[f] += ms[i][f] || 0;
      }
      // ★ 每天的四类之和**必须等于** total_tokens（真实数据实测差 0），
      //   夹具对不上的话「分层精确」就成了假绿。
      agg.total_tokens = agg.input_tokens + agg.output_tokens
                       + agg.cache_read_tokens + agg.cache_write_tokens;
      out.push(Object.assign({ date: date, models: ms }, agg));
    }
    return out;
  })(),
  models: [
    { model: 'gpt-5.5', requests: 226, total_tokens: 21400000, input_tokens: 3982390,
      output_tokens: 174123, cache_read_tokens: 17243487, cache_write_tokens: 0,
      cost: 30.0, actual_cost: 8.12 },
    { model: 'gpt-6-astra', requests: 134, total_tokens: 9100000, input_tokens: 1500000,
      output_tokens: 80000, cache_read_tokens: 7520000, cache_write_tokens: 0,
      cost: 14.2, actual_cost: 3.51 }
  ],
  runway: { days: 30.1, per_active_day: 2.32, sample_days: 7, reason: null },
  // 取数看过的区间：夹具 daily 的 20 天（月初之后建的快照 ⇒ 本月不完整，KPI 写「≥」）。
  covered: [[localYmd(new Date(Date.now() - 19 * 86400000)), localYmd(new Date())]],
  usage_path: '/usage', fetched_at: Math.floor(Date.now() / 1000)
};
// ★★ 2026-09-09「一个 provider,两种上游」之后 `path` 恒指向**账号池那一份** ——
//    中转站不再有自己的 profile。`profile_stale` 整个消失(没有第二份文件可漂移),
//    新增 `relay_disabled`(登记着但被停用 ⇒ 代理退回账号池、用户以为在花钱)。
var POOL_TOML = '/Users/x/.codex/rotateproxy.config.toml';
var RELAY_ROUTES = {
  pool:    { state: 'pool', profile: 'rotateproxy', path: POOL_TOML },
  relay:   { state: 'relay', profile: 'tokendun', path: POOL_TOML,
             label: 'TokenDun', key_fp: 'sk-73a1…294 (0f39111c7caf)' },
  missing: { state: 'profile_missing', profile: 'tokendun', path: POOL_TOML,
             detail: 'rotateproxy.config.toml 不存在 ⇒ codex 会静默退回 base 配置' },
  // ★ 键名叫 `offroute` 不叫 `disabled`:`disabled` 已经是**条目**的状态
  //   (用户把这个中转站停用了),两者同名会让 relayRoute() 与 relayEntry() 互相打架。
  offroute:{ state: 'relay_disabled', profile: 'tokendun', path: POOL_TOML, label: 'TokenDun',
             detail: 'TokenDun 已停用 ⇒ 代理退回账号池。你以为在按量付费,实际扣的是订阅额度。' },
  orphan:  { state: 'orphan', profile: 'tokendun', path: POOL_TOML,
             detail: "路由指向 'tokendun',但它已不在登记表里 ⇒ 代理退回账号池。你以为在按量付费,实际扣的是订阅额度。" },
  corrupt: { state: 'route_corrupt', profile: null, path: '/Users/x/relay/route.local.json',
             detail: '路由文件不是合法 JSON: Expecting value: line 1 column 2 (char 1)' }
};
// ★ `key` 是**诱饵**:真实 `relay-ctl status` 的 payload 里没有它(只有 key_fp)。
//   放在这里是为了让「页面不许渲染完整 key」那条闸**真的能失败** ——
//   夹具里没有完整 key 的话,那条断言永远红不了,是个空守卫。
var RELAY_ROW = { id: 'tokendun', label: 'TokenDun', base_url: 'https://api.tokendun.com/v1',
                  enabled: true, usage_path: '/usage', model: null,
                  key: 'sk-DECOY-must-never-be-rendered-0000000000',
                  key_fp: 'sk-73a1…294 (0f39111c7caf)', added_at: '2026-09-09T10:28:24+0800' };
function relayMode() { return p.get('relay') || 'relay'; }
function relayRoute() {
  var m = relayMode();
  return RELAY_ROUTES[m] || RELAY_ROUTES[m === 'never' || m === 'unreachable' || m === 'auth' || m === 'nobill' || m === 'empty' ? 'relay' : 'relay'];
}
// ★★ **稀疏夹具**：只在少数几天有请求，散布在一大段自然日里 ——
//    还原真实快照的形状（中转站是"撞额度才切过来的备胎"）。
//    稠密夹具下「窗口按自然日切」与「按最近 N 个有数据的日子切」**结果完全一样**，
//    那条闸换任何档位都绿，是个空守卫。这份夹具专门让两者分开。
function relaySparseDaily() {
  var out = [], offsets = [0, 2, 9, 16, 23];   // 今天/2/9/16/23 天前
  for (var i = 0; i < offsets.length; i++) {
    var d = new Date(Date.now() - offsets[i] * 86400000);
    out.push({ date: localYmd(d), requests: 10,
               total_tokens: 1000000, input_tokens: 200000, output_tokens: 20000,
               cache_read_tokens: 780000, cache_write_tokens: 0,
               cost: 5, actual_cost: 1.25,
               models: [{ model: 'gpt-5.5', requests: 10, total_tokens: 1000000,
                          input_tokens: 200000, output_tokens: 20000,
                          cache_read_tokens: 780000, cache_write_tokens: 0,
                          cost: 5, actual_cost: 1.25 }] });
  }
  return out.sort(function (a, b) { return a.date < b.date ? -1 : 1; });
}

// ★★ **混币夹具**：两家中转站，一家 USD、一家 CNY。
//    KPI 条原来把所有中转站的钱**直接相加**、币种取第一家的 —— 得到的数
//    不属于任何一种货币，而它长得和一个正常金额一模一样。
//    ⚠️ 单家夹具下"相加"与"不相加"**结果完全相同**，那条闸恒绿 —— 空守卫。
//    这份夹具专门让两者分开（另一半："读不到币种"也自成一类，与 USD 同样不可加）。
// ★ `?relay=pair`：同一平台（同 host）两把 key、同币种 ⇒ 一个平台节点下两个账户，「合计 / 单个」视角才出现。
var RELAY_ROW2 = { id: 'tokendun2', label: 'TokenDun-备用', base_url: 'https://api.tokendun.com/v1',
                   enabled: true, usage_path: '/usage', model: null,
                   key: 'sk-DECOY-must-never-be-rendered-1111111111',
                   key_fp: 'sk-9c0e…a17 (5b1d2e7f9a30)', added_at: '2026-10-01T09:00:00+0800' };
function relayPairEntries() {
  return [Object.assign({ id: 'tokendun', label: 'TokenDun', base_url: RELAY_ROW.base_url, key_fp: RELAY_ROW.key_fp,
                          ok: true, state: 'ok' }, { data: RELAY_USAGE_OK }),
          { id: 'tokendun2', label: RELAY_ROW2.label, base_url: RELAY_ROW2.base_url, key_fp: RELAY_ROW2.key_fp,
            ok: true, state: 'ok', data: Object.assign({}, RELAY_USAGE_OK, { balance: 12.4,
              today: { cost: 0.9, actual_cost: 0.21, requests: 3, total_tokens: 98000 } }) }];
}
function relayMixedEntries() {
  var mk = function (id, label, unit, bal) {
    return { id: id, label: label, base_url: RELAY_ROW.base_url, key_fp: RELAY_ROW.key_fp,
             ok: true, state: 'ok',
             data: Object.assign({}, RELAY_USAGE_OK, { unit: unit, balance: bal }) };
  };
  return [mk('tokendun', 'TokenDun', 'USD', 69.88),
          mk('cnrelay', '国内中转', 'CNY', 420.5)];
}

function relayEntry() {
  var m = relayMode();
  // ★ `?relay=zero`：出口账户余额 = 0（P8 横幅最高优先级）。`balance: 0` 是**读到了 0**，不是读不到。
  if (m === 'zero') return { id: 'tokendun', label: 'TokenDun', base_url: RELAY_ROW.base_url, key_fp: RELAY_ROW.key_fp,
    ok: true, state: 'ok', data: Object.assign({}, RELAY_USAGE_OK, { balance: 0,
      runway: { days: 0, per_active_day: 2.32, sample_days: 7, reason: null } }) };
  if (m === 'sparse') {
    return { id: 'tokendun', label: 'TokenDun', base_url: RELAY_ROW.base_url,
             key_fp: RELAY_ROW.key_fp, ok: true, state: 'ok',
             data: Object.assign({}, RELAY_USAGE_OK, { daily: relaySparseDaily() }) };
  }
  var base = { id: 'tokendun', label: 'TokenDun', base_url: RELAY_ROW.base_url, key_fp: RELAY_ROW.key_fp };
  // ★ `disabled` 是**用户的选择**,不是故障 —— `collect()` 对它返回的 payload 没有 `ok`,
  //   页面原来把它渲染成"用量读不到（disabled）：undefined"。这个态必须有夹具。
  if (m === 'disabled') return { id: 'tokendun', label: 'TokenDun', state: 'disabled' };
  // ★★★ `stale` = **这次没取到，但保留了上一次的 `data`**（`monitor.py::collect` 的
  //   失败分支就是这么写的：`res = {**res, "data": old, "stale": True, "stale_since": …}`）。
  //   在这之前**没有这一档夹具** —— 而它恰恰是生产里最常见的失败形态：
  //   `unreachable`/`auth` 那两档根本没有 `data`，走的是"读不到"那条路，
  //   而这一档是"读到的是旧的"，两者在页面上必须长得不一样。
  //   没有它，「余额旁的旧读数标记」一个像素都验不到（而截图会正常渲染、探针报干净）。
  if (m === 'stale') return Object.assign(base, {
    ok: false, state: 'unreachable', detail: 'URLError: no route to host',
    stale: true, stale_since: Math.floor(Date.now() / 1000) - 137 * 60,
    data: RELAY_USAGE_OK });
  if (m === 'unreachable') return Object.assign(base, { ok: false, state: 'unreachable', detail: 'URLError: no route to host' });
  if (m === 'auth') return Object.assign(base, { ok: false, state: 'auth', http: 401, detail: '{"code":"INVALID_API_KEY"}' });
  if (m === 'nobill') return Object.assign(base, { ok: false, state: 'no_billing_endpoint',
    detail: '试过 /usage, /dashboard/billing/usage, /dashboard/billing/subscription,没有一条返回可解析的 JSON' });
  if (m === 'never') return Object.assign(base, { ok: true, state: 'ok', data: Object.assign({}, RELAY_USAGE_OK, {
    balance: null, today: { cost: null, actual_cost: null, requests: null, total_tokens: null },
    runway: { days: null, per_active_day: null, sample_days: 1, reason: '活跃日样本不足 2 天' } }) });
  return Object.assign(base, { ok: true, state: 'ok', data: RELAY_USAGE_OK });
}

  function invoke(cmd, args) {
    ipc[cmd] = (ipc[cmd] || 0) + 1;
    // 记下每次 setSize 的目标高度 —— 菜单栏的高度就是这么定的,只数次数看不出设成了多少
    if (cmd.indexOf('set_size') >= 0 || cmd.indexOf('setSize') >= 0) {
      try { sizes.push(JSON.stringify(args)); } catch (e) { sizes.push('?'); }
    }
    args = args || {};
    // 空闲托盘：菜单栏 webview 最后一次交给 Rust 的那份（选了谁、剩多少、红不红）
    if (cmd === 'set_idle_tray') { try { idleTray = JSON.parse(JSON.stringify(args)); } catch (e) { idleTray = '?'; } }
    switch (cmd) {
      case 'plugin:event|listen':
        (listeners[args.event] = listeners[args.event] || []).push(args.handler);
        return Promise.resolve(1);
      case 'plugin:event|unlisten':
      case 'plugin:event|emit_to':
        return Promise.resolve(null);
      case 'plugin:event|emit':
        // ★ 记下**发了哪个事件**。验"点菜单栏的账号跳去哪一页"只能靠它 ——
        //   `ipc` 只数 run_traffic/read_traffic_snapshot,截图也看不出跳转意图
        //   (菜单栏与主窗是两个 webview,harness 里只渲染其中一个)。
        emitted.push(args.event + (args.payload != null ? '=' + args.payload : ''));
        try { emittedJ.push({ event: args.event, payload: args.payload }); } catch (e) { emittedJ.push({ event: args.event, payload: '?' }); }
        fire(args.event, args.payload);
        // 空闲额度格子（`?hv=idle`）：harness 里没有菜单栏 webview，由这里替它回一份格子
        if (args.event === 'idle-panel-want' && location.pathname.indexOf('harness-tpshover') >= 0 && p.get('hv') === 'idle')
          setTimeout(function () { fire('idle-panel', HV_IDLE_CELLS(p.get('hvcells'))); }, 0);
        // 刘海屏版空闲格子（`?nt=I`）同一份格子
        if (args.event === 'idle-panel-want' && location.pathname.indexOf('harness-notch') >= 0 && p.get('ntcells') !== 'none')
          setTimeout(function () { fire('idle-panel', HV_IDLE_CELLS(p.get('ntcells'))); }, 0);
        return Promise.resolve(null);
      // ★ `?snap_delay=<ms>` 让快照**异步**送达。默认 0(同步)保持既有行为。
      //   真机上快照是 `invoke` 异步取的,内容会在挂载**之后**才长出来 —— harness 原本内联同步给,
      //   按设计绕开了这个竞态,也就**看不见**任何"挂载时量了一次、之后再没量"的缺陷。
      //   菜单栏高度钉死在 PANEL_H_MIN 那个 bug 就是这么漏掉的。
      // ★ 宽窗口（年度 / 自定义 >90 天）的快照。**不打桩就是假绿**：落到 default 返回 null
      //   ⇒ 换到年度档时 `data` 恒 null ⇒ 页面画骨架、零报错、sweep 报干净，
      //   而我们要验的正是那一档画成什么样。同 `read_rotation_snapshot` 那条的教训。
      //   ⚠️ 这里返回的是**同一份 90 天快照** —— 所以年度视图里 1~5 月是空格。
      //   那不是 bug，正是本机今天的真实形态（数据从 2026-03 才开始），也正好验到补零那一路。
      // ★ agy 账号池。**不打桩就是假绿**：落到 default 返回 null ⇒ 池恒为空 ⇒
      //   Google 档永远退回那张只读卡，而"一号一卡 + 切换"整条路一个像素都验不到。
      //   `?agypool=n` 造 n 个号（默认 0 = 没建池，就是退回只读卡那条路）。
      case 'read_dawn_status':
        return Promise.resolve(JSON.stringify(DAWN_STATUS('codex')));
      case 'read_agy_pool': {
        var n = parseInt(p.get('agypool') || '0', 10);
        if (!n) return Promise.resolve(null);
        var accs = {}, subs = [];
        for (var i = 0; i < n; i++) {
          var sub = 'sub' + i;
          subs.push(sub);
          accs[sub] = {
            // ★ `?agyname0=<名字>` 换第一个号的名字（2026-10-16：长名字 + ULTRA + 当前 + 下一个 把「当前」挤成两行）。
            label: (i === 0 && p.get('agyname0')) || (p.get('anon') === '1' ? AGY_ANON : ['qq55', 'Asen', 'Huo', 'wing'])[i] || ('acc' + i),
            email: 'demo' + i + '@example.com',
            // ★ 档位（2026-10-15）：第一个号 Ultra（当值 ⇒ Hero / 卡 / 菜单栏都看得到徽章），其余 Pro（不画）。
            plan: i === 0 ? 'ultra' : 'pro',
            // 第二个号刻意造成**低额度**：选号阈值那条线只有在有高有低时才看得出来。
            quota: { gemini: { remaining: i === 1 ? 0.08 : 0.956,
                               reset: new Date(__NOW__ * 1000 + 4300000).toISOString() },
                     claude: { remaining: 1, reset: new Date(__NOW__ * 1000 + 18000000).toISOString() } },
            quota_at: __NOW__,
            // ★ 第三个号刻意摘出轮换池 —— 按号开关那一档只有有高有低时才看得出来。
            rotate_off: (i === 2 && p.get('agyrotoff') !== '0') || undefined,
            // ★★ `weekly_seen` = **上次当值时读到的周额度**（`agy-quota` 归属明确时写）。
            //   非当值号的周窗口不可能现取（云端那条结构上没有周，2026-09-15 实测），
            //   但它当值时读到过。只给**第一个**号，这样同屏就能对照出
            //   「有记忆的号画降级行」与「从没当值过的号仍画非当值号」两种形态。
            weekly_seen: i === 0 ? {
              at: __NOW__ - 7200,
              buckets: { 'gemini-weekly': { remaining_percent: 93.4,
                                            reset_at: __NOW__ + 380000, group: 'Gemini Models' } },
            } : undefined,
            // ★★★ **卡片真正吃的是这个**（`toSnapshot` 只读 `quota_summary`）。
            //   上面那个 `quota` 是 B53 之前的旧形状，只剩选号与 CLI 打印在用。
            //   ⚠️ 2026-09-16 发现夹具**一直没跟上 B53**：只给旧形状 ⇒ `groups` 为空 ⇒
            //      `ok=false` ⇒ agy 卡在 harness 里**永远渲染降级态**，
            //      而降级态照常渲染、零报错，看着完全像通过。
            //      于是「页脚画的是什么」这一格**根本验不到** —— 本仓那条
            //      「sweep 报干净之前先正面证明被测的东西真的渲染了」的又一次实证。
            quota_summary: [
              { displayName: 'Gemini Models', buckets: [
                { bucketId: 'gemini-5h', window: '5h',
                  remainingFraction: i === 1 ? 0.08 : 0.956,
                  resetTime: new Date(__NOW__ * 1000 + 4300000).toISOString() },
                { bucketId: 'gemini-weekly', window: 'weekly',
                  remainingFraction: i === 1 ? 0.41 : 0.934,
                  resetTime: new Date(__NOW__ * 1000 + 380000000).toISOString() } ] },
              { displayName: 'Claude + GPT Models', buckets: [
                { bucketId: 'claude-5h', window: '5h', remainingFraction: 1,
                  resetTime: new Date(__NOW__ * 1000 + 18000000).toISOString() } ] },
            ],
          };
        }
        // ★ `quota_ran_at` = 「上次**尝试过** `agy-rotate quota`」。给成"刚跑过"，
        //   否则 harness 一挂载就触发自动保鲜，把打桩的 `run_agy_rotate` 卷进截图时序。
        //   ⚠️ 要验"过期会自动取"那条路径，传 `?agystale=1` 把它推回 0。
        // ★ `?agyodd=unknown|verify` 只改**第一个**号（当值号 ⇒ Hero 也看得到）：
        //   unknown = 周那个桶不带 `remainingFraction`（proto3 省略零值，2026-10-15 #2）；
        //   verify  = 取额度被 403 VALIDATION_REQUIRED 拒绝，带验证链接（#3）。
        var odd = p.get('agyodd'), a0 = accs[subs[0]];
        // ★ `?agyodd=floating`：第一个号的 5h 闲置（reset 跟着 now 滑），账本已判 floating ⇒ 画「未启动」。
        if (odd === 'floating' && a0) {
          var r5 = a0.quota_summary[0].buckets[0];
          r5.remainingFraction = 1; a0.quota.gemini.remaining = 0.934;
          var rs5 = __NOW__ + 18000; r5.resetTime = new Date(rs5 * 1000).toISOString();
          a0.quota_anchor = { 'gemini-5h': { state: 'floating', slides: 3, used_max: 0, reset: rs5 } };
        }
        // ★ `?agyodd=carried`：第一个号的 Gemini 组这次云端没回来，沿用 25 分钟前那份（`seenAt`），2026-10-16。
        //   ★ 每个号都标：当值号的卡走本机 RPC 那份（能证明归属时 `snapshotOf` 优先它），只标第一个会落空。
        if (odd === 'carried') {
          subs.forEach(function (sb) {
            var qs = accs[sb].quota_summary;
            if (qs && qs[0]) qs[0].buckets.forEach(function (b) { b.seenAt = __NOW__ - 1500; });
          });
        }
        // ★ `?agyodd=expired`：周那格沿用超过一天（`CARRY_MAX_SECS`）⇒ 数被删、`seenAt` 留着 ⇒ 画「旧读数已过期」。
        if (odd === 'expired') {
          subs.forEach(function (sb) {
            var qs = accs[sb].quota_summary, wk = qs && qs[0] && qs[0].buckets[1];
            if (wk) { delete wk.remainingFraction; wk.seenAt = __NOW__ - 90000; }
          });
        }
        if (odd === 'unknown' && a0) {
          delete a0.quota_summary[0].buckets[1].remainingFraction;
          a0.quota.gemini = { remaining: null, reset: null };
        } else if (odd === 'verify' && a0) {
          a0.quota = null; a0.quota_summary = null; a0.weekly_seen = undefined;
          a0.quota_err = '额度 HTTP 403 VALIDATION_REQUIRED: Verify your account to continue.';
          a0.quota_err_reason = 'VALIDATION_REQUIRED';
          a0.quota_err_url = 'https://accounts.google.com/signin/continue?flowName=GlifWebSignIn';
        }
        return Promise.resolve(JSON.stringify({
          accounts: accs, live_seen: subs[0],
          quota_ran_at: p.get('agystale') === '1' ? 0 : __NOW__,
        }));
      }
      case 'run_agy_rotate':
        // ⚠️ 打桩里读载荷一律用 **`args`** —— 这个 stub 的签名就是 `invoke(cmd, args)`。
        //    我曾在这两条分支里写成 `a.args`：`a` 不在作用域 ⇒ ReferenceError，
        //    而它发生在 `await invoke(...)` 里、被调用方的 `catch` 吞掉 ⇒
        //    **`errors` 探针里一个字都没有**，页面只是安静地少了「当前」徽章与开关状态。
        //    这正是本仓那条「打桩缺口 ⇒ 零渲染看着像通过」的又一次。
        // ★ `live` 回的是 JSON（「**现在**钥匙串里是谁」），不是人话。回 'ok' 会让
        //   `JSON.parse` 抛，然后「当前」徽章整个消失 —— 而那正好长得像"池是空的"。
        //   `?agydrift=1` 专门渲染"被别的 agy 进程抢回去了"那一态。
        // ★ 新增的几条也要打桩，否则 `JSON.parse` 抛 ⇒ 整块静默降级。
        // ★★ `?agy_delay=<ms>` 让这两条**异步**送达（默认 0，保持既有行为）。
        //    真机上它们各起一个 python 子进程，实测各约 80ms；harness 原本同步回，
        //    于是「现读回来之前 `liveSub` 是什么」这个中间态窄到采不着 ——
        //    而 2026-09-14 用户报的「切档跳来跳去」**整个就发生在那个窗口里**。
        //    同 `?snap_delay=`：打桩同步给 = 按设计绕开竞态 = 看不见任何竞态缺陷。
        // ★ 记下每次调用（同 `__RUN_ROTATE__`）：交互闸要能数「Gemini 档点了删除之后到底发没发 remove」。
        (window.__RUN_AGY__ = window.__RUN_AGY__ || []).push(args.args || []);
        var _agyD = parseInt(p.get('agy_delay') || '0', 10);
        var _later = function (v) {
          if (!_agyD) return Promise.resolve(v);
          return new Promise(function (res) { setTimeout(function () { res(v); }, _agyD); });
        };
        if ((args.args || [])[0] === 'auto-switch') {
          return _later(JSON.stringify({ enabled: p.get('agyauto') !== '0' }));
        }
        if ((args.args || [])[0] === 'live') {
          var np = parseInt(p.get('agypool') || '0', 10);
          var lsubs = []; for (var li = 0; li < np; li++) lsubs.push('sub' + li);
          var drift = p.get('agydrift') === '1' && np > 1;
          return _later(JSON.stringify({
            sub: drift ? lsubs[1] : (lsubs[0] || null),
            email: null,
            live_seen: lsubs[0] || null,
            drifted: drift,
          }));
        }
        // ★ 探针（`--json`，2026-10-15 起 GUI 要拿 5h 前后对比出 toast）。回 'ok' 会 `JSON.parse` 失败、
        //   页面挂一条「探针输出读不懂」—— 而那正好长得像探针坏了。`?agyprobe=flat` = 5h 没降那一态。
        if ((args.args || [])[0] === 'probe') {
          var flat = p.get('agyprobe') === 'flat';
          return _later(JSON.stringify([{ label: /^[^-]/.test((args.args || [])[1] || '') ? args.args[1] : 'qq55', ok: true, note: '答「ok」',
            usage: { total_tokens: 15195 },
            q5h: { before: 100, after: flat ? 100 : 99.6, reset: __NOW__ + 17970, started: !flat } }]));
        }
        // ★ 定时探针胶囊的读回（2026-10-15）。不打桩 ⇒ 落到 'ok' ⇒ JSON.parse 抛 ⇒ 胶囊恒「关」，
        //   而「关」本身是一个合法态 —— 看着完全像通过。`?dawn=on|off|ran`，缺省 off。
        if ((args.args || [])[0] === 'dawn-probe' && (args.args || []).indexOf('--status') >= 0) {
          return _later(JSON.stringify(DAWN_STATUS('agy')));
        }
        // ★ 借用开关的读回（设置页）。`?agyborrow=0` 渲染「已关闭」那一态。
        if ((args.args || [])[0] === 'borrow' && (args.args || []).indexOf('--status') >= 0) {
          return _later(JSON.stringify({ borrow: p.get('agyborrow') !== '0' }));
        }
        return _later('ok');
      case 'read_traffic_snapshot_days':
      case 'read_traffic_snapshot':
      case 'run_traffic': {
        var dly = parseInt(p.get('snap_delay') || '0', 10);
        if (!dly) return Promise.resolve(SNAPSHOT);
        return new Promise(function (res) { setTimeout(function () { res(SNAPSHOT); }, dly); });
      }
      // ★ **脱敏** fixture。真实 state.json 的邮箱/account_id 能认人,绝不进伺服目录;
      //   结构、额度、套餐、到期日保留真实形状,否则量不出真实排版。
      // ★★ 装机链路总闸。**必须打桩** —— 落到 default 返回 null 会被 `useIntegration` 的
      //   catch 接住,合成 `unknown`(琥珀「判定不了」),于是每张截图都挂着一条**不该有的**
      //   告警,而页面照常渲染、零报错。这正是本文件反复记的那类「打桩缺口 = 假绿」,
      //   只是这次方向相反:不是看不见,是永远看见一条假的。
      //   `?integ=ready|notinst|broken|noacc|unknown`,缺省 `ready`(= 不画横幅)。
      // Connector 的 plan 必须打桩 —— 不打的话面板只会画出「读不到接入状态」,
      // 而那看起来像功能坏了。`?conn=fresh|mixed|ready|blocked`,缺省 `mixed`。
      // 注意:这段 JS 是从 Python 写进来的,**注释和字符串里都不要出现反斜杠转义** ——
      // 多一层转义会把它变成真换行,把注释劈成两半/把字符串截断,整个 harness 脚本
      // 解析失败 ⇒ React 从未挂载 ⇒ 截图一片空白。2026-09-19 实测踩过两次,
      // 第二次正是那条**警告本身**被转义掉的。换行一律用 NL 变量拼。
      case 'connector_plan': {
        var _c = p.get('conn') || 'mixed';
        var NL = String.fromCharCode(10);
        var BT = String.fromCharCode(96);
        var mk = function (id, title, why, state, detail, preview, optional) {
          return { id: id, title: title, why: why, state: state,
                   detail: detail, preview: preview || '', optional: !!optional };
        };
        var PROV = [
          '# >>> codexbar-connector managed >>>',
          '[model_providers.rotateproxy]',
          'name = "codex-rotate proxy"',
          'base_url = "http://127.0.0.1:8011"',
          'wire_api = "responses"',
          'supports_websockets = false',
          '# <<< codexbar-connector managed <<<'
        ].join(NL);
        var st = function (a, b, c, d, e, f) {
          return [
            mk('runtime', '准备运行时', '★ 复制到数据目录，不指向 App 内部', a,
               '18 个文件 → ~/Library/Application Support/com.doushutangmu.codexbar/runtime'),
            mk('provider', '写入 model provider', 'codex 靠它知道请求要发给本机代理', b,
               '只写托管标记之间那一段，config.toml 里你自己的内容一个字节都不动', PROV),
            mk('profile', '建 profile overlay',
               '缺了它 codex 不报错，会静默退回单号直连 —— 和正常运行长得一模一样', c,
               '~/.codex/rotateproxy.config.toml'),
            mk('entries', '建命令入口', 'cxp 走代理轮换 · cxd 单号直连 · codex-rotate 管池子', d,
               '缺：cxp、cxd、codex-rotate、agy-rotate'),
            mk('services', '装常驻服务（launchd）',
               '轮换代理要一直在；额度要自动刷新。全部用户级，不需要 sudo', e,
               '缺：proxy、quotad'),
            mk('wrapper', '让 ' + BT + 'codex' + BT + ' 本身也走轮换',
               '不装这一步，敲 codex 仍是官方单号直连；装了之后 cxd 是唯一的直连入口', f,
               '~/.local/bin/codex → runtime/scripts/codex-wrapper-with-logout-guard.sh',
               '', true)
          ];
        };
        var body;
        if (_c === 'fresh') body = { steps: st('todo','todo','todo','todo','todo','todo'), ready: false };
        else if (_c === 'ready') body = { steps: st('done','done','done','done','done','done'), ready: true };
        else if (_c === 'blocked') body = { steps: st('blocked','todo','todo','todo','todo','todo'),
                                            ready: false, blocked: true };
        else body = { steps: st('done','external','todo','done','done','external'), ready: false };
        body.runtime = '~/Library/Application Support/com.doushutangmu.codexbar/runtime';
        body.inplace = false; body.port = 8011; body.blocked = !!body.blocked;
        body.codex_home = '~/.codex'; body.local_bin = '~/.local/bin';
        return Promise.resolve(JSON.stringify(body));
      }
      case 'connector_apply':
      case 'connector_remove':
        return Promise.resolve(JSON.stringify({ ok: true, done: [], notes: [], removed: [], kept: [] }));
      case 'read_integration': {
        var _ig = p.get('integ') || 'ready';
        var _mk = function (state, level, lines) {
          return JSON.stringify({ level: level, state: state, checks: [],
                                  lines: lines, port: 8011, accounts: 9 });
        };
        if (_ig === 'notinst') return Promise.resolve(_mk('not_installed', 'warn', [
          'ℹ️  接入闸:这台机器**只装了用量看板那一半**,没有轮换能力。',
          '     ★ 最省事:打开 CodexBar → 设置 → 「账号池接入(Connector)」,逐项勾选即可。']));
        if (_ig === 'broken') return Promise.resolve(_mk('broken', 'warn', [
          '⚠️  接入闸:**接线断了** —— codex 对此不报错,会静默退回单号直连。',
          '     ✗ profile overlay:~/.codex/rotateproxy.config.toml 不存在']));
        if (_ig === 'noacc') return Promise.resolve(_mk('no_accounts', 'warn', [
          '⚠️  接入闸:接线齐全,但**池子是空的** —— 轮换无号可换。',
          '     修:codex-rotate login(★ 不要用 `codex login`,它会吊销当前号)。']));
        if (_ig === 'unknown') return Promise.resolve(_mk('unknown', 'unknown', [
          '⚠️  接入闸:**判定不了** —— 这不等于「没问题」。',
          '     ❔ model_provider 块:~/.codex/config.toml 存在但读不到(权限?)']));
        return Promise.resolve(_mk('ready', 'ok', ['  ✅ 接入闸:已接入账号池(9 个号)']));
      }
      // run_rotate 的桩。默认什么都不做(返回 null),只有 `priority --set` 要真的改 STATE ——
      // 否则总览拖完顺序、`read_state` 回来的还是旧的,端到端闸验的就不是真链路了。
      // ★ 2026-09-19 加:codex 档的拖拽顺序改写进 state.json(它就是轮换优先级)。
      // ★★★ 续航条的桩挂在 **`read_rotation_board`** 上，不是 `run_rotate`。
      //   2026-09-21 事故：它原来复用 `run_rotate`，而那条命令无条件
      //   `emit("state-changed")`，hook 又监听同一个事件 ⇒ 自激回环
      //   （实测 12 秒 789 个 python 子进程）。真实链路已改走专用只读 IPC，
      //   **桩必须跟着改** —— 否则 harness 验的是一条产品里已经不存在的路。
      // ★★ Gemini 总览的续航条（2026-09-24 与 codex 对齐）。**必须按池夹具真算**，
      //   规则与 `agy/pool.py::pick/board` 同一把键：置顶 > 容量；停用 / 见底（< 15%）进「不可用」。
      //   `?agypin=<label,…>` 置顶、`?agyborrow=0` 关借用、`?agystrand=1` 全部不可用。
      //   ⚠️ 迟滞 5pp 这里不模拟（`next` = 队首）—— harness 只验画面，选号语义由 Python 闸守。
      case 'read_agy_board':
        return invoke('read_agy_pool', {}).then(function (raw) {
          if (!raw) return JSON.stringify({ cur: null, cur_ago_min: null, next: null, next_reason: 'none',
            queue: [], rest: [], weekly_left_pp: 0, burn_pp_per_hour: null,
            runway_hours: null, rate_span_h: null, first_reset_h: null, outlasts_reset: false,
            samples: 0, last_sample_min: null });
          var pool = JSON.parse(raw), accs = pool.accounts || {};
          var pins = (p.get('agypin') || '').split(',').filter(Boolean);
          var subOf = {}; Object.keys(accs).forEach(function (s2) { subOf[accs[s2].label] = s2; });
          var pinned = pins.map(function (l) { return subOf[l]; }).filter(Boolean);
          var strand = p.get('agystrand') === '1';
          var rem = function (a) { var g = (a.quota || {}).gemini;
            return g && typeof g.remaining === 'number' ? g.remaining * 100 : null; };
          var usable = function (s2) { var a = accs[s2]; var r = rem(a);
            return !strand && !a.rotate_off && !(r != null && r < 15); };
          var ent = function (s2) {
            var a = accs[s2] || {}, wins = [];
            ((a.quota_summary || [])[0] || { buckets: [] }).buckets.forEach(function (b) {
              wins.push({ label: b.window === 'weekly' ? '周' : '5h',
                          rem: typeof b.remainingFraction === 'number' ? Math.round(b.remainingFraction * 100) : null,
                          // 同 `agy/pool.py::_floating`：账本判 floating 的窗口说「未启动」。
                          reset: ((a.quota_anchor || {})[b.bucketId] || {}).state === 'floating' ? '未启动'
                            : b.window === 'weekly' ? '4d9h' : '1h11m' });
            });
            var r = rem(a), pi = pinned.indexOf(s2);
            return { aid: s2, label: a.label, email: a.email, plan: a.plan || null,
                     pin: pi < 0 ? null : pi + 1, off: !!a.rotate_off, dead: false,
                     cool_min: (strand || (r != null && r < 15)) && !a.rotate_off ? 71 : 0,
                     wins: wins,
                     tightest: !wins.length || wins.some(function (w) { return w.rem == null; }) ? null
                       : Math.min.apply(null, wins.map(function (w) { return w.rem; })),
                     weekly: (wins.filter(function (w) { return w.label === '周'; })[0] || {}).rem };
          };
          var ids = Object.keys(accs);
          var ok = ids.filter(usable);
          ok.sort(function (x, y) {
            var px = pinned.indexOf(x) < 0 ? pinned.length : pinned.indexOf(x);
            var py = pinned.indexOf(y) < 0 ? pinned.length : pinned.indexOf(y);
            if (px !== py) return px - py;
            return (rem(accs[y]) || 0) - (rem(accs[x]) || 0);
          });
          var q = ok.map(ent), rest = ids.filter(function (s2) { return ok.indexOf(s2) < 0; }).map(ent);
          // ★ 与真后端一致：`cur` = **现读**钥匙串（`live --json` 那份），不是种子 `live_seen`。
          var _np = Object.keys(accs).length;
          var live = (p.get('agydrift') === '1' && _np > 1) ? 'sub1' : pool.live_seen;
          return JSON.stringify({
            cur: live && accs[live] ? ent(live) : null, cur_ago_min: null,
            next: q[0] || null, next_reason: q.length ? 'new' : 'none',
            queue: q, rest: rest,
            weekly_left_pp: q.reduce(function (t2, e) { return t2 + (e.weekly || 0); }, 0),
            burn_pp_per_hour: null, runway_hours: null, rate_span_h: null, first_reset_h: null,
            outlasts_reset: false, samples: 0, last_sample_min: null });
        });
      case 'read_rotation_board': {
        {
          // ★★ **必须真的按 STATE 算**，不能返回一份写死的样本 —— 闸要验的正是
          //   「置顶排最前、停用不进队列、取不到写 —」，写死的话这些一条都验不到，
          //   而截图会正常渲染、探针报干净。
          var _pin = STATE.pinned || [];
          var _pw = p.get('relay') === 'long' ? 48 : 4.0;
          var _rem = function (sl, k) {
            var w = (sl.quota || {})[k] || {};
            return w.used_percent == null ? null : Math.round(100 - w.used_percent);
          };
          var _ent = function (aid) {
            var sl = (STATE.slots || {})[aid] || {};
            var ws = [];
            if (_rem(sl, 'primary') != null) ws.push({ label: '5h', rem: _rem(sl, 'primary'), reset: '4h19m' });
            if (_rem(sl, 'secondary') != null) ws.push({ label: '周', rem: _rem(sl, 'secondary'), reset: '5d0h' });
            var pi = _pin.indexOf(aid);
            return { aid: aid, label: sl.label, email: sl.email, plan: sl.plan,
                     pin: pi < 0 ? null : pi + 1, off: !!sl.rotate_off, dead: !!sl.auth_dead,
                     cool_min: Math.max(0, Math.floor(((sl.cooling_until || 0) - Date.now() / 1000) / 60)), wins: ws,
                     tightest: ws.length ? Math.min.apply(null, ws.map(function (w) { return w.rem; })) : null,
                     weekly: _rem(sl, 'secondary'),
                     // 与 `codex-rotate::_eta5h` 同形：全池 3 次用完、一整窗 4.0 分钟（2026-10-15 真机数）
                     eta5h: _rem(sl, 'primary') == null || sl.plan === 'pro' ? null
                       : { left_min: Math.round(10 * _pw * _rem(sl, 'primary') / 100) / 10, per_window_min: _pw, n: 3, scope: 'pool' } };
          };
          var _ids = Object.keys(STATE.slots || {});
          // ★★★ `?pool=stranded` 专验「池子见底」那一支 —— 一个号都不可用时，
          //   代理会**忽略用户的停用设置**去借一个号，而那条 ⚠️ 只写在 proxy.log 里。
          //   2026-09-21 真实发生过（5 冷却 / 3 停用 / 1 失效），用户看到的是
          //   「轮换失效了，禁用的账号也被使用了」。没有这个开关，那条告警
          //   **一个像素都验不到**，而截图会正常渲染、探针报干净。
          var _strand = p.get('pool') === 'stranded';
          var _rec = p.get('pool') === 'recovered';
          var _ok = _strand ? [] : _ids.filter(function (a2) { var s2 = STATE.slots[a2];
            return !s2.auth_dead && !s2.rotate_off && !((s2.cooling_until || 0) > Date.now() / 1000); });
          // 与 `proxy.py::_sort_avail` 同一把键：(套餐档, 置顶, 最紧已用%)
          _ok.sort(function (x, y) {
            var ex = _ent(x), ey = _ent(y);
            var tx = (STATE.slots[x].plan === 'pro') ? 1 : 0, ty = (STATE.slots[y].plan === 'pro') ? 1 : 0;
            if (tx !== ty) return tx - ty;
            var px = ex.pin == null ? _pin.length : ex.pin - 1;
            var py = ey.pin == null ? _pin.length : ey.pin - 1;
            if (px !== py) return px - py;
            return (100 - (ex.tightest || 0)) - (100 - (ey.tightest || 0));
          });
          var _q = _ok.map(_ent), _rest = _ids.filter(function (a2) { return _ok.indexOf(a2) < 0; }).map(_ent);
          // ★ 见底夹具要让冷却/停用**都有**，否则「N 冷却 · M 已停用」那行验不全；
          //   并给一个真实的冷却分钟数，「最快 X 分钟后回来」才有东西可断言。
          if (_strand) _rest.forEach(function (e, i) {
            if (!e.off && !e.dead) { e.cool_min = 54 + i; }
          });
          var _wk = _q.reduce(function (t2, e) { return t2 + (e.weekly || 0); }, 0);
          // ★ `?runway=none` 专验「取不到写 —，不写 0」那一支 —— 没有这个开关，
          //   那条分支一个像素都验不到（本仓反复记的假绿）。
          var _none = p.get('runway') === 'none';
          // ★ 与真 CLI 同一个耦合：`_burst` 为 None ⇔ 没有一个号带 `eta5h`（`codex-rotate::_burst`）。
          //   只关 burst、留着 eta5h 的话，续航条照样按每号配速算出数字，而说明行说「算不出来」——
          //   那是一个真机不会出现的组合，验它等于验夹具。
          if (_none) _q.concat(_rest).forEach(function (e) { e.eta5h = null; });
          // ★ `?runway=reset` 专验「续航长过最早一次周重置 ⇒ 只说撑得到重置」那一支。
          var _past = p.get('runway') === 'reset';
          return Promise.resolve(JSON.stringify({
            // ★ 见底时 `cur` 必须是一个**不可用**的号 —— 那正是「临时借用」要说的事。
            //   给 `_q[0]`（空）会让左侧整块不渲染，那条分支就又验不到了。
            // ★★★ `?pool=recovered` = **池子已恢复，但最近一次用的是个不可用的号**。
            //   这正是用户 2026-09-21 截图那一幕：3 小时前池子空过、代理借了 qq55，
            //   现在 4 个号可用、下一个是 wing，而顶部仍挂着红色的「临时借用」。
            //   ⚠️ 没有这个夹具，「借用角标只在借用仍在发生时亮」这条**根本验不到** ——
            //     默认夹具里 `cur` 本来就可用，改不改判据它都是绿的（本仓形态⑩：
            //     判据档位要挑只有被测那条能挡住的输入）。
            cur: _rec ? (_rest[0] || _q[0] || null)
                      : (_q[0] || (_strand ? _rest[0] : null)),
            cur_ago_min: _rec ? 180 : 7, next: _q[0] || null,
            queue: _q, rest: _rest, weekly_left_pp: _wk,
            burn_pp_per_hour: _none ? null : 39.3,
            runway_hours: _none ? null : Math.round(_wk / 39.3 * 10) / 10,
            rate_span_h: _none ? null : 22.4,
            first_reset_h: _past ? 2.5 : 134.1,
            outlasts_reset: !_none && _past,
            samples: _none ? 3 : 226, last_sample_min: _none ? null : 181,
            // 连续使用口径（`codex-rotate::_burst`，2026-10-15 真机数）；`?runway=none` ⇒ 没有用完历史
            burst: _none ? null : { now_min: Math.round(_q.reduce(function (t2, e) { return t2 + (e.eta5h ? e.eta5h.left_min : 0); }, 0) * 10) / 10,
                                    // 真 `_burst`：比值缺失 ⇒ `week_min` 为 None（同一个耦合，见上面 `_none`）
                                    week_min: p.get('relay') === 'long' ? null : 146.3, refill_h: 2.46, n: 6,
                                    wk_per_5h: p.get('relay') === 'long' ? null : 0.156, events: 3, per_window_min: _pw } }));
        }
      }
      // run_rotate 的桩。默认什么都不做(返回 null),只有 `priority --set` 要真的改 STATE ——
      // 否则总览拖完顺序、`read_state` 回来的还是旧的,端到端闸验的就不是真链路了。
      case 'run_rotate': {
        var _a = (args && args.args) || [];
        // ★ 记录每次调用：确认弹窗的闸要断言「点确认之前一次 use-credit 都没发出去」。
        (window.__RUN_ROTATE__ = window.__RUN_ROTATE__ || []).push(_a);
        // ★ `borrow --on/--off` 真的改 STATE —— 否则设置页点完开关、`read_state`
        //   回来的还是旧值，端到端闸验的就不是真链路了（同 `priority --set` 的理由）。
        if (_a[0] === 'borrow') {
          if (_a[1] === '--off') STATE.borrow_off = true; else delete STATE.borrow_off;
        }
        // 置顶 / 停轮换也真改 STATE：总览的置顶分区、FLIP 换位、「不轮换」标签要走真链路才验得到（P5）。
        if (_a[0] === 'pin') {
          var byLabel = {}; Object.keys(STATE.slots).forEach(function (k) { byLabel[STATE.slots[k].label] = k; });
          var cur = (STATE.pinned || []).slice();
          if (_a[1] === '--add') { var ad = byLabel[_a[2]]; if (ad && cur.indexOf(ad) < 0) cur.push(ad); }
          else if (_a[1] === '--remove') { var rm = byLabel[_a[2]]; cur = cur.filter(function (x) { return x !== rm; }); }
          else if (_a[1] === '--clear') cur = [];
          else cur = _a.slice(1).map(function (l) { return byLabel[l]; }).filter(Boolean);
          if (cur.length) STATE.pinned = cur; else delete STATE.pinned;
        }
        if (_a[0] === 'rotate' && STATE.slots[_a[1]]) {
          if (_a[2] === '--off') STATE.slots[_a[1]].rotate_off = true; else delete STATE.slots[_a[1]].rotate_off;
        }
        // `remove <aid|label>` 真删夹具里的号：延迟删除提交之后，`read_state` 回来就不该再有它（P5 删除闸要验这一步）
        if (_a[0] === 'remove') {
          var rk = STATE.slots[_a[1]] ? _a[1] : Object.keys(STATE.slots).filter(function (k) { return STATE.slots[k].label === _a[1]; })[0];
          if (rk) delete STATE.slots[rk];
        }
        // `?probe_delay=<ms>`：探针晚点回来（真机一次 3–30 s）—— 在途锁的闸要在「还没回来」那段时间里连点
        if (_a[0] === 'probe' && p.get('probe_delay')) {
          return new Promise(function (res) { setTimeout(function () { res('probe ok'); }, parseInt(p.get('probe_delay'), 10)); });
        }
        if (_a[0] === 'priority' && _a[1] === '--set') {
          var want = _a.slice(2);
          var byLabel = {};
          Object.keys(STATE.slots || {}).forEach(function (k) {
            byLabel[(STATE.slots[k] || {}).label] = k;
          });
          // ★ 写 `card_order`（与 `codex-rotate priority --set` 一致：新键；`pick_order` 只读兼容旧装机）。
          STATE.card_order = want.map(function (n) { return byLabel[n]; })
                                 .filter(function (x) { return !!x; });
        }
        return Promise.resolve('');
      }
      case 'read_state':
        return Promise.resolve(STATE);
      // `slotToAccount(aid, slot, tokens)` 会直接索引 tokens[aid] —— 返回 null 会抛
      // 「Cannot read properties of null」并让整页零渲染。给每个槽位一个远期 exp 即可。
      case 'read_auth_tokens':
        return Promise.resolve(Object.fromEntries(Object.keys(STATE.slots).map(function (k) {
          return [k, { exp: Math.floor(Date.now() / 1000) + 7 * 86400 }];
        })));
      // 总览详情 Sheet 下半的技术信息。`?nodetail=1` 验「读不到」那一态（不能永远停在「正在读…」）。
      case 'read_account_detail': {
        if (p.get('nodetail') === '1') return Promise.reject('harness: no detail');
        var sl = STATE.slots[args && args.aid] || {};
        return Promise.resolve({ account_id: 'user-HARNESSabcdef', email: sl.email, label: sl.label, plan: sl.plan || 'plus',
          sub_until: '2026-11-15T00:00:00Z', sub_checked: '2026-10-15T00:00:00Z', last_refresh: '2026-10-21T09:00:00Z',
          file: (args && args.aid) + '.json', access_token_tail: 'abcd1234', access_token_len: 1820,
          access_exp: Math.floor(Date.now() / 1000) + 86400, access_iat: Math.floor(Date.now() / 1000) - 3600,
          refresh_token_tail: 'wxyz9876', refresh_token_len: 64, id_token_len: 1300, quota_source: 'usage-api',
          quota_captured_at: Math.floor(Date.now() / 1000) - 120 });
      }
      // ★★ 构建号 `B`（`vX.Y.Z+B`）。**不打桩就是假绿**：落到 default 返回 null ⇒
      //   `fullVersion()` 的 catch 接住 ⇒ 版本退回纯 `X.Y.Z` ⇒ 截图里**永远看不到 `+B`**，
      //   而页面照常渲染、零报错。这正是本仓反复记的「打桩缺口 ⇒ 零渲染看着像通过」。
      //   `?build=<n>`：给 0 就验"刚发版还没本地构建过"那一态（只显示 X.Y.Z）。
      case 'build_number':
        return Promise.resolve(p.get('build') || '7');
      case 'read_logs':
        return Promise.resolve(LOGS_TXT);
      // ★ 代理轮换台账。**不打桩就是假绿** —— 落到 default 返回 null ⇒ `rot` 恒 null ⇒
      //   上半区永远画「读不到 proxy.log」,而页面照常渲染、零报错、零溢出,sweep 会报干净。
      //   这是本仓第三次踩同一个坑(前两次:grok 卡、agy 卡),所以这次一并把降级态也做成开关。
      //   `?rot=ok|busy|empty|undated|fail`
      // ★ 快照即时读取。harness 里直接返回与全扫**同一份**数据 —— 真机上快照可能更旧,
      //   但那条时序在 headless 里模拟不出来(两次调用之间没有真实时间流逝)。
      //   这里要验的是"快照这条路被走到了、且能画出页面",不是新鲜度。
      case 'read_rotation_snapshot': {
        var rs = p.get('rot') || 'ok';
        if (rs === 'fail' || rs === 'nosnap') return Promise.resolve(null);
        if (rs === 'snaponly') return Promise.resolve(anonDeep(ROT.ok, ANON));
        if ((rs === 'ok' || !ROT[rs]) && args && args.hours >= 168) return Promise.resolve(anonDeep(_rotLong(args.hours), ANON));
        return Promise.resolve(rotNamed(anonDeep(ROT[rs] || ROT.ok, ANON)));
      }
      // ★ Gemini 版「代理轮换」（2026-09-24）。夹具由 **真的 `traffic/agy_rotation.py::collect`**
      //   在生成 harness 时跑一份合成日志算出来（见文件末尾 `agy_rot_fixture`）——
      //   不在这里手写 JSON，否则验的是一份与引擎无关的假数据。`?agyrot=fail` 验失败态。
      case 'read_agy_rotation':
        if (p.get('agyrot') === 'fail') return Promise.reject('读不到 agy 日志');
        return Promise.resolve(anonDeep(__AGYROT__, { qq55: AGY_ANON[0], Asen: AGY_ANON[1], Huo: AGY_ANON[2], wing: AGY_ANON[3] }));
      case 'read_proxy_rotation': {
        var rk = p.get('rot') || 'ok';
        // ★★ `?rot=snaponly` —— **全扫永不返回**,只有快照能把页面画出来。
        //    这是"快照那条路真的被走到了"的**唯一有判别力**的证据:两条路平时返回同一份
        //    数据,页面画出来一模一样,光看截图分不出是哪条路画的
        //    (harness 的 `ipc` 探针只统计 run_traffic/read_traffic_snapshot 两个白名单命令,
        //     指望它也证不了)。
        if (rk === 'snaponly') return new Promise(function () {});
        if (rk === 'fail') return Promise.reject('读不到 proxy/proxy.log');
        if ((rk === 'ok' || !ROT[rk]) && args && args.hours >= 168) return Promise.resolve(anonDeep(_rotLong(args.hours), ANON));
        return Promise.resolve(rotNamed(anonDeep(ROT[rk] || ROT.ok, ANON)));
      }
      case 'set_dock_visible':
      case 'set_main_visible':
      case 'quit_app':
        return Promise.resolve(null);
      case 'plugin:app|version':
        return Promise.resolve(__VERSION__);
      // ★ grok 周额度。**不打桩就是假绿**:落到 default 会返回 null,页面永远画「未探测」,
      //   而你想验的六个降级态一张都截不到 —— 页面照常渲染、零报错,看着像通过。
      //   同族的前车之鉴:`metadata` 空对象 / `read_auth_tokens` 返 null 那两次假阴性。
      //   `?grok=ok|expired|401|missing|never|stale`,email 一律脱敏。
      // ★ 菜单栏在跑条 / 悬停面板的实时读数（`read_live`，契约 PLAN §2.1 `--live`）。
      //   `?run=0`（默认，空闲）· `1` 只有 Codex · `3` Codex×2 + Claude×3 + Gemini（交接包示意同形）。
      case 'read_live': {
        if (p.get('hv')) return Promise.resolve(JSON.stringify(HV_LIVE(p.get('hv'), null)));
        var rn = parseInt(p.get('run') || '0', 10);
        var mk = function (on, n, tps, tok, base) {
          var ss = [];
          for (var j = 0; j < n; j++) ss.push({ id: base + j, title: 'proj-' + base + j, tps: tps == null ? null : tps / n,
                                                tokens: tok / n, last_t_end: _NOW - 5, active: true });
          return { running: on, n_sessions: on ? n : 0, tps: on ? tps : null, tokens_today: tok, sessions: on ? ss : [] };
        };
        return Promise.resolve(JSON.stringify({ v: 1, generated_at: _NOW, platforms: {
          codex: mk(rn >= 1, 2, 244, 3.8e6, 'c'), claude: mk(rn >= 3, 3, 190, 5.1e6, 'k'),
          agy: mk(rn >= 3, 1, 141, 0.6e6, 'g'), grok: mk(false, 0, null, 0, 'x') },
          today: { tokens: 415e6, avg_tps: 58.4, n: 312 } }));
      }
      // ★ Claude 额度（`read_statusline_quota`，契约 PLAN §2.2 `--read`）。
      //   `?claudeq=ok`（默认，状态栏转写，带重置时刻）· `plan`（Claude.app，无重置时刻）·
      //   `stale`（2 小时前的读数）· `low`（5h 剩 6%）· `none`（读不到）· `err`（命令失败）·
      //   `idle`（5h 已过重置点、之后的读数没再报它 ⇒ 100% 未启动）· `weektight`（5h 剩 99、周剩 67）。
      // ★ 悬停面板的三条命令（`tps_hover.rs` / lib.rs）：记下参数，测试核「高度报了多少、托盘 logo 藏 / 放回」。
      // ★ 刘海卡片（`harness-notch.html`，交接包 4e）的四条命令：几何 / 谁在跑 / 卡片高度上报 / 版面。
      //   不打桩 ⇒ 落到 default 返回 null ⇒ 刘海尺寸、光晕全是默认空值，卡片照样渲染、零报错 —— 假绿。
      case 'notch_geometry':
        return Promise.resolve({ left: 0, width: 179, height: 32, top: 0, open: p.get('ntopen') !== '0',
                                 mode: p.get('ntmode') || ((p.get('nt') || 'A') === 'I' ? 'idle' : 'run') });
      case 'notch_activity': {
        var ntS = p.get('nt') || 'A';
        // `?ntact=1`：空闲格子开着时 AI 开跑（展开种类已定，光晕不该跟着换）
        return Promise.resolve((ntS === 'B' || ntS === 'I') && p.get('ntact') !== '1' ? { codex: false, claude: false, agy: false, grok: false }
                                           : { codex: true, claude: true, agy: true, grok: false });
      }
      case 'notch_dismiss':
        // 同 Rust `notch::dismiss`：收起（推 `notch-open` false）—— 不推的话「点了真的收起」验不到
        ntCalls.push(cmd + '=' + JSON.stringify(args));
        setTimeout(function () { fire('notch-open', false); }, 0);
        return Promise.resolve(null);
      case 'notch_card_resize':
        ntCalls.push(cmd + '=' + JSON.stringify(args));
        return Promise.resolve(null);
      case 'notch_layout':
        return Promise.resolve(null);
      case 'tpshover_resize':
      case 'tpshover_dismiss':
      case 'tray_pill_hide_logos':
        hvCalls.push(cmd + '=' + JSON.stringify(args));
        return Promise.resolve(null);
      case 'tpshover_layout':
        hvCalls.push(cmd);
        return Promise.resolve(p.get('hvnull') === '1' ? null : p.get('hv') === 'idle' ? HV_IDLE_LAYOUT() : HV_LAYOUT(p.get('hv')));
      // ★ 设置页「Claude 实测速度」（`claude_otel_env.py`）。`?cotel=off`（默认）· `recv` 已开且收到过 ·
      //   `wait` 已开没收到 · `down` 端口被占 · `conflict` 已有别的 OTel 配置 · `err` 命令失败。
      //   enable / disable 只切 off ↔ recv，**不碰任何真实文件**。
      case 'claude_otel': {
        var co = window.__cotel || p.get('cotel') || 'off';
        if (co === 'err') return Promise.reject('script not found: claude_otel_env.py');
        var act = args && args.action;
        if (act === 'enable') co = window.__cotel = 'recv';
        else if (act === 'disable') co = window.__cotel = 'off';
        var on = co === 'recv' || co === 'wait' || co === 'down';
        var ui = co === 'recv' ? 'on_receiving' : co === 'wait' ? 'on_waiting' : co === 'down' ? 'on_down' : co;
        return Promise.resolve(JSON.stringify({ ok: true, state: on ? 'on' : co, ui: ui, error: null,
          conflicts: co === 'conflict' ? ['OTEL_EXPORTER_OTLP_ENDPOINT', 'OTEL_METRICS_EXPORTER', 'OTEL_EXPORTER_OTLP_HEADERS'] : [],
          settings: '~/.claude/settings.json',
          receiver: { last_post_at: co === 'recv' ? _NOW - 300 : null, listening: co === 'down' ? false : true,
                      error: co === 'down' ? '端口 4318 已被别的程序占用（可能是你自己的 OTel 收集器，或另一份接收端）' : null,
                      port_open: true } }));
      }
      case 'read_statusline_quota': {
        var cq = p.get('claudeq') || 'ok';
        if (cq === 'err') return Promise.reject('statusline_quota.py: not found');
        var cap = cq === 'stale' ? _NOW - 7200 : _NOW - 120;
        var w5 = cq === 'idle' ? { used_pct: 56, resets_at: _NOW - 1800, captured_at: _NOW - 6000, expired: true }
          : { used_pct: cq === 'low' ? 94 : 37, resets_at: cq === 'plan' ? null : _NOW + 7500, captured_at: cap, expired: false };
        var w7 = { used_pct: cq === 'weektight' ? 33 : 22, resets_at: cq === 'plan' ? null : _NOW + 4 * 86400 + 3600, captured_at: cap, expired: false };
        if (cq === 'weektight') w5.used_pct = 1;   // 5h 剩 99、周剩 67：logo 水位该跟 5h（用户 2026-10-22）
        var cl = cq === 'none' ? { source: 'none', captured_at: null, five_hour: null, seven_day: null, error: null }
          : { source: cq === 'plan' ? 'plan-usage-history' : 'statusline', captured_at: cap, five_hour: w5, seven_day: w7, error: null };
        return Promise.resolve(JSON.stringify({ claude: cl, agy: { source: 'none', captured_at: null, plan_tier: null, buckets: {}, error: null } }));
      }
      case 'read_requests': {
        var rq = p.get('req') || 'ok';
        reqCalls++;
        if (rq === 'errfirst' || (rq === 'error' && reqCalls > 1))
          return Promise.reject('读 traffic/requests-ledger 失败：Resource temporarily unavailable');
        var rqf = REQ_FIXTURE(rq);
        // ★ 代理轮换页的 t/s 列按号取实测中位数：账本里要有这几个号的行（plus6 只有估值行 ⇒ 必须画「—」）。
        if ((p.get('nav') || '') === 'logs') {
          [['plus4', [88, 102, 140]], ['plus5', [71, 95]], ['plus7', [120]], ['Pro1', [64, 66]], ['plus6', [300]]].forEach(function (q, j) {
            q[1].forEach(function (v, i) {
              rqf.requests.push({ key: 'codex:rot' + j + ':' + i, platform: 'codex', t_start: _NOW - 900 - i * 60 - 30, t_end: _NOW - 900 - i * 60,
                model: 'gpt-6-sol', source: '交互', session: 's', session_title: 'demo-project', account: q[0], input: 1000, cached: 0,
                output: 900, reasoning: null, ttft_ms: 900, gen_ms: 8000, total_ms: 9000, tool_ms: null, tps: v,
                est: q[0] === 'plus6', session_req_n: 1 });
            });
          });
        }
        return Promise.resolve(JSON.stringify(anonDeep(rqf, ANON)));
      }
      case 'read_relay_snapshot':
      case 'run_relay_usage': {
        if (relayMode() === 'empty') return Promise.resolve(JSON.stringify({ ok: true, relays: [], route: relayRoute(), fetched_at: Math.floor(Date.now()/1000) }));
        return Promise.resolve(JSON.stringify({ ok: true,
          relays: relayMode() === 'mixed' ? relayMixedEntries() : relayMode() === 'pair' ? relayPairEntries() : [relayEntry()],
          route: relayRoute(), fetched_at: Math.floor(Date.now()/1000) }));
      }
      case 'relay_ctl': {
        // ★ 记下调用(sub+arg),**不记 payload** —— 它含 key。
        relayCalls.push(String((args && args.sub) || '') + ((args && args.arg) ? ':' + args.arg : ''));
        var sub = args && args.sub;
        // `?relayfail=set|remove`：CLI 正常返回但 `ok:false`（写盘失败）—— 页面不许照样报「已停用 / 已删除」。
        if (p.get('relayfail') === sub) return Promise.resolve(JSON.stringify({ ok: false, state: 'invalid', detail: '写盘失败（夹具）' }));
        if (sub === 'status') {
          return Promise.resolve(JSON.stringify({ ok: true, v: 1,
            relays: relayMode() === 'empty' ? [] : relayMode() === 'pair' ? [RELAY_ROW, RELAY_ROW2] : [RELAY_ROW], route: relayRoute() }));
        }
        if (sub === 'test') return Promise.resolve(JSON.stringify({ ok: true, id: 'tokendun', state: 'ok', model_count: 22 }));
        return Promise.resolve(JSON.stringify({ ok: true, route: relayRoute() }));
      }
      case 'read_grok_quota':
      case 'run_grok_quota': {
        var g = p.get('grok') || 'ok';
        if (g === 'never') return Promise.resolve(null);
        return Promise.resolve(JSON.stringify(GROK[g] || GROK.ok));
      }
      // ★ agy 额度。**不打桩就是假绿** —— 落到 default 返回 null ⇒ `agyQuotaVisible` 判 false
      //   ⇒ 整张卡 `return null`,于是 sweep 一张 agy 卡都没渲染却报"干净"。
      //   与 grok 那条同族的坑,这里再踩一次的代价是新加的卡从未被任何一次布局验证覆盖过。
      //   `?agy=ok|tight|noproc|warm|notinst|never`。
      case 'read_agy_quota':
      case 'run_agy_quota': {
        var ag = p.get('agy') || 'ok';
        if (ag === 'never') return Promise.resolve(null);
        var base = AGY[ag] || AGY.ok;
        // ★ `?agypush=<rem>`:**推送到达之后**的读取返回一份更新过的快照。
        //   `agyPushed` 由下面的 `?agypush` 分支在 fire 事件前置位 ——
        //   这样这条测试判的是"推送触发了重读并采纳了新值",
        //   而不是"夹具本来就是新值"（后者恒绿，等于没测）。
        if (agyPushed) {
          var bumped = JSON.parse(JSON.stringify(base));
          bumped.fetched_at = (base.fetched_at || 0) + 600;
          try {
            bumped.quota.groups[0].buckets[0].remaining_percent = Number(p.get('agypush'));
          } catch (e) { /* 夹具形状变了就让断言去发现 */ }
          return Promise.resolve(JSON.stringify(bumped));
        }
        return Promise.resolve(JSON.stringify(base));
      }
      case 'plugin:autostart|is_enabled':
        return Promise.resolve(false);
      default:
        unknown.push(cmd);
        return Promise.resolve(null);
    }
  }

  // Tauri v2 的 `@tauri-apps/api/event` 在 unlisten 时走这个**独立的全局**,不是 __TAURI_INTERNALS__。
  // 缺了它,每次组件卸载都抛一次 unhandledrejection(不致命,但会淹没真正的报错)。
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: function () {} };

  window.__TAURI_INTERNALS__ = {
    invoke: invoke,
    transformCallback: function (cb, once) { var id = ++cbid; cbs[id] = { cb: cb, once: once }; return id; },
    // ★ `metadata` 不能是空对象:`getCurrentWindow()` 直接取 `metadata.currentWindow.label`,
    //   缺了它模块初始化就抛 `Cannot read properties of undefined (reading 'label')`,
    //   整页零渲染 —— 而零渲染的页面量出来是"零溢出",看着像通过。
    metadata: {
      currentWindow: { label: 'main' },
      currentWebview: { label: 'main', windowLabel: 'main' },
    },
  };

  // 页面切换靠 app 自己监听的导航事件(App.tsx 的 navigate-traffic / navigate-settings /
  // navigate-platform),不去猜 DOM 结构点击侧栏。
  // ★★ 悬停面板（`harness-tpshover.html`，交接包 page2）。数据照 HoverSpec.html 画板（账号无、标题脱敏）。
  //   `?hv=1`  1 家 1 会话（C）· `2` Codex + Gemini 还没出数（D）· `4` 四家、Codex×2 / Claude×3（A）
  //   `?hvstop=codex` 900 ms 时推一份 tps-live，那家停下（40% → 3 s → 收起；dump 用短 budget 拍 40% 态）
  //   `?hvexpand=claude` 1000 ms 时把鼠标移进那一行（250 ms 后应展开）· `?hvleave=1` 再 1000 ms 后移出
  //   `?hvnull=1` 打开事件 payload = null（不飞，直接淡入）· `?hvopen=0` 不发打开事件
  //   `?hvtheme=light` · `?hvreduce=1`（减弱动态效果）· `?hvclick=link` 1200 ms 点「请求页 →」
  //   `?hvclose=leave|click` 1600 ms 发关闭 · `?hvbg=desk` 画一块桌面 + 菜单栏底（截图看得见透明窗）
  //   1800 ms 起把几何核对 / IPC / emit 写进 <body data-hv-*>（dump-dom 读）。
  function HV_LIVE(mode, stop) {
    var S = function (id, title, tps, tok) { return { id: id, title: title, tps: tps, tokens: tok, last_t_end: _NOW - 4, active: true }; };
    var P = function (k, sess, nOverride) {
      if (!sess || stop === k) return { running: false, n_sessions: 0, tps: null, tokens_today: 0, sessions: [] };
      var any = false, sum = 0, tok = 0;
      sess.forEach(function (x) { if (typeof x.tps === 'number') { any = true; sum += x.tps; } tok += x.tokens; });
      return { running: true, n_sessions: nOverride || sess.length, tps: any ? sum : null, tokens_today: tok, sessions: sess };
    };
    var m = String(mode);
    var codex = m === '4' ? [S('c1', 'codex-account-rotator · 重构轮换', 178, 2.6e6), S('c2', 'market-intel · 选品报告', 66, 1.2e6)]
                          : [S('c1', 'codex-account-rotator · 重构轮换', 178, 2.6e6)];
    var claude = m === '4' ? [S('k1', 'CodexBar · 托盘胶囊', 82, 2.3e6), S('k2', '四方评审 · 交接包', 64, 1.9e6), S('k3', 'ERP · 退货对账', 44, 0.9e6)] : null;
    var agy = m === '4' ? [S('g1', 'skill-hub', 141, 0.6e6)] : (m === '2' ? [S('g1', 'skill-hub', null, 0.1e6)] : null);
    var grok = m === '4' ? [S('x1', 'oneman-co', 82, 0.4e6)] : null;
    return { v: 1, generated_at: _NOW, platforms: { codex: P('codex', codex), claude: P('claude', claude), agy: P('agy', agy), grok: P('grok', grok) },
             today: { tokens: 48.7e6, avg_tps: 58.4, n: 312 } };
  }
  // 版面夹具：与 `tps_hover.rs::window_rect` 同形（面板在窗口内 (40, 30)，胶囊在面板正上方居中 —— 用户 2026-10-21「居中弹窗」）。
  function HV_LAYOUT(mode) {
    var keys = String(mode) === '4' ? ['codex', 'claude', 'agy', 'grok'] : (String(mode) === '2' ? ['codex', 'agy'] : ['codex']);
    var pw = keys.length === 1 ? 70 : (keys.length === 2 ? 96 : 104), px = 40 + 300 / 2 - pw / 2, py = 3;
    var segs = keys.map(function (k, i) {
      var x = 6 + i * ((pw - 12) / Math.max(1, keys.length));
      return { platform: k, x: x, w: 12, logo: { x: px + x, y: py + 3, size: 12 } };
    });
    return { window: { w: 380, h: 380 }, menubar_h: 24, panel: { x: 40, y: 30, w: 300, h: 224 },
             pill: { x: px, y: py, w: pw, h: 18 }, segments: segs };
  }
  // ★ 空闲额度格子（AICoop P11 §6）：`?hv=idle` 发 `mode: "idle"` 的打开事件（托盘里 Codex / Claude / Gemini 三家，
  //   logo 14 pt、胶囊宽 63，面板 435（1.5×）、在胶囊正下方居中）。格子夹具 `?hvcells=4`（默认：托盘三家 + Grok；
  //   Gemini 剩 6% 是插队）· `8` 两行（再加 Kimi / DeepSeek 未接入 + 两个重复填充不可能出现，所以只到 6 家）· `1` 只一家。
  function HV_IDLE_CELLS(mode) {
    var C = function (key, main, reset, inBar) { return { key: key, main: main, reset: reset, inBar: inBar, low: main !== null && Math.round(main) < 10, stale: false }; };
    var all = [C('codex', 67, '↻ 2h14m', true), C('claude', 40, '↻ 1h05m', true), C('agy', String(mode) === 'ok' ? 86 : 6, '↻ 3h40m', true),
               C('grok', 86, '↻ 5d21h', false), C('kimi', null, '', false), C('deepseek', null, '', false)];
    var m = String(mode || '4');
    return { cells: m === '1' ? all.slice(0, 1) : m === '8' ? all : all.slice(0, 4), max: m === '8' ? 8 : 4 };
  }
  function HV_IDLE_LAYOUT() {
    var keys = ['codex', 'claude', 'agy'], pw = 4 + 3 * 14 + 2 * 5 + 7, px = 40 + 435 / 2 - pw / 2, py = 3;
    var segs = keys.map(function (k, i) { var x = 4 + i * 19; return { platform: k, x: px + x, w: 14, logo: { x: px + x, y: py + 2, size: 14 } }; });
    return { mode: 'idle', window: { w: 515, h: 330 }, menubar_h: 24, panel: { x: 40, y: 30, w: 435, h: 118 },
             pill: { x: px, y: py, w: pw, h: 18 }, segments: segs };
  }
  if (location.pathname.indexOf('harness-tpshover') >= 0) {
    try { localStorage.setItem('codexbar_theme', p.get('hvtheme') === 'light' ? 'light' : 'dark'); } catch (e) { errors.push('hv theme: ' + e); }
    if (p.get('hvreduce') === '1') {
      var _mm = window.matchMedia ? window.matchMedia.bind(window) : null;
      window.matchMedia = function (q) {
        if (String(q).indexOf('prefers-reduced-motion') >= 0) return { matches: true, media: q, addEventListener: function () {}, removeEventListener: function () {} };
        return _mm ? _mm(q) : { matches: false, media: q, addEventListener: function () {}, removeEventListener: function () {} };
      };
    }
    if (p.get('hvbg') === 'desk') {
      var hb = document.createElement('style');
      hb.textContent = 'html{background:linear-gradient(' + (p.get('hvtheme') === 'light' ? '#e9edf2,#e9edf2' : '#1c2128,#1c2128')
        + ') 0 0/100% 24px no-repeat,linear-gradient(160deg,#33496b,#4b3f6b) !important}';
      document.head.appendChild(hb);
    }
    window.addEventListener('load', function () {
      var hv = p.get('hv') || '4';
      if (p.get('hvopen') !== '0') setTimeout(function () { fire('tpshover-open', p.get('hvnull') === '1' ? null : hv === 'idle' ? HV_IDLE_LAYOUT() : HV_LAYOUT(hv)); }, 150);
      if (p.get('hvstop')) setTimeout(function () { fire('tps-live', JSON.stringify(HV_LIVE(hv, p.get('hvstop')))); }, 900);
      var rowEl = function (k) { return document.querySelector('[data-hover-row="' + k + '"]'); };
      if (p.get('hvexpand')) {
        setTimeout(function () {
          var el = rowEl(p.get('hvexpand'));
          clicks.push('hvexpand →命中 ' + (el ? 1 : 0));
          if (el) el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: null }));
        }, 1000);
        if (p.get('hvleave') === '1') setTimeout(function () {
          var el = rowEl(p.get('hvexpand'));
          if (el) el.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }));
        }, 2000);
      }
      // `hvcursor=<行>`：模仿 Rust 光标轮询（app 不在前台、网页收不到鼠标事件时唯一的来源）——
      // 每 16 ms 报一次那一行里的坐标、带 1–2 px 抖动（Rust 只在坐标变了时报）。`hvcursorleave=1` 在 2 s 时报 null。
      if (p.get('hvcursor')) {
        setTimeout(function () {
          var el = rowEl(p.get('hvcursor'));
          clicks.push('hvcursor →命中 ' + (el ? 1 : 0));
          if (!el) return;
          var r = el.getBoundingClientRect(), n = 0;
          var id = setInterval(function () {
            fire('tpshover-cursor', [r.left + r.width / 2 + (n % 3), r.top + r.height / 2]);
            if (++n >= 40) clearInterval(id);
          }, 16);
        }, 1000);
        if (p.get('hvcursorleave') === '1') setTimeout(function () { fire('tpshover-cursor', null); }, 2000);
      }
      if (p.get('hvclick') === 'link') setTimeout(function () {
        var a = document.querySelector('[data-hover-link]');
        clicks.push('hvclick →命中 ' + (a ? 1 : 0));
        if (a) a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      }, 1200);
      if (p.get('hvclose')) setTimeout(function () { fire('tpshover-close', p.get('hvclose')); }, 1600);
      setTimeout(function () {
        var geom = [];
        document.querySelectorAll('[data-logo-target]').forEach(function (e) {
          var r = e.getBoundingClientRect(), t = e.getAttribute('data-logo-target').split(',');
          geom.push({ k: e.getAttribute('data-hover-logo-cell'), tx: +t[0], ty: +t[1], ax: r.left, ay: r.top, w: r.width });
        });
        var pnl = document.querySelector('[data-hover-panel]');
        var b = document.body;
        b.setAttribute('data-hv-geom', JSON.stringify(geom));
        if (pnl) b.setAttribute('data-hv-panel', JSON.stringify({ h: pnl.getBoundingClientRect().height, logic: +pnl.getAttribute('data-hover-h'),
                                                                  w: pnl.getBoundingClientRect().width }));
        b.setAttribute('data-hv-calls', JSON.stringify(hvCalls));
        b.setAttribute('data-hv-emit', JSON.stringify(emittedJ));
        b.setAttribute('data-hv-clicks', JSON.stringify(clicks));
        b.setAttribute('data-hv-errors', JSON.stringify(errors.concat(unknown)));
      }, parseInt(p.get('hvat') || '1800', 10));
    });
  }

  // ★★ 刘海卡片（`harness-notch.html`，交接包 page4 · 4e）。场景照 `P4NotchMotion.html`：
  //   `?nt=A`（默认）Codex×2 / Claude×3 / Gemini 在跑 · `B` 空闲（默认今日、在跑置灰）· `C` Gemini 当前号 5h 剩 8%（告警）
  //   `?ntopen=0` 不展开（拍果冻下垂）· `?ntcur=<dx>,<distance>` 200 ms 时推一帧 `notch-cursor`
  //   `?nttab=today` 1000 ms 点「今日」· `?ntexpand=claude` 1000 ms 把鼠标移进那一行（250 ms 后应展开）
  //   `?ntclose=1&ntreopen=1` 收起后 2200 ms 再展开 · `?ntreduce=1` 减弱动态效果 · `?ntclick=requests|traffic|overview` 1200 ms 点链接 · `?ntclose=1` 1600 ms 收起
  //   `?nt=I` 空闲 + 刘海屏版额度格子（AICoop P11 `P11_NotchHover`）：`?ntcells=1|4|8|ok|none`（同托盘面板那份；`ok` = 没有低额度）·
  //   `?ntempty=1` 1000 ms 格子变空 · `?ntnear=1` 200 ms 推 `notch-near`（配 `ntopen=0` 拍「靠近」光晕）· `?ntpick=<key>` 1200 ms 点那一格
  //   `?ntbg=desk` 画一块桌面 + 32 高菜单栏底（截图看得见透明窗）。刘海与卡片恒黑，浅色主题无关。
  //   `?ntat=<ms>`（默认 1800）起把卡片实量 / logo 落点 / IPC / emit 写进 <body data-nt-*>（dump-dom 读）。
  if (location.pathname.indexOf('harness-notch') >= 0) {
    var ntScene = p.get('nt') || 'A';
    if (!p.get('run')) p.set('run', ntScene === 'B' || ntScene === 'I' ? '0' : '3');
    if (!p.get('agypool')) p.set('agypool', '2');
    if (ntScene === 'C' && !p.get('agylive')) { p.set('agylive', 'sub1'); p.set('agylive_at', '60'); }
    if (p.get('ntreduce') === '1') {
      var _ntmm = window.matchMedia ? window.matchMedia.bind(window) : null;
      window.matchMedia = function (q) {
        if (String(q).indexOf('prefers-reduced-motion') >= 0) return { matches: true, media: q, addEventListener: function () {}, removeEventListener: function () {} };
        return _ntmm ? _ntmm(q) : { matches: false, media: q, addEventListener: function () {}, removeEventListener: function () {} };
      };
    }
    if (p.get('ntbg') === 'desk') {
      var nb = document.createElement('style');
      nb.textContent = 'html{background:linear-gradient(rgba(28,28,30,.86),rgba(28,28,30,.86)) 0 0/100% 32px no-repeat,linear-gradient(170deg,#2c4a6b,#3d3a66) !important}';
      document.head.appendChild(nb);
    }
    window.addEventListener('load', function () {
      if (p.get('ntcur')) setTimeout(function () {
        var c = p.get('ntcur').split(',');
        fire('notch-cursor', { x: 0, y: 0, dx: +c[0], distance: +c[1] });
      }, 200);
      if (p.get('ntnear') === '1') setTimeout(function () { fire('notch-near', true); }, 200);
      // `?ntempty=1` 1000 ms 时格子变空（设置改成「只看菜单栏」之类）—— 展开着的空闲面板应自己收起
      if (p.get('ntempty') === '1') setTimeout(function () { fire('idle-panel', { cells: [], max: 4 }); }, 1000);
      if (p.get('ntpick')) setTimeout(function () {
        var el = document.querySelector('[data-notch-idle-cell="' + p.get('ntpick') + '"]');
        clicks.push('ntpick →命中 ' + (el ? 1 : 0));
        if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      }, 1200);
      if (p.get('nttab') === 'today') setTimeout(function () {
        var el = document.querySelector('[data-notch-tab="today"]');
        clicks.push('nttab →命中 ' + (el ? 1 : 0));
        if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      }, 1000);
      if (p.get('ntexpand')) setTimeout(function () {
        var el = document.querySelector('[data-notch-row="' + p.get('ntexpand') + '"]');
        clicks.push('ntexpand →命中 ' + (el ? 1 : 0));
        if (el) el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: null }));
      }, 1000);
      if (p.get('ntclick')) setTimeout(function () {
        var a = document.querySelector('[data-notch-link="' + p.get('ntclick') + '"]');
        clicks.push('ntclick →命中 ' + (a ? 1 : 0));
        if (a) a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      }, 1200);
      if (p.get('ntclose') === '1') setTimeout(function () { fire('notch-open', false); }, 1600);
      // ★ `?ntreopen=1` 2200 ms 再展开一次 —— 验「每次展开都回到默认 Tab」（要配 `ntclose=1` 与 `ntat` ≥ 2400）
      if (p.get('ntreopen') === '1') setTimeout(function () { fire('notch-open', true); }, 2200);
      setTimeout(function () {
        var b = document.body, stage = document.querySelector('.nh-stage'), card = document.querySelector('[data-notch-card]');
        var sr = stage ? stage.getBoundingClientRect() : { left: 0, top: 0 };
        var geom = [];
        document.querySelectorAll('[data-notch-logo]').forEach(function (e) {
          var r = e.getBoundingClientRect();
          geom.push({ k: e.getAttribute('data-notch-logo'), x: r.left - sr.left, y: r.top - sr.top, w: r.width });
        });
        var content = document.querySelector('.nh-content');
        if (card) b.setAttribute('data-nt-card', JSON.stringify({
          h: card.getBoundingClientRect().height, logic: +document.querySelector('[data-notch-h]').getAttribute('data-notch-h'),
          content: content ? content.getBoundingClientRect().height : null, w: card.getBoundingClientRect().width,
          x: card.getBoundingClientRect().left - sr.left, y: card.getBoundingClientRect().top - sr.top }));
        b.setAttribute('data-nt-geom', JSON.stringify(geom));
        var ip = document.querySelector('[data-notch-idle]');
        if (ip) {
          var ir = ip.getBoundingClientRect(), cs = getComputedStyle(ip);
          var ng = document.querySelector('[data-notch-near-glow]');
          b.setAttribute('data-nt-idle', JSON.stringify({
            x: ir.left - sr.left, y: ir.top - sr.top, w: ir.width, h: ir.height, op: +cs.opacity,
            glow: ng ? +getComputedStyle(ng).opacity : null,
            lowdot: !!document.querySelector('[data-notch-idle-lowdot]') && !!ng && +getComputedStyle(ng).opacity > 0,
            runglow: +getComputedStyle(document.querySelector('.nh-glow')).opacity,
            drip: document.querySelector('[data-notch-drip]').getAttribute('data-notch-drip'),
            cells: Array.prototype.map.call(document.querySelectorAll('[data-notch-idle-cell]'), function (e) {
              var r = e.getBoundingClientRect(), m = e.querySelector('[data-notch-idle-main]');
              return { k: e.getAttribute('data-notch-idle-cell'), x: r.left - ir.left, y: r.top - ir.top, w: r.width, h: r.height,
                       main: m ? m.getAttribute('data-notch-idle-main') : null, bg: getComputedStyle(e).backgroundColor };
            }) }));
        }
        b.setAttribute('data-nt-fly', String(document.querySelectorAll('[data-notch-fly]').length));
        b.setAttribute('data-nt-calls', JSON.stringify(ntCalls));
        b.setAttribute('data-nt-emit', JSON.stringify(emittedJ));
        b.setAttribute('data-nt-clicks', JSON.stringify(clicks));
        b.setAttribute('data-nt-errors', JSON.stringify(errors.concat(unknown)));
      }, parseInt(p.get('ntat') || '1800', 10));
    });
  }

  // ★ `?notrans=1` 关掉所有 CSS 过渡。headless 的 `--virtual-time-budget` **不推进 CSS 过渡**：
  //   切浅色后截图拍到的是 .35s 颜色过渡的半路（深字还没变过来，表格像被擦掉），
  //   侧栏选中底色同理 —— 截图在说一件 DOM 里没有的事。
  if (p.get('notrans') === '1') {
    var nt = document.createElement('style');
    nt.textContent = '*,*::before,*::after{transition:none !important}';
    document.head.appendChild(nt);
    // 导航选中块用 WAAPI 滑（不吃上面的 CSS）：NavRail 看这个标记不播
    document.documentElement.setAttribute('data-notrans', '1');
  }
  window.addEventListener('load', function () {
    setTimeout(function () {
      var nav = p.get('nav') || 'traffic';
      if (nav.indexOf('platform:') === 0) fire('navigate-platform', nav.slice(9));
      else if (nav === 'settings') fire('navigate-settings');
      else if (nav === 'home') { /* 账号池是默认页,不发导航事件 */ }
      // ★ `?nav=ovjump&ovto=<platform>`：菜单栏账号行点击的那条（`open-main-page` → Rust → `main-open-page`），
      //   带平台参数 ⇒ 停在那一档。先切到日志页，证明「跳过来」真的发生了。`?navtwice=1` 同上。
      else if (nav === 'ovjump') {
        var lg = document.querySelector('[data-page="logs"]');
        if (lg) lg.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        setTimeout(function () {
          var pl = { page: 'overview', platform: p.get('ovto') || null };
          if (p.get('navtwice') === '1') fire('open-main-page', pl);
          fire('main-open-page', pl);
        }, 150);
      }
      // ★ `?nav=requests` 走 `open-main-page` 事件（托盘悬停面板 / 刘海卡片的「请求页 →」用的同一条），
      //   顺带验 App.tsx 的订阅。`?rplat=claude` = 带平台过来；`?rday=yest`、`?rf=<平台>`、`?rsel=<行号>`、
      //   `?rscroll=<px>` 按 `data-req-*` 身份点 / 滚（不按位置、不按文字）。要等异步 IPC 的行出来，所以轮询。
      else if (nav === 'requests') {
        // ★ 主窗口只听 Rust 转发的 `main-open-page`（App.tsx）。`?navtwice=1` 模拟真机：发送方全局 `emit` 时
        //   主窗口**也**收到一份原名 `open-main-page` —— 两个都听就会跳两回（`data-nav-count` = 2）。
        if (p.get('navtwice') === '1') fire('open-main-page', { page: 'requests', platform: p.get('rplat') || null });
        fire('main-open-page', { page: 'requests', platform: p.get('rplat') || null });
        (function pollReq(tries) {
          var ready = document.querySelector('[data-req-row], [data-req-empty]');
          if (!ready && tries > 0) { setTimeout(function () { pollReq(tries - 1); }, 100); return; }
          if (!ready) { errors.push('请求页没有渲染出行或空态'); return; }
          var hit = function (sel, name) {
            var el = document.querySelector(sel);
            clicks.push(name + ' →命中 ' + (el ? 1 : 0));
            if (!el) errors.push('请求页点不到 ' + sel);
            return el;
          };
          if (p.get('rday')) { var d = hit('[data-req-day="' + p.get('rday') + '"]', 'rday'); if (d) d.click(); }
          if (p.get('rf')) { var f = hit('[data-req-filter="' + p.get('rf') + '"]', 'rf'); if (f) f.click(); }
          setTimeout(function () {
            if (p.get('rsel')) {
              var r = hit('[data-req-row="' + p.get('rsel') + '"]', 'rsel');
              if (r) r.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }
            if (p.get('rscroll')) {
              var sc = hit('[data-req-scroll]', 'rscroll');
              if (sc) sc.scrollTop = parseInt(p.get('rscroll'), 10);
            }
          }, 80);
        })(30);
      }
      // ★★ `?nav=logs` —— 日志页**没有** `navigate-logs` 事件(App.tsx 只监听 traffic/
      //   settings/platform 三个,因为只有它们是 Rust/托盘会发的)。所以只能点侧栏。
      //   ⚠️ **不能用 `?click=日志`**:窗口 <860 时侧栏自动折叠、只剩图标,文字压根不渲染
      //   ⇒ 命中 0 个。sweep 要在 860/900/940 三档扫这一页,那三档全会静默漏掉。
      //   按**位置**点(第 3 个 rail 项)在两种形态下都成立;图标恒在。
      // ★★ **按身份点,不按位置。** 原来点的是 `.cb-rail > div` 的第 3 项 ——
      //   2026-09-09 加「中转站」页时才发现:任何一次插入新页都会让它静默点到别处,
      //   而"点错位置"和"没点中"在截图里长得一模一样。App.tsx 已给每项加 `data-page`。
      //   ⚠️ 仍**不能**用 `?click=日志`:窗口 <860 时侧栏折叠、文字不渲染 ⇒ 命中 0 个,
      //     而 sweep 要在 860/900/940 三档扫这一页。图标恒在,`data-page` 也恒在。
      else if (nav === 'logs' || nav === 'relay') {
        setTimeout(function () {
          var want = nav === 'relay' ? 'relay' : 'logs';
          var el = document.querySelector('.cb-rail [data-page="' + want + '"]');
          if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          // ★ `?rtab=账号|用量` 切中转站页内的版块。**按文字身份点,不按位置** ——
          //   位置耦合在这个仓库已经静默点错过两次(插一页就全歪),而"点错"和"没点中"
          //   在截图里长得一模一样。
          var rtab = p.get('rtab');
          if (rtab) {
            setTimeout(function () {
              var box = document.querySelector('[data-relay-tabs]');
              var hit = 0;
              if (box) {
                var opts = box.querySelectorAll('span,div');
                for (var k = 0; k < opts.length; k++) {
                  if ((opts[k].textContent || '').trim() === rtab) {
                    opts[k].dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    hit++; break;
                  }
                }
              }
              clicks.push('rtab=' + rtab + ' →命中 ' + hit);
              if (!hit) errors.push('中转站页里点不到版块 "' + rtab + '" —— bundle 可能是旧的');
              // ★ `?rrange=30d` / `?rstation=<站名>` —— 在**用量版块内**按文字身份点档位/站。
              //   （`rmode` 随「分模型/总量」两档一起被设计稿取消,2026-09-10。）
              //   限定在 `[data-section="relay-usage"]` 里找,免得点到页签那个 Seg。
              //   位置耦合在本仓静默点错过两次,所以一律按文字。
              setTimeout(function () {
                ['rrange', 'rstation'].forEach(function (name) {
                  var want = p.get(name);
                  if (!want) return;
                  var scope = document.querySelector('[data-section="relay-usage"]');
                  var n = 0;
                  if (scope) {
                    var os = scope.querySelectorAll('span,div');
                    for (var q = 0; q < os.length; q++) {
                      if ((os[q].textContent || '').trim() === want) {
                        os[q].dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        n++; break;
                      }
                    }
                  }
                  clicks.push(name + '=' + want + ' →命中 ' + n);
                  if (!n) errors.push('用量版块里点不到档位 "' + want + '"');
                });
                // ★ `?rcard=<模型名>` 点一张模型卡 = 聚焦（设计稿 §5）。
                //   按 `data-model-card` 身份点,不按位置 —— 位置耦合在本仓静默点错过两次。
                var rcard = p.get('rcard');
                if (rcard) {
                  setTimeout(function () {
                    var c = document.querySelector('[data-model-card="' + rcard + '"]');
                    if (c) c.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    clicks.push('rcard=' + rcard + ' →命中 ' + (c ? 1 : 0));
                    if (!c) errors.push('点不到模型卡 "' + rcard + '"');
                  }, 120);
                }
              }, 260);
            }, 300);
          }
          var items = document.querySelectorAll('.cb-rail [data-page]');
          clicks.push('nav=' + want + ' →rail 共' + items.length + '项,按 data-page 命中 ' + (el ? 1 : 0));
          // 命中数照样要报 —— 没有 `data-page` 的旧构建会静默什么都不点。
          if (!el) errors.push('rail 里没有 data-page="' + want + '" —— 前端 bundle 可能是旧的');
          if (items.length < 5) errors.push('rail 项数异常: ' + items.length);
        }, 500);
      }
      else fire('navigate-traffic');

      // ★ `?prange=7d|90d|今日…` 点平台详情页的档位。按**文字身份**点（本仓纪律:
      //   位置耦合已经静默点错过两次）。用来验"路由分账跟着档位走"。
      var prange = p.get('prange');
      if (prange) {
        setTimeout(function () {
          var hit = 0, os = document.querySelectorAll('#root span, #root div');
          for (var q = 0; q < os.length; q++) {
            if ((os[q].textContent || '').trim() === prange && !os[q].children.length) {
              os[q].dispatchEvent(new MouseEvent('click', { bubbles: true })); hit++; break;
            }
          }
          clicks.push('prange=' + prange + ' →命中 ' + hit);
          if (!hit) errors.push('点不到平台页档位 "' + prange + '"');
        }, 700);
      }

      // ★★ `?pickcard=<名字>` 点一张**账号卡**把它选中，用来验展开的动作条。
      //    ⚠️ 不能用第二个 `click=` —— 同名 query 重复时 `URLSearchParams.get` 只取
      //    第一个（本仓空守卫形态⑨，稀疏夹具就是这么静默失效的）。
      //    ★ 必须点**卡片本身**而不是名字那个 span：名字上没有 onClick，
      //      点它靠冒泡才到卡上；名字要是被改成带子节点的结构，冒泡链就断了。
      var pick = p.get('pickcard');
      if (pick) {
        setTimeout(function () {
          var hit = 0, cards = document.querySelectorAll('[data-cards-grid] > div');
          for (var q = 0; q < cards.length; q++) {
            if ((cards[q].textContent || '').indexOf(pick) >= 0) {
              cards[q].dispatchEvent(new MouseEvent('click', { bubbles: true })); hit++; break;
            }
          }
          clicks.push('pickcard=' + pick + ' →命中 ' + hit);
          if (!hit) errors.push('点不到账号卡 "' + pick + '"');
        }, 900);
      }

      // ★ `?mbshow=<ms>` 在指定时刻发 `menubar-shown` —— Rust 是在 `win.show()` 之后发它的
      //   (lib.rs 的 `toggle_menubar`)。菜单栏的高度靠这个事件在**窗口真正可见时**重量一次,
      //   所以要验那条路径,必须能在 harness 里模拟"用户点了托盘"。
      var mbs = parseInt(p.get('mbshow') || '0', 10);
      if (mbs) setTimeout(function () { fire('menubar-shown'); }, mbs);

      // ★★ `?busyfrom=<actionId>` 模拟**另一个 webview** 正在跑某个动作。
      //    harness 只渲染一个 webview,所以"跨窗口同步"这条路径**只能这样验**:
      //    `useBusyMirror` 的接收端不关心事件从哪来,只看 `from` 是不是自己 ——
      //    这里发 `from: 'other-window'`,正是真机上另一个窗口发来的形状。
      //    ⚠️ 没有这个开关,「两端同步」的改动在 harness 里**一个像素都验不到**,
      //      而截图会正常渲染、探针会报干净 —— 本仓点名过的那种假绿。
      // ★★ `?agypush=<rem>` 模拟**采样器写完 sidecar、Rust 广播**（Phase 5）。
      //   判据是"推送到达后 UI 上的数变了" —— 而不是源码里有没有 `listen`。
      if (p.get('agypush')) {
        setTimeout(function () { agyPushed = true; fire('agy-quota-updated'); }, 900);
      }
      if (p.get('busyfrom')) {
        setTimeout(function () {
          fire('action-busy', { action: p.get('busyfrom'), at: Date.now() / 1000,
                                from: 'other-window' });
        }, 200);
      }
      // `?busyself=<actionId>` 是它的**反向对照**:`from` 写成本窗口标签,
      // 接收端必须**忽略**它。少了这条,自过滤那行删掉也不会有测试变红。
      if (p.get('busyself')) {
        setTimeout(function () {
          fire('action-busy', { action: p.get('busyself'), at: Date.now() / 1000,
                                from: (window.__TAURI_INTERNALS__ &&
                                       window.__TAURI_INTERNALS__.metadata &&
                                       window.__TAURI_INTERNALS__.metadata.currentWindow &&
                                       window.__TAURI_INTERNALS__.metadata.currentWindow.label) || 'main' });
        }, 200);
      }
    }, 500);

    // ★★★ `trails` —— 几个**身份格**的取值随时间怎么变，不是它最后是什么。
    //
    //   本仓大部分探针问的是终态（有没有溢出/折行/渲染出来）。但有一整类缺陷**终态永远是对的**，
    //   错的只是中间那几帧 —— 2026-09-14 用户报的「gemini 没有缓存，切档跳来跳去」就是：
    //   每进一次 Gemini 档，`liveSub` 先被池文件里陈旧的 `live_seen` 打回去，约 160ms 后才被
    //   现读改正，于是 Hero 的号名/邮箱/环形百分比整块闪一次、「当前」徽章在两张卡之间跳一趟。
    //   **单次终态快照对它完全沉默，而沉默在报告里长得和通过一模一样**（本仓的老病根）。
    //
    //   采样而不是 MutationObserver：要的是"这一格先后显示过哪些值"，
    //   React 一次 commit 里改哪几个节点不重要。相邻重复值折叠，所以序列长度 = 真实变化次数。
    var trails = {};
    (function watchIdentityCells() {
      var WATCH = {
        // 「当前使用中」到底是谁（Gemini 档的 Hero）。
        hero: '[data-hero-acct]',
        // 分档条上 Gemini 那一枚 pill 的整段文字（含计数）。
        gemtab: '[data-provtab="gemini"]',
      };
      Object.keys(WATCH).forEach(function (k) { trails[k] = []; });
      setInterval(function () {
        Object.keys(WATCH).forEach(function (k) {
          var e = document.querySelector(WATCH[k]);
          var v = e ? (e.textContent || '').trim() : null;
          var t = trails[k];
          if (!t.length || t[t.length - 1].v !== v) {
            t.push({ t: Math.round(performance.now()), v: v });
          }
        });
      }, 16);
    })();

    // ★★★ `?agylive=<subN>` —— 模拟**另一个 webview** 广播了它现读到的当值号。
    //    主窗与菜单栏是两个独立 webview，各自跑 `agy-rotate live --json`，而钥匙串正被
    //    多个常驻 agy 进程反复抢 ⇒ 两次探测落在不同时刻就会得到不同的号。
    //    2026-09-14 用户实报：菜单栏说 `sam`、总览说 `dbk`，同一屏两个答案。
    //    ⚠️ harness 里只渲染**一个** webview，所以那个分歧**结构上模拟不出来** ——
    //      能验的是「收到兄弟的广播之后会不会收敛」，这正是修法本身。
    //    `at` 给一个远大于 `Date.now()` 的值，确保通过单调采纳那一关。
    if (p.get('agylive')) {
      setTimeout(function () {
        fire('agy-live-changed', { sub: p.get('agylive'), drifted: true,
                                   at: Date.now() + 3600000 });
        clicks.push('agylive → 广播 ' + p.get('agylive'));
      }, parseInt(p.get('agylive_at') || '1500', 10));
    }

    // `?click=a,b` —— 按**文本**依次点击(全站 45 处是 div/span+onClick,没有 button 可选)。
    // 用于验证需要交互才出现的形态(选中卡片 → 改名输入框)。取最内层匹配节点,
    // 否则会点到包住它的容器上 —— 那个容器往往挂着**另一个** onClick。
    // 写法 `文本` 或 `文本~2`(第 2 个匹配)。**分隔符不能用 `#`** —— 浏览器会把它之后的
    // 整段当 URL 片段截掉,序号永远传不进来(看起来像"选择器不生效")。★ 同一段文字常出现多次(卡片名在 Hero 里也有一份),
    // 不带序号时默认第 1 个,**并把匹配总数报进探针** —— 否则点错位置和没点中长得一模一样。
    (p.get('click') ? p.get('click').split(',') : []).forEach(function (spec, i) {
      setTimeout(function () {
        var parts = spec.split('~'), want = parts[0].trim(), nth = parseInt(parts[1] || '1', 10);
        // `*前缀` = **包含**匹配。图例这类元素的 textContent 是「名字+数字」连在一起
        // (`缓存读7.51B · 97.24%`),全等匹配永远命不中,而数字是活的没法写死。
        var loose = want.charAt(0) === '*';
        if (loose) want = want.slice(1);
        var all = [];
        document.querySelectorAll('div,span').forEach(function (e) {
          var txt = (e.textContent || '').trim();
          if (loose ? txt.indexOf(want) < 0 : txt !== want) return;
          all = all.filter(function (h) { return !h.contains(e); });   // 只留最内层
          all.push(e);
        });
        clicks.push(spec + ' →命中' + all.length + '个,点第' + nth);
        if (all[nth - 1]) all[nth - 1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        else errors.push('click miss: ' + spec + ' (共' + all.length + '个)');
      }, 700 + i * 300);
    });

    // ★★ `?focusacc=<号名>` 点泳道左侧的号名 → 聚焦(稿子 §3:其余泳道 opacity .28
    //    且事件列表同步过滤)。★ **不能用通用的 `?click=`**:那个是**固定 700ms** 触发,
    //    而泳道要等异步 IPC 回来才渲染 —— 实测它「命中 1 个、零报错」,而截图里
    //    一条泳道都没变暗。命中的是**总览页**上同名的那个元素(切页之前还在)。
    //    「点中了」和「点中了想点的那个」是两回事,这是本轮第三次栽在固定延时上。
    if (p.get('focusacc')) {
      (function pollLane(tries) {
        var el = document.querySelector('[data-lane="' + p.get('focusacc') + '"]');
        if (!el && tries > 0) { setTimeout(function () { pollLane(tries - 1); }, 120); return; }
        clicks.push('focusacc=' + p.get('focusacc') + ' →' + (el ? '命中泳道' : '没找到泳道'));
        if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        else errors.push('focusacc miss: ' + p.get('focusacc'));
      })(20);
    }

    // ★★ `?tipseg=<n>` 给**泳道色块**派发 mouseenter,把时段明细浮层逼出来(稿子 §2)。
    //    与 `?mm=` 不是一回事:那个打的是 `svg rect[fill=transparent]`,而泳道是绝对定位的
    //    div,选择器根本命不中。没有这个开关,浮层(段 token / 模型构成 / 切入原因)
    //    **在 harness 里一个像素都验不到**,而截图会正常渲染、探针会报干净。
    if (p.get('tipseg')) {
      // ★ 必须**轮询等它出现**,不能定死一个延时:泳道要等 `read_proxy_rotation` 这个
      //   异步 IPC 回来才渲染,而固定延时下第一版量到「0 个色块」——那看着像"选择器写错了",
      //   实际只是发早了。同族教训:harness 里凡是等异步产物的驱动都别用固定延时。
      (function pollSeg(tries) {
        var segs = document.querySelectorAll('[data-seg]');
        if (!segs.length && tries > 0) { setTimeout(function () { pollSeg(tries - 1); }, 120); return; }
        var n = parseInt(p.get('tipseg'), 10);
        clicks.push('tipseg →色块共' + segs.length + '个,悬第' + n);
        // ★★ 必须派发 **`mouseover`(bubbles:true)**,不能派发 `mouseenter`。
        //    React 的 `onMouseEnter` 是**合成事件**:它在根节点上监听 `mouseover`/`mouseout`
        //    再自己算进出,原生 `mouseenter` 不冒泡、根本到不了它的委托监听器。
        //    实测:派发 mouseenter → 13 个色块全命中、零报错、浮层**一个字都没出来**;
        //    换成 mouseover 才真的渲染。这正是"命中了 ≠ 生效了"的又一例。
        if (segs[n - 1]) segs[n - 1].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        else errors.push('tipseg miss: 只有 ' + segs.length + ' 个色块');
      })(20);
    }

    // `?mm=<0..100>` 在图表命中带上派发 mousemove,把 hover 浮层逼出来。
    // headless 里鼠标事件不会自己发生,而"悬浮才出现的读数"恰恰只能这样验。
    if (p.get('mm')) {
      setTimeout(function () {
        var rects = document.querySelectorAll('svg rect[fill="transparent"]');
        var hit = rects[rects.length - 1];
        if (!hit) { errors.push('mm: 没找到命中带'); return; }
        var r = hit.getBoundingClientRect();
        var x = r.left + r.width * (parseFloat(p.get('mm')) / 100);
        ['mouseenter', 'mousemove'].forEach(function (type) {
          hit.dispatchEvent(new MouseEvent(type, {
            bubbles: true, clientX: x, clientY: r.top + r.height / 2,
          }));
        });
      }, 1400);
    }

    // 探针:横向溢出是本项目 UI 的主要失败模式(外层 overflow:hidden,溢出被静默裁掉)。
    setTimeout(function () {
      var over = [];
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length && over.length < 6; i++) {
        var e = all[i];
        if (e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1) {
          // ★ 带上文本片段。只报 `SPAN 210/174` 没法诊断 —— 得知道是**哪段内容**装不下。
          //   同时排掉**本来就可滚动**的容器:每个页面自带滚动容器是项目规则,报它们纯属噪音。
          var ocs = getComputedStyle(e);
          if (ocs.overflowX === 'auto' || ocs.overflowX === 'scroll'
              || ocs.overflow === 'auto' || ocs.overflow === 'scroll') continue;
          // ★ **带省略号的元素本来就 scrollWidth > clientWidth** —— 那正是省略号在工作,
          //   不是缺陷。不排掉的话,每个刻意做了截断的标签(数据源路径、长模型名)都会被报一次,
          //   真缺陷淹在噪音里。这与「散文允许换行」是同一条原则:**刻意的取舍不是缺陷**。
          if (ocs.textOverflow === 'ellipsis') continue;
          // ★ **浮动读出层本来就在盒子外**（`.cb-hoverpop`，绝对定位、`pointer-events:none`）。
          //   它会计进父元素的 scrollWidth，但那不是"内容装不下"——是这个设计的定义。
          //   不排掉的话，每个带悬浮浮层的角标都会被报一次，真溢出淹在噪音里
          //   （同上面省略号那条：**刻意的取舍不是缺陷**）。
          //   ⚠️ 判据必须是**整棵子树**，不是 `:scope >`（2026-09-21 修）。角标一旦被挂到
          //     别的元素里（这次是泳道表头的「账号」旁），浮层就成了祖先的**孙节点**，
          //     原写法够不到 ⇒ 祖先被报成横向溢出 477/152。而那仍然只是浮层的宽度。
          //   ★ 代价说清楚：带浮层的那条祖先链**整条**不再被溢出探针覆盖。可以接受的原因是
          //     浮层本身尺寸受 `maxWidth: min(…, 92vw)` 约束（另有闸盯着），而祖先链上真正
          //     会溢出的内容仍会被**它们自己那一层之外**的兄弟节点暴露出来。
          if (e.querySelector && e.querySelector('.cb-hoverpop')) continue;
          over.push((e.className || e.tagName) + ' ' + e.scrollWidth + '/' + e.clientWidth
                    + ' 「' + (e.textContent || '').trim().slice(0, 22) + '」');
        }
      }
      var r = document.getElementById('root');
      document.title = '__PROBE__' + JSON.stringify({
        // ★ 先看 mounted:它为 0 说明整页没渲染,此时 overflow 的"无"是**假阴性**,不是通过。
        mounted: r ? r.querySelectorAll('*').length : 0,
        rootW: r ? r.scrollWidth + '/' + r.clientWidth : null,
        // ★ 身份格的**变化序列**（见上面 `watchIdentityCells`）。瞬态缺陷只能在这里看见。
        trails: trails,
        // 菜单栏弹窗的高度由 JS 量 `.mb-root` 的 scrollHeight 再 setSize 出来。
        // 量它随时间怎么变,才能区分「内容超过 PANEL_H_MAX 被钳」和「量早了、之后没再量」。
        mbH: (function () {
          var e = document.querySelector('.mb-root');
          return e ? { scroll: e.scrollHeight, client: e.clientHeight,
                       bodyScroll: document.body.scrollHeight } : null;
        })(),
        // ★ 溢出探针会把**本来就可滚动**的容器算进去(每个页面都有自己的滚动容器,那是项目规则)。
        //   过滤掉 overflow:auto/scroll 的元素,否则每次扫描都带一堆无意义的 DIV。
        overflow: (over || []).filter(function (x) { return true; }),
        // ★ 可滚容器的实测几何。加它是因为「内容放不下时到底是**滚动**还是**裁切**」
        //   在别的探针里分不出来:两种情况的 `overflow` 都是 0(裁切根本不算溢出)。
        //   而裁切比太高更糟 —— 下面的内容直接看不见,还没有滚动条提示。
        geom: (function () {
          var out = {};
          // ★ `mb-today` / `mb-pane` 是 2026-09-06 加的:面板固定高之后,**空白**成了新缺陷,
          //   而空白量 = 窗口高 − 内容自然高,少量一个就算不出来。
          ['mb-root', 'mb-pane', 'mb-list', 'mb-today'].forEach(function (c) {
            var el = document.querySelector('.' + c);
            if (!el) { out[c] = 'missing'; return; }
            var cs = getComputedStyle(el);
            out[c] = { h: Math.round(el.getBoundingClientRect().height),
                       scrollH: el.scrollHeight, clientH: el.clientHeight,
                       maxH: cs.maxHeight, flex: cs.flex, minH: cs.minHeight,
                       ovY: cs.overflowY, parent: el.parentElement ? el.parentElement.className : '?' };
          });
          return out;
        })(),
        scrollables: (function () {
          var out = [];
          document.querySelectorAll('*').forEach(function (el) {
            var cs = getComputedStyle(el);
            if (cs.overflowY !== 'auto' && cs.overflowY !== 'scroll') return;
            if (el.scrollHeight <= el.clientHeight + 1) return;   // 装得下,不是可滚状态
            out.push({ sel: el.className || el.tagName,
                       scrollH: el.scrollHeight, clientH: el.clientHeight,
                       hidden: el.scrollHeight - el.clientHeight });
          });
          return out;
        })(),
        // ★★ **被 flex 压扁的元素** —— 既有的 `overflow` 探针对它完全是瞎的:
        //   flex 布局在空间不够时**压缩子项**而不是溢出,所以 `scrollWidth > clientWidth` 永远不成立,
        //   元素还在 DOM 里、文本也还在,只是渲染宽被压到接近 0 ⇒ 肉眼看是"这个字段没了"。
        //   2026-08-23 缩菜单栏宽度时踩到:332px 下当前号那行的「到期 2026-09-08」整个消失,
        //   而 overflow=无、DOM 里日期一个不少,两种自动检查全绿。判据只能是**渲染宽 vs 自然宽**。
        squeezed: (function () {
          var r0 = document.getElementById('root');
          var out = [], all = r0 ? r0.querySelectorAll('*') : [];
          for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.children.length) continue;                 // 只看叶子节点
            var tag = e.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TITLE') continue;
            if (tag === 'svg' || tag === 'path' || tag === 'circle' || tag === 'rect') continue;
            var t = (e.textContent || '').trim();
            if (!t) continue;
            var shown = e.getBoundingClientRect().width;
            if (shown > 4) continue;                          // 还看得见就不算
            out.push(t.slice(0, 24) + ' →' + Math.round(shown) + 'px');
          }
          return out.slice(0, 8);
        })(),
        // ★★ **折行探针** —— 前面三个探针对"文字在控件内部折行"全是瞎的:
        //   `overflow` 要 scrollWidth>clientWidth(flex 压缩时不成立);
        //   `squeezed` 只认渲染宽 ≤4px,而「切换到此号」被压到 ~20px 竖排,正好漏过;
        //   `--dump-dom` 拿的是源文本,根本看不到浏览器在哪断的行。
        //   判据只能是**渲染高 vs 单行高**:叶子文本节点高过 1.6 行 = 它折行了。
        //   2026-08-24 用户连报三处(头部按钮 / 菜单栏刷新时间 / 卡片动作条),
        //   全部靠肉眼截图发现 —— 这个探针就是为了让下一次不必再靠肉眼。
        // ★★ 互斥单选控件（`Seg`）**折成了几行**。
        //   上面那个 `wrapped` 探针看不见这一类：它判的是**叶子文本节点**的渲染高，
        //   而 Seg 折行时每个 span 仍是单行、折的是**容器**。
        //   2026-08-24 用户连报三处「控件被压成竖排」、2026-09-16 又报一次
        //   （平台详情页「分模型/总量」折两行、旁边的档位条一行，两个控件组高度对不齐）
        //   —— 全部靠肉眼截图发现。这条探针就是为了让下一次不必再靠肉眼。
        //   ★ 判据 = 容器 clientHeight ÷ 第一个子项 offsetHeight，四舍五入即行数。
        segRows: (function () {
          var out = [], all = document.querySelectorAll('[data-seg]');
          for (var i = 0; i < all.length; i++) {
            var e = all[i], k = e.firstElementChild;
            if (!k || !k.offsetHeight) continue;
            out.push({ opts: e.getAttribute('data-seg'),
                       rows: Math.round(e.clientHeight / k.offsetHeight),
                       w: Math.round(e.getBoundingClientRect().width) });
          }
          return out;
        })(),
        wrapped: (function () {
          var r0 = document.getElementById('root');
          var out = [], all = r0 ? r0.querySelectorAll('*') : [];
          for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.children.length) continue;
            var tag = e.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TITLE') continue;
            if (tag === 'svg' || tag === 'path' || tag === 'circle' || tag === 'rect') continue;
            var t = (e.textContent || '').trim();
            if (!t) continue;
            var cs = getComputedStyle(e);
            var lh = parseFloat(cs.lineHeight);
            if (!lh || isNaN(lh)) lh = parseFloat(cs.fontSize) * 1.2;
            // ★ 必须减掉 padding,比的是 **content box**。第一版拿 border box 比,
            //   `padding: 7px 11px` 的按钮单行高就有 27px,对 13px 行高判成"折行" ——
            //   一次扫描报出 4 个假阳性,而真正折行的那条淹没在里面。
            var h = e.clientHeight
                    - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0);
            if (h <= lh * 1.6) continue;               // 单行,正常
            // ★★ **折行不等于缺陷。** 规则是「控件与原子值不许折行,散文可以」——
            //   设置页的说明段落、降级横幅的那句话本来就该换行。第一版不分青红皂白全报,
            //   一次扫描 10 处里 6 处是误报,而项目铁律说「一盏长亮的灯指错方向比没有更糟」。
            //   判据三选一(命中即视为控件/原子值):
            //     · 可点(cursor:pointer)—— 按钮、分段控件、可点的时间戳
            //     · 等宽字体 —— 设计规范规定"一切数字/时间/代码/标签/模型名"都用 JetBrains Mono
            //     · 短文本(≤12 字)—— 标题、徽章、单位这类不该断的碎片
            // ★ **散文一律放行,先于任何其它判据** —— grok 降级横幅那段话在可点的卡片里,
            //   会从祖先**继承** `cursor:pointer`,第一版据此把它判成控件。继承来的 pointer
            //   说明不了这个元素是控件。控件文本天然短,所以长度门是更可靠的判据。
            if (t.length > 20) continue;
            var interactive = cs.cursor === 'pointer';
            var mono = (cs.fontFamily || '').indexOf('JetBrains Mono') >= 0;
            var atomic = t.length <= 12;
            if (!interactive && !mono && !atomic) continue;   // 散文:允许换行
            out.push(t.slice(0, 20) + ' 内容高' + Math.round(h) + '/行' + Math.round(lh)
                     + (interactive ? ' [可点]' : mono ? ' [等宽]' : ' [短]'));
          }
          return out.slice(0, 12);
        })(),
        // ★★ **对齐探针**:报每张账号卡里「到期」那行的 y 坐标。卡片之间要对齐到同一条
        //   水平线,靠肉眼比截图判不准(用户 2026-08-26 用红线标出来才发现),而且
        //   偏移可能有**多个来源**(窗口条数不同、徽章行折行数不同),只看一个会漏。
        //   同时报徽章行的高度 —— 那是第二个偏移源。
        alignY: (function () {
          var out = { expiry: [], bars: [], rings: [], expanded: [], cards: [] };
          var grid = document.querySelector('[data-cards-grid]');
          if (!grid) return out;

          // 这个元素属于哪张卡 = 网格的哪个**直接子元素**。比"向上找账号名"可靠 ——
          // 后者在某些层级会先撞到 hero 或相邻卡（我 2026-08-26 就被这样误导过一轮）。
          function cardOf(el) {
            var n = el;
            while (n && n.parentElement !== grid) n = n.parentElement;
            return n;
          }
          var meta = new Map();       // card 元素 → {name, expanded}
          Array.prototype.forEach.call(grid.children, function (card) {
            var name = '?';
            card.querySelectorAll('span').forEach(function (x) {
              if (name === '?' && /^(plus\d+|Pro\d+|grok)$/.test((x.textContent || '').trim()))
                name = x.textContent.trim();
            });
            // ★ 展开态判据 = 动作条里那颗「重命名」按钮。它只在选中时渲染,
            //   且不是任何其他地方的文案 —— 比按 class/结构猜稳。
            var expanded = false;
            card.querySelectorAll('span').forEach(function (x) {
              if ((x.textContent || '').trim() === '重命名') expanded = true;
            });
            var cr = card.getBoundingClientRect();
            var rowMain = card.querySelector(':scope > div');
            var col = rowMain && rowMain.children.length > 1 ? rowMain.children[1] : null;
            var hs = [];
            if (col) Array.prototype.forEach.call(col.children, function (c) {
              hs.push(Math.round(c.getBoundingClientRect().height));
            });
            out.cards.push(name + ' ' + Math.round(cr.width) + '×' + Math.round(cr.height)
                           + ' 列内=[' + hs.join(',') + ']');
            meta.set(card, { name: name, expanded: expanded });
            if (expanded) out.expanded.push(name);
          });
          // ★ 标签里带上**网格行号**（卡片顶边）。卡片多于 3 张时网格会换行，
          //   跨行比 y 必然把"第二行"读成错位 —— 那是把两排东西放一起比。
          function tag(el) {
            var c = cardOf(el);
            var m = c ? meta.get(c) : null;
            if (!m || !c) return '?#r0';
            return m.name + (m.expanded ? '(展开)' : '') + '#r'
                   + Math.round(c.getBoundingClientRect().top);
          }

          // 「到期」行
          grid.querySelectorAll('span').forEach(function (e) {
            var t = (e.textContent || '').trim();
            if (t.indexOf('到期') !== 0) return;
            var r = e.getBoundingClientRect();
            if (r.width >= 1) out.expiry.push(tag(e) + '@' + Math.round(r.top));
          });

          // 条形行:按「窗口标签 → y」收。同一种窗口(5h / 周)必须落在同一条线上 ——
          // 只看「到期」对齐不够,用户的红线画在条上。
          grid.querySelectorAll('span').forEach(function (e) {
            var t = (e.textContent || '').trim();
            if (t.charAt(0) !== '↻') return;              // ↻ = 重置倒计时,每条条形行都有
            var row = e.parentElement; if (!row) return;
            var lab = row.firstElementChild;
            var vis = row.style.visibility !== 'hidden';
            out.bars.push(tag(e) + '/' + (lab ? lab.textContent.trim() : '?') + (vis ? '' : '(空)')
                          + '@' + Math.round(row.getBoundingClientRect().top));
          });

          // 环:卡片里唯一 52×52 的 svg。报**中心 y** —— 环是圆的,比顶边更能反映"看起来在不在一条线上"。
          // ★ 用户 2026-08-26 指出环顶对齐难看,改回居中;居中之后它也必须跨卡对齐,所以一并守住。
          grid.querySelectorAll('svg').forEach(function (e) {
            var r = e.getBoundingClientRect();
            if (Math.round(r.width) !== 52) return;
            out.rings.push(tag(e) + '@' + Math.round(r.top + r.height / 2));
          });
          return out;
        })(),
        errors: errors.slice(0, 4),
        unknownCmds: unknown.filter(function (v, i, a) { return a.indexOf(v) === i; }),
        clicks: clicks,
        // ★ 只记 sub+arg,**不记 payload** —— 它含 API key。
        relayCalls: relayCalls,
        // 只报关心的两个,别把 plugin:event|* 的噪音带进来
        sizes: sizes,
        idleTray: idleTray,
        ipc: { run_traffic: ipc['run_traffic'] || 0,
               read_traffic_snapshot: ipc['read_traffic_snapshot'] || 0 },
        emitted: emitted.slice(0, 12),
        // 字体探针:app 的字体是本地 woff2,没加载上会静默回落到系统 sans —— 截图上看不出来
        fonts: {
          mono: document.fonts.check('12px "JetBrains Mono"'),
          disp: document.fonts.check('12px "Space Grotesk"'),
          loaded: Array.from(document.fonts).map(function (f) { return f.family; })
            .filter(function (v, i, a) { return a.indexOf(v) === i; }),
        },
        computed: (function () {
          var pick = function (sel) {
            var e = document.querySelector(sel);
            return e ? getComputedStyle(e).fontFamily.split(',')[0].replace(/["']/g, '') : null;
          };
          return { h1: pick('h1'), body: getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, '') };
        })(),
        inputs: Array.prototype.map.call(document.querySelectorAll('input'), function (e) {
          var r = e.getBoundingClientRect();
          return { v: e.value, w: Math.round(r.width), h: Math.round(r.height), focus: e === document.activeElement };
        }),
        text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 700),
      });
    // ★ 探针是**一次性**的:到点写一次 title 就不再更新。默认 2200ms 足够等首屏+入场动效,
    //   但验**定时器驱动**的东西(30s 心跳)时必须调大,否则观测窗口根本没到 —— 我就因此
    //   量出「开关开/关都是 1 次扫描」,差点把"没测到"当成"闸没生效"。
    //   配 `--virtual-time-budget` 一起用,虚拟时间下 150s 只要几秒真实时间。
    }, parseInt(p.get('probe_ms') || '2200', 10));
  });
})();
</script>
"""

def redacted_state():
    """把真实 state.json 脱敏成 fixture。

    ★ **结构、额度、套餐、到期日、重置卡全部保真** —— 用设计稿假数据渲染量不出真实排版
    (上次正是真数据才暴露出徽章变长把日期挤断行)。**只替换能认人的三样**:邮箱、姓名、
    account_id。account_id 同时是槽位的键和 `active` 的值,必须整体重映射,否则「当前号」判错。
    """
    raw = json.loads((REPO / "state.json").read_text())
    idmap, out_slots = {}, {}
    for i, (aid, sl) in enumerate(raw.get("slots", {}).items(), 1):
        fake = f"user-demo{i:02d}0000000000000000000000"
        idmap[aid] = fake
        sl = dict(sl)
        sl["email"] = f"demo{i}@example.com"
        sl.pop("name", None)
        sl["file"] = f"{fake}.json"
        out_slots[fake] = sl
    # ★★ `?lowquota=1` 把额度压到会**触发警告色**的档位。
    #    真实数据现在全是高额度,所以「低额度夺色」那条路径**截图根本证明不了** ——
    #    而它正是用户明确要求的行为(2026-08-26:「低额度靠条色报警」)。
    #    只改 used_percent,窗口结构/套餐/到期日全部保真。
    if os.environ.get("CODEXBAR_LOW_QUOTA"):
        levels = [(72.0, 5.0), (95.0, 58.0)]     # (5h 已用, 周已用) → 剩 28% 琥珀 / 剩 5% 红
        for i, sl in enumerate(out_slots.values()):
            q = sl.get("quota") or {}
            for k, used in zip(("primary", "secondary"), levels[i % len(levels)]):
                w = q.get(k)
                if isinstance(w, dict) and w.get("window_minutes"):
                    w["used_percent"] = used
    # ★★ `CODEXBAR_STALE_QUOTA=1` 把**第二个活号**的快照做旧(3.8 天前)。
    #    这是**唯一能验证陈旧标记的夹具**:真实数据里唯一陈旧的号是 Pro1,而它是死号、
    #    只在折叠的「失效账号」区渲染、根本没有卡片 —— 于是那个标记**永远截不到**,
    #    只能得到一个「看起来没问题、实际从未被验证过」的结论(本仓刚为同类问题栽过一次)。
    if os.environ.get("CODEXBAR_STALE_QUOTA"):
        # ★ 必须挑**活号**。第一版挑的是 `values()[1:2]`,而那恰好是死号 —— 死号只在折叠的
        #   「失效账号」区渲染、**根本没有卡片**,于是标记 0 次,夹具白造。
        #   (这也正是真实数据验不了这条的原因:线上唯一陈旧的号就是那个死号。)
        for sl in out_slots.values():
            q = sl.get("quota")
            if sl.get("auth_dead") or not isinstance(q, dict) or not q.get("captured_at"):
                continue
            q["captured_at"] -= int(3.8 * 86400)
            break

    # ★★ `CODEXBAR_FLOATING_ANCHOR=1` 给**第一个活号的每个窗口**造一份账本判定
    #    `floating`，于是倒计时渲染成「未启动」。
    #    这是**唯一能证明那条分支真的渲染出来的夹具**：真实 `state.json` 里 `quota_anchor`
    #    要 quotad 连观测三轮才会出现 `floating`，而截图当下多半是 `unknown`（回落成「待确认」）
    #    —— 只用真数据截图，只能证明回落路径没坏，**证不了新分支存在**。
    #    本仓 2026-09-05 刚为同类问题栽过：8 个新视图全判「干净」，而那些组件一个都没渲染。
    if os.environ.get("CODEXBAR_FLOATING_ANCHOR"):
        for sl in out_slots.values():
            q = sl.get("quota")
            if sl.get("auth_dead") or not isinstance(q, dict):
                continue
            anchor = {"at": q.get("captured_at")}
            for k in ("primary", "secondary"):
                w = q.get(k)
                if isinstance(w, dict) and w.get("window_minutes") and w.get("resets_at"):
                    # `reset` 必须与窗口现值对得上 —— 前端要核身份,对不上就回落。
                    anchor[str(int(w["window_minutes"]))] = {
                        "state": "floating", "held_secs": 0, "samples": 1,
                        "slides": 3, "used_max": 0.0, "reset": int(w["resets_at"])}
            if len(anchor) > 1:
                sl["quota_anchor"] = anchor
                break

    # ★★ `?cardexp=1` 只给**第一个**号一张快到期的重置卡 ⇒ 它的徽章文案变长
    #    （「重置卡 ×1 · 剩1天」），另一个号仍是短文案。
    #    这是**唯一能证伪"卡片已对齐"的夹具**：页脚一旦因文案长短而折行高度就不同，
    #    而条形区是从页脚往上推的 —— 真实数据里两个号的徽章恰好一样长，
    #    只用它截图会得到一个**看起来对齐、实际没被验过**的结论。
    if os.environ.get("CODEXBAR_CARD_EXPIRING"):
        soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        first = next(iter(out_slots.values()), None)
        if first is not None:
            first["credits_detail"] = {"credits": [{"status": "available", "expires_at": soon}]}
    # ★★ `?unprobed=1`：加一个**刚加进来、从没探测过**的号（`windows: []`）。
    #    这个夹具不是凑数的，它一次抓到两件事（2026-08-26）：
    #      ① 池里到 3 个号时，三列网格把 grok 挤到**第二行** —— 对齐必须按排比，跨排比必然误报；
    #      ② 没有窗口的卡不画任何条形行，行数与兄弟卡不同 ⇒ 它的「到期」高 9px。
    #    真实 state.json 里两个号都探测过，**不造这个状态就永远验不到**。
    if os.environ.get("CODEXBAR_UNPROBED"):
        fake = "user-demo990000000000000000000000"
        out_slots[fake] = {"label": "Newbie", "email": "newbie@example.com", "file": f"{fake}.json"}
    # ★★ 置顶队列（2026-09-21）。**夹具必须真有两个** —— 只有一个的话「队列位次」
    #   那半（角标上的 1 / 2）一个像素都验不到，而截图会正常渲染、探针报干净。
    #   取前两个非 dead 的号，与 `pinned` 的真实形状一致（aid 列表，按点击先后）。
    alive_ids = [a for a, sl in out_slots.items() if not sl.get("auth_dead")]
    # ★★ **「停轮换」状态不能指望真 state.json 恰好有** —— 夹具取自真实状态，而用户一旦把所有号都放回轮换，
    #   `test_connector_oneclick` / `test_runway_hero` 两条依赖「有 rotate_off 的号」的闸会**一起红**（2026-10-03 实测：
    #   真状态里 9 个号 0 个停用）。判别力不能靠运气：不足 3 个时，从**末尾**补到 3 个（与此前真实形状同量：3 个），
    #   不动前面的号 —— 置顶 / 重置卡等夹具依赖的前几个号保持原样。
    off = [a for a in alive_ids if out_slots[a].get("rotate_off")]
    for a in reversed(alive_ids):
        if len(off) >= 3:
            break
        if a not in off:
            out_slots[a]["rotate_off"] = True
            off.append(a)
    # ★★ 「快到期的重置卡」同理不能靠运气（2026-10-14：真状态里没有 3 天内到期的卡 ⇒
    #   `test_card_left_wording` 没有一张「剩 N 天」角标可比，闸失去判别力而红）。
    #   没有就从**末尾**挑一个没卡的活号补一张 30 小时后到期的（「剩1天」），不动前面的号 ——
    #   置顶 / 用卡弹窗（3 张卡那个号）等夹具依赖它们。30h 而不是整 24h：落在天与小时的分界之外，
    #   免得 harness 生成到测试运行之间的几分钟把它推过边界。
    now_s = time.time()

    def _soon(sl):
        for c in (sl.get("credits_detail") or {}).get("credits") or []:
            try:
                t = time.mktime(time.strptime(c.get("expires_at", "")[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            except (ValueError, TypeError):
                continue
            if c.get("status") == "available" and c.get("id") and 0 < t - now_s <= 3 * 86400:
                return True
        return False
    if not any(_soon(out_slots[a]) and (out_slots[a].get("credits") or {}).get("available")
               for a in alive_ids):
        for a in reversed(alive_ids):
            sl = out_slots[a]
            if (sl.get("credits") or {}).get("available"):
                continue
            sl["credits"] = {**(sl.get("credits") or {}), "available": 1}
            sl["credits_detail"] = {"credits": [{
                "id": "card-demo-soon", "status": "available",
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_s + 30 * 3600))}]}
            break
    active = idmap.get(raw.get("active"), "")
    # ★★ `last_aid`（代理最近一次真的用了谁）**必须与 `active` 不同**（2026-09-23）。
    #   菜单栏/托盘改成跟代理走之后，判据就是「高亮落在 last_aid 而不是 active 上」——
    #   两者相同的夹具下，改没改都是同一个像素（本仓形态⑩：判据档位要挑只有被测那条能挡住的输入）。
    # ★ 挑「剩得最多」的那个（2026-10-21）：原来取第一个活号，它是不是碰巧见底由当天用量决定 ——
    #   在用号见底就多出刘海告警行、菜单栏通知，同一份代码下午重生成 harness 后 4 条闸变红。
    def _used(a):
        q = out_slots[a].get("quota") or {}
        return max((q.get(w) or {}).get("used_percent") or 0 for w in ("primary", "secondary"))
    others = [a for a in alive_ids if a != active]
    last_aid = min(others, key=lambda a: (_used(a), alive_ids.index(a))) if others else active
    # ★ 置顶里必须有在用的那个（2026-10-21）：「正在使用」上的置顶角标只画给置顶号，
    #   原来固定取前两个活号，在用号换成「剩得最多」后它在不在置顶里就看当天用量（`test_the_pin_is_visible_on_the_banner` 红过）。
    pinned = [last_aid] + [a for a in alive_ids if a != last_aid][:1]
    return {"active": active, "last_aid": last_aid, "slots": out_slots,
            "pinned": pinned,
            "last_proxy_ts": raw.get("last_proxy_ts")}


def agy_rot_fixture():
    """合成三个号的 agy 会话日志 + 换号记录，交给**真引擎** `agy_rotation.collect` 算一份 24h 的结果。

    ★ 形状覆盖：同号长会话、并发会话、有记录的换号、**没有记录的换号**（钥匙串被写回 ⇒ drift）、
      一场认不出身份的会话（进 `responses_unplaced`）、一个池里有但窗口内没跑过的号。
    """
    import sys as _s
    import tempfile as _t
    _s.path.insert(0, str(HERE.parent.parent / "traffic"))
    import agy_rotation as AR
    now = time.time()
    from pathlib import Path
    d = Path(_t.mkdtemp(prefix="harness-agyrot-"))
    logs = d / "log"; logs.mkdir()
    runs = [(-20 * 3600, -14 * 3600, "demo0@example.com"), (-13 * 3600, -9 * 3600, "demo0@example.com"),
            (-8.5 * 3600, -6 * 3600, "demo1@example.com"), (-5.5 * 3600, -2 * 3600, "demo0@example.com"),
            (-5 * 3600, -4 * 3600, "demo0@example.com"), (-90 * 60, -10, "demo1@example.com"),
            (-3 * 3600, -3 * 3600 + 600, None)]
    for i, (a, b, email) in enumerate(runs):
        t0 = now + a
        f = logs / time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(t0 + i))
        body = "I%s 00000 x.go:1] start\n" % time.strftime("%m%d %H:%M:%S.000000", time.localtime(t0))
        if email:
            body += "I%s 11111 server_oauth.go:196] applyAuthResult: email=%s, authMethod=consumer\n" % (
                time.strftime("%m%d %H:%M:%S.000000", time.localtime(t0 + 2)), email)
        f.write_text(body)
        os.utime(f, (now + b, now + b))
    (d / "agy.log").write_text("[agy %s] auto 自动切到 [Asen]（剩余 91.0%%，new，落点 keyring）\n"
                               % time.strftime("%m-%d %H:%M:%S", time.localtime(now - 8.5 * 3600 - 30)))
    (d / ".agy-pool.json").write_text(json.dumps({"accounts": {
        "s0": {"label": "qq55", "email": "demo0@example.com", "quota": {"gemini": {"remaining": 0.93}}},
        "s1": {"label": "Asen", "email": "demo1@example.com", "quota": {"gemini": {"remaining": 0.41}}},
        "s2": {"label": "Huo", "email": "demo2@example.com", "quota": {"gemini": {"remaining": 1.0}},
               "rotate_off": True}}}))
    return AR.collect(24, now=now, log_dir=logs, store=d)


# 版本号从 tauri.conf.json 现取 —— 写死过 0.9.0,发到 0.9.1 后截图上的版本号就在说假话
VERSION = json.loads((HERE.parent / "src-tauri/tauri.conf.json").read_text())["version"]
stub = (STUB.replace("__SNAPSHOT__", json.dumps(snapshot))
            .replace("__VERSION__", json.dumps(VERSION))
            # ★ 现算,不写死:grok 夹具里的重置时间和"N 分钟前"都是相对 now 的,
            #   钉死一个时间戳会让夹具随日子腐烂成「已重置 / 3 天前」,那时截出来的图是错的。
            .replace("__NOW__", str(int(time.time())))
            .replace("__STATE__", json.dumps(redacted_state()))
            .replace("__AGYROT__", json.dumps(agy_rot_fixture())))
ANCHOR = "<script type=\"module\""
for src, dst in (("index.html", "harness.html"), ("menubar.html", "harness-menubar.html"),
                 ("notch.html", "harness-notch.html"), ("tps-hover.html", "harness-tpshover.html")):
    html = (APP / src).read_text()
    assert html.count(ANCHOR) >= 1, f"{src} 注入锚点未命中"
    (APP / dst).write_text(html.replace(ANCHOR, stub + "\n    " + ANCHOR, 1))
    print(f"  ✓ {dst}")
print(f"  ✓ 内联快照 {len(snapshot)//1024}KB，bundle 与部署产物同一份")
print("  ✓ state fixture 已脱敏（邮箱/姓名/account_id 全替换），真实 state.json 未进入伺服目录")
