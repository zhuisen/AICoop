//! 托盘胶囊的悬停面板 `tpshover`（交接包 2026-10-19 page 2，macOS 专属）。
//!
//! 鼠标停在胶囊上 200 ms 弹出（**只在有 AI 在跑时**；空闲不弹，点击照旧打开菜单栏弹窗）；
//! 离开胶囊**和**面板 300 ms 后关闭；点击胶囊 ⇒ 收起面板、走原有菜单栏弹窗。
//!
//! ★ 进出判定**不靠网页 mouseleave**（同刘海那条理由：Accessory 应用几乎从不在前台，后台 WKWebView
//!   收不收得到鼠标移动没验过）：托盘 `Enter` 叫醒一条 30 Hz 的光标轮询线程，判定全在线程里，关掉就退出。
//! ★ 窗口顶部覆盖到菜单栏胶囊（logo 从胶囊飞进面板），透明的那部分不接鼠标：只有光标落在面板矩形里时
//!   窗口才接鼠标（`setIgnoresMouseEvents` 随光标切换）。
//! ★ 出现用 `orderFrontRegardless`，不用 `show()`（tao 的 show 是 makeKeyAndOrderFront，会抢主窗口焦点）。
//! 网页拿到的事件：`tpshover-open`（payload = `layout()`：面板 / 胶囊 / 各段 logo 在窗口内的坐标）、
//! `tpshover-close`（payload = 原因 `"leave" | "click" | "idle"`）。高度由网页 `tpshover_resize(h)` 报上来。
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager};

pub const LABEL: &str = "tpshover";
/// 面板宽 300（比菜单栏弹窗 352 窄）。
pub const PANEL_W: f64 = 300.0;
/// 空闲额度面板（P11 §6 格子）：画板 2× 下宽 580；用户 2026-10-21 选 1.5× ⇒ 435。与 `idleGridLayout.ts::PANEL_W` 同值。
/// ★ 用户 2026-10-21「改为居中弹窗」（选「托盘正下方居中」，随后「运行中的悬浮弹窗也要改」）：
///   两种面板都是中线 = 状态栏按钮中线，取代原型的「右沿比胶囊右沿多出 8 / 15」。贴屏幕边时往里收。
pub const IDLE_PANEL_W: f64 = 435.0;
/// 悬停多久打开。★ 用户 2026-10-21「运行中和空闲的悬浮弹窗响应要加快」：稿里的 150 / 200 ms 都降到 80 ms
///   （仍留一点停留，光标横扫菜单栏时不乱弹）。
const IDLE_OPEN_DWELL: Duration = Duration::from_millis(80);
/// 面板外的透明边：阴影 `0 16 40 rgba(0,0,0,.45)` 要往外 ~40、往下再多 16。
const PAD_X: f64 = 40.0;
const PAD_B: f64 = 56.0;
/// 面板顶到菜单栏下沿的距离（原型：胶囊容器 22 高、面板从 28 起 ⇒ 下方 6）。
const GAP: f64 = 6.0;
const OPEN_DWELL: Duration = Duration::from_millis(80);
const CLOSE_DWELL: Duration = Duration::from_millis(300);
/// 关闭动画：数据 100 ms 淡出 → logo 飞回胶囊 → 外壳延后 120 ms 淡出。动画走完再真隐藏。
const CLOSE_ANIM: Duration = Duration::from_millis(520);
const CLICK_ANIM: Duration = Duration::from_millis(160);
/// 轮询粒度（只在光标停在托盘 / 面板上时跑）：33 → 16 ms，停留判定的误差跟着减半。
const TICK: Duration = Duration::from_millis(16);
const GEOM_REFRESH: Duration = Duration::from_millis(250);

const IDLE: u8 = 0;
const DWELL: u8 = 1;
const OPEN: u8 = 2;

static PHASE: AtomicU8 = AtomicU8::new(IDLE);
static POLLER: AtomicBool = AtomicBool::new(false);
/// 点过胶囊之后，直到光标离开胶囊都不再弹（点击 = 菜单栏弹窗，此后不跟随鼠标）。
static SUPPRESS: AtomicBool = AtomicBool::new(false);
/// 每次打开 / 关闭 +1；延迟隐藏核对自己那一代（中途又打开了就不许把它藏掉）。
static GEN: AtomicU64 = AtomicU64::new(0);
static PANEL_H: Mutex<f64> = Mutex::new(240.0);
static GEOM: Mutex<Option<Tray>> = Mutex::new(None);
/// 这一次打开的是哪种面板：空闲额度格子（true）还是在跑速度面板（false）。在 `on_enter` 定下，关闭前不变。
static IDLE_PANEL: AtomicBool = AtomicBool::new(false);

/// 状态栏按钮在桌面坐标（主屏左上原点，逻辑 pt）里的位置，以及它所在屏。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tray { pub x: f64, pub y: f64, pub w: f64, pub h: f64, pub screen_x: f64, pub screen_w: f64, pub primary_h: f64 }

/// 窗口矩形（桌面坐标）与面板在窗口内的位置。纯函数，单测覆盖贴屏幕右缘时的钳位。
#[cfg(test)]
pub fn window_rect(t: &Tray, panel_h: f64) -> ((f64, f64, f64, f64), (f64, f64)) {
    window_rect_for(t, PANEL_W, panel_h)
}

/// 面板在状态栏按钮正下方居中（胶囊在按钮里居中，所以也是胶囊中线），贴屏幕边时往里收。
fn window_rect_for(t: &Tray, panel_w: f64, panel_h: f64) -> ((f64, f64, f64, f64), (f64, f64)) {
    let panel_x = (t.x + t.w / 2.0 - panel_w / 2.0)
        .min(t.screen_x + t.screen_w - panel_w - 4.0)
        .max(t.screen_x + 4.0);
    let wx = panel_x - PAD_X;
    let w = panel_w + PAD_X * 2.0;
    let h = t.h + GAP + panel_h + PAD_B;
    ((wx, t.y, w, h), (PAD_X, t.h + GAP))
}

fn contains(r: (f64, f64, f64, f64), x: f64, y: f64) -> bool {
    x >= r.0 && x <= r.0 + r.2 && y >= r.1 && y <= r.1 + r.3
}

/// 当前这种面板的宽、胶囊各段（胶囊内坐标）。
/// 空闲面板在「文字标题」模式下也会弹（P9 S1：选文字标题时悬停面板那组设置仍在）：托盘里没有 logo 可飞，
/// 「胶囊」= 整个状态栏按钮（宽 = 按钮宽 ⇒ 面板右沿对齐按钮右沿 + 10），格子里的 logo 原位淡入。
fn pill_and_panel(t: &Tray) -> (serde_json::Value, f64) {
    if IDLE_PANEL.load(Ordering::SeqCst) {
        let pill = if crate::tray_pill::idle_icons_shown() { crate::tray_pill::idle_rects() }
                   else { serde_json::json!({ "width": t.w, "height": t.h, "segments": [] }) };
        (pill, IDLE_PANEL_W)
    } else {
        (crate::tray_pill::segment_rects(), PANEL_W)
    }
}

fn rect_now(t: &Tray) -> ((f64, f64, f64, f64), (f64, f64), f64) {
    let (_, pw) = pill_and_panel(t);
    let (r, p) = window_rect_for(t, pw, *PANEL_H.lock().unwrap());
    (r, p, pw)
}

/// 给网页的版面（窗口内坐标）。`mode` = `"idle"`（空闲额度格子）/ `"run"`（在跑速度面板）。
pub fn layout() -> Option<serde_json::Value> {
    let t = (*GEOM.lock().unwrap())?;
    let (pill, pw) = pill_and_panel(&t);
    let pill_w = pill["width"].as_f64().unwrap_or(0.0);
    let ph = *PANEL_H.lock().unwrap();
    let ((wx, wy, ww, wh), (px, py)) = window_rect_for(&t, pw, ph);
    let pill_x = t.x + (t.w - pill_w) / 2.0 - wx;
    let pill_y = t.y + (t.h - crate::tray_pill::H) / 2.0 - wy;
    let segs: Vec<serde_json::Value> = pill["segments"].as_array().cloned().unwrap_or_default().into_iter().map(|mut s| {
        if let Some(x) = s["x"].as_f64() { s["x"] = (x + pill_x).into(); }
        if let Some(x) = s["logo"]["x"].as_f64() { s["logo"]["x"] = (x + pill_x).into(); }
        if let Some(y) = s["logo"]["y"].as_f64() { s["logo"]["y"] = (y + pill_y).into(); }
        s
    }).collect();
    Some(serde_json::json!({
        "mode": if IDLE_PANEL.load(Ordering::SeqCst) { "idle" } else { "run" },
        "window": { "w": ww, "h": wh },
        "menubar_h": t.h,
        "panel": { "x": px, "y": py, "w": pw, "h": ph },
        "pill": { "x": pill_x, "y": pill_y, "w": pill_w, "h": crate::tray_pill::H },
        "segments": segs,
    }))
}

/// 状态栏按钮（本进程的 NSStatusBarWindow 里那一个）在桌面坐标里的位置。主线程。
fn read_tray() -> Option<Tray> {
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use objc2_app_kit::NSApplication;
    use objc2_foundation::NSRect;
    let mtm = objc2_foundation::MainThreadMarker::new()?;
    let app = NSApplication::sharedApplication(mtm);
    // SAFETY: 主线程；只读窗口 / 屏幕的几何属性。
    unsafe {
        let screens: *mut AnyObject = msg_send![class!(NSScreen), screens];
        if screens.is_null() { return None; }
        let n: usize = msg_send![screens, count];
        if n == 0 { return None; }
        let primary: *mut AnyObject = msg_send![screens, objectAtIndex: 0usize];
        let pf: NSRect = msg_send![primary, frame];
        for w in app.windows().iter() {
            let cls = w.class().name().to_string_lossy().to_string();
            if !cls.contains("StatusBar") { continue; }
            let f = w.frame();
            let sp: *mut AnyObject = msg_send![&*w, screen];
            let sf: NSRect = if sp.is_null() { pf } else { msg_send![sp, frame] };
            return Some(Tray {
                x: f.origin.x, y: pf.size.height - (f.origin.y + f.size.height), w: f.size.width, h: f.size.height,
                screen_x: sf.origin.x, screen_w: sf.size.width, primary_h: pf.size.height,
            });
        }
    }
    None
}

fn refresh_geom_soon(app: &AppHandle) {
    let _ = app.run_on_main_thread(|| {
        if let Some(t) = read_tray() { *GEOM.lock().unwrap() = Some(t); }
    });
}

fn cursor(primary_h: f64) -> (f64, f64) {
    use objc2::{class, msg_send};
    // SAFETY: 类方法，无参数，返回值是值类型（tao 自己也在任意线程调它）。
    let p: objc2_foundation::NSPoint = unsafe { msg_send![class!(NSEvent), mouseLocation] };
    (p.x, primary_h - p.y)
}

fn ns_window(app: &AppHandle) -> Option<*mut objc2::runtime::AnyObject> {
    let w = app.get_webview_window(LABEL)?;
    let p = w.ns_window().ok()?;
    (!p.is_null()).then_some(p as *mut objc2::runtime::AnyObject)
}

/// 建窗后设一次层级与 Spaces 行为（主线程）。层级同刘海窗口：要盖过菜单栏，logo 才能从胶囊飞出来。
pub fn prepare(win: &tauri::WebviewWindow) {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let Ok(ptr) = win.ns_window() else { return };
    if ptr.is_null() { return; }
    // SAFETY: 主线程；ptr 是本窗口仍存活的 NSWindow；只设标量属性。
    unsafe {
        let w = ptr as *mut AnyObject;
        let _: () = msg_send![w, setLevel: 26isize];
        let behavior: usize = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8);
        let _: () = msg_send![w, setCollectionBehavior: behavior];
        let _: () = msg_send![w, setHasShadow: false];
        let _: () = msg_send![w, setHidesOnDeactivate: false];
        let _: () = msg_send![w, setIgnoresMouseEvents: true];
    }
}

fn set_accepting(app: &AppHandle, accept: bool) {
    let a = app.clone();
    let _ = app.run_on_main_thread(move || {
        use objc2::msg_send;
        if let Some(w) = ns_window(&a) {
            // SAFETY: 主线程；本窗口仍存活。
            unsafe { let _: () = msg_send![w, setIgnoresMouseEvents: !accept]; }
        }
    });
}

fn place(app: &AppHandle, front: bool) {
    let Some(t) = *GEOM.lock().unwrap() else { return };
    let ((x, y, w, h), _, _) = rect_now(&t);
    let a = app.clone();
    let _ = app.run_on_main_thread(move || {
        let Some(win) = a.get_webview_window(LABEL) else { return };
        let _ = win.set_size(LogicalSize::new(w, h));
        let _ = win.set_position(LogicalPosition::new(x, y));
        if front {
            use objc2::msg_send;
            if let Some(p) = ns_window(&a) {
                // SAFETY: 主线程；只排到最前、不当 key（不抢焦点）。
                unsafe {
                    let _: () = msg_send![p, setIgnoresMouseEvents: true];
                    let _: () = msg_send![p, orderFrontRegardless];
                }
            }
        }
    });
}

fn open(app: &AppHandle) {
    PHASE.store(OPEN, Ordering::SeqCst);
    GEN.fetch_add(1, Ordering::SeqCst);
    place(app, true);
    let _ = app.emit_to(LABEL, "tpshover-open", layout().unwrap_or(serde_json::Value::Null));
}

fn close(app: &AppHandle, reason: &'static str) {
    if PHASE.swap(IDLE, Ordering::SeqCst) != OPEN { return; }
    let gen = GEN.fetch_add(1, Ordering::SeqCst) + 1;
    let _ = app.emit_to(LABEL, "tpshover-close", reason);
    set_accepting(app, false);
    let a = app.clone();
    let wait = if reason == "click" { CLICK_ANIM } else { CLOSE_ANIM };
    // ★ 托盘 logo 等 logo 飞回胶囊之后再画回（交接包 page2「飞行期间托盘图片画无 logo 的胶囊」）；
    //   一关就画回会同时看到两个 logo。中途又打开了就交给新的那一代。
    std::thread::spawn(move || {
        std::thread::sleep(wait);
        if GEN.load(Ordering::SeqCst) != gen || PHASE.load(Ordering::SeqCst) == OPEN { return; }
        crate::tray_pill::set_hide_logos(&a, false);
        if let Some(w) = a.get_webview_window(LABEL) { let _ = w.hide(); }
    });
}

fn menubar_visible(app: &AppHandle) -> bool {
    app.get_webview_window("menubar").and_then(|w| w.is_visible().ok()).unwrap_or(false)
}

/// 这种面板此刻还该开着吗：在跑面板要有 AI 在跑；空闲面板要没有。
fn panel_wanted(idle: bool) -> bool { crate::tray_pill::is_running() != idle }

/// 托盘 `Enter`：叫醒轮询线程（已有一条就什么也不做）。
/// 在跑 ⇒ 速度面板（Page 2）；空闲 ⇒ 额度格子（P11 §6，「AI 图标」与「文字标题」两种空闲托盘都弹）。
pub fn on_enter(app: &AppHandle) {
    if SUPPRESS.load(Ordering::SeqCst) { return; }
    let idle = !crate::tray_pill::is_running();
    if PHASE.load(Ordering::SeqCst) == IDLE {
        IDLE_PANEL.store(idle, Ordering::SeqCst);
        PHASE.store(DWELL, Ordering::SeqCst);
    }
    if POLLER.swap(true, Ordering::SeqCst) { return; }
    refresh_geom_soon(app);
    let app = app.clone();
    std::thread::spawn(move || {
        let start = Instant::now();
        let mut dwell_from = start;
        let mut out_since: Option<Instant> = None;
        let mut accepting = false;
        let mut last_cur: Option<(f64, f64)> = None;
        let mut geom_at = Instant::now();
        loop {
            std::thread::sleep(TICK);
            let phase = PHASE.load(Ordering::SeqCst);
            if phase == IDLE { break; }
            let Some(t) = *GEOM.lock().unwrap() else {
                if start.elapsed() > Duration::from_secs(1) { PHASE.store(IDLE, Ordering::SeqCst); break; }
                continue;
            };
            if geom_at.elapsed() >= GEOM_REFRESH { refresh_geom_soon(&app); geom_at = Instant::now(); }
            let (x, y) = cursor(t.primary_h);
            let in_tray = contains((t.x, t.y, t.w, t.h), x, y);
            let idle = IDLE_PANEL.load(Ordering::SeqCst);
            if phase == DWELL {
                if !in_tray || SUPPRESS.load(Ordering::SeqCst) { PHASE.store(IDLE, Ordering::SeqCst); break; }
                // 停留期间托盘换了样（开跑 / 全停）⇒ 改按新的那种面板，停留重新计时；否则会一直等一个不会再成立的条件
                if !panel_wanted(idle) {
                    IDLE_PANEL.store(!idle, Ordering::SeqCst);
                    dwell_from = Instant::now();
                    continue;
                }
                let dwell = if idle { IDLE_OPEN_DWELL } else { OPEN_DWELL };
                if dwell_from.elapsed() >= dwell && !menubar_visible(&app) && (!idle || idle_has_cells()) {
                    open(&app);
                }
                continue;
            }
            // 打开着：托盘换了样 ⇒ 收起；光标还在托盘上就回到停留，按新的那种面板再弹（不用移开再进来）
            if !panel_wanted(idle) {
                close(&app, "idle");
                if in_tray {
                    IDLE_PANEL.store(!idle, Ordering::SeqCst);
                    PHASE.store(DWELL, Ordering::SeqCst);
                    dwell_from = Instant::now() + CLOSE_ANIM;
                    out_since = None;
                    if accepting { accepting = false; set_accepting(&app, false); }
                    continue;
                }
                break;
            }
            let ((wx, wy, _, _), (px, py), pw) = rect_now(&t);
            let panel = (wx + px, wy + py, pw, *PANEL_H.lock().unwrap());
            let in_panel = contains(panel, x, y);
            if in_panel != accepting { accepting = in_panel; set_accepting(&app, in_panel); }
            // 面板内光标坐标交给网页做行命中（展开会话）：app 不在前台时 WKWebView 收不到鼠标移动。只在变了时报
            let cur = in_panel.then(|| (x - wx, y - wy));
            if cur != last_cur {
                last_cur = cur;
                let _ = app.emit_to(LABEL, "tpshover-cursor", cur.map(|(a, b)| [a, b]));
            }
            if in_tray || in_panel {
                out_since = None;
            } else if out_since.get_or_insert_with(Instant::now).elapsed() >= CLOSE_DWELL {
                close(&app, "leave");
                break;
            }
        }
        POLLER.store(false, Ordering::SeqCst);
    });
}

/// 托盘 `Leave`：点击后的「不再弹」到这里解除（离开 / 关闭的计时在轮询线程里）。
pub fn on_leave() { SUPPRESS.store(false, Ordering::SeqCst); }

/// 面板里点了格子（空闲额度格子跳总览）：快速收起。
/// ★ 不设 `SUPPRESS`：点的时候光标在面板里，托盘的 `Leave` 早就发过了 ⇒ 没人会再清它，下一次悬停会被吞掉。
pub fn dismiss(app: &AppHandle) {
    if PHASE.load(Ordering::SeqCst) == OPEN { close(app, "click"); }
    PHASE.store(IDLE, Ordering::SeqCst);
}

/// 托盘点击：先收起悬停面板，调用方再走原有菜单栏弹窗。
pub fn on_click(app: &AppHandle) {
    SUPPRESS.store(true, Ordering::SeqCst);
    if PHASE.load(Ordering::SeqCst) == OPEN { close(app, "click"); }
    PHASE.store(IDLE, Ordering::SeqCst);
}

// ---------------------------------------------------------------- 空闲托盘：鼠标靠近（P11 §4–§5）

static NEAR_WATCH: AtomicBool = AtomicBool::new(false);
static NEAR_GLOW: AtomicBool = AtomicBool::new(true);
/// 0 关闭 · 1 每天一次（默认）· 2 每次空闲 1 小时后
static HELLO_MODE: AtomicU8 = AtomicU8::new(1);
static LAST_HELLO: Mutex<Option<(i64, f64)>> = Mutex::new(None);
/// 光标离托盘远时慢轮询（只为发现它回来），离托盘 `NEAR_FAST_PT` 以内 30 Hz。
/// ★ 按到托盘矩形的距离判，不按「离屏幕顶多远」：浏览器标签栏、副屏顶部都在顶部 90 pt 内，按纵向判就几乎一直 30 Hz。
const NEAR_TICK_FAR: Duration = Duration::from_millis(150);
const NEAR_FAST_PT: f64 = 150.0;
/// 托盘位置只在光标靠近时刷新（远处不用知道它挪了几个 pt；靠近时按它判光晕）。
const NEAR_GEOM_REFRESH: Duration = Duration::from_secs(2);

/// 设置页「鼠标靠近光晕」「打招呼」，外加重启前记下的「上次打招呼」（epoch 秒，前端 localStorage）。
pub fn set_idle_prefs(glow: bool, hello: &str, last_hello: Option<f64>) {
    NEAR_GLOW.store(glow, Ordering::SeqCst);
    if let Some(e) = last_hello.filter(|e| e.is_finite() && *e > 0.0) {
        let mut last = LAST_HELLO.lock().unwrap();
        if last.map_or(true, |(_, t)| e > t) { *last = Some((local_day(e), e)); }
    }
    let m = match crate::tray_idle::HelloMode::parse(hello) {
        crate::tray_idle::HelloMode::Off => 0, crate::tray_idle::HelloMode::Daily => 1, crate::tray_idle::HelloMode::AfterIdle => 2,
    };
    HELLO_MODE.store(m, Ordering::SeqCst);
}

fn hello_mode() -> crate::tray_idle::HelloMode {
    match HELLO_MODE.load(Ordering::SeqCst) {
        0 => crate::tray_idle::HelloMode::Off, 2 => crate::tray_idle::HelloMode::AfterIdle, _ => crate::tray_idle::HelloMode::Daily,
    }
}

/// 本机时区的日期键（年 × 1000 + 年内第几天）。打招呼「每天最多一次」按本地日界。
fn local_day(epoch: f64) -> i64 {
    let t = epoch as libc::time_t;
    // SAFETY: `localtime_r` 只写我们给的 `tm`；`t` 是有效的 time_t。
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    let ok = unsafe { !libc::localtime_r(&t, &mut tm).is_null() };
    if ok { (tm.tm_year as i64 + 1900) * 1000 + tm.tm_yday as i64 } else { (epoch / 86400.0) as i64 }
}

/// 空闲托盘开着就跑一条光标轮询线程：进入托盘周围 ~35 pt ⇒ 光晕（+ 每天一次的打招呼），离开 ⇒ 熄。
/// 设置改回「文字标题」后线程自己退出。只读 `NSEvent mouseLocation`（任意线程可调），不接管任何事件。
pub fn start_near_watch(app: &AppHandle) {
    if NEAR_WATCH.swap(true, Ordering::SeqCst) { return; }
    refresh_geom_soon(app);
    let app = app.clone();
    std::thread::spawn(move || {
        // 起头先报一次「不靠近」：上一条线程若在靠近时退出，前端的 `near` 会卡在 true（挡住跨天重排）
        let mut near = false;
        let mut glow = false;
        let _ = app.emit_to("menubar", "idle-near", false);
        let mut geom_at: Option<Instant> = None;
        while crate::tray_pill::icon_idle_on() {
            let Some(t) = *GEOM.lock().unwrap() else {
                if geom_at.map_or(true, |g| g.elapsed() >= NEAR_GEOM_REFRESH) { refresh_geom_soon(&app); geom_at = Some(Instant::now()); }
                std::thread::sleep(NEAR_TICK_FAR);
                continue;
            };
            let (x, y) = cursor(t.primary_h);
            let d = crate::tray_idle::dist_to_rect(x, y, (t.x, t.y, t.w, t.h));
            let close_by = d <= NEAR_FAST_PT;
            if close_by && geom_at.map_or(true, |g| g.elapsed() >= NEAR_GEOM_REFRESH) { refresh_geom_soon(&app); geom_at = Some(Instant::now()); }
            // 远处不问托盘在画什么（那要锁绘制状态）：远处本来就不靠近
            let now_near = close_by && d <= crate::tray_idle::NEAR_PT && crate::tray_pill::idle_icons_shown();
            // 光晕跟着设置走：靠近期间关掉「鼠标靠近光晕」也立刻熄
            let want_glow = now_near && NEAR_GLOW.load(Ordering::SeqCst);
            if now_near != near || want_glow != glow {
                let hello = now_near && !near && greet_allowed(&app);
                if now_near != near { let _ = app.emit_to("menubar", "idle-near", now_near); }
                near = now_near;
                glow = want_glow;
                crate::tray_pill::idle_near(&app, glow, hello);
            }
            std::thread::sleep(if close_by { TICK } else { NEAR_TICK_FAR });
        }
        // 退出时靠近着 ⇒ 熄光晕、告诉前端「不靠近了」
        if near || glow {
            crate::tray_pill::idle_near(&app, false, false);
            let _ = app.emit_to("menubar", "idle-near", false);
        }
        NEAR_WATCH.store(false, Ordering::SeqCst);
        // 退出与清标记之间又被打开：补一条
        if crate::tray_pill::icon_idle_on() { start_near_watch(&app); }
    });
}

/// 这次靠近要不要打招呼：先挡「不打招呼」的几种时刻（P11 §5），再问频率。打了就记账。
fn greet_allowed(app: &AppHandle) -> bool {
    if crate::tray_pill::ai_running() || crate::tray_pill::is_running() || PHASE.load(Ordering::SeqCst) != IDLE
        || menubar_visible(app) || crate::tray_pill::idle_greet_blocked() { return false; }
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64());
    let today = local_day(now);
    let mut last = LAST_HELLO.lock().unwrap();
    let ok = crate::tray_idle::should_hello(hello_mode(), today, now, crate::tray_pill::last_active_epoch(), *last);
    if ok {
        *last = Some((today, now));
        // 前端记进 localStorage，重启后经 `set_idle_prefs` 带回来（否则每次重启 / 部署都会再打一次招呼）
        let _ = app.emit_to("menubar", "idle-hello", now);
    }
    ok
}

/// 空闲面板有没有格子（菜单栏 webview 随 `set_idle_tray` 带来）。没有就不弹 —— 否则是一条带阴影的细线。
static IDLE_CELLS: AtomicBool = AtomicBool::new(false);
pub fn idle_has_cells() -> bool { IDLE_CELLS.load(Ordering::SeqCst) }
pub fn set_idle_cells(n: usize) { IDLE_CELLS.store(n > 0, Ordering::SeqCst); }

pub fn set_panel_height(app: &AppHandle, h: f64) {
    *PANEL_H.lock().unwrap() = h.clamp(40.0, 640.0);
    if PHASE.load(Ordering::SeqCst) == OPEN { place(app, false); }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tray(x: f64) -> Tray { Tray { x, y: 0.0, w: 100.0, h: 24.0, screen_x: 0.0, screen_w: 1470.0, primary_h: 956.0 } }

    #[test]
    fn both_panels_open_fast() {
        // ★ 用户 2026-10-21「运行中和空闲的悬浮弹窗响应要加快」：停留判定不超过 100 ms、轮询粒度不超过 20 ms
        assert!(OPEN_DWELL <= Duration::from_millis(100) && IDLE_OPEN_DWELL <= Duration::from_millis(100));
        assert!(TICK <= Duration::from_millis(20));
    }
    #[test]
    fn run_panel_is_centred_under_the_pill() {
        let ((wx, wy, w, h), (px, py)) = window_rect(&tray(1000.0), 200.0);
        assert_eq!(wx + px + PANEL_W / 2.0, 1000.0 + 100.0 / 2.0, "★ 用户「运行中的悬浮弹窗也要改为居中」：面板中线 = 按钮中线");
        assert_eq!((wy, py), (0.0, 24.0 + GAP), "窗口顶到屏幕顶（盖住胶囊），面板在菜单栏下方");
        assert_eq!(w, PANEL_W + 2.0 * PAD_X);
        assert_eq!(h, 24.0 + GAP + 200.0 + PAD_B);
    }
    #[test]
    fn idle_panel_is_435_wide_and_centred_under_the_pill() {
        let ((wx, _, w, _), (px, _)) = window_rect_for(&tray(1000.0), IDLE_PANEL_W, 90.0);
        assert_eq!(IDLE_PANEL_W, 435.0, "画板 580 × 0.75（1.5×）");
        assert_eq!(wx + px + IDLE_PANEL_W / 2.0, 1000.0 + 100.0 / 2.0, "★ 用户「居中弹窗」：面板中线 = 胶囊中线");
        assert_eq!(w, IDLE_PANEL_W + 2.0 * PAD_X);
        // 贴屏幕右缘：往里收，不越出屏幕
        let ((wx, _, _, _), (px, _)) = window_rect_for(&tray(1440.0), IDLE_PANEL_W, 90.0);
        assert!(wx + px + IDLE_PANEL_W <= 1470.0 - 4.0 + 1e-9);
    }
    #[test]
    fn panel_stays_on_screen_at_the_right_edge() {
        let ((wx, _, _, _), (px, _)) = window_rect(&tray(1440.0), 200.0);
        assert!(wx + px + PANEL_W <= 1470.0 - 4.0 + 1e-9, "贴屏幕右缘时面板不越出屏幕");
    }
}
