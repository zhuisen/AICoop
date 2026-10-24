import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

let permitted: boolean | null = null;

/** 发系统通知。返回是否真的发出去了（没有通知权限 ⇒ false，调用方可以换别的方式说）。 */
export async function notify(title: string, body: string): Promise<boolean> {
  if (permitted === null) {
    permitted = await isPermissionGranted();
    if (!permitted) {
      const p = await requestPermission();
      permitted = p === "granted";
    }
  }
  if (permitted) {
    sendNotification({ title, body });
  }
  return permitted;
}
