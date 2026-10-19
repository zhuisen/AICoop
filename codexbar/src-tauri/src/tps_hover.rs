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
/// 面板外的透明边：阴影 `0 16 40 rgba(0,0,0,.45)` 要往外 ~40、往下再多 16。
const PAD_X: f64 = 40.0;
const PAD_B: f64 = 56.0;
/// 面板顶到菜单栏下沿的距离（原型：胶囊容器 22 高、面板从 28 起 ⇒ 下方 6）。
const GAP: f64 = 6.0;
/// 面板右沿比胶囊右沿多出 8（原型 `panelLeft = 104 - panelW + 8`），锚点右上。
const RIGHT_OVERHANG: f64 = 8.0;
const OPEN_DWELL: Duration = Duration::from_millis(200);
const CLOSE_DWELL: Duration = Duration::from_millis(300);
/// 关闭动画：数据 100 ms 淡出 → logo 飞回胶囊 → 外壳延后 120 ms 淡出。动画走完再真隐藏。
const CLOSE_ANIM: Duration = Duration::from_millis(520);
const CLICK_ANIM: Duration = Duration::from_millis(160);
const TICK: Duration = Duration::from_millis(33);
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

/// 状态栏按钮在桌面坐标（主屏左上原点，逻辑 pt）里的位置，以及它所在屏。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tray { pub x: f64, pub y: f64, pub w: f64, pub h: f64, pub screen_x: f64, pub screen_w: f64, pub primary_h: f64 }

/// 窗口矩形（桌面坐标）与面板在窗口内的位置。纯函数，单测覆盖贴屏幕右缘时的钳位。
pub fn window_rect(t: &Tray, pill_w: f64, panel_h: f64) -> ((f64, f64, f64, f64), (f64, f64)) {
    let pill_right = t.x + (t.w + pill_w) / 2.0;
    let panel_x = (pill_right + RIGHT_OVERHANG - PANEL_W)
        .min(t.screen_x + t.screen_w - PANEL_W - 4.0)
        .max(t.screen_x + 4.0);
    let wx = panel_x - PAD_X;
    let w = PANEL_W + PAD_X * 2.0;
    let h = t.h + GAP + panel_h + PAD_B;
    ((wx, t.y, w, h), (PAD_X, t.h + GAP))
}

fn contains(r: (f64, f64, f64, f64), x: f64, y: f64) -> bool {
    x >= r.0 && x <= r.0 + r.2 && y >= r.1 && y <= r.1 + r.3
}

/// 给网页的版面（窗口内坐标）。
pub fn layout() -> Option<serde_json::Value> {
    let t = (*GEOM.lock().unwrap())?;
    let pill = crate::tray_pill::segment_rects();
    let pill_w = pill["width"].as_f64().unwrap_or(0.0);
    let ph = *PANEL_H.lock().unwrap();
    let ((wx, wy, ww, wh), (px, py)) = window_rect(&t, pill_w, ph);
    let pill_x = t.x + (t.w - pill_w) / 2.0 - wx;
    let pill_y = t.y + (t.h - crate::tray_pill::H) / 2.0 - wy;
    let segs: Vec<serde_json::Value> = pill["segments"].as_array().cloned().unwrap_or_default().into_iter().map(|mut s| {
        if let Some(x) = s["x"].as_f64() { s["x"] = (x + pill_x).into(); }
        if let Some(x) = s["logo"]["x"].as_f64() { s["logo"]["x"] = (x + pill_x).into(); }
        if let Some(y) = s["logo"]["y"].as_f64() { s["logo"]["y"] = (y + pill_y).into(); }
        s
    }).collect();
    Some(serde_json::json!({
        "window": { "w": ww, "h": wh },
        "menubar_h": t.h,
        "panel": { "x": px, "y": py, "w": PANEL_W, "h": ph },
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
    let pill_w = crate::tray_pill::segment_rects()["width"].as_f64().unwrap_or(0.0);
    let ((x, y, w, h), _) = window_rect(&t, pill_w, *PANEL_H.lock().unwrap());
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

/// 托盘 `Enter`：叫醒轮询线程（已有一条就什么也不做）。
pub fn on_enter(app: &AppHandle) {
    if SUPPRESS.load(Ordering::SeqCst) || !crate::tray_pill::is_running() { return; }
    if PHASE.load(Ordering::SeqCst) == IDLE { PHASE.store(DWELL, Ordering::SeqCst); }
    if POLLER.swap(true, Ordering::SeqCst) { return; }
    refresh_geom_soon(app);
    let app = app.clone();
    std::thread::spawn(move || {
        let start = Instant::now();
        let mut out_since: Option<Instant> = None;
        let mut accepting = false;
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
            if phase == DWELL {
                if !in_tray || SUPPRESS.load(Ordering::SeqCst) { PHASE.store(IDLE, Ordering::SeqCst); break; }
                if start.elapsed() >= OPEN_DWELL && crate::tray_pill::is_running() && !menubar_visible(&app) {
                    open(&app);
                }
                continue;
            }
            // 打开着
            if !crate::tray_pill::is_running() { close(&app, "idle"); break; }
            let pill_w = crate::tray_pill::segment_rects()["width"].as_f64().unwrap_or(0.0);
            let ((wx, wy, _, _), (px, py)) = window_rect(&t, pill_w, *PANEL_H.lock().unwrap());
            let panel = (wx + px, wy + py, PANEL_W, *PANEL_H.lock().unwrap());
            let in_panel = contains(panel, x, y);
            if in_panel != accepting { accepting = in_panel; set_accepting(&app, in_panel); }
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

/// 托盘点击：先收起悬停面板，调用方再走原有菜单栏弹窗。
pub fn on_click(app: &AppHandle) {
    SUPPRESS.store(true, Ordering::SeqCst);
    if PHASE.load(Ordering::SeqCst) == OPEN { close(app, "click"); }
    PHASE.store(IDLE, Ordering::SeqCst);
}

pub fn set_panel_height(app: &AppHandle, h: f64) {
    *PANEL_H.lock().unwrap() = h.clamp(40.0, 640.0);
    if PHASE.load(Ordering::SeqCst) == OPEN { place(app, false); }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tray(x: f64) -> Tray { Tray { x, y: 0.0, w: 100.0, h: 24.0, screen_x: 0.0, screen_w: 1470.0, primary_h: 956.0 } }

    #[test]
    fn panel_is_anchored_top_right_under_the_pill() {
        let ((wx, wy, w, h), (px, py)) = window_rect(&tray(1000.0), 96.0, 200.0);
        let pill_right = 1000.0 + (100.0 + 96.0) / 2.0;
        assert_eq!(wx + px + PANEL_W, pill_right + 8.0, "面板右沿 = 胶囊右沿 + 8");
        assert_eq!((wy, py), (0.0, 24.0 + GAP), "窗口顶到屏幕顶（盖住胶囊），面板在菜单栏下方");
        assert_eq!(w, PANEL_W + 2.0 * PAD_X);
        assert_eq!(h, 24.0 + GAP + 200.0 + PAD_B);
    }
    #[test]
    fn panel_stays_on_screen_at_the_right_edge() {
        let ((wx, _, _, _), (px, _)) = window_rect(&tray(1440.0), 60.0, 200.0);
        assert!(wx + px + PANEL_W <= 1470.0 - 4.0 + 1e-9, "贴屏幕右缘时面板不越出屏幕");
    }
}
