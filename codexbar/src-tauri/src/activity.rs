//! 「谁正在跑」—— 四家 CLI 的会话文件写入检测（macOS 专属），以及跟着它走的 t/s 实时循环。
//!
//! 2026-10-19 从 `notch.rs` 抽出来（判据、FSEvents 监听、单测**原样搬**，行为不变）。抽的原因：
//! 刘海光晕之外，托盘胶囊（`tray_pill.rs`）和悬停面板也要知道谁在跑；两份监听 = 两份 FSEvents 订阅。
//! 现在只有一条检测线程，谁要用谁 `subscribe`：刘海窗口存在时订 `NOTCH`，托盘 t/s 开关开着时订 `TPS`；
//! 两个都退订了线程就退出（默认关的功能不常驻任何东西 —— 刘海那条老规矩）。
//!
//! ★ 实时循环（`requests.py --live`）只在**有平台在跑**时每 2 s 跑一次；全部空闲后**再跑最后一次**就停
//!   （最后那次把「停了」写进 `.live.json` 并广播，托盘才能走 40% → 3 s 的停下规则）。纯判定在 `live_step`。
//! ★★ 2026-10-19 起「谁在跑」的裁判是 live（`requests.py` 读各家自己写的**轮次结束标记**，用户拍板），
//!   FSEvents 降为「叫醒」信号：45 s 内有写入就把实时循环叫起来；live 读不到 / 失败 / 卡住时光晕才退回它。
//!   原来光晕直接用「45 s 内写过」：停手后要等 ~48 s 才熄，长工具调用（不写文件）中途又会熄（实测 transcript
//!   一轮之内的静默间隔 p99 99 s、p99.9 600 s）。纯判定在 `glow`。
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::{Condvar, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

/// 活动检测的周期，以及「最近这么多秒内写过 = 叫醒实时循环」（也是 live 不可用时光晕的退路）。
const ACTIVITY_TICK: Duration = Duration::from_secs(2);
pub const ACTIVE_SECS: u64 = 45;
/// 一次 `--live` 跑了这么久还没回来 = 卡住了，光晕退回 FSEvents（实测一次 0.17 s）。
pub const LIVE_HUNG_SECS: u64 = 10;

/// 订阅者（位掩码）。
pub const NOTCH: u8 = 1;
pub const TPS: u8 = 2;
/// 空闲托盘（P11）：打招呼要「谁在跑」「上次 AI 活动」，关掉 t/s 胶囊时也要。
pub const IDLE_TRAY: u8 = 4;
static CONSUMERS: AtomicU8 = AtomicU8::new(0);

/// 正在跑的检测线程领到的号；0 = 没有。★ 新起的一条**直接接管**（store），旧的看到不是自己就退 ——
/// 原来用一个 `WATCHING` 布尔：快速关了再开时它还是 true，新线程起不来，旧线程随后退出，就一条都没有了（评审 2026-10-17）。
static WATCHER: AtomicU64 = AtomicU64::new(0);
static WATCHER_SEQ: AtomicU64 = AtomicU64::new(0);
static ACTIVITY: Mutex<Activity> = Mutex::new(IDLE);
/// 四家各自最近一次写入的时刻（秒，0 = 没见过），下标见 `Roots::classify`。FSEvents 回调写，检测线程读。
static LAST_WRITE: [AtomicU64; 4] = [const { AtomicU64::new(0) }; 4];
/// ★ 写入叫醒实时循环（用户 2026-10-21「t/s 更新太慢」）：FSEvents 一有这四家的写入就叫醒，不再等满 2 s 的 tick。
///   实测（n=34）一条 Claude 响应结束后要 p50 2.24 s 才换成实测值，其中 tick 平均占 ~1 s。
///   叫醒后先去抖 `WAKE_DEBOUNCE`（一次写入常是一串事件），且两次 `--live` 之间至少隔 `LIVE_MIN_GAP`
///   （一次 0.15–0.16 s 子进程；流式写入不停时这条上限 = 每秒最多 1 次）。
static WAKE: (Mutex<bool>, Condvar) = (Mutex::new(false), Condvar::new());
const WAKE_DEBOUNCE: Duration = Duration::from_millis(150);
const LIVE_MIN_GAP: Duration = Duration::from_millis(1000);

fn wake() {
    let (m, cv) = &WAKE;
    *m.lock().unwrap() = true;
    cv.notify_one();
}

/// 睡到下一 tick，或被写入叫醒（返回 true）。
fn wait_wake(tick: Duration) -> bool {
    let (m, cv) = &WAKE;
    let g = m.lock().unwrap();
    let (mut g, _) = cv.wait_timeout_while(g, tick, |woke| !*woke).unwrap();
    std::mem::replace(&mut *g, false)
}

/// 被写入叫醒之后还要再等多久才跑下一次：至少去抖，且离上一次开跑不少于 `LIVE_MIN_GAP`。
pub fn early_delay(since_last_run: Duration) -> Duration {
    WAKE_DEBOUNCE.max(LIVE_MIN_GAP.saturating_sub(since_last_run))
}

/// 实时循环正在跑一次 `--live`（防止慢的一次没跑完下一 tick 又起一个）。
static LIVE_BUSY: AtomicBool = AtomicBool::new(false);
/// 最近一次 `--live` 的结果里**还有平台在跑**。实时循环要等它也说「停了」才停。
/// ★ 用户 2026-10-19 实测：Claude 停手几分钟，托盘仍钉着 `92 t/s`、不淡出也不回空闲。两位裁判在 45 s 边界上不一致：
///   这里按 FSEvents 回调时刻取**整秒**（`now - t < 45`），`requests.py` 按文件 mtime 取**小数秒**（`mt >= now - 45`）⇒
///   这里判「停了」的那一 tick，Python 那边常常还差零点几秒、仍报 `running: true`；而那正是「最后一次」，之后循环就停了，
///   「停了」永远没落盘。另一条同形的路：最后那一 tick 撞上上一次还没跑完（`LIVE_BUSY`）被跳过。
///   两条都靠这一个量收口：只要最近一份结果还说在跑，就继续每 2 s 跑；结果自己说停了，再按原规则补最后一次。
static LIVE_ANY: AtomicBool = AtomicBool::new(false);
/// 最近一次 `--live` 的各家「在跑」。None = 还没成功过 / 最近一次失败了（⇒ 光晕退回 FSEvents）。
static LIVE_ACT: Mutex<Option<Activity>> = Mutex::new(None);
/// 正在跑的那次 `--live` 是几时开跑的（秒，0 = 没在跑）。超过 `LIVE_HUNG_SECS` = 卡住。
static LIVE_SINCE: AtomicU64 = AtomicU64::new(0);

/// 谁正在跑。PR #1 作者 2026-10-17 起头（Codex / agy）；维护者 2026-10-18 扩到四家（四方评审时 Claude / Codex / agy / grok 同时跑）。
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Activity { pub codex: bool, pub claude: bool, pub agy: bool, pub grok: bool }
pub const IDLE: Activity = Activity { codex: false, claude: false, agy: false, grok: false };

impl Activity {
    pub fn any(&self) -> bool { self.codex || self.claude || self.agy || self.grok }
    /// 固定顺序 Codex → Claude → Gemini（agy）→ grok，与托盘槽位、光晕同序。
    pub fn as_array(&self) -> [bool; 4] { [self.codex, self.claude, self.agy, self.grok] }
}

/// 四家「在生成」时会写的目录（2026-10-19 起只用来叫醒实时循环 / live 不可用时的退路，谁在跑由 live 判）。
/// ★ 判据都是「这家自己的会话文件刚被写过」：
///   - Codex：`sessions/**/rollout-*.jsonl`。★ 不用 `state.json` 的 `last_proxy_ts`：codex 会定时
///     `GET /models`，代理照样刷新它，停手后仍显示「在跑」（2026-10-17 实测）。
///   - Claude Code：`projects/**/*.jsonl`，含子 agent 的 `subagents/agent-*.jsonl`（四方评审的 Opus 就写在那里）。
///   - agy：对话库是 WAL 模式，生成时写的是 `-wal`（主库 mtime 不动，见 scan.py `_agy_db_sig`）。
///   - grok：`**/updates.jsonl`（traffic/scan.py 读的同一份）。
struct Roots { codex: PathBuf, claude: PathBuf, agy: PathBuf, grok: PathBuf }

impl Roots {
    fn from_env() -> Roots {
        let home = PathBuf::from(std::env::var("HOME").unwrap_or_default());
        let env_or = |k: &str, d: PathBuf| std::env::var(k).map(PathBuf::from).unwrap_or(d);
        Roots {
            codex: env_or("CODEX_HOME", home.join(".codex")).join("sessions"),
            claude: home.join(".claude").join("projects"),
            agy: env_or("AGY_DB_DIR", home.join(".gemini").join("antigravity-cli").join("conversations")),
            grok: home.join(".grok"),
        }
        .canonical()
    }
    /// FSEvents 报的是真实路径（`/private/var/...`、解开软链之后）；根也换成真实路径才比得上。不存在就原样留着。
    fn canonical(self) -> Roots {
        let c = |p: PathBuf| std::fs::canonicalize(&p).unwrap_or(p);
        Roots { codex: c(self.codex), claude: c(self.claude), agy: c(self.agy), grok: c(self.grok) }
    }
    fn all(&self) -> [&Path; 4] { [&self.codex, &self.claude, &self.agy, &self.grok] }
    /// ★★ FSEvents 只在**关掉**一个写过的文件时报「内容变了」（2026-10-22 实测：一直开着写的文件 7 s 零事件，
    ///   关的那一刻才报；agy 会话库的 `-wal` 30 s 涨了 10 MB，探针零事件）。agy 的库整个会话一直开着 ⇒
    ///   只有 agy 在跑时实时循环永远不醒、托盘一直空闲（用户 2026-10-22「gemini 有请求了，状态栏还是空闲」）；
    ///   有 Claude 同时在写时被它叫醒，才「碰巧」看得到。Codex 的 rollout 也是一直开着写的（**未实测**，同样补上）。
    ///   所以这两家每 tick 补一次 mtime：agy 约 500 个 `-wal`，实测一次 1.3 ms；Codex 只看最近两个日期目录。
    ///   返回 (下标, 最新 mtime 秒)。
    fn poll_open_writers(&self) -> Vec<(usize, u64)> {
        let mut out = Vec::new();
        if let Some(t) = newest_mtime(&self.agy, |n| n.ends_with(".db-wal")) { out.push((2, t)); }
        let codex = recent_day_dirs(&self.codex, 2).iter()
            .filter_map(|d| newest_mtime(d, |n| n.starts_with("rollout-") && n.ends_with(".jsonl"))).max();
        if let Some(t) = codex { out.push((0, t)); }
        out
    }
}

/// 目录下（不递归）名字满足 `keep` 的文件里最新的 mtime（秒）。目录不在 / 读不了 ⇒ None。
fn newest_mtime(dir: &Path, keep: impl Fn(&str) -> bool) -> Option<u64> {
    std::fs::read_dir(dir).ok()?
        .filter_map(|e| e.ok())
        .filter(|e| e.file_name().to_str().is_some_and(&keep))
        .filter_map(|e| e.metadata().ok()?.modified().ok())
        .filter_map(|t| t.duration_since(std::time::UNIX_EPOCH).ok().map(|d| d.as_secs()))
        .max()
}

/// Codex 的 `sessions/YYYY/MM/DD`：按名字倒序取最近 `n` 个日期目录（跨月 / 跨年也对：先取最近两个年、月）。
fn recent_day_dirs(root: &Path, n: usize) -> Vec<PathBuf> {
    let sub = |d: &Path| -> Vec<PathBuf> {
        let mut v: Vec<PathBuf> = std::fs::read_dir(d).map(|it| it.filter_map(|e| e.ok()).map(|e| e.path())
            .filter(|p| p.is_dir()).collect()).unwrap_or_default();
        v.sort_by(|a, b| b.cmp(a));
        v
    };
    let mut days = Vec::new();
    for y in sub(root).into_iter().take(2) {
        for m in sub(&y).into_iter().take(2) {
            days.extend(sub(&m));
        }
    }
    days.sort_by(|a, b| b.cmp(a));
    days.truncate(n);
    days
}

impl Roots {
    /// 一条写入事件属于哪家（`LAST_WRITE` 的下标）；不是「在生成」的信号返回 None。
    fn classify(&self, p: &Path) -> Option<usize> {
        let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if p.starts_with(&self.codex) && n.starts_with("rollout-") && n.ends_with(".jsonl") { return Some(0); }
        if p.starts_with(&self.claude) && n.ends_with(".jsonl") { return Some(1); }
        if p.starts_with(&self.agy) && (n.ends_with(".db-wal") || n.ends_with(".db")) { return Some(2); }
        if p.starts_with(&self.grok) && n == "updates.jsonl" { return Some(3); }
        None
    }
}

/// 只认「内容变了」：新建、写数据。改元数据 / 改名 / 读都不算（扫描器读这些文件，不能把自己读成「在跑」）。
fn is_write(kind: &notify::EventKind) -> bool {
    use notify::event::{EventKind, ModifyKind};
    matches!(kind, EventKind::Create(_) | EventKind::Modify(ModifyKind::Data(_)) | EventKind::Modify(ModifyKind::Any))
}

fn active(newest: Option<u64>, now: u64) -> bool {
    newest.is_some_and(|t| now.saturating_sub(t) < ACTIVE_SECS)
}

fn now_secs() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn snapshot(now: u64) -> Activity {
    let at = |i: usize| { let t = LAST_WRITE[i].load(Ordering::Relaxed); (t > 0).then_some(t) };
    Activity { codex: active(at(0), now), claude: active(at(1), now), agy: active(at(2), now), grok: active(at(3), now) }
}

/// 实时循环这一 tick 做什么。`was_live` = 上一 tick 是否处在「有人在跑」。
/// 有人在跑 ⇒ 跑；刚变成全空闲 ⇒ **再跑最后一次**（把「停了」落盘并广播）；一直空闲 ⇒ 不跑。
/// 返回 (这一 tick 要不要跑, 新的 was_live)。
pub fn live_step(any_active: bool, was_live: bool) -> (bool, bool) {
    match (any_active, was_live) {
        (true, _) => (true, true),
        (false, true) => (true, false),
        (false, false) => (false, false),
    }
}

/// 实时循环的一 tick：活动检测（FSEvents）**或**最近一份 live 结果说有人在跑，都算在跑（见 `LIVE_ANY`）。
/// ★ 长工具调用期间文件不写、FSEvents 早判了停，而轮次没结束 ⇒ live 仍说在跑 ⇒ 循环不停，直到 live 自己说停。
pub fn loop_step(fs_active: bool, live_running: bool, was_live: bool) -> (bool, bool) {
    live_step(fs_active || live_running, was_live)
}

/// 光晕（刘海）的「谁在跑」：live 可用就**用 live**（与托盘胶囊同一个裁判，同时亮、同时熄）；
/// live 还没成功过 / 最近一次失败 / 这一次卡住超过 `LIVE_HUNG_SECS` ⇒ 退回 FSEvents（`fs`）。
/// ★ 不按「live 多旧」判：全部空闲后循环本来就停了，最后那份 live 就是事实（停之后没有新写入叫醒它）。
pub fn glow(fs: Activity, live: Option<Activity>, busy_since: u64, now: u64) -> Activity {
    let hung = busy_since > 0 && now.saturating_sub(busy_since) > LIVE_HUNG_SECS;
    match live {
        Some(a) if !hung => a,
        _ => fs,
    }
}

/// 订阅。没有线程在跑就起一条（新线程接管）。
pub fn subscribe(app: &AppHandle, who: u8) {
    let prev = CONSUMERS.fetch_or(who, Ordering::SeqCst);
    if prev == 0 || WATCHER.load(Ordering::SeqCst) == 0 {
        watch_activity(app);
    }
}

/// 退订。最后一个退订后，检测线程在下一 tick 退出。
pub fn unsubscribe(who: u8) {
    CONSUMERS.fetch_and(!who, Ordering::SeqCst);
}

/// 活动检测线程。只在状态**变了**才推 `notch-activity`。
/// ★★ 写入靠 **FSEvents 推送**，不轮询文件（维护者 2026-10-18）：PR #1 原来每 2s 挨个 stat，Codex + agy 约 3 ms；
///   加上 Claude Code（含子 agent 约 8000 个会话文件）全扫一遍约 50 ms，每 2s 一次就是常驻 2–3% CPU。
///   现在这条线程每 2s 只读 4 个原子量；监听器随线程建、随线程退出时 drop。
/// ★ 只在**有人订阅**时跑：刘海窗口存在（合盖 / 外接屏 / 关掉就退订），或托盘 t/s 开着。
/// ★ 两条任一不满足就退：没被新的一条接管（`WATCHER`）、还有订阅者（`CONSUMERS`）。
fn watch_activity(app: &AppHandle) {
    let me = WATCHER_SEQ.fetch_add(1, Ordering::SeqCst) + 1;
    WATCHER.store(me, Ordering::SeqCst);
    let app = app.clone();
    std::thread::spawn(move || {
        use notify::Watcher;
        let roots = std::sync::Arc::new(Roots::from_env());
        let r2 = roots.clone();
        let fs = notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
            let Ok(ev) = res else { return };
            if !is_write(&ev.kind) { return; }
            let now = now_secs();
            for p in &ev.paths {
                if let Some(i) = r2.classify(p) { LAST_WRITE[i].store(now, Ordering::Relaxed); wake(); }
            }
        });
        // 建不起监听器（极少见）：光晕与胶囊一直不亮，记一条日志，不影响刘海面板本身
        let _fs = match fs {
            Ok(mut w) => {
                for root in roots.all() {
                    if root.is_dir() {
                        if let Err(e) = w.watch(root, notify::RecursiveMode::Recursive) {
                            log::warn!("activity: watch {} failed: {}", root.display(), e);
                        }
                    }
                }
                Some(w)
            }
            Err(e) => { log::warn!("activity: watcher unavailable: {}", e); None }
        };
        // ★ 起头当作「刚停」：订阅那一刻先跑一次 live —— 长工具调用中途打开刘海 / t/s 时没有新写入来叫醒它
        let mut was_live = true;
        let mut last_run = Instant::now();
        while WATCHER.load(Ordering::SeqCst) == me && CONSUMERS.load(Ordering::SeqCst) != 0 {
            // 一直开着写的文件 FSEvents 不报（见 `poll_open_writers`），这一 tick 自己看一眼 mtime
            for (i, t) in roots.poll_open_writers() { LAST_WRITE[i].fetch_max(t, Ordering::Relaxed); }
            let fs = publish(&app);
            let (run, live) = loop_step(fs.any(), LIVE_ANY.load(Ordering::SeqCst), was_live);
            was_live = live;
            if run { run_live_soon(&app, fs); last_run = Instant::now(); }
            if wait_wake(ACTIVITY_TICK) { std::thread::sleep(early_delay(last_run.elapsed())); }
        }
        // 被接管时状态归新的那条管，不清
        if WATCHER.compare_exchange(me, 0, Ordering::SeqCst, Ordering::SeqCst).is_ok() {
            *ACTIVITY.lock().unwrap() = IDLE;
            crate::tray_pill::on_activity_only(&app, IDLE.as_array());
        }
    });
}

/// 算一次光晕的「谁在跑」（`glow`），变了才推 `notch-activity`。返回 FSEvents 那一份（给实时循环判要不要跑）。
/// 检测线程每 tick 调一次；live 一回来也立刻调一次（不等下一 tick —— 光晕要与托盘同时熄）。
fn publish(app: &AppHandle) -> Activity {
    let now = now_secs();
    let fs = snapshot(now);
    let a = glow(fs, *LIVE_ACT.lock().unwrap(), LIVE_SINCE.load(Ordering::SeqCst), now);
    let changed = { let mut cur = ACTIVITY.lock().unwrap(); let c = *cur != a; *cur = a; c };
    if changed { let _ = app.emit_to(crate::notch::LABEL, "notch-activity", a); }
    fs
}

/// 跑一次 `requests.py --live`（单独线程；上一次没跑完就跳过这一 tick）。
/// 成功 ⇒ 广播 `tps-live`（payload = live JSON 字符串）并喂托盘胶囊；
/// 失败 ⇒ 广播 `tps-live-error`（原因字符串），托盘退回只按活动检测画（速度写 —）。
/// ★ 失败**不**伪装成「没有平台在跑」：那会让托盘回到空闲标题，而事实是我们读不到。
/// `a` = 活动检测（FSEvents）那一份，live 读不到时托盘与光晕都退回它。
fn run_live_soon(app: &AppHandle, a: Activity) {
    if LIVE_BUSY.swap(true, Ordering::SeqCst) { return; }
    LIVE_SINCE.store(now_secs().max(1), Ordering::SeqCst);
    let app = app.clone();
    std::thread::spawn(move || {
        let res = crate::run_live_blocking();
        let act = res.as_ref().ok().and_then(|b| live_activity(b));
        *LIVE_ACT.lock().unwrap() = act;
        LIVE_ANY.store(act.map(|x| x.any()).unwrap_or(a.any()), Ordering::SeqCst);
        LIVE_SINCE.store(0, Ordering::SeqCst);
        publish(&app);
        match res {
            Ok(body) => {
                let _ = app.emit("tps-live", body.clone());
                crate::tray_pill::on_live(&app, &body, a.as_array());
            }
            Err(e) => {
                log::warn!("activity: requests.py --live failed: {}", e);
                let _ = app.emit("tps-live-error", e);
                crate::tray_pill::on_activity_only(&app, a.as_array());
            }
        }
        LIVE_BUSY.store(false, Ordering::SeqCst);
    });
}

/// live JSON → 各家 `running`（顺序 Codex → Claude → Gemini(agy) → grok；缺的那家算没在跑）。解不开 ⇒ None。
pub fn live_activity(body: &str) -> Option<Activity> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    let ps = v.get("platforms")?.as_object()?;
    let on = |k: &str| ps.get(k).and_then(|p| p.get("running")).and_then(|r| r.as_bool()) == Some(true);
    Some(Activity { codex: on("codex"), claude: on("claude"), agy: on("agy"), grok: on("grok") })
}


pub fn activity() -> Activity { *ACTIVITY.lock().unwrap() }

#[cfg(test)]
mod loop_tests {
    use super::*;

    /// 用户 2026-10-19：停手后托盘一直钉着 t/s。FSEvents 已判停、但最后那份 live 还说在跑 ⇒ 不许停，
    /// 一直跑到 live 自己说停了，再补最后一次。
    #[test]
    fn the_loop_waits_until_the_live_result_itself_says_stopped() {
        let mut was = true;
        let mut runs = vec![];
        // (FSEvents 在跑?, 最近一份 live 在跑?)：t0 FSEvents 先判停；live 又说了两次在跑；然后两边都停
        for (fs, live) in [(false, true), (false, true), (false, false), (false, false), (false, false)] {
            let (run, w) = loop_step(fs, live, was);
            was = w;
            runs.push(run);
        }
        assert_eq!(runs, vec![true, true, true, false, false], "live 说停之后补一次，然后才停");
    }

    #[test]
    fn reads_running_from_the_live_json() {
        let any = |b: &str| live_activity(b).map(|a| a.any());
        assert_eq!(any(r#"{"platforms":{"codex":{"running":false},"claude":{"running":true}}}"#), Some(true));
        assert_eq!(any(r#"{"platforms":{"codex":{"running":false}}}"#), Some(false));
        assert_eq!(any("not json"), None);
        assert_eq!(live_activity(r#"{"platforms":{"agy":{"running":true},"grok":{"running":false}}}"#),
                   Some(Activity { agy: true, ..IDLE }), "按平台名对号，不按出现顺序");
    }

    /// 长工具调用：文件好几分钟不写（FSEvents 早判停），轮次没结束 ⇒ live 一直说在跑 ⇒ 循环每 tick 都跑。
    #[test]
    fn the_loop_keeps_running_while_live_says_running_without_writes() {
        let mut was = true;
        for _ in 0..200 {
            let (run, w) = loop_step(false, true, was);
            assert!(run, "LIVE_ANY 在 ⇒ 不许停");
            was = w;
        }
        let (run, w) = loop_step(false, false, was);
        assert!(run && !w, "live 说停了 ⇒ 补最后一次");
        assert_eq!(loop_step(false, false, w), (false, false), "之后不再跑（不常驻轮询）");
    }

    /// 用户 2026-10-19：停手后要等 ~48 s 才淡出。live 读到结束标记说停了 ⇒ 光晕立刻跟着熄，哪怕文件刚写过。
    #[test]
    fn the_glow_follows_live_not_the_45s_write_window() {
        let wrote = Activity { claude: true, ..IDLE };
        assert_eq!(glow(wrote, Some(IDLE), 0, 1000), IDLE, "写了结束标记 ⇒ 熄（FSEvents 还在 45 s 内也熄）");
        let tool = Activity { codex: true, ..IDLE };
        assert_eq!(glow(IDLE, Some(tool), 0, 1000), tool, "长工具调用不写文件 ⇒ 仍亮（live 说轮次没结束）");
    }

    #[test]
    fn the_glow_falls_back_to_writes_when_live_is_unavailable() {
        let wrote = Activity { grok: true, ..IDLE };
        assert_eq!(glow(wrote, None, 0, 1000), wrote, "live 失败 / 还没成功过 ⇒ 退回 FSEvents");
        assert_eq!(glow(wrote, Some(IDLE), 1000 - LIVE_HUNG_SECS - 1, 1000), wrote, "这一次 live 卡住了 ⇒ 退回 FSEvents");
        assert_eq!(glow(wrote, Some(IDLE), 1000 - 2, 1000), IDLE, "正在跑但没超时 ⇒ 仍用上一份 live");
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn a_write_wakes_the_loop_but_live_runs_at_most_once_a_second() {
        use super::{early_delay, LIVE_MIN_GAP, WAKE_DEBOUNCE};
        use std::time::Duration;
        assert_eq!(early_delay(Duration::ZERO), LIVE_MIN_GAP, "刚跑过 ⇒ 等满 1 s 再跑");
        assert_eq!(early_delay(Duration::from_millis(400)), Duration::from_millis(600));
        assert_eq!(early_delay(Duration::from_secs(5)), WAKE_DEBOUNCE, "很久没跑 ⇒ 只去抖 150 ms");
        assert!(early_delay(Duration::from_millis(900)) >= WAKE_DEBOUNCE, "去抖是下限");
    }

    #[test]
    fn the_watcher_callback_wakes_the_loop() {
        let src = include_str!("activity.rs");
        let cb = src.split("recommended_watcher(").nth(1).unwrap().split("});").next().unwrap();
        assert!(cb.contains("wake();"), "FSEvents 回调不叫醒实时循环 ⇒ 又回到等满 2 s");
        let lp = src.split("let mut last_run").nth(1).unwrap().split("// 被接管时").next().unwrap();
        assert!(lp.contains("wait_wake(ACTIVITY_TICK)"), "循环还在死睡 ACTIVITY_TICK");
    }

    /// 用户 2026-10-22「gemini 有请求了，状态栏还是空闲」：agy 的 `-wal` 一直开着写，FSEvents 不报。
    /// 轮询必须看到 agy 的 `-wal` 与 Codex 最近日期目录里的 rollout，且循环每 tick 都调它。
    #[test]
    fn open_file_writers_are_polled_by_mtime() {
        let d = std::env::temp_dir().join(format!("codexbar-poll-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        let agy = d.join("conv");
        let codex = d.join("sessions");
        std::fs::create_dir_all(&agy).unwrap();
        for day in ["2026/09/30", "2026/10/01", "2025/12/31"] { std::fs::create_dir_all(codex.join(day)).unwrap(); }
        std::fs::write(agy.join("a.db"), b"").unwrap();
        std::fs::write(agy.join("a.db-shm"), b"").unwrap();
        let r = Roots { codex: codex.clone(), claude: d.join("c"), agy: agy.clone(), grok: d.join("g") };
        assert!(r.poll_open_writers().is_empty(), "没有 -wal、没有 rollout ⇒ 什么都不报（.db / .db-shm 不算）");
        std::fs::write(agy.join("a.db-wal"), b"x").unwrap();
        std::fs::write(codex.join("2026/09/30/rollout-1.jsonl"), b"x").unwrap();
        let got: Vec<usize> = r.poll_open_writers().into_iter().map(|(i, _)| i).collect();
        assert_eq!(got, vec![2, 0]);
        let now = now_secs();
        assert!(r.poll_open_writers().iter().all(|&(_, t)| now.saturating_sub(t) < 5), "报的是 mtime（刚写 ⇒ 现在）");
        assert_eq!(recent_day_dirs(&codex, 2), vec![codex.join("2026/10/01"), codex.join("2026/09/30")], "跨月取最近两天");
        let _ = std::fs::remove_dir_all(&d);
        let src = include_str!("activity.rs");
        let lp = src.split("let mut last_run").nth(1).unwrap().split("// 被接管时").next().unwrap();
        assert!(lp.contains("roots.poll_open_writers()") && lp.find("poll_open_writers").unwrap() < lp.find("publish(&app)").unwrap(),
                "循环没在 publish 之前轮询 ⇒ 只有 agy 在跑时托盘不醒");
    }

    use super::*;

    #[test]
    fn activity_is_recent_writes_only() {
        assert!(active(Some(1000), 1030));
        assert!(!active(Some(1000), 1000 + ACTIVE_SECS));
        assert!(!active(None, 1000));
    }
    fn roots() -> Roots {
        Roots { codex: "/h/.codex/sessions".into(), claude: "/h/.claude/projects".into(),
                agy: "/h/.gemini/antigravity-cli/conversations".into(), grok: "/h/.grok".into() }
    }
    #[test]
    fn each_platform_is_told_apart_by_its_own_session_files() {
        let r = roots();
        let c = |p: &str| r.classify(Path::new(p));
        assert_eq!(c("/h/.codex/sessions/2026/10/18/rollout-x.jsonl"), Some(0));
        assert_eq!(c("/h/.codex/sessions/2026/10/18/rollout-x.jsonl.zst"), None, "压缩归档不是在写");
        assert_eq!(c("/h/.claude/projects/-Users-x/abc.jsonl"), Some(1));
        assert_eq!(c("/h/.claude/projects/-Users-x/abc/subagents/agent-1.jsonl"), Some(1), "四方评审的子 agent 也算");
        assert_eq!(c("/h/.gemini/antigravity-cli/conversations/x.db-wal"), Some(2));
        assert_eq!(c("/h/.gemini/antigravity-cli/conversations/x.db-shm"), None);
        assert_eq!(c("/h/.grok/sessions/a/b/updates.jsonl"), Some(3));
        assert_eq!(c("/h/.grok/auth.json"), None, "grok 刷 token 不是在跑");
        assert_eq!(c("/h/.claude/settings.json"), None);
        assert_eq!(c("/h/elsewhere/rollout-x.jsonl"), None, "目录不对就不认");
    }
    #[test]
    fn only_content_writes_count() {
        use notify::event::{AccessKind, CreateKind, DataChange, EventKind, MetadataKind, ModifyKind, RenameMode};
        assert!(is_write(&EventKind::Modify(ModifyKind::Data(DataChange::Content))));
        assert!(is_write(&EventKind::Create(CreateKind::File)));
        assert!(!is_write(&EventKind::Access(AccessKind::Read)), "扫描器读文件不能读成在跑");
        assert!(!is_write(&EventKind::Modify(ModifyKind::Metadata(MetadataKind::Any))));
        assert!(!is_write(&EventKind::Modify(ModifyKind::Name(RenameMode::Any))));
    }
    #[test]
    fn a_recent_write_lights_only_that_platform() {
        for i in 0..4 { LAST_WRITE[i].store(0, Ordering::Relaxed); }
        LAST_WRITE[1].store(1000, Ordering::Relaxed);
        assert_eq!(snapshot(1010), Activity { claude: true, ..IDLE });
        assert_eq!(snapshot(1000 + ACTIVE_SECS), IDLE, "45s 没写就算停了");
        for i in 0..4 { LAST_WRITE[i].store(0, Ordering::Relaxed); }
    }
    #[test]
    fn the_live_loop_runs_while_active_and_once_more_after() {
        let mut was = false;
        let mut runs = Vec::new();
        for any in [false, true, true, false, false, false, true, false] {
            let (run, w) = live_step(any, was);
            was = w;
            runs.push(run);
        }
        assert_eq!(runs, vec![false, true, true, true, false, false, true, true],
                   "全空闲后恰好再跑一次，之后不跑");
    }
}
