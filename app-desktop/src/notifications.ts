import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

let permissionChecked = false;
let permissionGranted = false;

async function ensurePermission(): Promise<boolean> {
  if (permissionChecked) return permissionGranted;
  permissionChecked = true;

  permissionGranted = await isPermissionGranted();
  if (!permissionGranted) {
    const result = await requestPermission();
    permissionGranted = result === "granted";
  }
  return permissionGranted;
}

/** Envoie une notif macOS native, seulement si la fenêtre n'a pas le focus
 * (document.hasFocus()) : si l'utilisateur regarde déjà l'app, il voit le
 * résultat en direct, une notif serait juste du bruit. */
export function notifyIfBackground(title: string, body: string) {
  if (document.hasFocus()) return;
  void ensurePermission().then((granted) => {
    if (granted) sendNotification({ title, body });
  });
}
