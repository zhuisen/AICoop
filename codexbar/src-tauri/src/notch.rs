//! 刘海额度条（macOS 专属，**默认关**，设置页开）。用户 2026-10-17 从 demo 里选定
//! 「收起 = 刘海下沿 7pt 黑边里的分段细线、悬停 = 额度环面板」。
//!
//! ★ 为什么能做成 Tauri 窗口而不是另起一个 Swift 进程：2026-10-17 独立验证程序实测 ——
//!   层级设到 `NSStatusWindowLevel + 1` 后窗口顶边与屏幕顶边间距 0、盖在菜单栏之上；
//!   全屏应用里可见（用户确认）；悬停在 CodexBar 不在前台时照样触发（用户试了十几次）。
//!
//! ★★ 刘海本身**没有像素**。画在刘海矩形里的东西看不见，所以收起态是在刘海**下沿**多出
//!    `LIP` 那 7pt 黑边，细线画在那里；两侧各 `FLARE` 是刘海上沿的内凹圆角。
//!
//! ★★ 悬停判定**不靠网页里的 mouseenter**：CodexBar 是 Accessory 应用、几乎永远不在前台，
//!    WKWebView 在后台窗口里收不收得到鼠标移动没验过，不赌它。做法分两段（Agent HUD 同理）：
//!    · 平时：系统鼠标事件监听（全局 + 本进程各一个）。鼠标不动就不触发 ——
//!      验证程序里纯轮询（80/250ms）空闲主进程 0.30% CPU（不轮询时的底数没量过）；
//!    · 光标进了刘海区：起一个 60ms 的跟踪线程，直到光标离开且面板收完。
//!      监听只负责"叫醒"，进出与停留的判定全在跟踪线程里 —— 光标停在我们自己的窗口上时，
//!      全局监听可能收不到事件，只靠事件会"离不开"。
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl};

pub const LABEL: &str = "notch";
/// 刘海上沿两侧的内凹圆角，窗口要比刘海各宽这么多。与 `notch.css` 的 `--flare` 同值。
const FLARE: f64 = 7.0;
/// 收起态在刘海下沿多出的黑边（细线就画在这里）。与 `notch.css` 的 `--lip` 同值。
const LIP: f64 = 7.0;
/// 展开面板宽。与 `NotchHud.tsx` 的 `PANEL_W` 同值，闸在 `tests/test_notch_hud.py`。
pub const PANEL_W: f64 = 312.0;
const OPEN_DWELL: Duration = Duration::from_millis(90);
const CLOSE_DWELL: Duration = Duration::from_millis(220);
/// 前端收起动画时长（`notch.css` 的 clip-path 过渡 .34s）。收完再缩窗口，否则动画被裁掉。
const COLLAPSE: Duration = Duration::from_millis(340);
const TRACK_TICK: Duration = Duration::from_millis(60);
/// 几何（刘海位置）最多多久重读一次。合盖/改分辨率后靠它自愈，不必监听屏幕变更通知。
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
}

static ENABLED: AtomicBool = AtomicBool::new(false);
static OPEN: AtomicBool = AtomicBool::new(false);
static TRACKING: AtomicBool = AtomicBool::new(false);
static GEOM: Mutex<Option<(Option<Notch>, Instant)>> = Mutex::new(None);
static PANEL_H: Mutex<f64> = Mutex::new(180.0);
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

/// 带刘海的那块屏幕上，刘海的位置。没有刘海的屏幕 ⇒ `None`（用户 2026-10-17 定：
/// 外接屏、合盖时**不显示**，不画替身条）。
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
            let left = l.origin.x + l.size.width;
            let right = r.origin.x;
            if right <= left { continue; }
            return Some(Notch {
                left, width: right - left, height: ins.top,
                top: pf.size.height - (f.origin.y + f.size.height),
                primary_h: pf.size.height,
            });
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

/// 收起/展开时窗口在桌面坐标里的矩形。
fn rect(g: &Notch, open: bool) -> (f64, f64, f64, f64) {
    if open {
        let h = *PANEL_H.lock().unwrap();
        let w = PANEL_W + FLARE * 2.0;
        (g.left + g.width / 2.0 - w / 2.0, g.top, w, h)
    } else {
        (g.left - FLARE, g.top, g.width + FLARE * 2.0, g.height + LIP)
    }
}

/// 光标是否在触发区内。收起时只认刘海 + 下沿黑边（两侧圆角那 7pt 是菜单栏，不算）。
fn hit(g: &Notch, open: bool, x: f64, y: f64) -> bool {
    let (rx, ry, rw, rh) = rect(g, open);
    let (rx, rw) = if open { (rx, rw) } else { (rx + FLARE, rw - FLARE * 2.0) };
    x >= rx && x <= rx + rw && y >= ry - 2.0 && y <= ry + rh
}

fn place(app: &AppHandle, open: bool) {
    let (Some(win), Some(g)) = (app.get_webview_window(LABEL), cached()) else { return };
    let (x, y, w, h) = rect(&g, open);
    let _ = win.set_size(LogicalSize::new(w, h));
    let _ = win.set_position(LogicalPosition::new(x, y));
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
    }
}

/// 光标位置（桌面坐标）。`+[NSEvent mouseLocation]` 给的是左下原点，翻一下。主线程调用。
fn mouse_on_main(g: &Notch) -> (f64, f64) {
    use objc2::{class, msg_send};
    // SAFETY: 类方法，无参数，返回值是值类型。
    let p: objc2_foundation::NSPoint = unsafe { msg_send![class!(NSEvent), mouseLocation] };
    (p.x, g.primary_h - p.y)
}

fn set_open(app: &AppHandle, open: bool) {
    if OPEN.swap(open, Ordering::SeqCst) == open { return; }
    if open {
        place(app, true);
        let _ = app.emit_to(LABEL, "notch-open", true);
    } else {
        let _ = app.emit_to(LABEL, "notch-open", false);
        let app = app.clone();
        std::thread::spawn(move || {
            std::thread::sleep(COLLAPSE);
            if !OPEN.load(Ordering::SeqCst) { place(&app, false); }
        });
    }
}

/// 跟踪线程：光标进刘海区之后才存在，离开并收完就退出。
fn track(app: AppHandle) {
    if TRACKING.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        let mut inside = true;
        let mut since = Instant::now();
        loop {
            std::thread::sleep(TRACK_TICK);
            if !ENABLED.load(Ordering::SeqCst) { break; }
            let (Some(g), Ok(p), Some(win)) = (cached(), app.cursor_position(), app.get_webview_window(LABEL))
                else { break };
            let scale = win.scale_factor().unwrap_or(2.0);
            let open = OPEN.load(Ordering::SeqCst);
            let now_in = hit(&g, open, p.x / scale, p.y / scale);
            if now_in != inside { inside = now_in; since = Instant::now(); }
            if inside && !open && since.elapsed() >= OPEN_DWELL {
                set_open(&app, true);
            } else if !inside && open && since.elapsed() >= CLOSE_DWELL {
                set_open(&app, false);
            } else if !inside && !open && since.elapsed() >= CLOSE_DWELL {
                break;   // 擦过没停够，或已经收完
            }
        }
        TRACKING.store(false, Ordering::SeqCst);
    });
}

/// 鼠标事件监听的回调（主线程）。只做"光标进没进刘海区"这一件事，命中就叫醒跟踪线程。
fn on_mouse(app: &AppHandle) {
    if !ENABLED.load(Ordering::Relaxed) || TRACKING.load(Ordering::Relaxed) { return; }
    let before = cached();
    let Some(g) = geometry() else { return };
    // 合盖/改分辨率后刘海位置变了：窗口跟过去
    if before != Some(g) { place(app, OPEN.load(Ordering::SeqCst)); }
    let (x, y) = mouse_on_main(&g);
    if hit(&g, false, x, y) { track(app.clone()); }
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
}

fn remove_monitors() {
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
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

/// 开/关。开 = 建窗口 + 装监听；关 = 拆监听 + **销毁窗口**（不只是隐藏 —— 隐藏的
/// WKWebView 仍占着两个系统进程，默认关的功能不该常驻任何东西）。
/// ★ 调用方是**同步**命令（Tauri 2 的同步命令在主线程跑），这里要读 NSScreen。
pub fn set_enabled(app: &AppHandle, on: bool) -> Result<(), String> {
    ENABLED.store(on, Ordering::SeqCst);
    if !on {
        OPEN.store(false, Ordering::SeqCst);
        let _ = app.run_on_main_thread(remove_monitors);
        if let Some(w) = app.get_webview_window(LABEL) { let _ = w.destroy(); }
        return Ok(());
    }
    *GEOM.lock().unwrap() = None;
    let Some(g) = geometry() else {
        // 没有刘海屏：什么都不建。开关仍记着"开"，换回带刘海的屏幕后重新开一次即可。
        return Ok(());
    };
    if app.get_webview_window(LABEL).is_none() {
        let (x, y, w, h) = rect(&g, false);
        let win = tauri::webview::WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("notch.html".into()))
            .title("CodexBar Notch")
            .decorations(false)
            .transparent(true)
            .resizable(false)
            .skip_taskbar(true)
            .shadow(false)
            .focused(false)
            .visible(false)
            .inner_size(w, h)
            .position(x, y)
            .build()
            .map_err(|e| e.to_string())?;
        let w2 = win.clone();
        let _ = app.run_on_main_thread(move || {
            raise(&w2);
            let _ = w2.show();
        });
    }
    place(app, false);
    let a = app.clone();
    let _ = app.run_on_main_thread(move || install_monitors(&a));
    Ok(())
}

pub fn notch_geometry() -> Option<Notch> { cached() }

/// 前端量出展开面板的自然高度后告诉这里（随额度窗口个数变）。
pub fn set_panel_height(app: &AppHandle, h: f64) {
    *PANEL_H.lock().unwrap() = h.clamp(80.0, 400.0);
    if OPEN.load(Ordering::SeqCst) { place(app, true); }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn air13() -> Notch { Notch { left: 646.0, width: 179.0, height: 32.0, top: 0.0, primary_h: 956.0 } }

    #[test]
    fn collapsed_window_covers_notch_plus_flares_and_lip() {
        assert_eq!(rect(&air13(), false), (639.0, 0.0, 193.0, 39.0));
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
}
