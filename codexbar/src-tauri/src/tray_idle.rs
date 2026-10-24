//! 空闲托盘（AICoop 交接包 2026-10-21 · `11_idle/P11_Spec` §3–§4、`P11_Gray`、`P11_Final`）。
//!
//! 空闲时托盘画 2–3 家官方 logo，**用掉的额度从上往下变成灰色剪影**（B 方案，水位）；剩余 < 10% 右上角红点。
//! 选谁上托盘由前端 `idleTray.ts::pickIdleSlots` 算好、经 `set_idle_tray` 发过来；这里只管「画」与「动」。
//!
//! 几何（画板 2× 坐标 ÷ 2）：胶囊高 18 · 圆角 9（同 Page 1）· 左内边距 4 · 右 7 · logo 14 · 间距 5。
//! 水位：画板的 `CUT` 表（6 家 × 剩余 0,5,…,100 共 21 档，单位 = 从 logo 顶往下裁掉的 %），两档之间线性插值。
//!   表是**按 logo 实际笔画面积**算好的（Claude / DeepSeek 这类扁 logo 上下有大片留白，按方框切会让 15% / 5% / 0% 看起来一样）。
//!   读不到额度 ⇒ 裁 100%（整只灰色剪影）。
//! 动画（只跟着事件走，平时一帧都不画）：
//!   · 用掉一些：水位 700 ms 临界阻尼推进，只动这一家；
//!   · 额度重置（剩余明显回升）：原色从下往上涨满 + 0.6 s 后一次白光 0.8 s；
//!   · 换位：沿弹簧互换（550 ms 临界阻尼）；进 / 出：缩放 0.6↔1 + 透明（200 ms）；
//!   · 红点：350 ms 弹出，允许 1 次轻微过冲；
//!   · 鼠标靠近：logo 后亮平台色光晕（50%、直径 22 pt），200 ms 淡入淡出；
//!   · 打招呼：从左到右依次上跳 2.5 pt，相邻错开 90 ms，共 ~0.9 s。
//!   「减弱动态效果」开时：水位直接到位、不闪光、不发光、不打招呼，换位只交叉淡入。
use crate::tray_pill::{Fade, Spring};

/// 六家 logo 的槽位（顺序同画板 `NM`）：Codex · Claude · Gemini · Grok · Kimi · DeepSeek。
pub const KEYS: [&str; 6] = ["codex", "claude", "agy", "grok", "kimi", "deepseek"];
/// ★ 用户 2026-10-22「空闲时状态栏背景也去掉，然后 AI SVG 放大」：14 → 18（与在跑胶囊的 logo 同大），底色块去掉。
pub const LOGO: f64 = 18.0;
/// ★ 用户 2026-10-22「空闲时多个 AI svg 可以堆叠靠在一起，这样就不会那么大了」：相邻 logo 互相压 3 pt（头像组式），
///   步进 14 + 5 = 19 → 14 − 3 = 11；3 家宽 63 → 47 pt。第一版压 5 pt + 底色圆半径 8.5，离线样张里右边两只被盖掉一半、Claude 只剩一角，退到 3 / 8。左边的压在右边的上面（右上角的红点不被盖住），
///   每只 logo 后垫一块底色圆把下面那只切开（`tray_pill.rs::idle_layer`）。原来的间距 5 见画板几何。
///   logo 放大到 18 后压 4 pt（同比例），步进 14；3 家宽 1 + 18 + 2×14 + 3 = 50 pt。没有底色块之后改成**镂空**：
///   画左边那只之前先把它身后一圈（`BACKING_R`）擦成透明，任何菜单栏底色下都切得开。
pub const OVERLAP: f64 = 4.0;
pub const STEP: f64 = LOGO - OVERLAP;
/// 每只 logo 身后擦掉的圆的半径（比 logo 半宽多 1，切出一圈透明缝）。
pub const BACKING_R: f64 = LOGO / 2.0 + 1.0;
/// 没有底色块，内边距只留红点外伸（右上 +2 pt）与 1 pt 余量。
pub const PAD_L: f64 = 1.0;
pub const PAD_R: f64 = 3.0;
/// 灰色剪影的不透明度（画板 `ghostOp: .3`）。
pub const GHOST_ALPHA: f64 = 0.3;
/// 光晕：平台色 50%（P11_Spec §4「鼠标靠近」）。稿里是 14 pt logo 配 22 pt 光晕；logo 放大到 18 后按同比例放大到 ≈28 ——
/// 仍用 22 的话光晕只比 logo 多出 2 pt、那一圈不透明度 < 9%，等于看不见（2026-10-24）。上下超出 22 pt 高的部分被托盘裁掉。
pub const GLOW_D: f64 = 22.0 * LOGO / 14.0;
/// 红点 #FF8A73，直径 4.5 pt、描边 1 pt #2C333F、右上角各外伸 2 pt（画板 9px / 2px / -4px，2×）。
pub const DOT_D: f64 = 4.5;
pub const DOT_RGB: (u8, u8, u8) = (0xFF, 0x8A, 0x73);
/// 光晕色（画板 `GL`）。
pub const GLOW_RGB: [(u8, u8, u8); 6] = [(45, 212, 191), (224, 120, 79), (77, 159, 255), (139, 124, 246), (236, 106, 174), (107, 124, 255)];

/// 画板 `CUT`：剩余 0, 5, …, 100 时从顶往下裁掉的百分比。
const CUT: [[f64; 21]; 6] = [
    [100.0, 89.5, 84.0, 79.0, 74.5, 70.5, 66.5, 60.5, 56.5, 52.5, 49.0, 45.0, 41.0, 37.0, 32.5, 29.0, 25.0, 20.5, 15.5, 10.0, 0.0],
    [100.0, 74.5, 69.0, 66.0, 63.5, 60.5, 57.5, 55.5, 53.0, 51.0, 49.0, 46.5, 44.0, 41.0, 38.0, 35.5, 32.5, 29.5, 26.5, 23.5, 20.5],
    [100.0, 79.0, 72.0, 67.0, 63.0, 60.0, 57.5, 55.0, 53.0, 51.5, 49.5, 48.0, 46.5, 44.5, 42.0, 39.5, 36.5, 32.5, 27.5, 20.5, 4.0],
    [100.0, 84.0, 81.5, 79.0, 76.0, 71.5, 67.0, 62.0, 56.5, 52.0, 47.5, 43.0, 39.5, 36.0, 32.0, 28.0, 24.0, 21.5, 19.5, 16.5, 2.0],
    [100.0, 86.0, 80.0, 74.5, 69.0, 63.5, 58.0, 54.0, 51.5, 49.0, 46.5, 44.0, 41.0, 36.0, 30.5, 25.5, 21.0, 17.5, 14.0, 10.5, 4.0],
    [100.0, 79.5, 76.5, 72.5, 68.0, 63.0, 58.5, 54.5, 50.0, 46.5, 43.0, 40.0, 37.5, 35.0, 32.5, 30.5, 28.5, 26.0, 23.5, 20.5, 12.5],
];

/// 剩余（0–100；None = 读不到）→ 从顶往下裁掉的百分比。画板 `cutOf` 原样。
pub fn cut_of(logo: usize, remaining: Option<f64>) -> f64 {
    let Some(p) = remaining.filter(|p| p.is_finite()) else { return 100.0 };
    let f = p.clamp(0.0, 100.0) / 5.0;
    let a = f.floor() as usize;
    let b = (a + 1).min(20);
    let r = f - a as f64;
    let row = &CUT[logo.min(5)];
    row[a.min(20)] + (row[b] - row[a.min(20)]) * r
}

/// 一家的输入（前端算好）。
#[derive(Clone, Debug, PartialEq)]
pub struct IdleIn { pub logo: usize, pub remaining: Option<f64>, pub red: bool }

pub fn logo_of(key: &str) -> Option<usize> { KEYS.iter().position(|k| *k == key) }

/// 解 `set_idle_tray` 的 payload：`[{key, remaining, red}]`。不认识的 key 丢掉；重复的只留第一个。
pub fn parse_slots(v: &serde_json::Value) -> Vec<IdleIn> {
    let mut out: Vec<IdleIn> = Vec::new();
    for s in v.as_array().into_iter().flatten() {
        let Some(logo) = s.get("key").and_then(|k| k.as_str()).and_then(logo_of) else { continue };
        if out.iter().any(|o| o.logo == logo) { continue; }
        let remaining = s.get("remaining").and_then(|r| r.as_f64()).filter(|r| r.is_finite());
        let red = s.get("red").and_then(|r| r.as_bool()).unwrap_or(false);
        out.push(IdleIn { logo, remaining, red });
    }
    out.truncate(3);
    out
}

/// 胶囊宽：左 4 + 14 + (n−1)·9 + 右 7（堆叠）；一家都没有 ⇒ 0（调用方退回模板图标）。
pub fn width_for(n: usize) -> f64 {
    if n == 0 { 0.0 } else { PAD_L + LOGO + (n - 1) as f64 * STEP + PAD_R }
}

/// 第 i 个 logo 的左沿（胶囊内坐标）。
pub fn x_for(i: usize) -> f64 { PAD_L + i as f64 * STEP }

/// 剩余回升超过这么多 = 「额度重置」（播从下往上涨满 + 白光），而不是普通的读数抖动。
pub const RESET_JUMP: f64 = 20.0;
const FLASH_DELAY: f64 = 0.6;
const FLASH_DUR: f64 = 0.8;
const HELLO_STAGGER: f64 = 0.09;
const HELLO_DUR: f64 = 0.7;
const HELLO_LIFT: f64 = 2.5;

fn cut_spring(v: f64) -> Spring { Spring::new(v, 0.66, 1.0, 0.05) }   // ≈700 ms 落定，无回弹
fn x_spring(v: f64) -> Spring { Spring::new(v, 0.38, 1.0, 0.05) }     // ≈550 ms（同 Page 1）
fn s_spring(v: f64) -> Spring { Spring::new(v, 0.38, 1.0, 0.002) }
fn dot_spring(v: f64) -> Spring { Spring::new(v, 0.35, 0.7, 0.002) }  // 350 ms，1 次轻微过冲

#[derive(Clone, Debug)]
struct Slot {
    present: bool,
    leaving: bool,
    x: Spring,
    scale: Spring,
    alpha: Fade,
    cut: Spring,
    remaining: Option<f64>,
    dot: Spring,
    flash_at: Option<f64>,
}

impl Slot {
    fn new() -> Slot {
        Slot { present: false, leaving: false, x: x_spring(0.0), scale: s_spring(1.0), alpha: Fade::new(0.0),
               cut: cut_spring(100.0), remaining: None, dot: dot_spring(0.0), flash_at: None }
    }
}

/// 一帧里的一个 logo（胶囊内坐标）。
#[derive(Clone, Debug, PartialEq)]
pub struct IdleDraw {
    pub logo: usize,
    pub x: f64,
    /// 上跳（打招呼）：向上为正，pt
    pub lift: f64,
    pub alpha: f64,
    pub scale: f64,
    /// 从顶往下裁掉的百分比（0 = 全原色，100 = 全灰）
    pub cut: f64,
    /// 红点缩放（0 = 没有）
    pub dot: f64,
    /// 白光强度 0–1
    pub flash: f64,
    /// 光晕强度 0–1
    pub glow: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct IdleFrame { pub width: f64, pub logos: Vec<IdleDraw> }

#[derive(Clone, Debug)]
pub struct IdleAnim {
    slots: Vec<Slot>,
    width: Spring,
    glow: Fade,
    hello_at: Option<f64>,
    pub reduce: bool,
    last_now: f64,
    /// 至少收到过一次目标（之前一张图都不画，调用方继续用模板图标）
    pub armed: bool,
    event_busy: bool,
}

impl Default for IdleAnim { fn default() -> Self { IdleAnim::new() } }

impl IdleAnim {
    pub fn new() -> IdleAnim {
        IdleAnim { slots: (0..6).map(|_| Slot::new()).collect(), width: x_spring(0.0), glow: Fade::new(0.0),
                   hello_at: None, reduce: false, last_now: 0.0, armed: false, event_busy: false }
    }

    /// 当前目标宽（不含动画中间值）。
    pub fn target_width(&self) -> f64 { self.width.target }

    pub fn retarget(&mut self, want: &[IdleIn], now: f64) {
        // 空列表不算「收到过目标」：前端数据还没到时发的那份，若算数，第一份真目标就会走进场动画而不是原位画出
        if want.is_empty() && !self.armed { return; }
        let r = self.reduce;
        let first = !self.armed;
        self.armed = true;
        let w = width_for(want.len());
        self.width.target = w;
        if r || first { self.width.snap(w); }
        for logo in 0..6 {
            let s = &mut self.slots[logo];
            match want.iter().position(|x| x.logo == logo) {
                Some(i) => {
                    let inp = &want[i];
                    let x = x_for(i);
                    let cut = cut_of(logo, inp.remaining);
                    if !s.present || s.leaving {
                        let fresh = !s.present;
                        if fresh {
                            // 新进场：直接出现在目标坐标、目标水位（只做缩放 + 淡入），之后的移动才走弹簧
                            s.x.snap(x);
                            s.cut.snap(cut);
                            // 首帧原位画出；之后进场（插队）的红点照样 350 ms 弹出
                            if first || r { s.dot.snap(if inp.red { 1.0 } else { 0.0 }); }
                            else { s.dot.snap(0.0); s.dot.target = if inp.red { 1.0 } else { 0.0 }; }
                            if r || first { s.scale.snap(1.0); } else { s.scale.snap(0.6); s.scale.target = 1.0; }
                            s.alpha = if first { Fade::new(1.0) } else { Fade::new(0.0) };
                        } else {
                            // 离场途中又被选回来：位置、水位、红点都按新目标（不只是停下离场）
                            s.x.target = x;
                            if r { s.x.snap(x); }
                            s.scale.target = 1.0;
                            s.cut.target = cut;
                            if r { s.cut.snap(cut); }
                            s.dot.target = if inp.red { 1.0 } else { 0.0 };
                            if r { s.dot.snap(s.dot.target); }
                        }
                        // 减弱动态效果：进场照样淡入（只去掉缩放与位移），只有首帧直接出现
                        s.alpha.go(1.0, now, first);
                        s.present = true;
                        s.leaving = false;
                    } else {
                        // 减弱动态效果：换位只交叉淡入（瞬移到新位置再淡入，不滑过去）
                        if r && (s.x.pos - x).abs() > 0.5 { s.alpha = Fade::new(0.0); s.alpha.go(1.0, now, false); }
                        s.x.target = x;
                        if r { s.x.snap(x); }
                        // 额度重置：剩余明显回升 ⇒ 原色从下往上涨满，0.6 s 后白光
                        let reset = matches!((s.remaining, inp.remaining), (Some(a), Some(b)) if b - a >= RESET_JUMP);
                        s.cut.target = cut;
                        if r { s.cut.snap(cut); }
                        if reset && !r { s.flash_at = Some(now + FLASH_DELAY); }
                        s.dot.target = if inp.red { 1.0 } else { 0.0 };
                        if r { s.dot.snap(s.dot.target); }
                    }
                    s.remaining = inp.remaining;
                }
                None if s.present && !s.leaving => {
                    s.leaving = true;
                    s.scale.target = 0.6;
                    if r { s.scale.snap(1.0); }
                    s.alpha.go(0.0, now, false);
                }
                None => {}
            }
        }
        self.last_now = now;
    }

    /// 鼠标进 / 出托盘周围约 35 pt。
    pub fn set_near(&mut self, near: bool, now: f64) {
        if self.reduce { self.glow.go(0.0, now, true); return; }
        self.glow.go(if near { 1.0 } else { 0.0 }, now, false);
    }

    /// 打招呼（调用方负责「每天最多一次」等判据）。
    pub fn hello(&mut self, now: f64) { if !self.reduce { self.hello_at = Some(now); } }

    pub fn step(&mut self, now: f64) -> bool {
        let dt = (now - self.last_now).clamp(0.0, 0.1);
        self.last_now = now;
        self.width.step(dt);
        // `event` = 事件动画（变灰 / 插队 / 重置 / 换位 / 打招呼）；光晕的淡入淡出不算 ——
        // 打招呼恰好发生在鼠标靠近、光晕正在亮起的那一刻
        let mut event = !self.width.settled();
        if let Some(t0) = self.hello_at {
            let n = self.slots.iter().filter(|s| s.present).count() as f64;
            if now - t0 > HELLO_DUR + HELLO_STAGGER * n { self.hello_at = None; } else { event = true; }
        }
        for s in self.slots.iter_mut() {
            if !s.present { continue; }
            for sp in [&mut s.x, &mut s.scale, &mut s.cut, &mut s.dot] {
                sp.step(dt);
                event |= !sp.settled();
            }
            event |= !s.alpha.done(now);
            if let Some(t) = s.flash_at {
                if now - t > FLASH_DUR { s.flash_at = None; } else { event = true; }
            }
            if s.leaving && s.alpha.done(now) && s.alpha.value(now) <= 1e-6 { *s = Slot::new(); }
        }
        self.event_busy = event;
        event || !self.glow.done(now)
    }

    /// 托盘正在播事件动画（变灰 / 插队 / 重置 / 换位 / 打招呼）—— 这时不打招呼（P11 §5）。
    pub fn event_busy(&self) -> bool { self.event_busy }

    pub fn frame(&self, now: f64) -> IdleFrame {
        let glow = self.glow.value(now);
        let mut order: Vec<(usize, &Slot)> = self.slots.iter().enumerate().filter(|(_, s)| s.present).collect();
        order.sort_by(|a, b| a.1.x.pos.partial_cmp(&b.1.x.pos).unwrap_or(std::cmp::Ordering::Equal));
        let logos = order.iter().enumerate().map(|(k, (logo, s))| {
            let lift = self.hello_at.map_or(0.0, |t0| {
                let u = (now - t0 - k as f64 * HELLO_STAGGER) / HELLO_DUR;
                if (0.0..=1.0).contains(&u) { HELLO_LIFT * (std::f64::consts::PI * u).sin() } else { 0.0 }
            });
            let flash = s.flash_at.map_or(0.0, |t| {
                let u = (now - t) / FLASH_DUR;
                if (0.0..=1.0).contains(&u) { (std::f64::consts::PI * u).sin() } else { 0.0 }
            });
            IdleDraw { logo: *logo, x: s.x.pos, lift, alpha: s.alpha.value(now), scale: s.scale.pos,
                       cut: s.cut.pos.clamp(0.0, 100.0), dot: s.dot.pos.max(0.0), flash, glow }
        }).collect();
        IdleFrame { width: self.width.pos.max(0.0), logos }
    }
}

/// 打招呼多久一次（P11 §5，设置页「打招呼」）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HelloMode { Off, Daily, AfterIdle }

impl HelloMode {
    pub fn parse(s: &str) -> HelloMode {
        match s { "off" => HelloMode::Off, "idle1h" => HelloMode::AfterIdle, _ => HelloMode::Daily }
    }
}

/// 距离上一次 AI 活动至少这么久才打招呼。
pub const HELLO_IDLE_SECS: f64 = 3600.0;

/// 这一次「鼠标靠近」要不要打招呼。只管频率；在跑 / 悬停面板开着 / 正在播事件动画 / 减弱动态效果由调用方先挡掉。
/// · 每天一次：今天还没打过，且距上次 AI 活动 > 60 分钟；
/// · 每次空闲 1 小时后：距上次 AI 活动 > 60 分钟，且这段空闲里还没打过。
/// `last_active` = 上次 AI 活动（epoch 秒，没观测到 = None ⇒ 当作很久以前）；`last_hello` = (那天的日期键, epoch 秒)。
pub fn should_hello(mode: HelloMode, today: i64, now: f64, last_active: Option<f64>, last_hello: Option<(i64, f64)>) -> bool {
    let idle_long = last_active.map_or(true, |a| now - a >= HELLO_IDLE_SECS);
    match mode {
        HelloMode::Off => false,
        HelloMode::Daily => idle_long && last_hello.map_or(true, |(d, _)| d != today),
        HelloMode::AfterIdle => idle_long && last_hello.map_or(true, |(_, at)| last_active.map_or(false, |a| at < a)),
    }
}

/// 光标离托盘矩形多远（pt；在矩形里 = 0）。
pub fn dist_to_rect(x: f64, y: f64, r: (f64, f64, f64, f64)) -> f64 {
    let dx = (r.0 - x).max(0.0).max(x - (r.0 + r.2));
    let dy = (r.1 - y).max(0.0).max(y - (r.1 + r.3));
    (dx * dx + dy * dy).sqrt()
}

/// 「靠近」= 进入托盘周围约 35 pt（P11 §4）。
pub const NEAR_PT: f64 = 35.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hello_daily_once_and_only_after_an_hour_idle() {
        let d = HelloMode::Daily;
        assert!(should_hello(d, 10, 10_000.0, None, None), "第一次靠近、从没见过活动 ⇒ 打");
        assert!(!should_hello(d, 10, 10_000.0, Some(9_000.0), None), "★ 上次活动不到 1 小时 ⇒ 不打");
        assert!(should_hello(d, 10, 10_000.0, Some(6_000.0), None));
        assert!(!should_hello(d, 10, 20_000.0, Some(6_000.0), Some((10, 10_000.0))), "★ 今天打过了 ⇒ 不再打");
        assert!(should_hello(d, 11, 100_000.0, Some(6_000.0), Some((10, 10_000.0))), "第二天再打");
    }

    #[test]
    fn hello_after_idle_once_per_idle_stretch() {
        let m = HelloMode::AfterIdle;
        assert!(should_hello(m, 10, 10_000.0, Some(5_000.0), Some((10, 4_000.0))), "这段空闲还没打过");
        assert!(!should_hello(m, 10, 10_500.0, Some(5_000.0), Some((10, 10_000.0))), "★ 这段空闲里打过了");
        assert!(!should_hello(m, 10, 10_000.0, Some(9_000.0), Some((10, 4_000.0))), "空闲不到 1 小时");
        assert!(!should_hello(HelloMode::Off, 10, 1e9, None, None));
        assert_eq!(HelloMode::parse("idle1h"), HelloMode::AfterIdle);
        assert_eq!(HelloMode::parse("off"), HelloMode::Off);
        assert_eq!(HelloMode::parse("daily"), HelloMode::Daily);
    }

    #[test]
    fn near_is_distance_to_the_tray_rect() {
        let r = (100.0, 0.0, 60.0, 24.0);
        assert_eq!(dist_to_rect(120.0, 10.0, r), 0.0, "在托盘里");
        assert_eq!(dist_to_rect(100.0, 59.0, r), 35.0, "正下方 35 pt");
        assert!(dist_to_rect(60.0, 30.0, r) > NEAR_PT, "左下斜角 √(40²+6²) 在范围外");
    }

    fn slot(logo: usize, rem: Option<f64>, red: bool) -> IdleIn { IdleIn { logo, remaining: rem, red } }
    fn settle(a: &mut IdleAnim, mut t: f64) -> f64 { for _ in 0..400 { t += 0.016; if !a.step(t) { break; } } t }

    #[test]
    fn cut_table_matches_the_board() {
        // 剩 100% ⇒ Codex 全原色；Claude 上方本来就是留白（20.5%）
        assert_eq!(cut_of(0, Some(100.0)), 0.0);
        assert_eq!(cut_of(1, Some(100.0)), 20.5);
        // 剩 0 ⇒ 全灰；读不到 ⇒ 全灰（整只灰色剪影），绝不当满
        assert_eq!(cut_of(2, Some(0.0)), 100.0);
        assert_eq!(cut_of(3, None), 100.0);
        // 两档之间线性插值：Codex 67% = 65 档 37 与 70 档 32.5 之间 0.4
        assert!((cut_of(0, Some(67.0)) - (37.0 + (32.5 - 37.0) * 0.4)).abs() < 1e-9);
        // 单调：剩得越多，裁掉的越少
        for logo in 0..6 {
            let mut prev = f64::INFINITY;
            for p in 0..=100 { let c = cut_of(logo, Some(p as f64)); assert!(c <= prev + 1e-9, "logo {} p {}", logo, p); prev = c; }
        }
    }

    /// 悬停面板飞 logo 按前端 `PILL_LOGO` 画图；它与这里的 `LOGO` 不一致 ⇒ 起飞那一帧 logo 跳大小。
    #[test]
    fn the_frontend_flies_logos_at_the_tray_size() {
        let ts = include_str!("../../src/idleGridLayout.ts");
        assert!(ts.contains(&format!("export const PILL_LOGO = {};", LOGO as i64)), "idleGridLayout.ts PILL_LOGO ≠ tray_idle::LOGO");
    }

    #[test]
    fn width_matches_the_board_geometry() {
        assert_eq!(width_for(0), 0.0);
        // 堆叠 + 放大 + 去底色（2026-10-22）：3 家 1 + 18 + 2·14 + 3 = 50 pt（14 pt 带底色时 47、不堆叠时 63）
        assert_eq!(width_for(3), 50.0);
        assert_eq!(x_for(2), 1.0 + 2.0 * 14.0);
        assert!(x_for(1) < x_for(0) + LOGO, "相邻两只确实压在一起");
        assert!(BACKING_R > LOGO / 2.0 && BACKING_R < LOGO / 2.0 + OVERLAP, "底色圆切得开、又不会把整只吃掉");
    }

    #[test]
    fn parse_drops_unknown_and_duplicates_and_keeps_three() {
        let v = serde_json::json!([{"key":"codex","remaining":67,"red":false},{"key":"nope"},{"key":"codex"},
                                   {"key":"claude","remaining":null},{"key":"deepseek","remaining":6,"red":true},{"key":"kimi"}]);
        let s = parse_slots(&v);
        assert_eq!(s, vec![slot(0, Some(67.0), false), slot(1, None, false), slot(5, Some(6.0), true)]);
    }

    #[test]
    fn first_target_is_drawn_in_place_without_entering_animation() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(67.0), false), slot(1, Some(40.0), false)], 1.0);
        assert!(!a.step(1.016), "第一张图直接到位，不播进场");
        let f = a.frame(1.016);
        assert_eq!(f.width, width_for(2));
        assert_eq!(f.logos.iter().map(|l| l.logo).collect::<Vec<_>>(), vec![0, 1]);
        assert!(f.logos.iter().all(|l| (l.alpha - 1.0).abs() < 1e-9 && (l.scale - 1.0).abs() < 1e-9));
    }

    #[test]
    fn using_quota_moves_only_that_logo_and_settles() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(67.0), false), slot(1, Some(40.0), false)], 1.0);
        a.step(1.016);
        a.retarget(&[slot(0, Some(40.0), false), slot(1, Some(40.0), false)], 2.0);
        a.step(2.1);
        let mid = a.frame(2.1);
        let c = mid.logos.iter().find(|l| l.logo == 0).unwrap().cut;
        assert!(c > cut_of(0, Some(67.0)) && c < cut_of(0, Some(40.0)), "水位在推进中：{}", c);
        let claude = mid.logos.iter().find(|l| l.logo == 1).unwrap().cut;
        assert!((claude - cut_of(1, Some(40.0))).abs() < 1e-9, "另一家不动");
        let t = settle(&mut a, 2.1);
        assert!(t - 2.0 < 1.2, "≈700 ms 内落定，实测 {:.2}s", t - 2.0);
        let c = a.frame(t).logos[0].cut;
        assert!((c - cut_of(0, Some(40.0))).abs() < 0.06);
        assert!(a.frame(t).logos[0].flash == 0.0, "用掉一些不闪光");
    }

    #[test]
    fn critical_damping_never_overshoots_the_water_line() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(90.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(0, Some(10.0), false)], 1.0);
        let target = cut_of(0, Some(10.0));
        let mut t = 1.0;
        for _ in 0..200 { t += 0.016; a.step(t); assert!(a.frame(t).logos[0].cut <= target + 1e-6); }
    }

    #[test]
    fn a_reset_flashes_once() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(5.0), true)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(0, Some(100.0), false)], 1.0);
        let peak = (0..120).map(|i| { let t = 1.0 + i as f64 * 0.016; a.step(t); a.frame(t).logos[0].flash })
            .fold(0.0f64, f64::max);
        assert!(peak > 0.9, "重置播白光");
    }

    #[test]
    fn swapping_order_moves_by_spring_not_fade() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(50.0), false), slot(1, Some(50.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(1, Some(50.0), false), slot(0, Some(50.0), false)], 1.0);
        a.step(1.1);
        let f = a.frame(1.1);
        assert!(f.logos.iter().all(|l| (l.alpha - 1.0).abs() < 1e-9), "换位不淡出");
        let t = settle(&mut a, 1.1);
        let f = a.frame(t);
        assert_eq!(f.logos.iter().map(|l| l.logo).collect::<Vec<_>>(), vec![1, 0]);
    }

    #[test]
    fn reduce_motion_snaps_everything() {
        let mut a = IdleAnim::new();
        a.reduce = true;
        a.retarget(&[slot(0, Some(90.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(0, Some(10.0), true)], 1.0);
        a.hello(1.0);
        a.set_near(true, 1.0);
        a.step(1.016);
        let f = a.frame(1.016);
        assert!((f.logos[0].cut - cut_of(0, Some(10.0))).abs() < 1e-9);
        assert_eq!((f.logos[0].lift, f.logos[0].glow, f.logos[0].flash), (0.0, 0.0, 0.0));
    }

    #[test]
    fn hello_lifts_left_to_right() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(50.0), false), slot(1, Some(50.0), false), slot(2, Some(50.0), false)], 0.0);
        a.step(0.016);
        a.hello(1.0);
        a.step(1.05);
        let f = a.frame(1.05);
        assert!(f.logos[0].lift > 0.0 && f.logos[1].lift == 0.0, "第二个还没开始跳");
        assert!(f.logos.iter().all(|l| l.lift <= HELLO_LIFT + 1e-9));
    }

    #[test]
    fn an_empty_target_does_not_count_as_the_first_one() {
        let mut a = IdleAnim::new();
        a.retarget(&[], 0.0);
        assert!(!a.armed, "★ 数据还没到时发的空列表不算「收到过目标」");
        a.retarget(&[slot(0, Some(67.0), false)], 1.0);
        assert!(!a.step(1.016), "★ 第一份真目标仍然原位画出，不播进场");
    }

    #[test]
    fn coming_back_while_leaving_takes_the_new_water_line_and_dot() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(80.0), false), slot(5, Some(80.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(0, Some(80.0), false)], 1.0);
        a.step(1.05);
        a.retarget(&[slot(0, Some(80.0), false), slot(5, Some(5.0), true)], 1.1);
        let t = settle(&mut a, 1.1);
        let d = a.frame(t).logos.into_iter().find(|l| l.logo == 5).unwrap();
        assert!((d.cut - cut_of(5, Some(5.0))).abs() < 0.06, "★ 离场途中被选回：水位要按新的剩余，实测 {}", d.cut);
        assert!((d.dot - 1.0).abs() < 0.01, "★ 红点也要出来");
    }

    #[test]
    fn an_inserted_red_dot_pops_instead_of_appearing() {
        let mut a = IdleAnim::new();
        a.retarget(&[slot(0, Some(80.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(0, Some(80.0), false), slot(5, Some(5.0), true)], 1.0);
        a.step(1.05);
        let d = a.frame(1.05).logos.into_iter().find(|l| l.logo == 5).unwrap().dot;
        assert!(d > 0.0 && d < 0.95, "★ 插队的红点 350 ms 弹出，不是一出场就满，实测 {}", d);
    }

    #[test]
    fn reduce_motion_swaps_by_cross_fade() {
        let mut a = IdleAnim::new();
        a.reduce = true;
        a.retarget(&[slot(0, Some(50.0), false), slot(1, Some(50.0), false)], 0.0);
        a.step(0.016);
        a.retarget(&[slot(1, Some(50.0), false), slot(0, Some(50.0), false)], 1.0);
        a.step(1.05);
        let f = a.frame(1.05);
        assert_eq!(f.logos.iter().map(|l| l.logo).collect::<Vec<_>>(), vec![1, 0], "减弱动态效果：直接到新位置");
        assert!(f.logos.iter().all(|l| l.alpha < 0.9), "★ 换位交叉淡入（P11 §3），不是瞬移");
    }
}
