//! 主窗口的拖动 / 缩放手感（用户 2026-10-22 从 `~/Downloads/codexbar_window_drag_demo_v2_20261022.html`
//! 选 D3 + G3 + S1 + S3 + S4 + M）。这里管窗口本身怎么动；抓手、微光、磁性、尺寸胶囊在网页
//! （`components/WindowGrip.tsx`）。
//!
//! - **S1 靠边吸附**：拖窗口松手时，离工作区左 / 右边、水平居中线、顶 / 底边 < 18 pt ⇒ 弹簧弹过去，留 8 pt。
//!   拖动由系统接管（`performWindowDragWithEvent`），中途改不了位置 ⇒ 只在松手后修正。
//!   判「是用户在拖」= `Moved` 时左键按着；程序自己 `set_position`（含这里的弹簧）时左键是松的，不会自触发。
//!   拖动中尺寸变了（左缘缩放、系统平铺）⇒ 不吸。
//! - **S3 尺寸档位**：macOS 上 `startResizeDragging` 不可用（tao 0.35 `drag_resize_window` 返回 NotSupported），
//!   抓手的缩放由这里的后台线程读 `NSEvent mouseLocation` 驱动，靠近 860×560 / 1200×800 / 1440×900 时吸住；
//!   每次变化发 `grip-size` 给网页画胶囊，松手发 `null`。原生四边缩放照常可用（不吸）。
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager};

pub const MIN_W: f64 = 860.0;
pub const MIN_H: f64 = 560.0;
pub const SNAP_GAP: f64 = 8.0;
pub const SNAP_T: f64 = 18.0;
pub const PRESET_T: f64 = 16.0;
pub const PRESETS: [(f64, f64, &str); 3] = [(860.0, 560.0, "最小"), (1200.0, 800.0, "常用"), (1440.0, 900.0, "宽屏")];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect { pub x: f64, pub y: f64, pub w: f64, pub h: f64 }

/// 松手后该弹到哪（桌面逻辑坐标，左上原点）。不用动 ⇒ `None`。横向：左边 > 右边 > 水平居中；纵向：顶 > 底。
pub fn snap_pos(win: Rect, area: Rect) -> Option<(f64, f64)> {
    let (mut x, mut y, mut hit) = (win.x, win.y, false);
    let (l, r) = (area.x + SNAP_GAP, area.x + area.w - SNAP_GAP);
    let (t, b) = (area.y + SNAP_GAP, area.y + area.h - SNAP_GAP);
    if (win.x - l).abs() < SNAP_T { x = l; hit = true; }
    else if (win.x + win.w - r).abs() < SNAP_T { x = r - win.w; hit = true; }
    else if (win.x + win.w / 2.0 - (area.x + area.w / 2.0)).abs() < SNAP_T { x = area.x + (area.w - win.w) / 2.0; hit = true; }
    if (win.y - t).abs() < SNAP_T { y = t; hit = true; }
    else if (win.y + win.h - b).abs() < SNAP_T { y = b - win.h; hit = true; }
    (hit && ((x - win.x).abs() > 0.5 || (y - win.y).abs() > 0.5)).then_some((x, y))
}

/// 抓手缩放的尺寸：靠近档位 ±16 pt 就吸住，返回吸住的档名。
pub fn snap_size(w: f64, h: f64) -> (f64, f64, Option<&'static str>) {
    for (pw, ph, n) in PRESETS {
        if (w - pw).abs() < PRESET_T && (h - ph).abs() < PRESET_T { return (pw, ph, Some(n)); }
    }
    (w, h, None)
}

/// 弹簧逐帧位置（demo 同参数 K 380 / C 30，60 fps）；最后一帧恰好是终点。
pub fn spring_path(from: (f64, f64), to: (f64, f64)) -> Vec<(f64, f64)> {
    let (k, c, dt) = (380.0, 30.0, 1.0 / 60.0);
    let (mut p, mut v) = (from, (0.0f64, 0.0f64));
    let mut out = Vec::new();
    for _ in 0..90 {
        v.0 += (k * (to.0 - p.0) - c * v.0) * dt;
        v.1 += (k * (to.1 - p.1) - c * v.1) * dt;
        p.0 += v.0 * dt;
        p.1 += v.1 * dt;
        out.push(p);
        if (to.0 - p.0).abs() < 0.3 && (to.1 - p.1).abs() < 0.3 && v.0.abs() < 4.0 && v.1.abs() < 4.0 { break; }
    }
    out.push(to);
    out
}

/// 拖动 / 缩放线程只许一个；弹簧动画期间也占着（期间的 `Moved` 不再起新线程）。
static WATCH: AtomicBool = AtomicBool::new(false);
static BUSY: AtomicBool = AtomicBool::new(false);

fn left_down() -> bool {
    use objc2::{class, msg_send};
    // SAFETY: 类方法，无参数，返回整数（同 `mouseLocation`，任意线程可调）。
    let b: usize = unsafe { msg_send![class!(NSEvent), pressedMouseButtons] };
    b & 1 == 1
}

/// 光标（Cocoa 坐标：左下原点，y 向上）。只用差值，不换算。
fn mouse() -> (f64, f64) {
    use objc2::{class, msg_send};
    // SAFETY: 同上。
    let p: objc2_foundation::NSPoint = unsafe { msg_send![class!(NSEvent), mouseLocation] };
    (p.x, p.y)
}

fn reduce_motion() -> bool {
    use objc2::{class, msg_send};
    use objc2::runtime::AnyObject;
    // SAFETY: 只读属性。
    unsafe {
        let ws: *mut AnyObject = msg_send![class!(NSWorkspace), sharedWorkspace];
        !ws.is_null() && { let r: bool = msg_send![ws, accessibilityDisplayShouldReduceMotion]; r }
    }
}

/// 主窗口外框与它所在屏的工作区（都是逻辑 pt，桌面左上原点）。
fn frame_and_area(app: &AppHandle) -> Option<(Rect, Rect)> {
    let w = app.get_webview_window("main")?;
    let sf = w.scale_factor().ok()?;
    let p = w.outer_position().ok()?.to_logical::<f64>(sf);
    let s = w.outer_size().ok()?.to_logical::<f64>(sf);
    let m = w.current_monitor().ok()??;
    let ms = m.scale_factor();
    let wa = m.work_area();
    let area = Rect { x: wa.position.x as f64 / ms, y: wa.position.y as f64 / ms,
                      w: wa.size.width as f64 / ms, h: wa.size.height as f64 / ms };
    Some((Rect { x: p.x, y: p.y, w: s.width, h: s.height }, area))
}

/// `WindowEvent::Moved`（主窗口）。左键按着 = 用户在拖 ⇒ 等松手再看要不要吸。
pub fn on_moved(app: &AppHandle) {
    if BUSY.load(Ordering::SeqCst) || !left_down() || WATCH.swap(true, Ordering::SeqCst) { return; }
    let app = app.clone();
    std::thread::spawn(move || {
        let start = frame_and_area(&app).map(|f| f.0);
        while left_down() { std::thread::sleep(Duration::from_millis(16)); }
        std::thread::sleep(Duration::from_millis(40));
        WATCH.store(false, Ordering::SeqCst);
        let (Some(s0), Some((win, area))) = (start, frame_and_area(&app)) else { return };
        if (win.w - s0.w).abs() > 1.0 || (win.h - s0.h).abs() > 1.0 { return; }
        let Some(to) = snap_pos(win, area) else { return };
        if BUSY.swap(true, Ordering::SeqCst) { return; }
        let Some(w) = app.get_webview_window("main") else { BUSY.store(false, Ordering::SeqCst); return };
        let path = if reduce_motion() { vec![to] } else { spring_path((win.x, win.y), to) };
        for p in path {
            let _ = w.set_position(LogicalPosition::new(p.0, p.1));
            std::thread::sleep(Duration::from_millis(16));
        }
        BUSY.store(false, Ordering::SeqCst);
    });
}

/// 抓手按下（网页 `grip_resize_start`）：跟着光标改尺寸直到松手。左上角不动（`setContentSize` 保左上）。
pub fn grip_start(app: &AppHandle) {
    if BUSY.swap(true, Ordering::SeqCst) { return; }
    let app = app.clone();
    std::thread::spawn(move || {
        let done = |app: &AppHandle| {
            let _ = app.emit_to("main", "grip-size", serde_json::Value::Null);
            BUSY.store(false, Ordering::SeqCst);
        };
        let (Some((win, area)), Some(w)) = (frame_and_area(&app), app.get_webview_window("main")) else { done(&app); return };
        let (max_w, max_h) = ((area.x + area.w - win.x).max(MIN_W), (area.y + area.h - win.y).max(MIN_H));
        let (cx0, cy0) = mouse();
        let mut last: Option<(f64, f64)> = None;
        while left_down() {
            let (cx, cy) = mouse();
            let (nw, nh, label) = snap_size((win.w + cx - cx0).clamp(MIN_W, max_w).round(),
                                            (win.h + cy0 - cy).clamp(MIN_H, max_h).round());
            if last != Some((nw, nh)) {
                last = Some((nw, nh));
                let _ = w.set_size(LogicalSize::new(nw, nh));
                let _ = app.emit_to("main", "grip-size", serde_json::json!({
                    "w": nw, "h": nh, "label": label, "zoom": crate::predicted_zoom(nw, nh) }));
            }
            std::thread::sleep(Duration::from_millis(8));
        }
        done(&app);
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    const AREA: Rect = Rect { x: 0.0, y: 25.0, w: 1512.0, h: 957.0 };

    #[test]
    fn near_the_left_edge_it_snaps_to_the_gap() {
        assert_eq!(snap_pos(Rect { x: 15.0, y: 200.0, w: 960.0, h: 620.0 }, AREA), Some((8.0, 200.0)));
    }

    #[test]
    fn near_the_right_and_bottom_it_snaps_to_the_corner() {
        let w = Rect { x: 1512.0 - 8.0 - 960.0 + 10.0, y: 25.0 + 957.0 - 8.0 - 620.0 - 12.0, w: 960.0, h: 620.0 };
        assert_eq!(snap_pos(w, AREA), Some((1512.0 - 8.0 - 960.0, 25.0 + 957.0 - 8.0 - 620.0)));
    }

    #[test]
    fn the_centre_line_snaps_and_far_away_does_not() {
        assert_eq!(snap_pos(Rect { x: 286.0, y: 300.0, w: 960.0, h: 620.0 }, AREA), Some((276.0, 300.0)));
        assert_eq!(snap_pos(Rect { x: 120.0, y: 200.0, w: 960.0, h: 620.0 }, AREA), None, "18 pt 外不吸");
    }

    #[test]
    fn already_on_the_edge_is_not_a_move() {
        assert_eq!(snap_pos(Rect { x: 8.0, y: 33.0, w: 960.0, h: 620.0 }, AREA), None);
    }

    #[test]
    fn sizes_snap_to_presets_only_when_close() {
        assert_eq!(snap_size(1197.0, 803.0), (1200.0, 800.0, Some("常用")));
        assert_eq!(snap_size(1180.0, 800.0), (1180.0, 800.0, None));
        assert_eq!(snap_size(870.0, 566.0).2, Some("最小"));
    }

    #[test]
    fn the_spring_ends_exactly_on_target_and_settles_fast() {
        let p = spring_path((15.0, 200.0), (8.0, 200.0));
        assert_eq!(*p.last().unwrap(), (8.0, 200.0));
        assert!(p.len() <= 40, "弹簧要在 ~0.6 s 内停下，实际 {} 帧", p.len());
        assert!(p.iter().all(|q| q.0 > 0.0), "回弹不许冲出屏幕左缘");
    }
}
