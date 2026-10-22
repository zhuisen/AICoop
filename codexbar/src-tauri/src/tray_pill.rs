//! 托盘胶囊（交接包 2026-10-19 page 1 · 定稿 D）：有 AI 在跑时，菜单栏标题换成一颗胶囊，
//! 每个在跑的 AI 一段（官方 logo + 该 AI 合计 t/s）；没有 AI 在跑时回到 v1.11.0 的标题。
//!
//! 三层，刻意分开：
//!   1. `layout`  —— **纯函数**：每家 {在跑, t/s, 会话数, 停下时刻} + 菜单栏明暗 → 各段坐标 / 宽度 / 颜色。
//!      数值照抄 `page1-tray/code/Main.html` 的内联样式（高 18 · 圆角 9 · 内边距 4/7、2 家起 6/7 ·
//!      段间距 8/7/3 · 段内 3 · logo 12 · JetBrains Mono 11.5 · 2 家起 min-width 96 + space-evenly）。
//!   2. `Tracker` + `Anim` —— 纯状态机：停下那一段 40% 保持 3 s 再退出；固定 4 槽（Codex→Claude→Gemini→grok）；
//!      横向全用临界阻尼弹簧（response 0.38），数字逐位滚动用 0.32 / 0.76，淡入淡出 200 ms ease-out，可打断。
//!   3. `draw`（macOS）—— 把一帧画进一张 NSBitmapImageRep → PNG → `TrayIcon::set_icon`（template = false）。
//!      ★ 不在 status item 里放自定义视图（交接包：macOS 27 对其 hover / occlusion 有回归）。
//!
//! ★ 动画帧只在过渡期间跑（≤ 60 fps，落定即停）；平时一张图都不重画。
//! ★ fail-open：画图失败 ⇒ 退回纯文本标题 `Codex 178 · Claude 64`（宁可没图，不可让菜单栏空掉）。
//! ⚠️ 偏离交接包（理由写在这里也写在 PLAN §4）：blurReplace 的「模糊 2→0 px」没做 —— NSImage 逐帧画
//!    没有现成的高斯模糊，只做了缩放 0.6→1 + 透明 0→1；空闲 ↔ 在跑的标题「缩小 + 模糊淡出」同理只缩小 + 淡出。
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

pub const KEYS: [&str; 4] = ["codex", "claude", "agy", "grok"];
/// ★ 用户 2026-10-22 从 demo（`~/Downloads/codexbar_tray_pill_nobg_demo_20261022.html`）选 B：**在跑胶囊去掉底色**，
///   图 20 → 22、logo 16 → 18、字 12.5 → 13.5，左右内边距收到 1 / 2。没有底色块就不用上下留空，22 贴着菜单栏可用高度。
///   （上一档 2026-10-21「胶囊内容需要放大，优先 AI svg」：18 → 20、logo 12 → 16、字 11.5 → 12.5。）
pub const H: f64 = 22.0;
/// 空闲「AI 图标」那一档仍画底色块（用户这次只改在跑胶囊）：块高 20、圆角 10，竖直居中在 22 的图里，外观与改之前一致。
const BG_H: f64 = 20.0;
const RADIUS: f64 = 10.0;
pub const LOGO: f64 = 18.0;
const INNER_GAP: f64 = 3.0;
/// logo 与数字之间。交接包是段内统一 3；真机上 logo 贴着数字（用户 2026-10-19「1 家状态下 svg 和速度太近」），放到 5。
pub const LOGO_GAP: f64 = 5.0;
/// ✗ 已删 `W_MIN`（2 家起胶囊最小宽 106）：它是给底色块定形的；去掉底色后多出来的空档只是菜单栏里一段空白（2026-10-22）。
/// 停下：那一段降到 40%、保持最后的数字 3 s，然后退出。
pub const HOLD_SECS: f64 = 3.0;
pub const STOP_ALPHA: f64 = 0.4;
/// 用户 2026-10-22「字体需要加大加粗」：13.5 → 15；数字 600 → 700、「t/s」500 → 600、上标 600 → 700。
pub const FONT_SIZE: f64 = 15.0;
/// 「t/s」：文字色 @ .78（Main.html 是 .62 —— 那是压在深色底色块上的；去底色后用户报「看不清字」，2026-10-22 提到 .78）
const SUFFIX_ALPHA: f64 = 0.78;
/// 多会话：照 Tollm 的状态栏（`tollm/Sources/Tollm/MenuBar/StatusIcon.swift`）—— 紧跟在「t/s」后面的上标「×N」，
///   小一号粗体、文字色 @ .8，不再写成同字号的「 · N」（用户 2026-10-22「学习 tollm 的方式处理」）。
///   Tollm 是 13 pt 正文配 8.5 pt 上标；这里 15 配 10。上标的顶与正文的顶对齐（抬高 = 两者行高差的一半）。
pub const SUP_SIZE: f64 = 10.0;
const SUP_ALPHA: f64 = 0.8;
/// 上标与「t/s」之间
const SUP_GAP: f64 = 1.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Appearance { Light, Dark }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rgb(pub u8, pub u8, pub u8);

impl Rgb {
    pub fn f(self) -> (f64, f64, f64) { (self.0 as f64 / 255.0, self.1 as f64 / 255.0, self.2 as f64 / 255.0) }
}

/// 底色块：浅色菜单栏 #1C2128、深色菜单栏 #3D4552（交接包 README「平台顺序与颜色」）。
/// ★ 2026-10-22 起只给空闲「AI 图标」那一档用；在跑胶囊没有底色。
pub fn capsule_bg(ap: Appearance) -> Rgb {
    match ap { Appearance::Light => Rgb(0x1C, 0x21, 0x28), Appearance::Dark => Rgb(0x3D, 0x45, 0x52) }
}

/// 菜单栏的参考底色（对比度闸用）。真机菜单栏半透明、压在壁纸上，没有固定底色 —— 这是去底色的代价，用户看过 demo 后接受。
#[cfg(test)]
pub fn menubar_ref(ap: Appearance) -> Rgb {
    match ap { Appearance::Light => Rgb(0xEC, 0xEC, 0xEC), Appearance::Dark => Rgb(0x2A, 0x2A, 0x2C) }
}

/// 数字色（按槽位 Codex / Claude / Gemini / grok），直接压在菜单栏上。
/// 浅色菜单栏：同色相深一档（2026-10-22 去底色；原来那套亮色是配深色胶囊底的）。深色菜单栏沿用原来深色那套
///   （其中 Claude #F19D7B 是对 #3D4552 胶囊底调出 4.54 : 1 的那一版）。闸 `number_colors_clear_4_5_to_1_on_the_menubar`。
pub fn num_color(ap: Appearance, slot: usize) -> Rgb {
    const LIGHT: [Rgb; 4] = [Rgb(0x0A, 0x74, 0x68), Rgb(0xB0, 0x4A, 0x1C), Rgb(0x1C, 0x63, 0xC4), Rgb(0x5F, 0x4B, 0xD0)];
    const DARK: [Rgb; 4] = [Rgb(0x5E, 0xEA, 0xD4), Rgb(0xF1, 0x9D, 0x7B), Rgb(0x7A, 0xB8, 0xFF), Rgb(0xB9, 0xAE, 0xFB)];
    match ap { Appearance::Light => LIGHT[slot], Appearance::Dark => DARK[slot] }
}

/// 在跑但还没出数：写 `—`。深色菜单栏灰 #aab3c0（Main.html「Claude 还没出数」那一行）；浅色菜单栏 #5f6672。
pub const DASH_COLOR: Rgb = Rgb(0xAA, 0xB3, 0xC0);
pub fn dash_color(ap: Appearance) -> Rgb {
    match ap { Appearance::Light => Rgb(0x5F, 0x66, 0x72), Appearance::Dark => DASH_COLOR }
}
/// 「t/s」「×N」的文字色（再乘各自的透明度）。
pub fn text_color(ap: Appearance) -> Rgb {
    match ap { Appearance::Light => Rgb(0x1D, 0x1F, 0x23), Appearance::Dark => Rgb(0xF2, 0xF4, 0xF7) }
}

/// 一家的输入。`stopping_since` = 这家停下的时刻（秒）；在跑时为 None。
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlatformIn {
    pub running: bool,
    pub tps: Option<f64>,
    pub n_sessions: u32,
    pub stopping_since: Option<f64>,
}

impl PlatformIn {
    /// 画不画这一段：在跑，或停下还没满 3 s。
    pub fn shown(&self, now: f64) -> bool {
        self.running || self.stopping_since.is_some_and(|t| now - t < HOLD_SECS)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode { Full, Compact, Minimal }

/// 一段的目标版面（胶囊内坐标，左上原点，逻辑 pt）。
#[derive(Clone, Debug, PartialEq)]
pub struct Seg {
    pub slot: usize,
    pub x: f64,
    pub w: f64,
    /// 数字文本（`—` 或整数）；3 家起为 None（只剩 logo）
    pub num: Option<String>,
    pub num_w: f64,
    /// 1 家时的「t/s」宽（含前面的 3 pt 段内间距）；否则 0
    pub unit_w: f64,
    /// 1 家且会话 ≥ 2 时的上标「×N」；宽含前面的 1 pt
    pub sess: Option<String>,
    pub sess_w: f64,
    /// 1 = 在跑；0.4 = 停下（保持 3 s）
    pub alpha: f64,
    pub color: Rgb,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Layout {
    pub width: f64,
    pub mode: Mode,
    pub segs: Vec<Seg>,
}

/// 速度只写整数；读不到写 `—`，不写 0，也不加「≈」。
pub fn fmt_tps(tps: Option<f64>) -> String {
    match tps {
        Some(t) if t.is_finite() && t >= 0.0 => format!("{:.0}", t),
        _ => "—".into(),
    }
}

fn text_w(s: &str, cw: f64) -> f64 { s.chars().count() as f64 * cw }

/// 纯版面。`cw` = JetBrains Mono 11.5 一个字符的步进（实测 6.9 pt；退回系统等宽字体时由调用方量）。
/// 没有任何一段要画 ⇒ None（= 空闲，回 v1.11.0 标题）。
pub fn layout(inp: &[PlatformIn; 4], ap: Appearance, cw: f64, now: f64) -> Option<Layout> {
    let shown: Vec<usize> = (0..4).filter(|&i| inp[i].shown(now)).collect();
    if shown.is_empty() { return None; }
    let mode = match shown.len() { 1 => Mode::Full, 2 => Mode::Compact, _ => Mode::Minimal };
    // 没有底色块 ⇒ 左右只留 1 / 2（右边贴着系统的下一个图标太紧会粘在一起）；段间距放宽一点替代原来的块边界
    let (pad_l, pad_r, gap) = match mode {
        Mode::Full => (1.0, 2.0, 8.0),
        Mode::Compact => (1.0, 2.0, 9.0),
        Mode::Minimal => (1.0, 2.0, 5.0),
    };
    let mut segs: Vec<Seg> = shown.iter().map(|&i| {
        let p = &inp[i];
        let num = (mode != Mode::Minimal).then(|| fmt_tps(p.tps));
        let num_w = num.as_deref().map_or(0.0, |s| LOGO_GAP + text_w(s, cw));
        let unit_w = if mode == Mode::Full { INNER_GAP + text_w("t/s", cw) } else { 0.0 };
        let sess = (mode == Mode::Full && p.n_sessions >= 2).then(|| format!("×{}", p.n_sessions));
        // 等宽字体的步进与字号成正比 ⇒ 上标步进 = 正文步进 × 字号比
        let sess_w = sess.as_deref().map_or(0.0, |s| SUP_GAP + text_w(s, cw * SUP_SIZE / FONT_SIZE));
        let color = if p.tps.is_some() && num.as_deref() != Some("—") { num_color(ap, i) } else { dash_color(ap) };
        Seg { slot: i, x: 0.0, w: LOGO + num_w + unit_w + sess_w, num, num_w, unit_w, sess, sess_w,
              alpha: if p.running { 1.0 } else { STOP_ALPHA }, color }
    }).collect();
    let n = segs.len() as f64;
    let width = pad_l + segs.iter().map(|s| s.w).sum::<f64>() + gap * (n - 1.0) + pad_r;
    let mut x = pad_l;
    for s in segs.iter_mut() {
        s.x = x;
        x += s.w + gap;
    }
    Some(Layout { width, mode, segs })
}

/// 一家的实时读数（来自 `.live.json`）。
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LiveIn { pub running: bool, pub tps: Option<f64>, pub n_sessions: u32 }

/// 「停下 → 40% 保持 3 s → 退出」的状态机。纯，时间由调用方给。
#[derive(Clone, Debug, Default)]
pub struct Tracker { pub p: [PlatformIn; 4] }

impl Tracker {
    pub fn observe(&mut self, live: &[LiveIn; 4], now: f64) {
        for i in 0..4 {
            let cur = &mut self.p[i];
            let l = &live[i];
            if l.running {
                *cur = PlatformIn { running: true, tps: l.tps, n_sessions: l.n_sessions, stopping_since: None };
            } else if cur.running {
                // 刚停：保持最后的数字
                cur.running = false;
                cur.stopping_since = Some(now);
            }
        }
        self.expire(now);
    }
    /// 停满 3 s 的清掉。返回是否有变化。
    pub fn expire(&mut self, now: f64) -> bool {
        let mut changed = false;
        for p in self.p.iter_mut() {
            if !p.running && p.stopping_since.is_some_and(|t| now - t >= HOLD_SECS) {
                *p = PlatformIn::default();
                changed = true;
            }
        }
        changed
    }
    /// 下一次要醒来清掉某段的时刻。
    pub fn next_deadline(&self) -> Option<f64> {
        self.p.iter().filter(|p| !p.running).filter_map(|p| p.stopping_since.map(|t| t + HOLD_SECS))
            .min_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
    }
    pub fn any_running(&self) -> bool { self.p.iter().any(|p| p.running) }
}

// ---------------------------------------------------------------- 动画（纯）

/// 弹簧。`response` 秒、`zeta` 阻尼比（1 = 临界阻尼、无回弹）。SwiftUI `.spring(response:dampingFraction:)` 同义。
#[derive(Clone, Copy, Debug)]
pub struct Spring { pub pos: f64, pub vel: f64, pub target: f64, omega: f64, zeta: f64, eps: f64 }

impl Spring {
    pub fn new(v: f64, response: f64, zeta: f64, eps: f64) -> Spring {
        Spring { pos: v, vel: 0.0, target: v, omega: 2.0 * std::f64::consts::PI / response, zeta, eps }
    }
    pub fn snap(&mut self, v: f64) { self.pos = v; self.target = v; self.vel = 0.0; }
    pub fn settled(&self) -> bool { (self.pos - self.target).abs() < self.eps && self.vel.abs() < self.eps * 10.0 }
    /// 解析解推进（不做数值积分：临界阻尼的数值解会有一丝过冲，而过冲叠加正是交接包说的「左右跳动」）。
    pub fn step(&mut self, dt: f64) {
        if self.settled() { self.pos = self.target; self.vel = 0.0; return; }
        let (w, z, d0, v0) = (self.omega, self.zeta, self.pos - self.target, self.vel);
        let (d, v) = if z >= 1.0 {
            let e = (-w * dt).exp();
            let c = v0 + w * d0;
            ((d0 + c * dt) * e, (v0 - w * c * dt) * e)
        } else {
            let wd = w * (1.0 - z * z).sqrt();
            let e = (-z * w * dt).exp();
            let (sn, cs) = (wd * dt).sin_cos();
            (e * (d0 * cs + (v0 + z * w * d0) / wd * sn), e * (v0 * cs - (z * w * v0 + w * w * d0) / wd * sn))
        };
        self.pos = self.target + d;
        self.vel = v;
        if self.settled() { self.pos = self.target; self.vel = 0.0; }
    }
}

/// 横向：临界阻尼 response 0.38（交接包 v3 曲线）。
fn hspring(v: f64) -> Spring { Spring::new(v, 0.38, 1.0, 0.05) }
/// 缩放（blurReplace 的 0.6↔1）：同一条弹簧。
fn sspring(v: f64) -> Spring { Spring::new(v, 0.38, 1.0, 0.002) }
/// 数字纵向逐位滚动：0.32 / 0.76（轻微回弹）。
fn rspring(v: f64) -> Spring { Spring::new(v, 0.32, 0.76, 0.002) }

/// 200 ms ease-out 淡入淡出。可打断：从当前值重新瞄准。
#[derive(Clone, Copy, Debug)]
pub struct Fade { from: f64, to: f64, t0: f64 }
const FADE: f64 = 0.2;

impl Fade {
    pub(crate) fn new(v: f64) -> Fade { Fade { from: v, to: v, t0: f64::NEG_INFINITY } }
    pub fn value(&self, now: f64) -> f64 {
        let k = ((now - self.t0) / FADE).clamp(0.0, 1.0);
        let e = 1.0 - (1.0 - k) * (1.0 - k);
        self.from + (self.to - self.from) * e
    }
    pub(crate) fn go(&mut self, to: f64, now: f64, instant: bool) {
        if (to - self.to).abs() < 1e-9 { return; }
        if instant { self.from = to; self.to = to; self.t0 = f64::NEG_INFINITY; return; }
        self.from = self.value(now);
        self.to = to;
        self.t0 = now;
    }
    pub(crate) fn done(&self, now: f64) -> bool { now - self.t0 >= FADE }
}

/// 逐位滚动：只有变了的位从下方 7 pt 滑入（SwiftUI `numericText` 同形）。
#[derive(Clone, Debug)]
pub struct Roll { pub from: String, pub to: String, pub p: Spring }

impl Roll {
    fn new(s: &str) -> Roll { let mut p = rspring(1.0); p.snap(1.0); Roll { from: s.into(), to: s.into(), p } }
    fn set(&mut self, s: &str, instant: bool) {
        if s == self.to { return; }
        self.from = std::mem::replace(&mut self.to, s.into());
        if instant { self.p.snap(1.0); } else { self.p.pos = 0.0; self.p.vel = 0.0; self.p.target = 1.0; }
    }
}

/// 一个固定槽（永远对应同一家；只改坐标 / 透明度 / 缩放，不按列表下标重排 —— 交接包「固定槽位」）。
#[derive(Clone, Debug)]
struct Slot {
    present: bool,
    leaving: bool,
    /// 段右沿到胶囊右沿的距离（右边缘不动 ⇒ 用右侧锚定）
    x_r: Spring,
    scale: Spring,
    alpha: Fade,
    seg_alpha: Fade,
    num_w: Spring, num_a: Fade, num: Roll,
    unit_w: Spring, unit_a: Fade,
    sess_w: Spring, sess_a: Fade, sess: Roll,
    color: Rgb,
}

impl Slot {
    fn new() -> Slot {
        Slot { present: false, leaving: false, x_r: hspring(0.0), scale: sspring(1.0), alpha: Fade::new(0.0),
               seg_alpha: Fade::new(1.0), num_w: hspring(0.0), num_a: Fade::new(0.0), num: Roll::new(""),
               unit_w: hspring(0.0), unit_a: Fade::new(0.0), sess_w: hspring(0.0), sess_a: Fade::new(0.0),
               sess: Roll::new(""), color: DASH_COLOR }
    }
    fn width(&self) -> f64 { LOGO + self.num_w.pos.max(0.0) + self.unit_w.pos.max(0.0) + self.sess_w.pos.max(0.0) }
}

/// 一帧要画的东西（胶囊内坐标）。
#[derive(Clone, Debug, PartialEq)]
pub struct DrawSeg {
    pub slot: usize,
    pub x: f64,
    pub w: f64,
    /// 文字（数字 / t/s / · N）的透明度 = 进出场 × 停下（0.4）
    pub alpha: f64,
    /// logo 的透明度：**只跟进出场走，停下不变暗**（交接包「logo 任何状态都不变暗；停下只降数字 / 段的透明度」）
    pub logo_alpha: f64,
    pub scale: f64,
    pub num_from: String,
    pub num_to: String,
    pub num_p: f64,
    pub num_x: f64,
    pub num_a: f64,
    pub unit_x: f64,
    pub unit_a: f64,
    pub sess_from: String,
    pub sess_to: String,
    pub sess_p: f64,
    pub sess_x: f64,
    pub sess_a: f64,
    pub color: Rgb,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Frame {
    pub width: f64,
    pub bg_a: f64,
    /// 空闲 ↔ 在跑过渡时，标题那一层的透明度与缩放（1 = 完整标题）
    pub title_a: f64,
    pub title_scale: f64,
    pub segs: Vec<DrawSeg>,
    /// 完全空闲且落定 ⇒ 调用方把真标题还回去
    pub idle: bool,
}

#[derive(Clone, Debug)]
pub struct Anim {
    width: Spring,
    bg_a: Fade,
    title_a: Fade,
    title_scale: Spring,
    slots: Vec<Slot>,
    pill: bool,
    pub reduce: bool,
    /// 空闲态也画胶囊底（P11：空闲 ↔ 在跑是同一个外框在变形）。
    pub idle_bg: bool,
    last_now: f64,
}

impl Anim {
    pub fn new() -> Anim {
        Anim { width: hspring(0.0), bg_a: Fade::new(0.0), title_a: Fade::new(1.0), title_scale: sspring(1.0),
               slots: (0..4).map(|_| Slot::new()).collect(), pill: false, reduce: false, idle_bg: false, last_now: 0.0 }
    }

    /// 瞄准新目标（可打断：从当前值重新瞄准，不排队）。`title_w` = 空闲标题的宽，过渡时外框从它弹到胶囊宽。
    pub fn retarget(&mut self, target: Option<&Layout>, title_w: f64, now: f64) {
        let r = self.reduce;
        match target {
            Some(l) => {
                if !self.pill {
                    // 空闲 → 在跑：外框从标题宽起跳（右边缘不动），标题缩小淡出，底色淡入
                    if self.width.pos <= 0.0 { self.width.snap(title_w); }
                    self.pill = true;
                }
                self.width.target = l.width;
                if r { self.width.snap(l.width); }
                // 在跑胶囊没有底色（2026-10-22）；从「AI 图标」空闲档过来时那块底色淡出
                self.bg_a.go(0.0, now, r);
                self.title_a.go(0.0, now, r);
                self.title_scale.target = 0.85;
                if r { self.title_scale.snap(0.85); }
                for i in 0..4 {
                    let seg = l.segs.iter().find(|s| s.slot == i);
                    let s = &mut self.slots[i];
                    match seg {
                        Some(g) => {
                            let x_r = l.width - (g.x + g.w);
                            let entering = !s.present || s.leaving;
                            if !s.present {
                                // 新进场的段直接出现在目标坐标（只做 blurReplace），之后的移动才走弹簧
                                s.x_r.snap(x_r);
                                s.num_w.snap(g.num_w); s.unit_w.snap(g.unit_w); s.sess_w.snap(g.sess_w);
                                s.num = Roll::new(g.num.as_deref().unwrap_or(""));
                                s.sess = Roll::new(g.sess.as_deref().unwrap_or(""));
                                s.num_a = Fade::new(if g.num.is_some() { 1.0 } else { 0.0 });
                                s.unit_a = Fade::new(if g.unit_w > 0.0 { 1.0 } else { 0.0 });
                                s.sess_a = Fade::new(if g.sess.is_some() { 1.0 } else { 0.0 });
                                s.seg_alpha = Fade::new(g.alpha);
                                if r { s.scale.snap(1.0); } else { s.scale.snap(0.6); s.scale.target = 1.0; }
                                s.alpha = Fade::new(0.0);
                            } else {
                                s.x_r.target = x_r;
                                s.num_w.target = g.num_w; s.unit_w.target = g.unit_w; s.sess_w.target = g.sess_w;
                                if let Some(t) = g.num.as_deref() { s.num.set(t, r); }
                                if let Some(t) = g.sess.as_deref() { s.sess.set(t, r); }
                                s.num_a.go(if g.num.is_some() { 1.0 } else { 0.0 }, now, r);
                                s.unit_a.go(if g.unit_w > 0.0 { 1.0 } else { 0.0 }, now, r);
                                s.sess_a.go(if g.sess.is_some() { 1.0 } else { 0.0 }, now, r);
                                s.seg_alpha.go(g.alpha, now, r);
                                s.scale.target = 1.0;
                                if r { s.x_r.snap(x_r); s.num_w.snap(g.num_w); s.unit_w.snap(g.unit_w);
                                       s.sess_w.snap(g.sess_w); s.scale.snap(1.0); }
                            }
                            if entering { s.alpha.go(1.0, now, r); }
                            s.present = true;
                            s.leaving = false;
                            s.color = g.color;
                        }
                        None if s.present && !s.leaving => {
                            // 退出：缩放 → 0.6 + 透明 → 0，与其余段补位同时进行
                            s.leaving = true;
                            s.scale.target = 0.6;
                            if r { s.scale.snap(0.6); }
                            s.alpha.go(0.0, now, r);
                        }
                        None => {}
                    }
                }
            }
            None => {
                for s in self.slots.iter_mut() {
                    if s.present && !s.leaving {
                        s.leaving = true;
                        s.scale.target = 0.6;
                        if r { s.scale.snap(0.6); }
                        s.alpha.go(0.0, now, r);
                    }
                }
                if self.pill {
                    // 最后一家退出时反向：外框弹回标题宽，底色淡出，标题放大淡入
                    self.width.target = title_w;
                    if r { self.width.snap(title_w); }
                    self.bg_a.go(if self.idle_bg { 1.0 } else { 0.0 }, now, r);
                    self.title_a.go(1.0, now, r);
                    self.title_scale.target = 1.0;
                    if r { self.title_scale.snap(1.0); }
                }
            }
        }
        self.last_now = now;
    }

    /// 推进到 `now`。返回是否还在动（需要下一帧）。
    pub fn step(&mut self, now: f64) -> bool {
        let dt = (now - self.last_now).clamp(0.0, 0.1);
        self.last_now = now;
        self.width.step(dt);
        self.title_scale.step(dt);
        let mut moving = !self.width.settled() || !self.title_scale.settled()
            || !self.bg_a.done(now) || !self.title_a.done(now);
        for s in self.slots.iter_mut() {
            if !s.present { continue; }
            for sp in [&mut s.x_r, &mut s.scale, &mut s.num_w, &mut s.unit_w, &mut s.sess_w, &mut s.num.p, &mut s.sess.p] {
                sp.step(dt);
                moving |= !sp.settled();
            }
            for f in [&s.alpha, &s.seg_alpha, &s.num_a, &s.unit_a, &s.sess_a] { moving |= !f.done(now); }
            if s.leaving && s.alpha.done(now) && s.alpha.value(now) <= 1e-6 {
                *s = Slot::new();
            }
        }
        if self.pill && self.slots.iter().all(|s| !s.present) && self.width.settled() && self.bg_a.done(now) {
            self.pill = false;
            self.width.snap(0.0);
        }
        moving
    }

    pub fn frame(&self, now: f64) -> Frame {
        let width = self.width.pos.max(0.0);
        let segs = self.slots.iter().enumerate().filter(|(_, s)| s.present).map(|(i, s)| {
            let w = s.width();
            let x = width - s.x_r.pos - w;
            let num_x = x + LOGO + LOGO_GAP;
            let unit_x = x + LOGO + s.num_w.pos.max(0.0) + INNER_GAP;
            let sess_x = unit_x - INNER_GAP + s.unit_w.pos.max(0.0) + SUP_GAP;
            DrawSeg {
                slot: i, x, w, alpha: s.alpha.value(now) * s.seg_alpha.value(now), logo_alpha: s.alpha.value(now),
                scale: s.scale.pos,
                num_from: s.num.from.clone(), num_to: s.num.to.clone(), num_p: s.num.p.pos, num_x,
                num_a: s.num_a.value(now), unit_x, unit_a: s.unit_a.value(now),
                sess_from: s.sess.from.clone(), sess_to: s.sess.to.clone(), sess_p: s.sess.p.pos, sess_x,
                sess_a: s.sess_a.value(now), color: s.color,
            }
        }).collect();
        Frame {
            width, bg_a: if self.pill { self.bg_a.value(now) } else if self.idle_bg { 1.0 } else { 0.0 },
            title_a: if self.pill { self.title_a.value(now) } else { 1.0 },
            title_scale: self.title_scale.pos, segs, idle: !self.pill,
        }
    }
}

impl Default for Anim { fn default() -> Self { Anim::new() } }

/// 从 `.live.json` 取四家读数。读不到某家 ⇒ 当作不在跑。
pub fn parse_live(body: &str) -> Option<[LiveIn; 4]> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    let ps = v.get("platforms")?.as_object()?;
    let mut out: [LiveIn; 4] = Default::default();
    for (i, k) in KEYS.iter().enumerate() {
        if let Some(p) = ps.get(*k) {
            out[i] = LiveIn {
                running: p["running"].as_bool().unwrap_or(false),
                tps: p["tps"].as_f64(),
                n_sessions: p["n_sessions"].as_u64().unwrap_or(0) as u32,
            };
        }
    }
    Some(out)
}

/// 画图失败时的纯文本标题（fail-open）：`Codex 178 · Claude 64`。
pub fn fallback_title(inp: &[PlatformIn; 4], now: f64) -> String {
    const NAMES: [&str; 4] = ["Codex", "Claude", "Gemini", "Grok"];
    (0..4).filter(|&i| inp[i].shown(now)).map(|i| format!("{} {}", NAMES[i], fmt_tps(inp[i].tps)))
        .collect::<Vec<_>>().join(" · ")
}

// ---------------------------------------------------------------- 运行时状态（与 Tauri 接线）

/// 「在跑时显示 t/s」开关（设置页，默认开；App.tsx 启动时重发，同 `set_tray_style`）。
static ENABLED: AtomicBool = AtomicBool::new(false);
/// 胶囊（或过渡帧）正占着 status item。`refresh_tray` 看到它就不改标题。
static SHOWN: AtomicBool = AtomicBool::new(false);
/// 悬停面板里 logo 飞行期间，托盘画「无 logo 的胶囊」（交接包 page 2「容易遗漏」）。
static HIDE_LOGOS: AtomicBool = AtomicBool::new(false);
static ANIM_RUNNING: AtomicBool = AtomicBool::new(false);
static DRAW_PENDING: AtomicBool = AtomicBool::new(false);
/// 空闲时画 AI 图标（P11）而不是文字标题。前端 `set_idle_tray` 带过来；默认关 = 沿用 v1.11.0 文字标题。
static ICON_IDLE: AtomicBool = AtomicBool::new(false);

/// 空闲托盘用得上吗：开着、且至少有一家可画。
fn icon_idle_active(s: &State) -> bool {
    ICON_IDLE.load(Ordering::SeqCst) && s.idle.armed && s.idle.target_width() > 0.0
}

struct State {
    tracker: Tracker,
    anim: Anim,
    /// 空闲托盘（P11）：设置「空闲时菜单栏 = AI 图标」时，空闲态画这一层而不是文字标题。
    idle: crate::tray_idle::IdleAnim,
    ap: Appearance,
    cw: f64,
    title_w: f64,
    last: Option<Frame>,
    /// 上一张图画的时候 logo 藏没藏。帧相同但这个变了也要重画（否则飞回后 logo 不回来）。
    last_hide: bool,
    last_idle: Option<crate::tray_idle::IdleFrame>,
    failed: bool,
}

static STATE: Mutex<Option<State>> = Mutex::new(None);
static CLOCK: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();

fn now() -> f64 { CLOCK.get_or_init(std::time::Instant::now).elapsed().as_secs_f64() }

fn with_state<R>(f: impl FnOnce(&mut State) -> R) -> R {
    let mut g = STATE.lock().unwrap();
    let st = g.get_or_insert_with(|| State {
        tracker: Tracker::default(), anim: Anim::new(), idle: crate::tray_idle::IdleAnim::new(),
        ap: Appearance::Dark, cw: 6.9, title_w: 80.0,
        last: None, last_hide: false, last_idle: None, failed: false,
    });
    f(st)
}

pub fn is_enabled() -> bool { ENABLED.load(Ordering::SeqCst) }
pub fn is_shown() -> bool { SHOWN.load(Ordering::SeqCst) }
/// 托盘此刻画的是 t/s 胶囊（含进出过渡与停下后的 3 s）。悬停面板按它选「在跑面板」还是「空闲额度面板」——
/// 面板跟着托盘上看得见的东西走，不跟着「有没有 AI 在跑」走：关掉 t/s 时托盘一直是空闲图标，悬停也就一直是额度格子。
pub fn is_running() -> bool { is_enabled() && with_state(|s| !s.anim.frame(now()).idle) }
/// 有没有 AI 在跑（事实，与 t/s 开关无关）。打招呼按它避开在跑。
pub fn ai_running() -> bool { with_state(|s| s.tracker.any_running()) }

pub fn set_hide_logos(app: &tauri::AppHandle, hidden: bool) {
    if HIDE_LOGOS.swap(hidden, Ordering::SeqCst) != hidden { request_draw(app); }
}

/// 当前帧各段的位置（胶囊内坐标）+ 胶囊宽。悬停面板飞 logo 用。
pub fn segment_rects() -> serde_json::Value {
    with_state(|s| {
        let f = s.anim.frame(now());
        serde_json::json!({
            "width": f.width, "height": H,
            "segments": f.segs.iter().map(|g| serde_json::json!({
                "platform": KEYS[g.slot], "x": g.x, "w": g.w,
                "logo": { "x": g.x, "y": (H - LOGO) / 2.0, "size": LOGO },
            })).collect::<Vec<_>>(),
        })
    })
}

pub fn set_enabled(app: &tauri::AppHandle, on: bool) {
    let was = ENABLED.swap(on, Ordering::SeqCst);
    #[cfg(target_os = "macos")]
    {
        if on { crate::activity::subscribe(app, crate::activity::TPS); }
        else { crate::activity::unsubscribe(crate::activity::TPS); }
    }
    if was && !on {
        // 关掉：立刻回到空闲（文字标题或空闲图标），不走 3 s。tracker 留着：打招呼仍要知道谁在跑
        with_state(|s| { s.anim = Anim::new(); s.anim.idle_bg = icon_idle_active(s); s.last = None; });
        restore_title(app);
        kick(app);
    }
}

/// 空闲托盘（P11）：前端算好的 2–3 家 + 「空闲时菜单栏 = AI 图标」开关。关掉 ⇒ 回 v1.11.0 文字标题。
pub fn set_idle_tray(app: &tauri::AppHandle, on: bool, slots: &serde_json::Value) {
    let was = ICON_IDLE.swap(on, Ordering::SeqCst);
    let want = crate::tray_idle::parse_slots(slots);
    with_state(|s| {
        let t = now();
        if on { s.idle.retarget(&want, t); }
        s.anim.idle_bg = icon_idle_active(s);
        // 外框回到空闲时弹向的宽 = 空闲胶囊此刻的目标宽。在跑期间槽位变了也跟着改，否则停下后外框先弹到旧宽、落定那一帧再跳
        if s.anim.idle_bg { s.title_w = s.idle.target_width(); }
        // 只有开关本身变了才强制重画；槽位变化由 `last_idle` 的比较发现（前端也只在变了时才发）
        if was != on { s.last = None; }
    });
    if was && !on && with_state(|s| s.anim.frame(now()).idle) { restore_title(app); }
    #[cfg(target_os = "macos")]
    {
        // 空闲托盘要知道「上次 AI 活动」与「谁在跑」（打招呼的判据），关掉 t/s 胶囊时也一样 ⇒ 自己订一份活动检测
        if on && !was { crate::activity::subscribe(app, crate::activity::IDLE_TRAY); }
        if !on && was { crate::activity::unsubscribe(crate::activity::IDLE_TRAY); }
        if on { crate::tps_hover::start_near_watch(app); }
    }
    kick(app);
}

/// 鼠标靠近托盘（约 35 pt 内）⇒ 每个 logo 后亮平台色光晕；`hello` ⇒ 打招呼。由光标轮询线程调。
pub fn idle_near(app: &tauri::AppHandle, glow: bool, hello: bool) {
    with_state(|s| { let t = now(); s.idle.set_near(glow, t); if hello { s.idle.hello(t); } });
    kick(app);
}

/// 上一次观测到有 AI 在跑（epoch 秒）。打招呼要「距上次 AI 活动 > 60 分钟」。
static LAST_ACTIVE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

pub fn last_active_epoch() -> Option<f64> {
    let v = f64::from_bits(LAST_ACTIVE.load(Ordering::SeqCst));
    (v > 0.0).then_some(v)
}

/// 重启后接上「上次 AI 活动」（前端从用量快照算出的最近一次使用）。只往后挪，不覆盖本进程看到的更新的值。
pub fn seed_last_active(epoch: f64) {
    if !epoch.is_finite() || epoch <= 0.0 { return; }
    let _ = LAST_ACTIVE.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |cur| {
        (epoch > f64::from_bits(cur)).then_some(epoch.to_bits())
    });
}

/// 打招呼的「跳过」判据里归 tray 管的那两条：正在播事件动画、减弱动态效果。
pub fn idle_greet_blocked() -> bool { with_state(|s| s.idle.event_busy() || s.idle.reduce) }

/// 设置里选了「空闲时菜单栏 = AI 图标」吗（光标轮询线程据此决定退出）。
pub fn icon_idle_on() -> bool { ICON_IDLE.load(Ordering::SeqCst) }

/// 空闲托盘此刻在画吗（光标轮询与悬停面板用）。
pub fn idle_icons_shown() -> bool {
    with_state(|s| icon_idle_active(s) && s.anim.frame(now()).idle)
}

/// 空闲托盘各 logo 的位置（胶囊内坐标，左上原点）+ 胶囊宽。悬停面板飞 logo 用。
pub fn idle_rects() -> serde_json::Value {
    with_state(|s| {
        let f = s.idle.frame(now());
        serde_json::json!({
            "width": f.width, "height": H,
            "segments": f.logos.iter().map(|l| serde_json::json!({
                "platform": crate::tray_idle::KEYS[l.logo], "x": l.x, "w": crate::tray_idle::LOGO,
                "logo": { "x": l.x, "y": (H - crate::tray_idle::LOGO) / 2.0, "size": crate::tray_idle::LOGO },
            })).collect::<Vec<_>>(),
        })
    })
}

/// 收到一份 live JSON。
/// `fallback` = 活动检测那一份「谁在跑」（顺序 Codex → Claude → Gemini → grok），JSON 解不开时用它。
pub fn on_live(app: &tauri::AppHandle, body: &str, fallback: [bool; 4]) {
    match parse_live(body) {
        Some(l) => feed(app, &l),
        None => on_activity_only(app, fallback),
    }
}

/// live 读不到：只按活动检测画（速度写 —）。
pub fn on_activity_only(app: &tauri::AppHandle, arr: [bool; 4]) {
    let l: [LiveIn; 4] = std::array::from_fn(|i| LiveIn { running: arr[i], tps: None, n_sessions: 0 });
    feed(app, &l);
}

fn feed(app: &tauri::AppHandle, l: &[LiveIn; 4]) {
    // 活动时刻与「谁在跑」在开关判断之前记：关了 t/s 胶囊，打招呼仍要知道（空闲托盘自己订了活动检测）
    if l.iter().any(|p| p.running) {
        let epoch = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64());
        LAST_ACTIVE.store(epoch.to_bits(), Ordering::SeqCst);
    }
    let on = is_enabled();
    with_state(|s| {
        let t = now();
        s.tracker.observe(l, t);
        if on {
            let lay = layout(&s.tracker.p, s.ap, s.cw, t);
            s.anim.retarget(lay.as_ref(), s.title_w, t);
        }
    });
    if on { kick(app); }
}

/// 起（或续）动画线程：过渡期间 ≤ 60 fps 逐帧画，落定且没有待清的停下段就退出。
fn kick(app: &tauri::AppHandle) {
    if ANIM_RUNNING.swap(true, Ordering::SeqCst) { return; }
    let app = app.clone();
    std::thread::spawn(move || {
        loop {
            let (moving, wake) = with_state(|s| {
                let t = now();
                if s.tracker.expire(t) && is_enabled() {
                    let lay = layout(&s.tracker.p, s.ap, s.cw, t);
                    s.anim.retarget(lay.as_ref(), s.title_w, t);
                }
                let moving = s.anim.step(t) | s.idle.step(t);
                (moving, s.tracker.next_deadline().map(|d| (d - t).max(0.0)))
            });
            request_draw(&app);
            if moving {
                std::thread::sleep(std::time::Duration::from_millis(16));
            } else if let Some(w) = wake {
                std::thread::sleep(std::time::Duration::from_secs_f64(w.min(1.0) + 0.005));
            } else {
                break;
            }
        }
        ANIM_RUNNING.store(false, Ordering::SeqCst);
        // ★ 决定退出与清标记之间若有新目标进来（`feed` 看到标记还在就没起新线程），这里补一条，免得新动画没人推
        let pending = with_state(|s| { let t = now(); s.anim.step(t) | s.idle.step(t) || s.tracker.next_deadline().is_some() });
        if pending { kick(&app); }
    });
}

/// 把当前帧画到托盘（主线程）。上一帧还没画完就不再排队。
fn request_draw(app: &tauri::AppHandle) {
    if DRAW_PENDING.swap(true, Ordering::SeqCst) { return; }
    let a = app.clone();
    let _ = app.run_on_main_thread(move || {
        DRAW_PENDING.store(false, Ordering::SeqCst);
        draw_now(&a);
    });
}

#[cfg(target_os = "macos")]
fn draw_now(app: &tauri::AppHandle) {
    let ap = draw::menubar_appearance().unwrap_or(Appearance::Dark);
    let reduce = draw::reduce_motion();
    let cw = draw::char_w();
    let (frame, idle, inp, changed_ap) = with_state(|s| {
        let changed = s.ap != ap || (s.cw - cw).abs() > 1e-6;
        s.ap = ap;
        s.cw = cw;
        s.anim.reduce = reduce;
        s.idle.reduce = reduce;
        s.anim.idle_bg = icon_idle_active(s);
        let t = now();
        // 还在空闲态时记下空闲层的宽：下一次「空闲 → 在跑」外框从它起跳
        if s.anim.frame(t).idle {
            s.title_w = if s.anim.idle_bg { s.idle.frame(t).width } else { draw::title_width(&title_spec(), ap) };
        }
        if changed && is_enabled() {
            let lay = layout(&s.tracker.p, s.ap, s.cw, t);
            s.anim.retarget(lay.as_ref(), s.title_w, t);
        }
        let mut f = s.anim.frame(t);
        let idle = s.anim.idle_bg.then(|| s.idle.frame(t));
        // 空闲层的变化（水位、光晕、打招呼）也要触发重画：把它折进帧的比较里
        if let Some(i) = &idle { if f.idle { f.width = i.width; } }
        // ★ 帧不含「logo 藏没藏」：只比帧的话，悬停面板关掉、`set_hide_logos(false)` 请求重画时帧没变 ⇒
        //   被当成「不用画」跳过，托盘一直是无 logo 的胶囊，直到 t/s 变了才画回（用户 2026-10-19 实测）。
        let hide = HIDE_LOGOS.load(Ordering::SeqCst);
        let same = s.last.as_ref() == Some(&f) && s.last_hide == hide && s.last_idle == idle;
        s.last = Some(f.clone());
        s.last_hide = hide;
        s.last_idle = idle.clone();
        (if same { None } else { Some(f) }, idle, s.tracker.p.clone(), changed)
    });
    if changed_ap { kick(app); }
    let Some(frame) = frame else { return };
    let Some(tray) = app.tray_by_id("main") else { return };
    if frame.idle && idle.is_none() {
        if SHOWN.swap(false, Ordering::SeqCst) { restore_title(app); }
        return;
    }
    let title = title_spec();
    let layer = match &idle { Some(i) => TitleLayer::Idle(i), None => TitleLayer::Text(&title) };
    match draw::render(&frame, ap, HIDE_LOGOS.load(Ordering::SeqCst), &layer) {
        Some(png) => match tauri::image::Image::from_bytes(&png) {
            Ok(img) => {
                if !SHOWN.swap(true, Ordering::SeqCst) || with_state(|s| std::mem::take(&mut s.failed)) {
                    let _ = tray.set_title(Some(""));
                }
                let _ = tray.set_icon(Some(img));
                let _ = tray.set_icon_as_template(false);
                draw::native_size();
            }
            Err(e) => fail_open(app, &inp, &format!("decode: {}", e)),
        },
        None => fail_open(app, &inp, "render returned nothing"),
    }
}

#[cfg(not(target_os = "macos"))]
fn draw_now(_app: &tauri::AppHandle) {}

/// 空闲标题（读 state.json）。过渡帧 60 fps 画它，所以缓存 1 s —— 不许每帧读一次盘。
#[cfg(target_os = "macos")]
fn title_spec() -> TitleSpec {
    static CACHE: Mutex<Option<(std::time::Instant, TitleSpec)>> = Mutex::new(None);
    let mut c = CACHE.lock().unwrap();
    if let Some((at, t)) = c.as_ref() {
        if at.elapsed() < std::time::Duration::from_secs(1) { return t.clone(); }
    }
    let t = crate::tray_title_spec();
    *c = Some((std::time::Instant::now(), t.clone()));
    t
}

/// 画图失败 ⇒ 纯文本标题（跟随菜单栏文字色），图标还原成模板图。
#[cfg(target_os = "macos")]
fn fail_open(app: &tauri::AppHandle, inp: &[PlatformIn; 4], why: &str) {
    log::warn!("tray pill: drawing failed ({}), falling back to text", why);
    SHOWN.store(true, Ordering::SeqCst);
    with_state(|s| s.failed = true);
    if let Some(tray) = app.tray_by_id("main") {
        if let Ok(icon) = tauri::image::Image::from_bytes(include_bytes!("../icons/tray.png")) {
            let _ = tray.set_icon(Some(icon));
            let _ = tray.set_icon_as_template(true);
        }
        let _ = tray.set_title(Some(fallback_title(inp, now())));
    }
}

/// 回到 v1.11.0 的标题：模板图标 + `refresh_tray`。
fn restore_title(app: &tauri::AppHandle) {
    SHOWN.store(false, Ordering::SeqCst);
    if let Some(tray) = app.tray_by_id("main") {
        #[cfg(not(target_os = "windows"))]
        if let Ok(icon) = tauri::image::Image::from_bytes(include_bytes!("../icons/tray.png")) {
            let _ = tray.set_icon(Some(icon));
            #[cfg(target_os = "macos")]
            let _ = tray.set_icon_as_template(true);
        }
    }
    crate::refresh_tray(app);
}

// ---------------------------------------------------------------- 绘制（macOS）

/// 空闲标题的内容（lib.rs 的 `format_tray_title` + 百分比那段的颜色），过渡帧要把它画进图里。
/// 胶囊「标题那一层」画什么：文字标题（v1.11.0）或空闲托盘的 AI 图标（P11）。
pub enum TitleLayer<'a> { Text(&'a TitleSpec), Idle(&'a crate::tray_idle::IdleFrame) }

#[derive(Clone, Debug, Default)]
pub struct TitleSpec { pub text: String, pub hi: Option<(std::ops::Range<usize>, (f64, f64, f64))> }

#[cfg(target_os = "macos")]
pub mod draw {
    use super::*;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use objc2_foundation::{NSPoint, NSRect, NSSize, NSString};
    use std::ffi::c_void;

    #[link(name = "CoreText", kind = "framework")]
    extern "C" {
        fn CTFontManagerCreateFontDescriptorFromData(data: *const c_void) -> *const c_void;
        fn CTFontCreateWithFontDescriptor(desc: *const c_void, size: f64, matrix: *const c_void) -> *const c_void;
    }

    /// 托盘胶囊单色 / 彩色 logo（`@lobehub/icons-static-svg`，MIT；交接包 `assets/logos/`）。
    /// ★ 用 Main.html 实际引用的那几张（胶囊底色固定深色 ⇒ Codex / grok 用 on-dark 白色版，Claude 补黑眼彩色版，
    ///   Gemini 彩色版），不是 `*-on-color.svg`：那几张是 #0b0f14 深色填充，画在深色胶囊上看不见。
    /// 前 4 张 = 在跑胶囊的 4 槽（Codex → Claude → Gemini → grok）；后 2 张只在空闲托盘（P11）用：Kimi · DeepSeek。
    const LOGO_SVGS: [&[u8]; 6] = [
        include_bytes!("../icons/tray-logos/codex-on-dark.svg"),
        include_bytes!("../icons/tray-logos/claudecode-color-eyes.svg"),
        include_bytes!("../icons/tray-logos/gemini-color.svg"),
        include_bytes!("../icons/tray-logos/grok-on-dark.svg"),
        include_bytes!("../icons/tray-logos/kimi-on-dark.svg"),
        include_bytes!("../icons/tray-logos/deepseek-color.svg"),
    ];
    /// JetBrains Mono（OFL）：前端打包的同一份 woff2。CoreText 能直接从 woff2 建字体（2026-10-19 本机实测，
    /// `JetBrainsMono-SemiBold`，「0」步进 6.9 pt @ 11.5）。建不起来就退回系统等宽字体。
    const FONT_500: &[u8] = include_bytes!("../../public/fonts/jetbrains-mono-latin-500-normal.woff2");
    const FONT_600: &[u8] = include_bytes!("../../public/fonts/jetbrains-mono-latin-600-normal.woff2");
    const FONT_700: &[u8] = include_bytes!("../../public/fonts/jetbrains-mono-latin-700-normal.woff2");

    /// 只建一次的资源（AppKit 对象，Retained 不是 Send，存成指针；进程内永不释放）。
    struct Res { logos: [usize; 6], logos_light: [usize; 6], ghosts: [usize; 6], f600: usize, f700: usize, fsup: usize,
                 cw: f64, cw_sup: f64, sup_raise: f64, icon: usize }
    // 只在持有它的线程（主线程 / 单测线程）上用
    static RES: std::sync::OnceLock<Res> = std::sync::OnceLock::new();

    unsafe fn nsdata(bytes: &[u8]) -> *mut AnyObject {
        msg_send![class!(NSData), dataWithBytes: bytes.as_ptr() as *const c_void, length: bytes.len()]
    }

    unsafe fn image_from(bytes: &[u8]) -> usize {
        let a: *mut AnyObject = msg_send![class!(NSImage), alloc];
        let img: *mut AnyObject = msg_send![a, initWithData: nsdata(bytes)];
        img as usize
    }

    unsafe fn font_from(bytes: &[u8], weight: f64, size: f64) -> usize {
        let desc = CTFontManagerCreateFontDescriptorFromData(nsdata(bytes) as *const c_void);
        if !desc.is_null() {
            let f = CTFontCreateWithFontDescriptor(desc, size, std::ptr::null());
            if !f.is_null() { return f as usize; }
        }
        let f: *mut AnyObject = msg_send![class!(NSFont), monospacedSystemFontOfSize: size, weight: weight];
        let _: *mut AnyObject = msg_send![f, retain];
        f as usize
    }

    fn res() -> &'static Res {
        RES.get_or_init(|| unsafe {
            let logos: [usize; 6] = std::array::from_fn(|i| image_from(LOGO_SVGS[i]));
            // 浅色菜单栏上没有深色底了：单色的白 logo（Codex / grok / Kimi，fill #eef2f7）换成深色墨，彩色的原样用
            let logos_light: [usize; 6] = std::array::from_fn(|i| {
                let svg = std::str::from_utf8(LOGO_SVGS[i]).unwrap_or("");
                if svg.contains("fill=\"#eef2f7\"") { image_from(svg.replace("fill=\"#eef2f7\"", "fill=\"#1d1f23\"").as_bytes()) } else { logos[i] }
            });
            // 灰色剪影（P11「用掉的部分变成灰色剪影」）：logo 形状填浅灰，画时再乘 30%。只建一次。
            let ghosts: [usize; 6] = std::array::from_fn(|i| silhouette(logos[i], (0.86, 0.88, 0.90)));
            let f500 = font_from(FONT_500, 0.23, FONT_SIZE);
            let f600 = font_from(FONT_600, 0.3, FONT_SIZE);
            let f700 = font_from(FONT_700, 0.4, FONT_SIZE);
            let fsup = font_from(FONT_700, 0.4, SUP_SIZE);
            let probe = NSString::from_str("0000000000");
            let sz: NSSize = msg_send![&*probe, sizeWithAttributes: attrs(f500, (1.0, 1.0, 1.0), 1.0)];
            let ss: NSSize = msg_send![&*probe, sizeWithAttributes: attrs(fsup, (1.0, 1.0, 1.0), 1.0)];
            let icon = image_from(include_bytes!("../icons/tray.png"));
            let cw = if sz.width > 0.0 { sz.width / 10.0 } else { FONT_SIZE * 0.6 };
            Res { logos, logos_light, ghosts, f600, f700, fsup, cw,
                  cw_sup: if ss.width > 0.0 { ss.width / 10.0 } else { SUP_SIZE * 0.6 },
                  // 上标的顶对齐正文的顶：各自竖直居中后，上标再抬高两者行高差的一半
                  sup_raise: if sz.height > 0.0 && ss.height > 0.0 { (sz.height - ss.height) / 2.0 } else { 2.5 }, icon }
        })
    }

    /// 实际字体一个字符的步进（版面用它，退回系统字体时也对得上）。
    pub fn char_w() -> f64 { res().cw }

    /// 字体有没有退回系统等宽（单测报告用）。
    #[cfg(test)]
    pub fn font_is_jetbrains() -> bool {
        unsafe {
            let n: *mut AnyObject = msg_send![res().f600 as *mut AnyObject, fontName];
            let s: Option<Retained<NSString>> = Retained::retain(n as *mut NSString);
            s.is_some_and(|s| s.to_string().contains("JetBrains"))
        }
    }

    /// SVG 是否真被解成了图（失败时段里退回一个平台色圆点）。
    #[cfg(test)]
    pub fn logo_ok(slot: usize) -> bool { res().logos[slot] != 0 }

    unsafe fn color(rgb: (f64, f64, f64), a: f64) -> *mut AnyObject {
        msg_send![class!(NSColor), colorWithSRGBRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: a]
    }

    unsafe fn attrs(font: usize, rgb: (f64, f64, f64), a: f64) -> *mut AnyObject {
        let d: *mut AnyObject = msg_send![class!(NSMutableDictionary), dictionary];
        let _: () = msg_send![d, setObject: font as *mut AnyObject, forKey: objc2_app_kit::NSFontAttributeName];
        let _: () = msg_send![d, setObject: color(rgb, a), forKey: objc2_app_kit::NSForegroundColorAttributeName];
        d
    }

    /// 在胶囊坐标（左上原点）里画一串字，竖直居中在 18 pt 高里，`dy` 向下为正。
    unsafe fn text(s: &str, x: f64, dy: f64, font: usize, rgb: (f64, f64, f64), a: f64) {
        if a <= 0.001 || s.is_empty() { return; }
        let ns = NSString::from_str(s);
        let at = attrs(font, rgb, a.min(1.0));
        let sz: NSSize = msg_send![&*ns, sizeWithAttributes: at];
        let y = (H - sz.height) / 2.0 - dy;   // 位图是左下原点：向下 = y 变小
        let _: () = msg_send![&*ns, drawAtPoint: NSPoint::new(x, y), withAttributes: at];
    }

    unsafe fn save() { let _: () = msg_send![class!(NSGraphicsContext), saveGraphicsState]; }
    unsafe fn restore() { let _: () = msg_send![class!(NSGraphicsContext), restoreGraphicsState]; }

    unsafe fn scale_about(cx: f64, cy: f64, k: f64) {
        let t: *mut AnyObject = msg_send![class!(NSAffineTransform), transform];
        let _: () = msg_send![t, translateXBy: cx, yBy: cy];
        let _: () = msg_send![t, scaleBy: k];
        let _: () = msg_send![t, translateXBy: -cx, yBy: -cy];
        let _: () = msg_send![t, concat];
    }

    /// 逐位滚动：两串右对齐，变了的那一位旧的往上滑出、新的从下方 `dist` pt 滑入。`dy0` = 整串的竖直偏移（向下为正）。
    #[allow(clippy::too_many_arguments)]
    unsafe fn rolling(from: &str, to: &str, p: f64, x: f64, cw: f64, font: usize, rgb: (f64, f64, f64), a: f64, dy0: f64, dist: f64) {
        let f: Vec<char> = from.chars().collect();
        let t: Vec<char> = to.chars().collect();
        let n = t.len();
        let off = f.len() as isize - n as isize;   // 右对齐
        for (i, ch) in t.iter().enumerate() {
            let j = i as isize + off;
            let old = (j >= 0).then(|| f.get(j as usize).copied()).flatten();
            let cx = x + i as f64 * cw;
            if old == Some(*ch) || p >= 0.999 {
                text(&ch.to_string(), cx, dy0, font, rgb, a);
            } else {
                let q = p.clamp(0.0, 1.2);
                if let Some(o) = old { text(&o.to_string(), cx, dy0 - dist * q, font, rgb, a * (1.0 - q).clamp(0.0, 1.0)); }
                text(&ch.to_string(), cx, dy0 + dist * (1.0 - q), font, rgb, a * q.clamp(0.0, 1.0));
            }
        }
    }

    pub fn title_width(t: &TitleSpec, _ap: Appearance) -> f64 {
        unsafe {
            let font: *mut AnyObject = msg_send![class!(NSFont), menuBarFontOfSize: 0.0f64];
            let ns = NSString::from_str(&t.text);
            let at = attrs(font as usize, (0.0, 0.0, 0.0), 1.0);
            let sz: NSSize = msg_send![&*ns, sizeWithAttributes: at];
            18.0 + 4.0 + sz.width
        }
    }

    /// 空闲标题画进图里（过渡帧用）：模板图标按菜单栏明暗着色 + 文字，百分比那段上色。右对齐在 `right`。
    unsafe fn title(t: &TitleSpec, ap: Appearance, right: f64, a: f64, k: f64) {
        if a <= 0.001 { return; }
        let ink = match ap { Appearance::Light => (0.0, 0.0, 0.0), Appearance::Dark => (1.0, 1.0, 1.0) };
        let w = title_width(t, ap);
        let x0 = right - w;
        save();
        scale_about(right - w / 2.0, H / 2.0, k);
        // 图标：模板图是纯黑图、靠系统按明暗反色；自己画就先在一张小图里用 sourceAtop 着好色
        if let Some(icon) = tinted_icon(ink) {
            let r = NSRect::new(NSPoint::new(x0, 0.0), NSSize::new(18.0, 18.0));
            let _: () = msg_send![&*icon, drawInRect: r, fromRect: NSRect::ZERO, operation: 2usize, fraction: 0.85 * a, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
        }
        let font: *mut AnyObject = msg_send![class!(NSFont), menuBarFontOfSize: 0.0f64];
        let ns = NSString::from_str(&t.text);
        let at = attrs(font as usize, ink, 0.85 * a);
        let sz: NSSize = msg_send![&*ns, sizeWithAttributes: at];
        let ma: *mut AnyObject = msg_send![class!(NSMutableAttributedString), alloc];
        let ma: *mut AnyObject = msg_send![ma, initWithString: &*ns, attributes: at];
        if let Some(ma) = Retained::<AnyObject>::from_raw(ma) {
            // 百分比那段上色 + 加粗（与 `paint_tray_title` 同一条：NSRange 是 UTF-16 单位，现算）
            if let Some((r, rgb)) = &t.hi {
                if r.end <= t.text.len() && t.text.is_char_boundary(r.start) && t.text.is_char_boundary(r.end) {
                    let pre = t.text[..r.start].encode_utf16().count();
                    let len = t.text[r.clone()].encode_utf16().count();
                    let range = objc2_foundation::NSRange::new(pre, len);
                    let pt: f64 = msg_send![font, pointSize];
                    let bold: *mut AnyObject = msg_send![class!(NSFont), boldSystemFontOfSize: pt];
                    let _: () = msg_send![&*ma, addAttribute: objc2_app_kit::NSForegroundColorAttributeName, value: color(*rgb, a), range: range];
                    let _: () = msg_send![&*ma, addAttribute: objc2_app_kit::NSFontAttributeName, value: bold, range: range];
                }
            }
            let _: () = msg_send![&*ma, drawAtPoint: NSPoint::new(x0 + 22.0, (H - sz.height) / 2.0)];
        }
        restore();
    }

    /// 一张 `w × 18` pt、2× 的位图和画进它的上下文。
    unsafe fn new_ctx(w: f64) -> Option<(Retained<AnyObject>, *mut AnyObject)> {
        const SCALE: f64 = 2.0;
        let (pw, ph) = ((w * SCALE).round() as isize, (H * SCALE) as isize);
        let a: *mut AnyObject = msg_send![class!(NSBitmapImageRep), alloc];
        let cs = NSString::from_str("NSDeviceRGBColorSpace");
        let rep: *mut AnyObject = msg_send![a,
            initWithBitmapDataPlanes: std::ptr::null_mut::<*mut u8>(),
            pixelsWide: pw, pixelsHigh: ph, bitsPerSample: 8isize, samplesPerPixel: 4isize,
            hasAlpha: true, isPlanar: false, colorSpaceName: &*cs, bytesPerRow: 0isize, bitsPerPixel: 0isize];
        let rep: Retained<AnyObject> = Retained::from_raw(rep)?;
        let _: () = msg_send![&*rep, setSize: NSSize::new(w, H)];
        let ctx: *mut AnyObject = msg_send![class!(NSGraphicsContext), graphicsContextWithBitmapImageRep: &*rep];
        if ctx.is_null() { return None; }
        Some((rep, ctx))
    }

    unsafe fn tinted_icon(ink: (f64, f64, f64)) -> Option<Retained<AnyObject>> {
        let icon = res().icon as *mut AnyObject;
        if icon.is_null() { return None; }
        let (rep, ctx) = new_ctx(18.0)?;
        save();
        let _: () = msg_send![class!(NSGraphicsContext), setCurrentContext: ctx];
        let r = NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(18.0, 18.0));
        let _: () = msg_send![icon, drawInRect: r, fromRect: NSRect::ZERO, operation: 2usize, fraction: 1.0f64, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
        // NSCompositingOperationSourceAtop = 5：只给已经有像素的地方上色
        let _: () = msg_send![ctx, setCompositingOperation: 5usize];
        let _: () = msg_send![color(ink, 1.0), setFill];
        let _: () = msg_send![class!(NSBezierPath), fillRect: r];
        let _: () = msg_send![ctx, flushGraphics];
        restore();
        let a: *mut AnyObject = msg_send![class!(NSImage), alloc];
        let img: *mut AnyObject = msg_send![a, initWithSize: NSSize::new(18.0, 18.0)];
        let img: Retained<AnyObject> = Retained::from_raw(img)?;
        let _: () = msg_send![&*img, addRepresentation: &*rep];
        Some(img)
    }

    /// 一张 logo 的单色剪影（同形状、填 `ink`）。失败返回 0（调用方跳过剪影那一层）。
    unsafe fn silhouette(logo: usize, ink: (f64, f64, f64)) -> usize {
        let img = logo as *mut AnyObject;
        if img.is_null() { return 0; }
        const S: f64 = 28.0;   // 14 pt @2×，与空闲 logo 同尺寸
        let Some((rep, ctx)) = new_ctx_sq(S) else { return 0 };
        save();
        let _: () = msg_send![class!(NSGraphicsContext), setCurrentContext: ctx];
        let r = NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(S, S));
        let _: () = msg_send![img, drawInRect: r, fromRect: NSRect::ZERO, operation: 2usize, fraction: 1.0f64, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
        let _: () = msg_send![ctx, setCompositingOperation: 5usize];   // sourceAtop：只染已有像素
        let _: () = msg_send![color(ink, 1.0), setFill];
        let _: () = msg_send![class!(NSBezierPath), fillRect: r];
        let _: () = msg_send![ctx, flushGraphics];
        restore();
        let a: *mut AnyObject = msg_send![class!(NSImage), alloc];
        let out: *mut AnyObject = msg_send![a, initWithSize: NSSize::new(S, S)];
        if out.is_null() { return 0; }
        let _: () = msg_send![out, addRepresentation: &*rep];
        out as usize   // 进程内永不释放（同 Res 里其它对象）
    }

    /// 正方形位图上下文（逻辑尺寸 = 像素尺寸，只给剪影用）。
    unsafe fn new_ctx_sq(px: f64) -> Option<(Retained<AnyObject>, *mut AnyObject)> {
        let a: *mut AnyObject = msg_send![class!(NSBitmapImageRep), alloc];
        let cs = NSString::from_str("NSDeviceRGBColorSpace");
        let rep: *mut AnyObject = msg_send![a,
            initWithBitmapDataPlanes: std::ptr::null_mut::<*mut u8>(),
            pixelsWide: px as isize, pixelsHigh: px as isize, bitsPerSample: 8isize, samplesPerPixel: 4isize,
            hasAlpha: true, isPlanar: false, colorSpaceName: &*cs, bytesPerRow: 0isize, bitsPerPixel: 0isize];
        let rep: Retained<AnyObject> = Retained::from_raw(rep)?;
        let ctx: *mut AnyObject = msg_send![class!(NSGraphicsContext), graphicsContextWithBitmapImageRep: &*rep];
        if ctx.is_null() { return None; }
        Some((rep, ctx))
    }

    /// 空闲托盘那一层（P11）：logo 右对齐画在 `right` 以左；整层随过渡淡出 / 缩小（同文字标题）。
    unsafe fn idle_layer(f: &crate::tray_idle::IdleFrame, right: f64, a: f64, k: f64, backing: (f64, f64, f64), bg_a: f64) {
        use crate::tray_idle::{BACKING_R, DOT_D, DOT_RGB, DOT_RING, GHOST_ALPHA, GLOW_D, GLOW_RGB, LOGO as IL};
        if a <= 0.001 || f.width <= 0.0 { return; }
        let r = res();
        let x0 = right - f.width;
        let rgb = |c: (u8, u8, u8)| (c.0 as f64 / 255.0, c.1 as f64 / 255.0, c.2 as f64 / 255.0);
        save();
        scale_about(right - f.width / 2.0, H / 2.0, k);
        // 堆叠（2026-10-22）：从右往左画，左边的压在上面；每只先垫一块底色圆把下面那只切开
        let mut order: Vec<&crate::tray_idle::IdleDraw> = f.logos.iter().collect();
        order.sort_by(|p, q| q.x.partial_cmp(&p.x).unwrap_or(std::cmp::Ordering::Equal));
        for l in order {
            let la = a * l.alpha;
            if la <= 0.001 { continue; }
            let x = x0 + l.x;
            let y = (H - IL) / 2.0 + l.lift;   // 位图左下原点：上跳 = y 变大
            save();
            scale_about(x + IL / 2.0, y + IL / 2.0, l.scale);
            // 光晕：平台色 50%，径向渐变到透明
            if l.glow > 0.001 {
                let c = rgb(GLOW_RGB[l.logo]);
                let g: *mut AnyObject = msg_send![class!(NSGradient), alloc];
                let g: *mut AnyObject = msg_send![g, initWithStartingColor: color(c, 0.5 * l.glow * la), endingColor: color(c, 0.0)];
                if let Some(g) = Retained::<AnyObject>::from_raw(g) {
                    let cx = x + IL / 2.0;
                    let cy = y + IL / 2.0;
                    let _: () = msg_send![&*g, drawFromCenter: NSPoint::new(cx, cy), radius: 0.0f64,
                        toCenter: NSPoint::new(cx, cy), radius: GLOW_D / 2.0, options: 0usize];
                }
            }
            if bg_a > 0.001 {
                let c = NSRect::new(NSPoint::new(x + IL / 2.0 - BACKING_R, y + IL / 2.0 - BACKING_R), NSSize::new(2.0 * BACKING_R, 2.0 * BACKING_R));
                let p: *mut AnyObject = msg_send![class!(NSBezierPath), bezierPathWithOvalInRect: c];
                let _: () = msg_send![color(backing, la * bg_a), setFill];
                let _: () = msg_send![p, fill];
            }
            let lr = NSRect::new(NSPoint::new(x, y), NSSize::new(IL, IL));
            // 灰色剪影（整只），再盖上「还剩的那部分」原色
            let ghost = r.ghosts[l.logo] as *mut AnyObject;
            if !ghost.is_null() {
                let _: () = msg_send![ghost, drawInRect: lr, fromRect: NSRect::ZERO, operation: 2usize, fraction: GHOST_ALPHA * la, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
            }
            let img = r.logos[l.logo] as *mut AnyObject;
            let keep = (1.0 - l.cut / 100.0).clamp(0.0, 1.0);
            if !img.is_null() && keep > 0.0 {
                save();
                // 从顶往下裁 cut%：原色只留下面那一截（左下原点 ⇒ 从 y 起、高 keep·14）
                let clip = NSRect::new(NSPoint::new(x - 1.0, y), NSSize::new(IL + 2.0, IL * keep));
                let _: () = msg_send![class!(NSBezierPath), clipRect: clip];
                let _: () = msg_send![img, drawInRect: lr, fromRect: NSRect::ZERO, operation: 2usize, fraction: la, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
                restore();
            }
            // 额度重置的白光
            if l.flash > 0.001 {
                let g: *mut AnyObject = msg_send![class!(NSGradient), alloc];
                let g: *mut AnyObject = msg_send![g, initWithStartingColor: color((1.0, 1.0, 1.0), 0.75 * l.flash * la), endingColor: color((1.0, 1.0, 1.0), 0.0)];
                if let Some(g) = Retained::<AnyObject>::from_raw(g) {
                    let c = NSPoint::new(x + IL / 2.0, y + IL / 2.0);
                    let _: () = msg_send![&*g, drawFromCenter: c, radius: 0.0f64, toCenter: c, radius: IL / 2.0 + 1.5, options: 0usize];
                }
            }
            // 红点：右上角各外伸 2 pt，1 pt 描边
            if l.dot > 0.001 {
                let d = DOT_D * l.dot;
                let cx = x + IL + 2.0 - DOT_D / 2.0;
                // 画板外伸 2 pt 时描边顶到 19 pt，超出 18 pt 高的位图被裁平 ⇒ 压到刚好不出界（低 1 pt，偏离记 PLAN）
                let cy = (y + IL + 2.0 - DOT_D / 2.0).min(H - DOT_D / 2.0 - 1.0);
                let ring = NSRect::new(NSPoint::new(cx - d / 2.0 - 1.0, cy - d / 2.0 - 1.0), NSSize::new(d + 2.0, d + 2.0));
                let p: *mut AnyObject = msg_send![class!(NSBezierPath), bezierPathWithOvalInRect: ring];
                let _: () = msg_send![color(rgb(DOT_RING), la), setFill];
                let _: () = msg_send![p, fill];
                let dot = NSRect::new(NSPoint::new(cx - d / 2.0, cy - d / 2.0), NSSize::new(d, d));
                let p: *mut AnyObject = msg_send![class!(NSBezierPath), bezierPathWithOvalInRect: dot];
                let _: () = msg_send![color(rgb(DOT_RGB), la), setFill];
                let _: () = msg_send![p, fill];
            }
            restore();
        }
        restore();
    }

    /// 画一帧 → PNG（2× 位图；`set_icon` 会缩到 18 pt 高，`native_size` 再改回 `H`）。失败返回 None（调用方 fail-open）。
    pub fn render(f: &Frame, ap: Appearance, hide_logos: bool, t: &TitleLayer) -> Option<Vec<u8>> {
        objc2::rc::autoreleasepool(|_| unsafe { render_inner(f, ap, hide_logos, t) })
    }

    unsafe fn render_inner(f: &Frame, ap: Appearance, hide_logos: bool, t: &TitleLayer) -> Option<Vec<u8>> {
        let r = res();
        // 图宽 = 外框此刻的宽（过渡时从标题宽弹到胶囊宽）；标题右对齐画在里面，超出的部分被图边裁掉
        let w = f.width.max(1.0).ceil();
        let (rep, ctx) = new_ctx(w)?;
        save();
        let _: () = msg_send![class!(NSGraphicsContext), setCurrentContext: ctx];

        // 胶囊底（右对齐：右边缘不动）
        let bx = w - f.width;
        if f.bg_a > 0.001 && f.width > 0.5 {
            let rr = NSRect::new(NSPoint::new(bx, (H - BG_H) / 2.0), NSSize::new(f.width, BG_H));
            let p: *mut AnyObject = msg_send![class!(NSBezierPath), bezierPathWithRoundedRect: rr, xRadius: RADIUS, yRadius: RADIUS];
            let _: () = msg_send![color(capsule_bg(ap).f(), f.bg_a), setFill];
            let _: () = msg_send![p, fill];
        }
        match t {
            TitleLayer::Text(t) => title(t, ap, w, f.title_a, f.title_scale),
            // 悬停面板飞 logo 期间托盘不画自己的 logo（同在跑胶囊那条）
            TitleLayer::Idle(i) => if !hide_logos { idle_layer(i, w, f.title_a, f.title_scale, capsule_bg(ap).f(), f.bg_a) },
        }

        // 各段：只在胶囊里画（滚动的数字不越出胶囊）
        save();
        let clip = NSRect::new(NSPoint::new(bx, 0.0), NSSize::new(f.width.max(0.0), H));
        let _: () = msg_send![class!(NSBezierPath), clipRect: clip];
        for s in &f.segs {
            if s.alpha <= 0.001 && s.logo_alpha <= 0.001 { continue; }
            let x = bx + s.x;
            save();
            scale_about(x + s.w / 2.0, H / 2.0, s.scale);
            if !hide_logos {
                let lr = NSRect::new(NSPoint::new(x, (H - LOGO) / 2.0), NSSize::new(LOGO, LOGO));
                let img = (if ap == Appearance::Light { r.logos_light[s.slot] } else { r.logos[s.slot] }) as *mut AnyObject;
                if !img.is_null() {
                    // ★ logo 停下时不变暗（交接包 README「Logo」+ page1 清单）：只跟进出场的透明度走，
                    //   40% 只落在数字 / t/s / · N 上。Main.html 那一行把 `opacity: .4` 写在整段上，与规则冲突，按规则来。
                    let _: () = msg_send![img, drawInRect: lr, fromRect: NSRect::ZERO, operation: 2usize, fraction: s.logo_alpha, respectFlipped: true, hints: std::ptr::null_mut::<AnyObject>()];
                } else {
                    // SVG 解不出来：平台色圆点兜底
                    let dot = NSRect::new(NSPoint::new(x + 2.0, (H - 8.0) / 2.0), NSSize::new(8.0, 8.0));
                    let p: *mut AnyObject = msg_send![class!(NSBezierPath), bezierPathWithOvalInRect: dot];
                    let _: () = msg_send![color(num_color(ap, s.slot).f(), s.logo_alpha), setFill];
                    let _: () = msg_send![p, fill];
                }
            }
            let ink = text_color(ap).f();
            if s.num_a > 0.001 {
                rolling(&s.num_from, &s.num_to, s.num_p, bx + s.num_x, r.cw, r.f700, s.color.f(), s.alpha * s.num_a, 0.0, 7.0);
            }
            if s.unit_a > 0.001 {
                text("t/s", bx + s.unit_x, 0.0, r.f600, ink, s.alpha * s.unit_a * SUFFIX_ALPHA);
            }
            if s.sess_a > 0.001 {
                // 上标「×N」：小一号、抬到正文顶部；滚动距离按字号缩
                rolling(&s.sess_from, &s.sess_to, s.sess_p, bx + s.sess_x, r.cw_sup, r.fsup, ink,
                        s.alpha * s.sess_a * SUP_ALPHA, -r.sup_raise, 7.0 * SUP_SIZE / FONT_SIZE);
            }
            restore();
        }
        restore();

        let _: () = msg_send![ctx, flushGraphics];
        restore();
        let props: *mut AnyObject = msg_send![class!(NSDictionary), dictionary];
        // NSBitmapImageFileTypePNG = 4
        let png: *mut AnyObject = msg_send![&*rep, representationUsingType: 4usize, properties: props];
        if png.is_null() { return None; }
        let len: usize = msg_send![png, length];
        let ptr: *const u8 = msg_send![png, bytes];
        if ptr.is_null() || len == 0 { return None; }
        Some(std::slice::from_raw_parts(ptr, len).to_vec())
    }

    /// 菜单栏是深是浅：看状态栏按钮自己的 effectiveAppearance（浅色模式下菜单栏也可能是深的）。主线程。
    pub fn menubar_appearance() -> Option<Appearance> {
        use objc2_app_kit::NSApplication;
        let mtm = objc2_foundation::MainThreadMarker::new()?;
        let app = NSApplication::sharedApplication(mtm);
        unsafe {
            for w in app.windows().iter() {
                let cls = w.class().name().to_string_lossy().to_string();
                if !cls.contains("StatusBar") { continue; }
                let wp: *const AnyObject = (&*w as *const objc2_app_kit::NSWindow).cast();
                let ap: *mut AnyObject = msg_send![wp, effectiveAppearance];
                if ap.is_null() { continue; }
                let n: *mut AnyObject = msg_send![ap, name];
                let s: Option<Retained<NSString>> = Retained::retain(n as *mut NSString);
                return Some(if s.is_some_and(|s| s.to_string().contains("Dark")) { Appearance::Dark } else { Appearance::Light });
            }
        }
        None
    }

    /// ★★ 按 1 : 1 显示（用户 2026-10-22「为什么 tollm 的 svg 可以做那么大」）。
    /// `tray-icon` 0.24 的 `set_icon` 把任何图都**硬缩到 18 pt 高**（`platform_impl/macos/mod.rs` 的 `icon_height = 18.0`），
    /// 所以我们画的 22 pt 图在菜单栏上只剩 82%：logo 18 → 14.7、字 15 → 12.3（改之前的 20 pt 图也被缩到 90%）。
    /// Tollm 是原生 Swift，直接给 22 pt 的图，logo 17 / 字 14 原样显示 —— 差的就是这一步。
    /// 这里在 `set_icon` 之后（它是同步的：tauri 的 `run_item_main_thread!` 等主线程执行完才返回）把按钮上那张图的尺寸改回
    /// `H` 高、宽按比例，再让按钮重新量一次尺寸。找按钮的方式同 `lib.rs::paint_tray_title`（按类名在本进程的窗口里找）。
    /// fail-open：找不到就保持 18 pt（只是小一点）。主线程。
    pub fn native_size() {
        use objc2_app_kit::NSApplication;
        let Some(mtm) = objc2_foundation::MainThreadMarker::new() else { return };
        let app = NSApplication::sharedApplication(mtm);
        unsafe fn find(v: *mut AnyObject) -> *mut AnyObject {
            let is_btn: bool = msg_send![v, isKindOfClass: class!(NSStatusBarButton)];
            if is_btn { return v; }
            let subs: *mut AnyObject = msg_send![v, subviews];
            let n: usize = msg_send![subs, count];
            for i in 0..n {
                let sv: *mut AnyObject = msg_send![subs, objectAtIndex: i];
                let b = find(sv);
                if !b.is_null() { return b; }
            }
            std::ptr::null_mut()
        }
        unsafe {
            for w in app.windows().iter() {
                if !w.class().name().to_string_lossy().contains("StatusBar") { continue; }
                let wp: *const AnyObject = (&*w as *const objc2_app_kit::NSWindow).cast();
                let cv: *mut AnyObject = msg_send![wp, contentView];
                if cv.is_null() { continue; }
                let btn = find(cv);
                if btn.is_null() { continue; }
                let img: *mut AnyObject = msg_send![btn, image];
                if img.is_null() { continue; }
                let sz: NSSize = msg_send![img, size];
                if sz.height <= 0.0 || (sz.height - H).abs() < 0.01 { return; }
                let _: () = msg_send![img, setSize: NSSize::new(sz.width * H / sz.height, H)];
                // `tray-icon` 自己也是先 setImage 再 setSize —— 按钮在排版时才读尺寸；这里让它重新量一次
                let _: () = msg_send![btn, invalidateIntrinsicContentSize];
                let _: () = msg_send![btn, setNeedsLayout: true];
                let _: () = msg_send![btn, setNeedsDisplay: true];
                return;
            }
        }
    }

    /// 「减弱动态效果」。
    pub fn reduce_motion() -> bool {
        unsafe {
            let ws: *mut AnyObject = msg_send![class!(NSWorkspace), sharedWorkspace];
            if ws.is_null() { return false; }
            let b: bool = msg_send![ws, accessibilityDisplayShouldReduceMotion];
            b
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    /// JetBrains Mono 步进 0.6 em：11.5 pt 实测 6.9 ⇒ 12.5 pt 7.5。
    const CW: f64 = 9.0;   // JetBrains Mono 15 的步进 ≈ 0.6 em

    fn run(tps: Option<f64>, n: u32) -> PlatformIn { PlatformIn { running: true, tps, n_sessions: n, stopping_since: None } }
    fn off() -> PlatformIn { PlatformIn::default() }
    fn inp(v: [PlatformIn; 4]) -> [PlatformIn; 4] { v }
    fn close(a: f64, b: f64) -> bool { (a - b).abs() < 1e-6 }

    #[test]
    fn idle_has_no_pill() {
        assert_eq!(layout(&Default::default(), Appearance::Dark, CW, 0.0), None);
    }

    #[test]
    fn one_ai_is_full_and_sized_by_content() {
        let l = layout(&inp([run(Some(178.4), 1), off(), off(), off()]), Appearance::Light, CW, 0.0).unwrap();
        assert_eq!(l.mode, Mode::Full);
        let s = &l.segs[0];
        assert_eq!(s.num.as_deref(), Some("178"));
        assert_eq!(s.sess, None, "1 个会话不加 · N");
        // 1 + logo 18 + LOGO_GAP 5 + 178 + 3 + t/s + 2（2026-10-22 去底色、logo 18 / 字 15 ⇒ ≈ 83；有底色、字 12.5 时 ≈ 80）
        assert!(close(l.width, 1.0 + LOGO + LOGO_GAP + 3.0 * CW + 3.0 + 3.0 * CW + 2.0));
        assert!((l.width - 83.0).abs() < 1.0, "1 家 ≈ 83 pt，实得 {}", l.width);
        assert!(close(s.x, 1.0));
    }

    #[test]
    fn one_ai_with_three_sessions_gets_a_tollm_style_superscript() {
        // 用户 2026-10-22「单 AI 多会话后面的文字学 tollm」：「190 t/s×3」，×3 是紧贴 t/s 的小号上标，不是同字号的「 · 3」
        let l = layout(&inp([off(), run(Some(190.0), 3), off(), off()]), Appearance::Light, CW, 0.0).unwrap();
        let s = &l.segs[0];
        assert_eq!(s.sess.as_deref(), Some("×3"));
        assert!(close(s.sess_w, SUP_GAP + 2.0 * CW * SUP_SIZE / FONT_SIZE), "上标按小字号算宽：{}", s.sess_w);
        assert!(SUP_SIZE < FONT_SIZE * 0.75, "上标要明显小一号");
        let one = layout(&inp([off(), run(Some(190.0), 1), off(), off()]), Appearance::Light, CW, 0.0).unwrap();
        assert!(close(l.width - one.width, s.sess_w), "只多出上标那一截");
    }

    #[test]
    fn two_ais_are_compact_and_sized_by_content() {
        let l = layout(&inp([run(Some(178.0), 1), run(Some(64.0), 1), off(), off()]), Appearance::Light, CW, 0.0).unwrap();
        assert_eq!(l.mode, Mode::Compact);
        assert!(l.segs.iter().all(|s| s.unit_w == 0.0 && s.sess.is_none()), "紧凑：去掉 t/s 与 ×N");
        // 去底色后不再有 106 的最小宽、不再 space-evenly：内容多宽就多宽
        let (a, b) = (&l.segs[0], &l.segs[1]);
        assert!(close(a.x, 1.0) && close(b.x - (a.x + a.w), 9.0) && close(l.width - (b.x + b.w), 2.0),
                "左 1 · 段间 9 · 右 2：{} {} {}", a.x, b.x - (a.x + a.w), l.width - (b.x + b.w));
    }

    /// 用户 2026-10-19：「1 家状态下 svg 和速度太近」—— logo 与数字之间 5，不是段内统一的 3。
    #[test]
    fn the_number_keeps_its_distance_from_the_logo() {
        let l = layout(&inp([off(), run(Some(190.0), 3), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        let s = &l.segs[0];
        assert!(close(s.num_w, LOGO_GAP + text_w("190", CW)), "num_w = {}", s.num_w);
        assert!(LOGO_GAP > INNER_GAP);
    }

    #[test]
    fn three_or_more_show_logos_only() {
        let l = layout(&inp([run(Some(1.0), 1), run(Some(2.0), 4), run(None, 1), off()]), Appearance::Dark, CW, 0.0).unwrap();
        assert_eq!(l.mode, Mode::Minimal);
        assert!(l.segs.iter().all(|s| s.num.is_none() && s.w == LOGO), "3 家起不显示数字（不是数字缩小）");
        assert!(close(l.width, 1.0 + 3.0 * LOGO + 2.0 * 5.0 + 2.0));
        let l4 = layout(&inp([run(Some(1.0), 1), run(Some(2.0), 1), run(None, 1), run(Some(3.0), 1)]), Appearance::Dark, CW, 0.0).unwrap();
        assert_eq!(l4.segs.iter().map(|s| s.slot).collect::<Vec<_>>(), vec![0, 1, 2, 3], "顺序 Codex → Claude → Gemini → grok");
    }

    #[test]
    fn running_without_a_first_response_writes_a_dash_not_zero() {
        let l = layout(&inp([run(Some(178.0), 1), run(None, 1), off(), off()]), Appearance::Light, CW, 0.0).unwrap();
        assert_eq!(l.segs[1].num.as_deref(), Some("—"));
        assert_eq!(l.segs[1].color, dash_color(Appearance::Light));
        assert_eq!(fmt_tps(Some(0.0)), "0", "真 0 才写 0");
    }

    #[test]
    fn colors_follow_the_menubar_appearance() {
        let one = inp([off(), off(), off(), run(Some(82.0), 1)]);
        let light = layout(&one, Appearance::Light, CW, 0.0).unwrap();
        let dark = layout(&one, Appearance::Dark, CW, 0.0).unwrap();
        assert_eq!(light.segs[0].color, Rgb(0x5F, 0x4B, 0xD0), "浅色菜单栏：深一档");
        assert_eq!(dark.segs[0].color, Rgb(0xB9, 0xAE, 0xFB));
        assert_eq!(num_color(Appearance::Light, 0), Rgb(0x0A, 0x74, 0x68));
        assert_eq!(num_color(Appearance::Dark, 2), Rgb(0x7A, 0xB8, 0xFF));
    }

    fn lum(c: Rgb) -> f64 {
        let ch = |v: u8| { let s = v as f64 / 255.0; if s <= 0.03928 { s / 12.92 } else { ((s + 0.055) / 1.055).powf(2.4) } };
        0.2126 * ch(c.0) + 0.7152 * ch(c.1) + 0.0722 * ch(c.2)
    }
    fn contrast(a: Rgb, b: Rgb) -> f64 { let (x, y) = (lum(a), lum(b)); (x.max(y) + 0.05) / (x.min(y) + 0.05) }

    /// 交接包「托盘胶囊数字色在两种菜单栏下的对比度需实测 ≥ 4.5 : 1」。2026-10-22 去底色后，对的是菜单栏本身
    /// （参考色；真机半透明压在壁纸上，没有固定值 —— 用户看过花壁纸 demo 后接受）。文字色 × 透明度后也要过 4.5。
    #[test]
    fn number_colors_clear_4_5_to_1_on_the_menubar() {
        for ap in [Appearance::Light, Appearance::Dark] {
            let bg = menubar_ref(ap);
            for i in 0..4 {
                let c = contrast(num_color(ap, i), bg);
                assert!(c >= 4.5, "{:?} 槽 {} 对比度 {:.2}", ap, i, c);
            }
            let d = contrast(dash_color(ap), bg);
            assert!(d >= 4.5, "{:?} 「—」对比度 {:.2}", ap, d);
            let mix = |a: f64| { let (t, b) = (text_color(ap), bg);
                let m = |x: u8, y: u8| (x as f64 * a + y as f64 * (1.0 - a)).round() as u8;
                Rgb(m(t.0, b.0), m(t.1, b.1), m(t.2, b.2)) };
            assert!(contrast(mix(SUP_ALPHA), bg) >= 4.5, "{:?} ×N 对比度 {:.2}", ap, contrast(mix(SUP_ALPHA), bg));
        }
    }

    /// 空闲「AI 图标」档的底色块仍在（用户只改了在跑胶囊）；在跑胶囊落定后没有底色。
    #[test]
    fn the_running_pill_has_no_background() {
        let mut a = Anim::new();
        a.idle_bg = true;
        let l = layout(&inp([run(Some(178.0), 1), off(), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        assert!(close(a.frame(0.0).bg_a, 1.0), "空闲 AI 图标档有底色");
        a.retarget(Some(&l), 80.0, 0.0);
        let mut now = 0.0;
        while a.step(now) { now += 0.016; }
        assert!(a.frame(now).bg_a < 1e-6, "在跑胶囊落定后底色为 0");
        assert!(BG_H < H && LOGO <= H - 2.0);
    }

    #[test]
    fn a_stopped_segment_holds_at_40_percent_for_three_seconds_then_goes() {
        let mut t = Tracker::default();
        let live = |c: bool, cl: bool| -> [LiveIn; 4] {
            [LiveIn { running: c, tps: Some(178.0), n_sessions: 1 }, LiveIn { running: cl, tps: Some(64.0), n_sessions: 1 },
             LiveIn::default(), LiveIn::default()]
        };
        t.observe(&live(true, true), 10.0);
        t.observe(&live(false, true), 12.0);
        let l = layout(&t.p, Appearance::Light, CW, 12.0).unwrap();
        assert_eq!(l.mode, Mode::Compact, "停下的那段仍在，3 s 内仍是 2 家紧凑");
        assert_eq!(l.segs[0].alpha, STOP_ALPHA);
        assert_eq!(l.segs[0].num.as_deref(), Some("178"), "保持最后的数字");
        assert_eq!(l.segs[1].alpha, 1.0, "只有那一段变暗，不是整颗胶囊");
        assert_eq!(t.next_deadline(), Some(15.0));
        assert!(layout(&t.p, Appearance::Light, CW, 14.9).unwrap().segs.len() == 2);
        assert!(t.expire(15.0));
        let l = layout(&t.p, Appearance::Light, CW, 15.0).unwrap();
        assert_eq!((l.mode, l.segs.len(), l.segs[0].slot), (Mode::Full, 1, 1), "3 s 后回到 1 家完整式");
    }

    /// 交接包：「logo 任何状态都不变暗；停下只降数字 / 段的透明度」。
    #[test]
    fn a_stopping_segment_keeps_its_logo_at_full_opacity() {
        let mut a = Anim::new();
        let both = inp([run(Some(178.0), 1), run(Some(64.0), 1), off(), off()]);
        a.retarget(layout(&both, Appearance::Light, CW, 0.0).as_ref(), 80.0, 0.0);
        let mut now = 0.0;
        while a.step(now) { now += 0.016; }
        let stopped = inp([PlatformIn { running: false, tps: Some(178.0), n_sessions: 1, stopping_since: Some(now) },
                           run(Some(64.0), 1), off(), off()]);
        a.retarget(layout(&stopped, Appearance::Light, CW, now).as_ref(), 80.0, now);
        while a.step(now) { now += 0.016; }
        let f = a.frame(now);
        let cx = f.segs.iter().find(|s| s.slot == 0).unwrap();
        assert!((cx.alpha - STOP_ALPHA).abs() < 1e-6, "数字 40%：{}", cx.alpha);
        assert!((cx.logo_alpha - 1.0).abs() < 1e-6, "logo 保持 100%：{}", cx.logo_alpha);
        let cl = f.segs.iter().find(|s| s.slot == 1).unwrap();
        assert!((cl.alpha - 1.0).abs() < 1e-6 && (cl.logo_alpha - 1.0).abs() < 1e-6);
    }

    #[test]
    fn coming_back_during_the_hold_cancels_the_stop() {
        let mut t = Tracker::default();
        let one = |r: bool| [LiveIn { running: r, tps: Some(5.0), n_sessions: 2 }, LiveIn::default(), LiveIn::default(), LiveIn::default()];
        t.observe(&one(true), 0.0);
        t.observe(&one(false), 1.0);
        t.observe(&one(true), 2.0);
        assert!(t.p[0].running && t.p[0].stopping_since.is_none());
        assert_eq!(t.next_deadline(), None);
    }

    /// 固定槽位：中间一家（Claude）停下退出时，grok 那段保持绑定在 grok 槽上，只移坐标 —— 不被重新绑定到左邻。
    #[test]
    fn slots_are_stable_when_the_middle_ai_stops() {
        let mut t = Tracker::default();
        let mut a = Anim::new();
        let live3 = |claude: bool| -> [LiveIn; 4] {
            [LiveIn { running: true, tps: Some(1.0), n_sessions: 1 }, LiveIn { running: claude, tps: Some(2.0), n_sessions: 1 },
             LiveIn::default(), LiveIn { running: true, tps: Some(3.0), n_sessions: 1 }]
        };
        t.observe(&live3(true), 0.0);
        a.retarget(layout(&t.p, Appearance::Dark, CW, 0.0).as_ref(), 80.0, 0.0);
        let mut now = 0.0;
        while a.step(now) { now += 0.016; if now > 3.0 { break; } }
        let before = a.frame(now);
        let grok_x0 = before.segs.iter().find(|s| s.slot == 3).unwrap().x;
        t.observe(&live3(false), now);
        let t_stop = now;
        // 3 s 保持
        a.retarget(layout(&t.p, Appearance::Dark, CW, now).as_ref(), 80.0, now);
        while now < t_stop + 2.9 { now += 0.016; a.step(now); }
        let held = a.frame(now);
        let cl = held.segs.iter().find(|s| s.slot == 1).unwrap();
        assert!((cl.alpha - STOP_ALPHA).abs() < 1e-6, "停下那段的文字 40%");
        assert!((cl.logo_alpha - 1.0).abs() < 1e-6, "停下那段的 logo 不变暗：{}", cl.logo_alpha);
        assert!((held.segs.iter().find(|s| s.slot == 3).unwrap().x - grok_x0).abs() < 1e-6, "保持期间其余段不动");
        // 到点退出：每一帧 grok 都在 grok 槽，x 单调向目标移动、不回跳
        now = t_stop + 3.0;
        t.expire(now);
        let target = layout(&t.p, Appearance::Dark, CW, now).unwrap();
        a.retarget(Some(&target), 80.0, now);
        let goal = target.segs.iter().find(|s| s.slot == 3).unwrap().x;
        let mut prev = grok_x0;
        for _ in 0..80 {
            now += 0.016;
            a.step(now);
            let f = a.frame(now);
            let g = f.segs.iter().find(|s| s.slot == 3).expect("grok 段一直在");
            // 去底色后外框宽也在变（不再钉在 106）：外框和段宽是两根弹簧，各自在差 < eps（0.05 pt）时吸附到目标，
            // 吸附那一帧会有 < 0.05 pt 的回退 —— 亚像素，看不见；超过它才算抖
            assert!((g.x - prev) * (goal - grok_x0).signum() >= -0.05, "单调靠近，不抖：{} → {}", prev, g.x);
            prev = g.x;
            assert!((f.width - target.width).abs() < 40.0, "外框跟着弹簧走，不乱跳");
        }
        assert!((prev - goal).abs() < 0.1, "落定在新位置 {} vs {}", prev, goal);
        assert!(a.frame(now).segs.iter().all(|s| s.slot != 1), "Claude 段已退出");
    }

    #[test]
    fn horizontal_springs_do_not_overshoot() {
        let mut s = hspring(0.0);
        s.target = 100.0;
        let mut t = 0.0;
        let mut max: f64 = 0.0;
        while t < 1.0 { s.step(0.016); t += 0.016; max = max.max(s.pos); }
        assert!(max <= 100.0 + 1e-6, "临界阻尼不许过冲（过冲叠加 = 左右跳动）：{}", max);
        assert!(s.settled());
        // ≈ 550 ms 落定（交接包）
        let mut s = hspring(0.0);
        s.target = 100.0;
        let mut t = 0.0;
        while !s.settled() { s.step(0.004); t += 0.004; }
        assert!(t > 0.3 && t < 0.75, "落定时间 {:.3}s", t);
    }

    #[test]
    fn digit_roll_has_a_slight_bounce() {
        let mut s = rspring(0.0);
        s.target = 1.0;
        let mut max: f64 = 0.0;
        for _ in 0..100 { s.step(0.01); max = max.max(s.pos); }
        assert!(max > 1.0 && max < 1.1, "0.32 / 0.76 有轻微回弹：{}", max);
    }

    #[test]
    fn a_new_segment_appears_at_its_target_and_only_scales_in() {
        let mut a = Anim::new();
        let l = layout(&inp([run(Some(178.0), 1), off(), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        a.retarget(Some(&l), 80.0, 0.0);
        let f = a.frame(0.0);
        assert_eq!(f.segs.len(), 1);
        assert!(close(f.segs[0].scale, 0.6), "blurReplace 从 0.6 起");
        assert!(f.segs[0].alpha < 1e-6);
        assert!(close(f.width, 80.0), "外框从标题宽起跳");
        let mut now = 0.0;
        while a.step(now) { now += 0.016; }
        let f = a.frame(now);
        assert!(close(f.width, l.width) && close(f.segs[0].scale, 1.0) && close(f.segs[0].alpha, 1.0));
        assert!(close(f.segs[0].x, l.segs[0].x), "段落在目标坐标");
        assert!(close(f.title_a, 0.0) && f.bg_a < 1e-6, "去底色：落定后 bg 为 0");
    }

    #[test]
    fn reduced_motion_cuts_instantly_but_keeps_the_hold() {
        let mut a = Anim::new();
        a.reduce = true;
        let l = layout(&inp([run(Some(178.0), 1), off(), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        a.retarget(Some(&l), 80.0, 0.0);
        assert!(!a.step(0.0), "减弱动态效果：一步到位");
        let f = a.frame(0.0);
        assert!(close(f.width, l.width) && close(f.segs[0].alpha, 1.0) && close(f.segs[0].scale, 1.0));
        let mut t = Tracker::default();
        t.observe(&[LiveIn { running: true, tps: Some(1.0), n_sessions: 1 }, LiveIn::default(), LiveIn::default(), LiveIn::default()], 0.0);
        t.observe(&Default::default(), 1.0);
        assert!(layout(&t.p, Appearance::Dark, CW, 3.9).is_some(), "停下的 3 s 保留");
    }

    #[test]
    fn last_ai_leaving_returns_to_idle() {
        let mut a = Anim::new();
        let l = layout(&inp([run(Some(178.0), 1), off(), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        a.retarget(Some(&l), 80.0, 0.0);
        let mut now = 0.0;
        while a.step(now) { now += 0.016; }
        a.retarget(None, 80.0, now);
        while a.step(now) { now += 0.016; if now > 5.0 { break; } }
        let f = a.frame(now);
        assert!(f.idle && f.segs.is_empty(), "最后一家退出后回空闲");
    }

    #[test]
    fn session_count_rolls_and_collapses_between_one_and_two_ais() {
        let mut a = Anim::new();
        let one = layout(&inp([off(), run(Some(190.0), 3), off(), off()]), Appearance::Dark, CW, 0.0).unwrap();
        a.retarget(Some(&one), 80.0, 0.0);
        let mut now = 0.0;
        while a.step(now) { now += 0.016; }
        let two = layout(&inp([run(Some(5.0), 1), run(Some(190.0), 3), off(), off()]), Appearance::Dark, CW, now).unwrap();
        a.retarget(Some(&two), 80.0, now);
        now += 0.1;
        a.step(now);
        let mid = a.frame(now);
        let cl = mid.segs.iter().find(|s| s.slot == 1).unwrap();
        assert!(cl.unit_a < 1.0 && cl.sess_a < 1.0, "「t/s · N」收拢的同时淡出");
        while a.step(now) { now += 0.016; }
        let f = a.frame(now);
        let cl = f.segs.iter().find(|s| s.slot == 1).unwrap();
        assert!(cl.unit_a < 1e-6 && cl.sess_a < 1e-6 && close(cl.w, two.segs[1].w));
    }

    #[test]
    fn live_json_is_read_per_platform_and_missing_ones_are_off() {
        let body = r#"{"v":1,"platforms":{"codex":{"running":true,"n_sessions":2,"tps":244.0},
                       "claude":{"running":true,"n_sessions":1,"tps":null},"agy":{"running":false,"tps":null}}}"#;
        let l = parse_live(body).unwrap();
        assert_eq!(l[0], LiveIn { running: true, tps: Some(244.0), n_sessions: 2 });
        assert_eq!(l[1], LiveIn { running: true, tps: None, n_sessions: 1 });
        assert!(!l[2].running && !l[3].running, "grok 没出现 = 不在跑");
        assert_eq!(parse_live("not json"), None);
    }

    #[test]
    fn fail_open_text_names_each_ai() {
        let i = inp([run(Some(178.0), 1), run(Some(64.2), 1), off(), off()]);
        assert_eq!(fallback_title(&i, 0.0), "Codex 178 · Claude 64");
    }

    /// 把几种状态真画成 PNG 看像素（`cargo test --lib render_samples -- --ignored`）。
    #[cfg(target_os = "macos")]
    #[test]
    #[ignore]
    fn render_samples() {
        let home = std::env::var("HOME").unwrap();
        let dir = std::path::PathBuf::from(home).join("Downloads/codexbar_screenshots_20261022_pill_nobg/tray");
        std::fs::create_dir_all(&dir).unwrap();
        let cw = draw::char_w();
        eprintln!("font JetBrains = {}, cw = {:.3}, logos = {:?}", draw::font_is_jetbrains(), cw,
                  (0..4).map(draw::logo_ok).collect::<Vec<_>>());
        let title = TitleSpec { text: "号A 5h 95% ↻3h12m".into(), hi: None };
        let cases: Vec<(&str, [PlatformIn; 4])> = vec![
            ("1ai_codex", inp([run(Some(178.0), 1), off(), off(), off()])),
            ("1ai_claude_3sessions", inp([off(), run(Some(190.0), 3), off(), off()])),
            ("2ai_compact", inp([run(Some(178.0), 1), run(Some(64.0), 1), off(), off()])),
            ("2ai_claude_dash", inp([run(Some(178.0), 1), run(None, 1), off(), off()])),
            ("3ai_logos_only", inp([run(Some(1.0), 1), run(Some(2.0), 1), run(Some(3.0), 1), off()])),
            ("4ai_logos_only", inp([run(Some(1.0), 1), run(Some(2.0), 1), run(Some(3.0), 1), run(Some(4.0), 1)])),
            ("stop_codex_40pct", inp([PlatformIn { running: false, tps: Some(178.0), n_sessions: 1, stopping_since: Some(0.0) },
                                      run(Some(64.0), 1), off(), off()])),
        ];
        for ap in [Appearance::Light, Appearance::Dark] {
            for (name, i) in &cases {
                let l = layout(i, ap, cw, 1.0).unwrap();
                let mut a = Anim::new();
                a.reduce = true;
                a.retarget(Some(&l), 80.0, 1.0);
                a.step(1.0);
                let f = a.frame(1.0);
                let png = draw::render(&f, ap, false, &TitleLayer::Text(&title)).expect("render");
                let tag = if ap == Appearance::Light { "light" } else { "dark" };
                std::fs::write(dir.join(format!("{}_{}.png", name, tag)), png).unwrap();
            }
        }
        // 过渡中间帧：空闲 → 1 家，第 120 ms
        let l = layout(&inp([run(Some(178.0), 1), off(), off(), off()]), Appearance::Dark, cw, 0.0).unwrap();
        let mut a = Anim::new();
        a.retarget(None, 0.0, 0.0);
        a.retarget(Some(&l), draw::title_width(&title, Appearance::Dark), 0.0);
        let mut now = 0.0;
        while now < 0.12 { now += 0.016; a.step(now); }
        let png = draw::render(&a.frame(now), Appearance::Dark, false, &TitleLayer::Text(&title)).expect("render");
        std::fs::write(dir.join("morph_idle_to_1ai_120ms_dark.png"), png).unwrap();
    }

    /// 空闲托盘（P11）样张：TCC 挡截屏，托盘像素只能离线画出来看。
    /// 运行：`cargo test --lib render_idle_samples -- --ignored --nocapture`
    #[test]
    #[ignore]
    #[cfg(target_os = "macos")]
    fn render_idle_samples() {
        use crate::tray_idle::{IdleAnim, IdleIn};
        let home = std::env::var("HOME").unwrap();
        let dir = std::path::PathBuf::from(home).join("Downloads/codexbar_screenshots_20261022_pill_nobg/tray_idle");
        std::fs::create_dir_all(&dir).unwrap();
        let s = |logo, rem: Option<f64>, red| IdleIn { logo, remaining: rem, red };
        let cases: Vec<(&str, Vec<IdleIn>, bool, f64)> = vec![
            ("board_codex67_claude40_deepseek6", vec![s(0, Some(67.0), false), s(1, Some(40.0), false), s(5, Some(6.0), true)], false, 0.0),
            ("levels_100_40_0", vec![s(0, Some(100.0), false), s(1, Some(40.0), false), s(2, Some(0.0), true)], false, 0.0),
            ("unknown_grok_gray", vec![s(0, Some(80.0), false), s(3, None, false)], false, 0.0),
            ("near_glow", vec![s(0, Some(67.0), false), s(1, Some(40.0), false), s(2, Some(86.0), false)], true, 0.0),
            ("kimi_white_mono_30", vec![s(4, Some(30.0), false), s(0, Some(30.0), false)], false, 0.0),
        ];
        for ap in [Appearance::Light, Appearance::Dark] {
            for (name, slots, near, _) in &cases {
                let mut ia = IdleAnim::new();
                ia.retarget(slots, 0.0);
                if *near { ia.set_near(true, 0.0); }
                ia.step(0.5);
                let idle = ia.frame(0.5);
                let mut a = Anim::new();
                a.idle_bg = true;
                let mut f = a.frame(0.5);
                f.width = idle.width;
                let png = draw::render(&f, ap, false, &TitleLayer::Idle(&idle)).expect("render");
                let tag = if ap == Appearance::Light { "light" } else { "dark" };
                std::fs::write(dir.join(format!("{}_{}.png", name, tag)), png).unwrap();
            }
        }
    }
}
