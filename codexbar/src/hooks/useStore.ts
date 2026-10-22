import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { type AppState, type TokenInfo, type Account, type Slot, slotToAccount, recommended, poolRefreshedAt, poolFreshness, CARD_WARN_DAYS, inUseAid } from "../helpers";
import { useBusyMirror } from "./useBusyMirror";
import { tqDue, tqEmpty, tqHas, tqHold, tqNext, tqPush, tqRearm, tqRemove } from "../toastQueue";

export interface ToastItem { id: number; msg: string; color: string; undo?: () => void }
export interface ToastOpts {
  color?: string; undo?: () => void; replace?: number;
  /** 到点自然消失（或被挤出堆）时执行 —— 「删除」靠它在撤销窗口过去后才真删。点「撤销」不触发。 */
  onExpire?: () => void;
}
export interface RunOpts {
  resultToast?: boolean;
  /** 成功时的 toast 文案（缺省 `✓ <msg>`）。 */
  done?: string;
  color?: string;
  ms?: number;
  /** 这一条 toast 的「撤销」（只撤自己这一步）。 */
  undo?: () => void;
  /** 不弹「…」与结果（撤销本身、或调用方自己说）。 */
  quiet?: boolean;
}
export const TOAST_MS = 3200;
export const TOAST_MAX = 4;
export const TOAST_OK = "#2dd4bf";
export const TOAST_BAD = "#FF8A73";
export const TOAST_WARN = "#fbbf24";
export const TOAST_MUTED = "#8f99a6";

export interface StoreCounts {
  total: number; live: number; cool: number; dead: number;
}

export function useStore() {
  const [state, setState] = useState<AppState>({});
  const [tokens, setTokens] = useState<Record<string, TokenInfo>>({});
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const { remote: remoteAction, announce } = useBusyMirror();
  /**
   * ★ Toast 是一个**堆**（交接包 P5 §7：最多 4 条、各自 3.2 s、悬停暂停、每条自己的撤销）。
   *   `toast`（最新一条的文字）保留给菜单栏 —— 它仍是单条样式。
   */
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // ★ 计时的真源是 `q`（纯状态机 `toastQueue.ts`，有 node 行为闸）；`toasts` 只是它的渲染镜像。
  //   到期回调（「删除」的真删）只在这里、在 React updater **之外**调，调之前先从表里删 ⇒ 恰好一次。
  const q = useRef(tqEmpty());
  const shown = useRef(new Map<number, ToastItem>());
  const expire = useRef(new Map<number, () => void>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seq = useRef(0);

  const fire = (ids: number[]) => {
    for (const id of ids) {
      shown.current.delete(id);
      const ex = expire.current.get(id);
      expire.current.delete(id);
      ex?.();
    }
  };
  const sync = useCallback(function sync() {
    const { s, expired } = tqDue(q.current, Date.now());
    q.current = s;
    fire(expired);
    setToasts(s.items.map((x) => shown.current.get(x.id)).filter((x): x is ToastItem => !!x));
    if (timer.current) clearTimeout(timer.current);
    const next = tqNext(s);
    timer.current = next == null ? null : setTimeout(sync, Math.max(0, next - Date.now()));
  }, []);
  const dismissToast = useCallback((id: number) => {
    expire.current.delete(id);                 // 撤销 / 点掉 ⇒ 到期回调不调
    shown.current.delete(id);
    q.current = tqRemove(q.current, id);
    sync();
  }, [sync]);
  /** `ms`：结果类 toast（探针的 5h 前后对比）要读得完。`replace` = 把那一条（进行中的「…」）原地换成结果；
   *  换字时到期回调跟着换成这次给的（没给就清掉）—— 这一条已经说的是另一件事了。 */
  const showToast = useCallback((msg: string, ms = TOAST_MS, o?: ToastOpts): number => {
    const color = o?.color ?? (msg.startsWith("✗") ? TOAST_BAD : TOAST_OK);
    const now = Date.now();
    const rid = o?.replace;
    let id: number;
    if (rid != null && tqHas(q.current, rid)) {
      id = rid;
      q.current = tqRearm(q.current, rid, ms, now);
    } else {
      id = ++seq.current;
      const r = tqPush(q.current, id, ms, now, TOAST_MAX);
      q.current = r.s;
      fire(r.evicted);                          // 被挤出堆 = 撤销窗口没了 ⇒ 当它到点
    }
    shown.current.set(id, { id, msg, color, undo: o?.undo });
    if (o?.onExpire) expire.current.set(id, o.onExpire); else expire.current.delete(id);
    sync();
    return id;
  }, [sync]);
  const holdToasts = useCallback((h: boolean) => { q.current = tqHold(q.current, h, Date.now()); sync(); }, [sync]);
  /** 窗口要没了（刷新 / 关闭 webview）⇒ 撤销窗口里还没到期的「删除」立刻执行：界面已经说了「已删除」。
   *  ⚠️ 尽力而为：进程被直接结束（托盘「退出」走 Rust `exit`）时 webview 收不到任何事件 ⇒ 删除没发，号还在 ——
   *  这是安全的那一侧（没有发生用户没确认的事），下次打开能看到它还在。 */
  useEffect(() => {
    const flush = () => { const ids = [...expire.current.keys()]; fire(ids); };
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); if (timer.current) clearTimeout(timer.current); };
  }, []);
  /** 「先隐藏、撤销窗口过去再真删」（P5 §5）。隐藏集合放在这里而不是总览：切页再回来、总览重挂，隐藏照旧，
   *  到期提交与隐藏是同一层。`key` 带平台前缀（codex 的 aid 与 agy 的 sub 不是一个空间）。
   *  成功后也移出集合：同一个 aid 重新登录回来时不能一直看不见（评审 Opus M2）。 */
  const [pendingDel, setPendingDel] = useState<ReadonlySet<string>>(() => new Set());
  const unpend = useCallback((key: string) => setPendingDel((h) => { const n = new Set(h); n.delete(key); return n; }), []);
  const deferDelete = useCallback((key: string, label: string, commit: () => Promise<boolean>) => {
    setPendingDel((h) => new Set(h).add(key));
    showToast(`已删除 ${label}`, TOAST_MS, { color: TOAST_BAD, undo: () => unpend(key),
      onExpire: () => { void commit().then(() => unpend(key)); } });
  }, [showToast, unpend]);
  const toast = toasts.length ? toasts[toasts.length - 1].msg : null;

  const refresh = useCallback(async () => {
    try {
      const [s, tk] = await Promise.all([
        invoke<AppState>("read_state"),
        invoke<Record<string, TokenInfo>>("read_auth_tokens"),
      ]);
      setState(s);
      setTokens(tk);
      const now = Date.now() / 1000;
      const cds: Record<string, number> = {};
      for (const [aid, sl] of Object.entries(s.slots ?? {})) {
        const cd = (sl.cooling_until ?? 0) - now;
        if (cd > 0) cds[aid] = Math.round(cd);
      }
      setCooldowns(cds);
    } catch {
      // read_state / read_auth_tokens failure — silently retry on next tick
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const u = listen("state-changed", () => refresh());
    return () => { u.then(f => f()); };
  }, [refresh]);

  useEffect(() => {
    const id = setInterval(() => {
      setCooldowns(prev => {
        const next = { ...prev };
        let changed = false;
        for (const aid of Object.keys(next)) {
          if (next[aid] > 0) { next[aid]--; changed = true; }
          if (next[aid] <= 0) delete next[aid];
        }
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const inflight = useRef<string[]>([]);
  const run = useCallback(async (actionId: string, args: string[], msg: string, opts?: RunOpts) => {
    inflight.current.push(actionId);
    setLoadingAction(actionId);
    // ★ 告诉另一个 webview「我开始跑了」。此前两边只在**结束**时靠 `state-changed` 同步,
    //   于是在菜单栏点刷新、再打开主界面,主界面整个执行期间看起来什么都没发生
    //   (用户 2026-09-06 报的就是这个)。
    announce(actionId);
    const tid = opts?.quiet ? null : showToast(`${msg}…`, 120_000);
    // ★★ **返回成功与否。** 原来无论成败都只落一个 toast、返回 `undefined` ——
    //    于是调用方**无法区分**"CLI 干成了"和"CLI 拒绝了"。
    //    自动切号就栽在这里：它无条件弹「已切到 X」，而 `cmd_switch` 其实拒绝了
    //    （目标号被用户暂停）。用户看到的是一句关于事实的假陈述。
    let ok = false;
    try {
      const out = await invoke<string>("run_rotate", { args });
      await refresh();
      // ★ 花掉不可逆东西的动作要把**结果原话**给用户（用了哪张、重置了几个窗口、还剩几张），
      //   不是一句泛泛的「✓ 用重置卡」。其余动作行为不变。
      const last = opts?.resultToast ? String(out ?? "").trim().split("\n").pop() : "";
      if (!opts?.quiet) showToast(last ? last.slice(0, 120) : (opts?.done ?? `✓ ${msg}`), opts?.ms ?? TOAST_MS,
                                  { replace: tid ?? undefined, color: opts?.color, undo: opts?.undo });
      ok = true;
    } catch (e: unknown) {
      const errMsg = String(e).slice(0, 80);
      showToast(`✗ 失败: ${errMsg}`, 6000, { replace: tid ?? undefined });
    } finally {
      // ★★ **必须在 `finally`** —— 上面 `catch` 之后还有 `showToast`,任何一处再抛,
      //    不在 finally 里的熄灯就漏了,对方会一直转圈。
      // 只熄自己这一盏：别的动作（探针）还在跑时点了图钉，不能把探针的转圈一起熄掉（评审 Opus M1）
      // ★ 并发的动作按在途清单熄灯（2026-10-22 评审）：先结束的那个不能把还在跑的转圈和跨窗镜像一起熄掉
      const i = inflight.current.indexOf(actionId);
      if (i >= 0) inflight.current.splice(i, 1);
      const rest = inflight.current[inflight.current.length - 1] ?? null;
      setLoadingAction((cur) => (cur === actionId ? rest : cur));
      announce(rest);
    }
    return ok;
  }, [refresh, showToast, announce]);

  const slots: Record<string, Slot> = state.slots ?? {};
  // 池里已没有的 aid 不算（老 state 可能留着）：否则卡片置顶序号整体错一位、与 CLI 对不上（阶段 A 评审）
  const pinned = (state.pinned ?? []).filter((x) => x in slots);
  const accounts: Account[] = Object.entries(slots)
    .map(([aid, sl]) => {
      const a = slotToAccount(aid, sl, tokens, pinned);
      if (cooldowns[aid] != null) a.cooldownSec = cooldowns[aid];
      if (a.cooldownSec > 0 && a.status !== "dead") a.status = "cool";
      return a;
    })
    .sort((a, b) => {
      if (a.status === "dead" && b.status !== "dead") return 1;
      if (b.status === "dead" && a.status !== "dead") return -1;
      return b.tightest - a.tightest || a.node.localeCompare(b.node);
    });

  const currentNode = state.active;
  /**
   * ★★ **代理此刻在用的号** —— 菜单栏跟着它走（用户 2026-09-23：「现在是代理轮换的状态，
   *   我希望菜单栏显示的账号信息跟着代理轮换走」）。
   *   `currentNode`（= `active`）保留给**切号/死号监视/自动切号**这些只关心 auth.json 的路径；
   *   显示「谁在用」一律用这个。取不到 `last_aid`（新装机、代理还没服务过任何请求）才退回 `active`。
   */
  const inUseNode = inUseAid(state);
  const hero = recommended(accounts);
  const counts: StoreCounts = {
    total: accounts.length,
    live: accounts.filter(a => a.status === "live" || a.status === "low").length,
    cool: accounts.filter(a => a.status === "cool").length,
    dead: accounts.filter(a => a.status === "dead").length,
  };

  // Relative time re-renders for free: refresh() replaces `state` every 30s, so no extra timer.
  const lastRefreshAt = poolRefreshedAt(slots);
  // ★★ `lastRefreshAt` 取的是**全池最大值**,它只能回答「最近有账号被刷新过」——
  //    **不能**读成「全池都是新的」。实测踩过:一个 token 已失效、快照陈旧 3.8 天的号,
  //    被每 300s 刷新的活号盖成「刚刚」,于是那件事在 UI 上完全看不见。
  //    覆盖度才回答「有几个是新的」。两个都下发,让消费方各取所需。
  const freshness = poolFreshness(slots);

  // Pool-wide banner subject = the single most urgent expiring card (design handoff §4).
  const cardAlert = accounts
    .filter(a => a.status !== "dead" && a.cards > 0 && a.cardDays != null && a.cardDays <= CARD_WARN_DAYS)
    .sort((x, y) => (x.cardDays ?? 0) - (y.cardDays ?? 0))[0] ?? null;

  return { state, tokens, accounts, hero, currentNode, inUseNode, slots, counts, lastRefreshAt, freshness, cardAlert,
           // ★ 本地优先:自己发起的动作永远比镜像来的可信(镜像可能已经过期,见 `useBusyMirror`)。
           //   两个 surface 因此显示同一个动作 id,按钮文案/转圈逻辑一行都不用改。
           // ★ 过滤掉流量扫描:它走 `useTraffic` 的 `busy`,不是账号池动作。
           //   两个 hook 共用同一条广播通道,不筛就会把 `traffic-scan` 塞进 `loadingAction`——
           //   眼下没有按钮匹配它所以看不见,但那是"碰巧无害",下一个按钮 id 撞上就变成乱转圈。
           loadingAction: loadingAction ?? (remoteAction === "traffic-scan" ? null : remoteAction),
           /** ★ 这个动作是**别的窗口**发起的。UI 可据此弱化措辞(是"正在刷新"不是"你点的那个")。 */
           remoteAction, toast, toasts, dismissToast, holdToasts, refresh, run, showToast, pendingDel, deferDelete };
}
