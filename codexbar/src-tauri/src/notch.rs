//! 刘海额度条（macOS 专属，**默认关**，设置页开）。PR #1 作者 2026-10-17 从 demo 里选定
//! 「收起 = 刘海周围的光晕、悬停 = 额度环面板」（起初是刘海下沿的分段细线，作者嫌不明显换成光晕）。
//! 2026-10-19 交接包 4e：展开态换成「悬浮卡片 + 光桥」—— 卡片在刘海下沿下方 10 pt、宽 300、最高约 560；
//! 吸附 = D 果冻下垂（光标距刘海 24 pt 内，网页按 `notch-cursor` 画一滴黑）；碰到刘海 +2 pt 立即展开。
//!
//! ★ 为什么能做成 Tauri 窗口而不是另起一个 Swift 进程：2026-10-17 独立验证程序实测 ——
//!   层级设到 `NSStatusWindowLevel + 1` 后窗口顶边与屏幕顶边间距 0、盖在菜单栏之上；
//!   全屏应用里可见（PR #1 作者确认）；悬停在 CodexBar 不在前台时照样触发（作者试了十几次）。
//!
//! ★★ 刘海本身**没有像素**。画在刘海矩形里的东西看不见，所以光晕画在刘海**外沿**
//!    （窗口四周多留 `GLOW_X` / `GLOW_Y`）；两侧各 `FLARE` 是刘海上沿的内凹圆角。
//!
//! ★★ 悬停判定**不靠网页里的 mouseenter**：CodexBar 是 Accessory 应用、几乎永远不在前台，
//!    WKWebView 在后台窗口里收不收得到鼠标移动没验过，不赌它。做法分两段（Agent HUD 同理）：
//!    · 平时：系统鼠标事件监听（全局 + 本进程各一个）。鼠标不动就不触发 ——
//!      验证程序里纯轮询（80/250ms）空闲主进程 0.30% CPU（不轮询时的底数没量过）；
//!    · 光标进了刘海所在屏的顶部 `SAMPLE_BAND`（180 pt）：起一个 60 Hz 的跟踪线程（交接包 4e 实装要求），
//!      直到光标离开那一带且卡片收完。监听只负责"叫醒"，进出与停留的判定全在跟踪线程里 ——
//!      光标停在我们自己的窗口上时，全局监听可能收不到事件，只靠事件会"离不开"。
//! ★ 「谁在跑」（光晕）2026-10-19 起在 `activity.rs`：窗口存在时订阅 `activity::NOTCH`，窗口没了就退订。
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl};

pub const LABEL: &str = "notch";
/// 刘海上沿两侧的内凹圆角，窗口要比刘海各宽这么多。与 `notch.css` 的 `--flare` 同值。
const FLARE: f64 = 7.0;
/// 4e 悬浮卡片：宽 300；在刘海下沿下方 `CARD_GAP`；命中区四周各多 `CARD_HIT_PAD`（交接包 page 99 / 4e「实装」）。
/// ★ 与 `notchCard.ts` 的 `CARD_W` / `CARD_GAP`、`notch.css` 的 `--cw` 同值（闸在 `tests/test_notch_hud.py`）。
pub const CARD_W: f64 = 300.0;
pub const CARD_GAP: f64 = 10.0;
const CARD_HIT_PAD: f64 = 10.0;
/// 卡片阴影 `0 18 40 rgba(0,0,0,.5)` + 顶部淡蓝外光要的透明边：blur 40 往外 ~40，向下再多偏移 18。
const CARD_SHADOW_X: f64 = 40.0;
const CARD_SHADOW_B: f64 = 58.0;
/// 卡片高度的上限：交接包「最高约 560 pt（C 场景 + 今日 Tab），需能放进 900 pt 高的 Air 屏幕」。留一点余量。
const CARD_H_MAX: f64 = 600.0;
/// 碰到刘海（+2 pt）立即展开（交接包 4e：「碰到刘海（+2 pt）立即展开」）。
const TOUCH: f64 = 2.0;
/// 光标离开命中区 300 ms 后收起（交接包：「光标离开卡片 10 pt 外 300 ms 收起」）。
const CLOSE_DWELL: Duration = Duration::from_millis(300);
/// 前端收起动画时长（4e：数据淡出 → logo 缩回 → 卡片 140 ms 淡出 + 260 ms 上移 → 光桥延后 80 ms 收回 180 ms）。
/// 收完再缩窗口，否则动画被裁掉。
const COLLAPSE: Duration = Duration::from_millis(560);
/// 60 Hz 采样（交接包 4e：「只在光标 y < 180 pt 时以 60 Hz 读光标算吸附」）。
const TRACK_TICK: Duration = Duration::from_millis(16);
const SAMPLE_BAND: f64 = 180.0;
/// 果冻下垂在光标距刘海 24 pt 内出现；多推 16 pt 让网页能把那滴黑收回去（离开范围时再推最后一帧）。
const DRIP_RANGE: f64 = 24.0;
const CURSOR_EMIT_RANGE: f64 = DRIP_RANGE + 16.0;
/// 收起态窗口在刘海两侧 / 下方多留的透明边，给光晕用。blur(σ) 要往外 ~2σ 才淡到看不见，
/// 外层光晕半宽 = 刘海半宽 + 圆角 + 14、blur 20 ⇒ 要 ≥ 54；下沿到刘海下 12 + 40 ⇒ 要 ≥ 52。
/// 不够的话 blur 的边缘会被窗口裁出一圈直边（第一版只留了 1σ，作者一眼看出「限制了范围」）。
/// 与 `notch.css` 的 `.nh-glow .g1/.g2` 尺寸配套。
/// 窗口收起时**不接收鼠标**，所以这圈边不会挡菜单栏图标。
const GLOW_X: f64 = 60.0;
const GLOW_Y: f64 = 60.0;
/// AICoop P11「刘海屏版」（交接包 2026-10-21 `P11_NotchHover`，1.5× 画、这里 ÷1.5）：**空闲时**
/// 光标进刘海四周的「靠近」区（左右各 60、向下 32）⇒ 网页亮中性白光晕（`notch-near`）；
/// 停在刘海上（刘海 + 下沿 5 pt）180 ms ⇒ 展开额度格子（`notch-mode` = idle）。有 AI 在跑时照旧：碰到即展开 4e 卡片。
const NEAR_X: f64 = 60.0;
const NEAR_B: f64 = 32.0;
const IDLE_DWELL: Duration = Duration::from_millis(180);
const IDLE_DWELL_B: f64 = 5.0;
/// 几何（刘海位置）最多多久重读一次。合盖/开盖/改分辨率后靠它自愈（下一次鼠标移动时）。
const GEOM_TTL: Duration = Duration::from_secs(3);

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Notch {
    /// 刘海左边界，桌面坐标（主屏左上为原点，逻辑 pt）
    pub left: f64,
    pub width: f64,
    pub height: f64,
    /// 刘海所在屏幕顶边在桌面坐标里的 y
    pub top: f64,
    /// 主屏高度：AppKit 坐标（左下原点）换算成桌面坐标要用
    #[serde(skip)]
    primary_h: f64,
    /// 刘海所在屏的左右边界（桌面 x）：60 Hz 采样只在这块屏的顶部那一带开
    #[serde(skip)]
    screen_x: f64,
    #[serde(skip)]
    screen_w: f64,
}

/// `set_notch_hud` 的回答。★ 「开关记住了」与「屏幕上真有东西」是两件事 ——
/// 没有刘海屏时开关照样记着开，但必须让设置页说出来，不能让用户对着空屏幕猜（四方评审 2026-10-17）。
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Status {
    pub active: bool,
    /// `active == false` 的原因：`"no_notch"` = 现在没有带刘海的屏幕（外接屏 / 合盖 / 本来就没有）
    pub reason: Option<&'static str>,
}

/// 推给刘海网页的光标（果冻下垂用）。坐标是**刘海窗口内**的逻辑 pt；`dx` 相对刘海中线；
/// `distance` = 光标到刘海矩形的距离（在刘海里为 0）。
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Cursor { pub x: f64, pub y: f64, pub dx: f64, pub distance: f64 }

static ENABLED: AtomicBool = AtomicBool::new(false);
static OPEN: AtomicBool = AtomicBool::new(false);
/// 这一轮展开是不是空闲额度格子（展开那一刻定，收起前不变 —— 刘海本身不随在跑 / 空闲变样，
/// 中途换内容只会让正在读的人眼前一跳）。
static OPEN_IDLE: AtomicBool = AtomicBool::new(false);
/// 最近一次推给网页的「靠近」（网页挂载时补问一次，`notch-near` 可能早于 listen 生效）。
static NEAR: AtomicBool = AtomicBool::new(false);
/// ★ 代次（四方评审 2026-10-17）：每次开/关 +1，每次展开/收起 +1。后台线程与排进主线程的闭包
///   **执行前**核对自己领到的那一代 —— 关掉之后旧线程不许再把窗口展开、旧的收起计时不许裁掉新一轮动画。
static ENABLE_GEN: AtomicU64 = AtomicU64::new(0);
static OPEN_GEN: AtomicU64 = AtomicU64::new(0);
/// 正在跑的跟踪线程领到的号；0 = 没有。退出时只清**自己那一号**（`compare_exchange`），
/// 否则旧线程退出会把新线程的标记抹掉，于是又起一条。
static TRACKER: AtomicU64 = AtomicU64::new(0);
static TRACKER_SEQ: AtomicU64 = AtomicU64::new(0);
static GEOM: Mutex<Option<(Option<Notch>, Instant)>> = Mutex::new(None);
/// 两种展开各自的面板高度（4e 卡片 / 空闲格子）。★ 分开存：共用一份时，换种类那一下窗口与命中区
/// 先用上一种的高度，要等网页收到 `notch-mode`、再一次 IPC 来回才更正（三方评审 2026-10-21）。
static PANEL_H: Mutex<f64> = Mutex::new(420.0);
static PANEL_H_IDLE: Mutex<f64> = Mutex::new(116.5);
/// 空闲格子面板当前宽（网页报上来，同托盘 `tps_hover::IDLE_W`）：格子少于一行时收窄，不留空白（用户 2026-10-24）。
static PANEL_W_IDLE: Mutex<f64> = Mutex::new(crate::tps_hover::IDLE_PANEL_W);
/// 两个监听器对象（`Retained::into_raw` 出来的指针）。`Retained` 不是 Send，只能这样存。
static MONITORS: Mutex<Vec<usize>> = Mutex::new(Vec::new());

#[repr(C)]
#[derive(Clone, Copy)]
struct EdgeInsets { top: f64, left: f64, bottom: f64, right: f64 }
// SAFETY: 与 AppKit 的 NSEdgeInsets 同布局（四个 CGFloat），编码名一致。
unsafe impl objc2::Encode for EdgeInsets {
    const ENCODING: objc2::Encoding = objc2::Encoding::Struct(
        "NSEdgeInsets",
        &[f64::ENCODING, f64::ENCODING, f64::ENCODING, f64::ENCODING],
    );
}

/// 一块屏的 AppKit 几何 → 刘海在桌面坐标里的位置。纯函数，单测覆盖「刘海屏不是主屏」。
///
/// ★ 只用两块 auxiliary 区域的**宽度**，不用它们的 origin：左块从屏幕左沿开始、右块到屏幕右沿结束
///   是定义，于是刘海 = `[frame.x + 左块宽, frame.x + frame.w − 右块宽]`。这样不必赌 auxiliary
///   矩形用的是全局坐标还是屏幕局部坐标 —— 刘海屏是主屏（原点 0）时两种说法恰好相等，测不出来。
fn notch_from(frame: (f64, f64, f64, f64), primary_h: f64, inset_top: f64,
              left_w: f64, right_w: f64) -> Option<Notch> {
    let (fx, fy, fw, fh) = frame;
    if inset_top <= 0.0 { return None; }
    let left = fx + left_w;
    let right = fx + fw - right_w;
    if right <= left { return None; }
    Some(Notch { left, width: right - left, height: inset_top, top: primary_h - (fy + fh), primary_h,
                 screen_x: fx, screen_w: fw })
}

/// 带刘海的那块屏幕上，刘海的位置。没有刘海的屏幕 ⇒ `None`（PR #1 作者 2026-10-17 定：
/// 外接屏、合盖时**不显示**，不画替身条）。主线程调用。
fn read_notch() -> Option<Notch> {
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use objc2_foundation::NSRect;
    // SAFETY: 只读 NSScreen 的几何属性；对象来自 `+screens`，在本次调用内有效。
    unsafe {
        let screens: *mut AnyObject = msg_send![class!(NSScreen), screens];
        if screens.is_null() { return None; }
        let n: usize = msg_send![screens, count];
        if n == 0 { return None; }
        let primary: *mut AnyObject = msg_send![screens, objectAtIndex: 0usize];
        let pf: NSRect = msg_send![primary, frame];
        for i in 0..n {
            let s: *mut AnyObject = msg_send![screens, objectAtIndex: i];
            let ins: EdgeInsets = msg_send![s, safeAreaInsets];
            if ins.top <= 0.0 { continue; }
            let f: NSRect = msg_send![s, frame];
            let l: NSRect = msg_send![s, auxiliaryTopLeftArea];
            let r: NSRect = msg_send![s, auxiliaryTopRightArea];
            if let Some(g) = notch_from((f.origin.x, f.origin.y, f.size.width, f.size.height),
                                        pf.size.height, ins.top, l.size.width, r.size.width) {
                return Some(g);
            }
        }
        None
    }
}

/// 缓存过的几何；过期就重读（`GEOM_TTL`）。★ **只在主线程调**（NSScreen 是 AppKit 对象）：
/// 鼠标监听回调与同步命令都在主线程；后台线程一律用 `cached()`。
fn geometry() -> Option<Notch> {
    let mut g = GEOM.lock().unwrap();
    if let Some((v, at)) = *g {
        if at.elapsed() < GEOM_TTL { return v; }
    }
    let v = read_notch();
    *g = Some((v, Instant::now()));
    v
}

/// 后台线程用：只取缓存，从不碰 AppKit。
fn cached() -> Option<Notch> {
    GEOM.lock().unwrap().and_then(|(v, _)| v)
}

/// 这一轮展开的面板宽：空闲额度格子 = 网页报上来的宽（与托盘悬停面板同一个 `panelWidth`：满一行 435，
/// 藏了几家就收窄 —— 用户 2026-10-24「删掉一个之后多余的空白，刘海屏版没修」），4e 卡片 = `CARD_W`。
fn card_w() -> f64 {
    if OPEN_IDLE.load(Ordering::SeqCst) { *PANEL_W_IDLE.lock().unwrap() } else { CARD_W }
}

fn card_h() -> f64 {
    if OPEN_IDLE.load(Ordering::SeqCst) { *PANEL_H_IDLE.lock().unwrap() } else { *PANEL_H.lock().unwrap() }
}

/// 收起/展开时窗口在桌面坐标里的矩形。
/// 展开：宽 = 卡片 + 两侧阴影边 与 收起态光晕宽 取大（展开时光晕降到 60% 仍在）；
/// 高 = 刘海 + 10 pt 空隙 + 卡片 + 下方阴影边。水平居中在刘海上。
fn rect(g: &Notch, open: bool) -> (f64, f64, f64, f64) {
    rect_h(g, open, card_h())
}

fn rect_h(g: &Notch, open: bool, ch: f64) -> (f64, f64, f64, f64) {
    if open {
        let glow_w = g.width + (FLARE + GLOW_X) * 2.0;
        let w = (card_w() + CARD_SHADOW_X * 2.0).max(glow_w);
        let h = (g.height + CARD_GAP + ch + CARD_SHADOW_B).max(g.height + GLOW_Y);
        (g.left + g.width / 2.0 - w / 2.0, g.top, w, h)
    } else {
        let m = FLARE + GLOW_X;
        (g.left - m, g.top, g.width + m * 2.0, g.height + GLOW_Y)
    }
}

/// 卡片在桌面坐标里的矩形（不含命中边）。
fn card_rect(g: &Notch, ch: f64) -> (f64, f64, f64, f64) {
    let cw = card_w();
    (g.left + g.width / 2.0 - cw / 2.0, g.top + g.height + CARD_GAP, cw, ch)
}

/// 光标到刘海矩形的距离（在里面为 0）。
fn notch_distance(g: &Notch, x: f64, y: f64) -> f64 {
    let dx = (g.left - x).max(0.0).max(x - (g.left + g.width));
    let dy = (g.top - y).max(0.0).max(y - (g.top + g.height));
    (dx * dx + dy * dy).sqrt()
}

/// 光标是否在触发区内。
/// 收起：只认刘海本身 + 2 pt —— 两侧圆角与光晕那圈都是菜单栏，不算。
/// 展开：刘海 + 10 pt 空隙 + 卡片，四周各 +10 pt（空隙算卡片内，穿过不收起）。
fn hit(g: &Notch, open: bool, x: f64, y: f64) -> bool {
    hit_h(g, open, x, y, card_h())
}

fn hit_h(g: &Notch, open: bool, x: f64, y: f64, ch: f64) -> bool {
    if !open {
        return x >= g.left - TOUCH && x <= g.left + g.width + TOUCH
            && y >= g.top - TOUCH && y <= g.top + g.height + TOUCH;
    }
    let (cx, cy, cw, chh) = card_rect(g, ch);
    let left = cx.min(g.left) - CARD_HIT_PAD;
    let right = (cx + cw).max(g.left + g.width) + CARD_HIT_PAD;
    x >= left && x <= right && y >= g.top - TOUCH && y <= cy + chh + CARD_HIT_PAD
}

/// 「靠近」区：刘海左右各 60、向下 32（P11 画板虚线框）。
fn in_near(g: &Notch, x: f64, y: f64) -> bool {
    x >= g.left - NEAR_X && x <= g.left + g.width + NEAR_X && y >= g.top - TOUCH && y <= g.top + g.height + NEAR_B
}

/// 空闲时「停在刘海上」的那块：刘海本身（左右 +2）+ 下沿 5 pt（画板 270×56 ÷ 1.5）。
fn on_notch(g: &Notch, x: f64, y: f64) -> bool {
    x >= g.left - TOUCH && x <= g.left + g.width + TOUCH && y >= g.top - TOUCH && y <= g.top + g.height + IDLE_DWELL_B
}

/// 收起态这一帧要不要展开、展开哪一种（`Some(true)` = 空闲额度格子，`Some(false)` = 4e 卡片）。
/// `dwelled` = 光标连续停在 `on_notch` 里多久（调用方离开就清零）。
/// ★ 空闲但格子为空（`idle_cells == false`）⇒ 退回 4e 卡片、碰到即开 —— 不能让刘海在空闲时变成点不开的死块。
fn closed_step(running: bool, idle_cells: bool, touch: bool, dwelled: Option<Duration>) -> Option<bool> {
    if running || !idle_cells { return touch.then_some(false); }
    dwelled.filter(|d| *d >= IDLE_DWELL).map(|_| true)
}

/// 光标在靠近区里时，「靠近」光晕该不该亮。
/// ★ 只在碰下去会展开空闲格子时亮：有 AI 在跑 / 没有格子 ⇒ 开的是 4e 卡片，白光晕会说错话。
/// ★ 刚收起、光标还没离开靠近区（`blocked`）⇒ 不亮：画板「面板先淡出上移，再收光晕」。
fn near_lit(open: bool, blocked: bool, running: bool, idle_cells: bool) -> bool {
    !open && !blocked && !running && idle_cells
}

/// 光标在不在刘海那块屏的顶部采样带里（60 Hz 采样只在这里开）。
fn in_band(g: &Notch, x: f64, y: f64) -> bool {
    x >= g.screen_x && x < g.screen_x + g.screen_w && y >= g.top && y < g.top + SAMPLE_BAND
}

/// 把窗口摆到收起/展开的位置。★ **只在主线程调**：`set_size` 本身会派发，但派发前读缩放
/// （`NSWindow.backingScaleFactor`）发生在调用线程；后台线程一律经 `place_soon`。
fn place(app: &AppHandle, open: bool) {
    let (Some(win), Some(g)) = (app.get_webview_window(LABEL), cached()) else { return };
    let (x, y, w, h) = rect(&g, open);
    let _ = win.set_size(LogicalSize::new(w, h));
    let _ = win.set_position(LogicalPosition::new(x, y));
    pass_clicks(&win, !open);
}

fn place_soon(app: &AppHandle, open: bool) {
    let a = app.clone();
    let _ = app.run_on_main_thread(move || place(&a, open));
}

/// ★ 收起态**不接鼠标**（四方评审 2026-10-17）：收起窗口比刘海左右各宽 7pt、向下多 7pt，
///   盖着菜单栏两侧和下面应用的顶边，接鼠标就会吞掉那里的点击、还会把自己变成 key window。
///   悬停判定本来就不靠窗口收事件（靠 NSEvent 监听 + 光标位置），所以收起时整个穿透没有代价。
/// ★ 展开态也只在光标落进命中区（刘海 + 空隙 + 卡片 +10）时接鼠标：展开窗口为了装阴影与光晕比卡片宽一圈，
///   那一圈盖着菜单栏图标（交接包 4e「展开时 overlay 命中区 = 刘海 + 10 pt 空隙 + 卡片（四周各 +10 pt）」）。
fn pass_clicks(win: &tauri::WebviewWindow, through: bool) {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let Ok(ptr) = win.ns_window() else { return };
    if ptr.is_null() { return; }
    // SAFETY: 主线程；ptr 是本窗口仍存活的 NSWindow；只设一个 BOOL 属性。
    unsafe {
        let _: () = msg_send![ptr as *mut AnyObject, setIgnoresMouseEvents: through];
    }
}

fn pass_clicks_soon(app: &AppHandle, through: bool) {
    let a = app.clone();
    let gen = OPEN_GEN.load(Ordering::SeqCst);
    let _ = app.run_on_main_thread(move || {
        if OPEN_GEN.load(Ordering::SeqCst) != gen { return; }
        if let Some(w) = a.get_webview_window(LABEL) { pass_clicks(&w, through); }
    });
}

/// Tauri 不给窗口层级与 Spaces 行为的接口，直接设到 NSWindow 上。必须在主线程。
fn raise(win: &tauri::WebviewWindow) {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let Ok(ptr) = win.ns_window() else { return };
    if ptr.is_null() { return; }
    // SAFETY: ptr 是本窗口仍存活的 NSWindow；只设置标量属性。
    unsafe {
        let w = ptr as *mut AnyObject;
        // NSStatusWindowLevel(25) + 1：盖过菜单栏(24)与状态栏图标。
        let _: () = msg_send![w, setLevel: 26isize];
        // canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary
        // ★ 少了 fullScreenAuxiliary，切到全屏应用那一屏时它就不见了。
        let behavior: usize = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8);
        let _: () = msg_send![w, setCollectionBehavior: behavior];
        let _: () = msg_send![w, setHasShadow: false];
        let _: () = msg_send![w, setHidesOnDeactivate: false];
        let _: () = msg_send![w, setIgnoresMouseEvents: true];
        // ★ 不用 `win.show()`：tao 的 show 是 `makeKeyAndOrderFront`，`.focused(false)` 拦不住，
        //   刘海窗口一出现就抢走主窗口的键盘焦点（⌘1/2/3 失灵）。只排到最前、不当 key。
        let _: () = msg_send![w, orderFrontRegardless];
    }
}

/// 光标位置（桌面坐标：主屏左上为原点的逻辑 pt）。`+[NSEvent mouseLocation]` 给的是左下原点，翻一下。
/// ★ 唤醒（主线程）与跟踪（后台线程）**必须用同一套算法** —— 原来跟踪线程用
///   `cursor_position() / 刘海窗口的 scale`，而 tao 是按**主屏** scale 换的物理坐标：
///   主屏是 1× 外接屏、刘海在 2× 内建屏时坐标被减半，唤醒判进、跟踪判出，面板永远打不开。
///   `mouseLocation` 是只读类方法、tao 自己也在任意线程调它；后台线程不再碰 NSWindow / NSScreen。
fn mouse_desktop(g: &Notch) -> (f64, f64) {
    use objc2::{class, msg_send};
    // SAFETY: 类方法，无参数，返回值是值类型。
    let p: objc2_foundation::NSPoint = unsafe { msg_send![class!(NSEvent), mouseLocation] };
    (p.x, g.primary_h - p.y)
}

/// 展开成哪一种：先发 `notch-mode`，再展开（同一线程按序到网页，网页收到 `notch-open` 时已知道画哪种）。
fn open_as(app: &AppHandle, idle: bool) {
    if OPEN.load(Ordering::SeqCst) { return; }
    OPEN_IDLE.store(idle, Ordering::SeqCst);
    let _ = app.emit_to(LABEL, "notch-mode", if idle { "idle" } else { "run" });
    set_open(app, true);
}

/// 点了空闲格子：收起（网页同时发了 `open-main-page`）。
pub fn dismiss(app: &AppHandle) { set_open(app, false); }

fn set_open(app: &AppHandle, open: bool) {
    if OPEN.swap(open, Ordering::SeqCst) == open { return; }
    let gen = OPEN_GEN.fetch_add(1, Ordering::SeqCst) + 1;
    if open {
        place_soon(app, true);
        let _ = app.emit_to(LABEL, "notch-open", true);
    } else {
        let _ = app.emit_to(LABEL, "notch-open", false);
        pass_clicks_soon(app, true);
        let app = app.clone();
        std::thread::spawn(move || {
            std::thread::sleep(COLLAPSE);
            // ★ 只收**这一轮**：中途又展开过一次再移出，旧计时醒来不许裁掉新一轮的动画。
            if OPEN_GEN.load(Ordering::SeqCst) == gen && !OPEN.load(Ordering::SeqCst) {
                place_soon(&app, false);
            }
        });
    }
}

/// 光标 → 刘海窗口内坐标（收起态窗口原点）。网页画果冻下垂用。
fn cursor_payload(g: &Notch, open: bool, x: f64, y: f64) -> Cursor {
    let (wx, wy, _, _) = rect(g, open);
    Cursor { x: x - wx, y: y - wy, dx: x - (g.left + g.width / 2.0), distance: notch_distance(g, x, y) }
}

/// 跟踪线程：光标进了刘海屏顶部那一带之后才存在，离开那一带并收完就退出。60 Hz。
fn track(app: AppHandle) {
    let me = TRACKER_SEQ.fetch_add(1, Ordering::SeqCst) + 1;
    if TRACKER.compare_exchange(0, me, Ordering::SeqCst, Ordering::SeqCst).is_err() { return; }
    let gen = ENABLE_GEN.load(Ordering::SeqCst);
    std::thread::spawn(move || {
        let mut since_out: Option<Instant> = None;
        let mut last_cursor: Option<(f64, f64)> = None;
        let mut emitting = false;
        let mut accepting = false;
        // 空闲「靠近」光晕：变了才推；线程退出时补一帧 false（否则光晕常亮）
        let mut near_sent = false;
        let mut dwell_from: Option<Instant> = None;
        // ★ 收起之后，光标没离开靠近区之前不再亮「靠近」：画板「面板先淡出上移，再收光晕」——
        //   不挡的话点完格子（格子上沿在靠近区里）光晕会从 55% 反跳到 100%（三方评审 2026-10-21）
        let mut was_open = false;
        let mut near_block = false;
        loop {
            std::thread::sleep(TRACK_TICK);
            if ENABLE_GEN.load(Ordering::SeqCst) != gen || !ENABLED.load(Ordering::SeqCst) { break; }
            let Some(g) = cached() else { break };
            let (x, y) = mouse_desktop(&g);
            let open = OPEN.load(Ordering::SeqCst);

            // 果冻下垂：只在收起态、光标在刘海附近时推；离开范围时补一帧让网页收回那滴黑
            let d = notch_distance(&g, x, y);
            let near = !open && d <= CURSOR_EMIT_RANGE;
            if (near || emitting) && last_cursor != Some((x, y)) {
                let _ = app.emit_to(LABEL, "notch-cursor", cursor_payload(&g, open, x, y));
                last_cursor = Some((x, y));
            }
            emitting = near;

            if was_open && !open {
                near_block = true;
                accepting = false;
                since_out = None;
            }
            was_open = open;
            let zone = in_near(&g, x, y);
            if !zone { near_block = false; }
            let near_now = zone && near_lit(open, near_block, crate::activity::activity().any(), crate::tps_hover::idle_has_cells());
            if near_now != near_sent {
                let _ = app.emit_to(LABEL, "notch-near", near_now);
                NEAR.store(near_now, Ordering::SeqCst);
                near_sent = near_now;
            }

            if !open {
                let on = on_notch(&g, x, y);
                if on { dwell_from.get_or_insert_with(Instant::now); } else { dwell_from = None; }
                // 不在停留区时 `touch` 必为假（碰触区是停留区的子集）、`dwell` 为空 ⇒ 不用读活动
                let step = if !on { None } else {
                    closed_step(crate::activity::activity().any(), crate::tps_hover::idle_has_cells(),
                                hit(&g, false, x, y), dwell_from.map(|t| t.elapsed()))
                };
                if let Some(idle) = step {
                    open_as(&app, idle);
                    accepting = true;
                    since_out = None;
                    dwell_from = None;
                    continue;
                }
                if !in_band(&g, x, y) { break; }
                continue;
            }
            let inside = hit(&g, true, x, y);
            if inside != accepting {
                accepting = inside;
                pass_clicks_soon(&app, !inside);
            }
            if inside {
                since_out = None;
            } else {
                let t = *since_out.get_or_insert_with(Instant::now);
                if t.elapsed() >= CLOSE_DWELL {
                    set_open(&app, false);
                    accepting = false;
                    since_out = None;
                }
            }
        }
        if near_sent { let _ = app.emit_to(LABEL, "notch-near", false); }
        NEAR.store(false, Ordering::SeqCst);
        let _ = TRACKER.compare_exchange(me, 0, Ordering::SeqCst, Ordering::SeqCst);
    });
}

/// 建窗口（主线程）。已经有了就只摆位置。
fn ensure_window(app: &AppHandle, g: &Notch) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(LABEL) {
        raise(&w);
        place(app, OPEN.load(Ordering::SeqCst));
        crate::activity::subscribe(app, crate::activity::NOTCH);
        return Ok(());
    }
    let (x, y, w, h) = rect(g, false);
    let win = tauri::webview::WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("notch.html".into()))
        .title("AICoop Notch")
        .decorations(false)
        .transparent(true)
        .resizable(false)
        .skip_taskbar(true)
        .shadow(false)
        .focused(false)
        // ★ CodexBar 几乎从不在前台：不接首次点击的话，点面板只会激活窗口，「点这里打开」要点两下。
        .accept_first_mouse(true)
        .visible(false)
        .inner_size(w, h)
        .position(x, y)
        .build()
        .map_err(|e| e.to_string())?;
    raise(&win);
    crate::activity::subscribe(app, crate::activity::NOTCH);
    Ok(())
}

fn drop_window(app: &AppHandle) {
    OPEN.store(false, Ordering::SeqCst);
    OPEN_IDLE.store(false, Ordering::SeqCst);
    NEAR.store(false, Ordering::SeqCst);
    crate::activity::unsubscribe(crate::activity::NOTCH);
    if let Some(w) = app.get_webview_window(LABEL) { let _ = w.destroy(); }
}

/// 刘海屏出现/消失/挪位置时让窗口跟上（主线程）。
/// ★ 原来 `geometry()` 读成 `None` 就直接 return：合盖后层级 26 的窗口留在原地、被系统挪到外接屏菜单栏正中
///   （一块黑块）；合盖时打开开关，开盖后也永远不出现（四方评审 2026-10-17）。
fn reconcile(app: &AppHandle) {
    let before = cached();
    let now = geometry();
    match now {
        None => if app.get_webview_window(LABEL).is_some() { drop_window(app); },
        Some(g) => {
            if app.get_webview_window(LABEL).is_none() {
                let _ = ensure_window(app, &g);
            } else if before != Some(g) {
                place(app, OPEN.load(Ordering::SeqCst));
                let _ = app.emit_to(LABEL, "notch-geom", g);
            }
        }
    }
}

/// 鼠标事件监听的回调（主线程）。先对齐几何，再看光标进没进刘海屏顶部那一带，进了就叫醒跟踪线程。
fn on_mouse(app: &AppHandle) {
    if !ENABLED.load(Ordering::Relaxed) || TRACKER.load(Ordering::Relaxed) != 0 { return; }
    reconcile(app);
    let Some(g) = cached() else { return };
    let (x, y) = mouse_desktop(&g);
    if in_band(&g, x, y) { track(app.clone()); }
}

fn install_monitors(app: &AppHandle) {
    use block2::RcBlock;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use std::ptr::NonNull;
    let mut mons = MONITORS.lock().unwrap();
    if !mons.is_empty() { return; }
    // NSEventMaskMouseMoved | LeftMouseDragged | RightMouseDragged
    let mask: u64 = (1 << 5) | (1 << 6) | (1 << 7);
    let a1 = app.clone();
    let global = RcBlock::new(move |_e: NonNull<AnyObject>| on_mouse(&a1));
    let a2 = app.clone();
    let local = RcBlock::new(move |e: NonNull<AnyObject>| -> *mut AnyObject { on_mouse(&a2); e.as_ptr() });
    // SAFETY: AppKit 会 copy 这两个 block；返回的监听器对象由我们持有，`remove_monitors` 里释放。
    unsafe {
        let g: Option<Retained<AnyObject>> =
            msg_send![class!(NSEvent), addGlobalMonitorForEventsMatchingMask: mask, handler: &*global];
        let l: Option<Retained<AnyObject>> =
            msg_send![class!(NSEvent), addLocalMonitorForEventsMatchingMask: mask, handler: &*local];
        for m in [g, l].into_iter().flatten() {
            mons.push(Retained::into_raw(m) as usize);
        }
    }
    // ★ 插拔显示器 / 合盖开盖：系统发 `NSApplicationDidChangeScreenParametersNotification`，立刻对齐一次
    //   （全方面评审 §9 存疑：原来只靠下一次鼠标移动里的 `reconcile`，不动鼠标时光晕留在旧位置）。
    let a3 = app.clone();
    // 几何有 `GEOM_TTL` 缓存 ⇒ 先作废再对齐，否则这一下读到的还是旧屏
    let screens = RcBlock::new(move |_n: NonNull<AnyObject>| { *GEOM.lock().unwrap() = None; reconcile(&a3); });
    // SAFETY: 主线程；通知中心 copy 这个 block，返回的观察者对象由我们持有，`remove_monitors` 里注销并释放。
    unsafe {
        let center: *mut AnyObject = msg_send![class!(NSNotificationCenter), defaultCenter];
        let queue: *mut AnyObject = msg_send![class!(NSOperationQueue), mainQueue];
        let name = objc2_foundation::NSString::from_str("NSApplicationDidChangeScreenParametersNotification");
        let obs: Option<Retained<AnyObject>> = msg_send![center, addObserverForName: &*name, object: std::ptr::null_mut::<AnyObject>(),
                                                         queue: queue, usingBlock: &*screens];
        if let Some(o) = obs { *SCREEN_OBS.lock().unwrap() = Some(Retained::into_raw(o) as usize); }
    }
}

/// 屏幕参数变更的通知观察者（`install_monitors` 装、`remove_monitors` 拆）。
static SCREEN_OBS: Mutex<Option<usize>> = Mutex::new(None);

fn remove_monitors() {
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    if let Some(p) = SCREEN_OBS.lock().unwrap().take() {
        // SAFETY: 指针来自 `install_monitors` 的 `Retained::into_raw`，只释放这一次。
        unsafe {
            if let Some(obj) = Retained::from_raw(p as *mut AnyObject) {
                let center: *mut AnyObject = msg_send![class!(NSNotificationCenter), defaultCenter];
                let _: () = msg_send![center, removeObserver: &*obj];
            }
        }
    }
    let mut mons = MONITORS.lock().unwrap();
    for p in mons.drain(..) {
        // SAFETY: 指针来自 `install_monitors` 的 `Retained::into_raw`，只释放这一次。
        unsafe {
            let obj = Retained::from_raw(p as *mut AnyObject);
            if let Some(obj) = obj {
                let _: () = msg_send![class!(NSEvent), removeMonitor: &*obj];
            }
        }
    }
}

/// 开/关。开 = 装监听 +（有刘海屏时）建窗口；关 = 拆监听 + **销毁窗口**（不只是隐藏 —— 隐藏的
/// WKWebView 仍占着两个系统进程，默认关的功能不该常驻任何东西）。
/// ★ 监听**无论有没有刘海屏都装**：合盖时打开、之后开盖，下一次鼠标移动就由 `reconcile` 把窗口建出来。
/// ★ 调用方是**同步**命令（Tauri 2 的同步命令在主线程跑），这里要读 NSScreen、直接操作 NSWindow。
pub fn set_enabled(app: &AppHandle, on: bool) -> Result<Status, String> {
    ENABLE_GEN.fetch_add(1, Ordering::SeqCst);
    ENABLED.store(on, Ordering::SeqCst);
    if !on {
        remove_monitors();
        drop_window(app);
        return Ok(Status { active: false, reason: None });
    }
    install_monitors(app);
    *GEOM.lock().unwrap() = None;
    let Some(g) = geometry() else {
        return Ok(Status { active: false, reason: Some("no_notch") });
    };
    ensure_window(app, &g)?;
    Ok(Status { active: true, reason: None })
}

/// 设置页打开时问一句「现在有没有刘海屏」，不改任何状态（主线程）。
pub fn status() -> Status {
    let enabled = ENABLED.load(Ordering::SeqCst);
    match geometry() {
        Some(_) => Status { active: enabled, reason: None },
        None => Status { active: false, reason: Some("no_notch") },
    }
}

pub fn activity() -> crate::activity::Activity { crate::activity::activity() }

pub fn notch_geometry() -> Option<Notch> { cached() }

pub fn is_open() -> bool { OPEN.load(Ordering::SeqCst) }

pub fn open_idle() -> bool { OPEN_IDLE.load(Ordering::SeqCst) }

pub fn is_near() -> bool { NEAR.load(Ordering::SeqCst) }

/// 展开态的版面（**刘海窗口内**坐标，逻辑 pt）：刘海在哪、卡片在哪。网页画光桥 / 卡片 / logo 来向用。
pub fn open_layout() -> Option<serde_json::Value> {
    let g = cached()?;
    let ch = card_h();
    let (wx, wy, ww, wh) = rect_h(&g, true, ch);
    let (cx, cy, cw, chh) = card_rect(&g, ch);
    Some(serde_json::json!({
        "window": { "w": ww, "h": wh },
        "notch": { "x": g.left - wx, "y": g.top - wy, "w": g.width, "h": g.height },
        "card": { "x": cx - wx, "y": cy - wy, "w": cw, "h": chh },
    }))
}

/// 空闲面板的最小高：一行「已隐藏 · 撤销」（`notchIdle.ts::notchGrid(0, 1).h` = 34）略小一点。
const IDLE_H_MIN: f64 = 32.0;

/// 前端量出面板的自然高度后告诉这里。`idle` = 空闲格子那份，否则 4e 卡片（随 Tab / 会话展开 / 告警行变）。
/// 只有这一轮展开正是这一种时才重摆窗口。
pub fn set_panel_height(app: &AppHandle, h: f64, idle: bool, w: Option<f64>) {
    if idle {
        if let Some(w) = w.filter(|w| w.is_finite()) {
            *PANEL_W_IDLE.lock().unwrap() = w.clamp(100.0, crate::tps_hover::IDLE_PANEL_W);
        }
    }
    let slot = if idle { &PANEL_H_IDLE } else { &PANEL_H };
    // ★ 空闲那份全藏了只剩「已隐藏 · 撤销」行时只有 34 pt；下限仍按 4e 卡的 80 会在下面留一块透明吃点击区（阶段 D 评审 gemini）
    *slot.lock().unwrap() = h.clamp(if idle { IDLE_H_MIN } else { 80.0 }, CARD_H_MAX);
    if OPEN.load(Ordering::SeqCst) && OPEN_IDLE.load(Ordering::SeqCst) == idle { place_soon(app, true); }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn air13() -> Notch {
        Notch { left: 646.0, width: 179.0, height: 32.0, top: 0.0, primary_h: 956.0, screen_x: 0.0, screen_w: 1470.0 }
    }

    #[test]
    fn collapsed_window_covers_notch_flares_and_glow_room() {
        assert_eq!(rect(&air13(), false), (579.0, 0.0, 313.0, 92.0));
    }
    #[test]
    fn the_glow_room_does_not_trigger() {
        let g = air13();
        assert!(!hit(&g, false, 620.0, 10.0), "光晕那圈是菜单栏");
        assert!(!hit(&g, false, 735.0, 40.0), "光晕下沿不算");
        assert!(hit(&g, false, 735.0, 30.0), "刘海本身算");
    }
    #[test]
    fn open_panel_is_centred_on_the_notch() {
        let (x, _, w, _) = rect(&air13(), true);
        assert!(((x + w / 2.0) - (646.0 + 179.0 / 2.0)).abs() < 1e-9);
    }
    #[test]
    fn the_menubar_beside_the_notch_does_not_trigger() {
        let g = air13();
        assert!(hit(&g, false, 735.0, 10.0));
        assert!(!hit(&g, false, 641.0, 10.0), "左侧内凹圆角那 7pt 是菜单栏");
        assert!(!hit(&g, false, 735.0, 60.0));
    }
    #[test]
    fn touching_the_notch_plus_two_points_opens() {
        let g = air13();
        assert!(hit(&g, false, 644.0, 10.0), "刘海左沿外 2 pt 算碰到");
        assert!(!hit(&g, false, 643.5, 10.0));
        assert!(hit(&g, false, 735.0, 34.0), "刘海下沿外 2 pt 算碰到");
        assert!(!hit(&g, false, 735.0, 34.5));
    }
    #[test]
    fn open_window_fits_the_tallest_card_with_its_shadow() {
        let g = air13();
        let (_, y, w, h) = rect_h(&g, true, 560.0);
        assert_eq!(y, 0.0);
        assert!(w >= CARD_W + 2.0 * 40.0, "卡片阴影 blur 40 要装得下");
        assert_eq!(h, 32.0 + 10.0 + 560.0 + 58.0);
        assert!(h <= 956.0 - 200.0, "最高的卡片也要放进 Air 的屏幕");
        let (cx, cy, cw, _) = card_rect(&g, 560.0);
        assert_eq!((cx, cy, cw), (735.5 - 150.0, 42.0, 300.0), "卡片在刘海下沿下方 10 pt、居中");
    }
    #[test]
    fn open_hit_area_is_notch_gap_and_card_plus_ten() {
        let g = air13();
        let ch = 400.0;
        assert!(hit_h(&g, true, 735.0, 37.0, ch), "刘海与卡片之间的 10 pt 空隙算面板内，穿过不收起");
        assert!(hit_h(&g, true, 585.5 - 10.0, 200.0, ch), "卡片左沿外 10 pt 仍在");
        assert!(!hit_h(&g, true, 585.5 - 10.5, 200.0, ch));
        assert!(hit_h(&g, true, 735.0, 42.0 + 400.0 + 10.0, ch), "卡片下沿外 10 pt 仍在");
        assert!(!hit_h(&g, true, 735.0, 42.0 + 400.0 + 10.5, ch));
        let (wx, _, _, _) = rect_h(&g, true, ch);
        assert!(!hit_h(&g, true, wx + 5.0, 100.0, ch), "阴影那圈透明边不接鼠标");
    }
    #[test]
    fn cursor_sampling_is_limited_to_the_top_band_of_the_notch_screen() {
        let g = air13();
        assert!(in_band(&g, 100.0, 179.0));
        assert!(!in_band(&g, 100.0, 180.0), "y ≥ 180 pt 不采样");
        assert!(!in_band(&g, 1500.0, 10.0), "别的屏不采样");
    }
    #[test]
    fn distance_to_the_notch_is_zero_inside_and_euclidean_outside() {
        let g = air13();
        assert_eq!(notch_distance(&g, 700.0, 10.0), 0.0);
        assert_eq!(notch_distance(&g, 700.0, 56.0), 24.0, "下沿正下方 24 pt");
        assert!((notch_distance(&g, 646.0 - 3.0, 32.0 + 4.0) - 5.0).abs() < 1e-9);
        let c = cursor_payload(&g, false, 735.5, 50.0);
        assert_eq!((c.x, c.y, c.dx, c.distance), (735.5 - 579.0, 50.0, 0.0, 18.0));
    }
    #[test]
    fn the_near_zone_is_sixty_each_side_and_thirty_two_below() {
        let g = air13();
        assert!(in_near(&g, 646.0 - 60.0, 10.0) && !in_near(&g, 646.0 - 60.5, 10.0));
        assert!(in_near(&g, 825.0 + 60.0, 10.0) && !in_near(&g, 825.0 + 60.5, 10.0));
        assert!(in_near(&g, 735.0, 64.0) && !in_near(&g, 735.0, 64.5), "刘海下沿往下 32 pt");
    }
    #[test]
    fn idle_dwell_area_is_the_notch_plus_five_below() {
        let g = air13();
        assert!(on_notch(&g, 735.0, 37.0) && !on_notch(&g, 735.0, 37.5));
        assert!(on_notch(&g, 644.0, 10.0) && !on_notch(&g, 643.5, 10.0));
        assert!(!on_notch(&g, 620.0, 10.0), "靠近区里、刘海外 ⇒ 只亮光晕，不展开");
    }
    #[test]
    fn idle_opens_the_grid_only_after_180ms_on_the_notch() {
        let ms = |n| Some(Duration::from_millis(n));
        assert_eq!(closed_step(false, true, true, None), None, "空闲：碰到不立即展开");
        assert_eq!(closed_step(false, true, true, ms(179)), None);
        assert_eq!(closed_step(false, true, true, ms(180)), Some(true));
        assert_eq!(closed_step(false, true, false, ms(200)), Some(true), "刘海下沿 5 pt 里停够也算（不在 +2 的碰触区）");
    }
    #[test]
    fn running_keeps_the_instant_card_and_no_cells_falls_back_to_it() {
        assert_eq!(closed_step(true, true, true, None), Some(false), "在跑：碰到即展开 4e 卡片");
        assert_eq!(closed_step(true, true, false, Some(Duration::from_secs(1))), None);
        assert_eq!(closed_step(false, false, true, None), Some(false), "空闲但没有格子 ⇒ 4e 卡片，不是死块");
        assert_eq!(closed_step(false, false, false, Some(Duration::from_secs(1))), None);
    }
    #[test]
    fn each_kind_of_opening_uses_its_own_height() {
        // ★ 换种类那一下 Rust 已有对的高度（不等网页收到 `notch-mode` 再报）
        *PANEL_H.lock().unwrap() = 400.0;
        *PANEL_H_IDLE.lock().unwrap() = 86.5;
        OPEN_IDLE.store(true, Ordering::SeqCst);
        assert_eq!(card_h(), 86.5);
        *PANEL_W_IDLE.lock().unwrap() = 222.0;
        assert_eq!(card_w(), 222.0, "★ 空闲格子按网页报的宽（藏了几家就收窄），不是写死 435");
        *PANEL_W_IDLE.lock().unwrap() = crate::tps_hover::IDLE_PANEL_W;
        OPEN_IDLE.store(false, Ordering::SeqCst);
        assert_eq!(card_h(), 400.0);
        assert_eq!(card_w(), CARD_W);
    }
    #[test]
    fn the_near_glow_only_promises_what_a_touch_would_open() {
        assert!(near_lit(false, false, false, true));
        assert!(!near_lit(true, false, false, true), "展开着：光晕归展开态管");
        assert!(!near_lit(false, true, false, true), "刚收起、还没离开靠近区 ⇒ 不反跳");
        assert!(!near_lit(false, false, true, true), "有 AI 在跑 ⇒ 碰到开 4e，不亮白光晕");
        assert!(!near_lit(false, false, false, false), "没有格子 ⇒ 碰到开 4e，不亮白光晕");
    }
    #[test]
    fn notch_screen_as_primary_matches_the_measured_air() {
        // 13 寸 Air：屏 1470×956，左右 auxiliary 各 646 / 645 宽，safeArea.top 32
        let g = notch_from((0.0, 0.0, 1470.0, 956.0), 956.0, 32.0, 646.0, 645.0).unwrap();
        assert_eq!((g.left, g.width, g.height, g.top), (646.0, 179.0, 32.0, 0.0));
    }
    #[test]
    fn notch_screen_that_is_not_primary_is_offset_by_its_frame() {
        // 主屏 1920×1080 外接屏；内建刘海屏摆在它右边、底边对齐（AppKit 左下原点）
        let g = notch_from((1920.0, 0.0, 1470.0, 956.0), 1080.0, 32.0, 646.0, 645.0).unwrap();
        assert_eq!(g.left, 1920.0 + 646.0, "刘海 x 必须带上那块屏自己的 origin");
        assert_eq!(g.top, 1080.0 - 956.0, "那块屏顶边在桌面坐标里比主屏低 124pt");
        assert_eq!((g.screen_x, g.screen_w), (1920.0, 1470.0));
    }
    #[test]
    fn a_screen_without_a_notch_has_none() {
        assert_eq!(notch_from((0.0, 0.0, 1920.0, 1080.0), 1080.0, 0.0, 0.0, 0.0), None);
        assert_eq!(notch_from((0.0, 0.0, 1470.0, 956.0), 956.0, 32.0, 800.0, 800.0), None);
    }
}
