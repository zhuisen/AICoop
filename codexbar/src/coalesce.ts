/**
 * 在途只许一个，期间来的调用合成**一次**尾随调用（全方面评审 §6：`useIntegration` / 接入面板
 * 每条 `state-changed` 都起一个 python，codex 在用时约每秒一次；两个 webview 各一份）。
 *
 * ★ 不是 debounce：尾随那一次**保证会跑**，期间发生的变更最终一定被读到。
 * ★ 一个在途 ⇒ 结果按发起顺序回来，慢的旧结果不会盖掉新的。
 * ★ `run` 自己处理错误；这里只保证抛错那条路也放行（`finally`），否则一次失败就永久堵死。
 * 零 import —— 测试用 `node --experimental-strip-types` 直接加载。同形的先例是 `useRotationBoard`。
 */
export function coalesce(run: () => Promise<unknown>): () => void {
  let inflight = false;
  let pending = false;
  const go = (): void => {
    if (inflight) { pending = true; return; }
    inflight = true;
    void (async () => {
      try {
        await run();
      } finally {
        inflight = false;
        if (pending) { pending = false; go(); }
      }
    })();
  };
  return go;
}
