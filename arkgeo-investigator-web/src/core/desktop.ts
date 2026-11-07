/**
 * Desktop (Electron) detection + platform flags.
 *
 * The desktop shell exposes `window.ark` from preload.js. We surface the
 * platform so the shell can pick the correct titlebar safe zones and window
 * control strategy. Classes are applied to <body> so CSS can scope desktop-only
 * chrome without any render-time branching.
 */

interface ArkBridge {
  isElectron?: boolean;
  platform?: string;
  backendPort?: number | null;
}

function bridge(): ArkBridge | undefined {
  return typeof window !== 'undefined' ? (window as unknown as { ark?: ArkBridge }).ark : undefined;
}

export function isDesktop(): boolean {
  return bridge()?.isElectron === true;
}

export function platform(): string {
  return bridge()?.platform ?? 'web';
}

/** Adds `ark-desktop` and `ark-platform-<os>` to <body>. No-op on the web. */
export function applyDesktopClasses(): void {
  if (typeof document === 'undefined' || !isDesktop()) return;
  const cls = document.body.classList;
  cls.add('ark-desktop');
  cls.add(`ark-platform-${platform()}`);
}
