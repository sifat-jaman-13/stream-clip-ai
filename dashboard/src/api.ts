import type { Creator, DashboardState } from "./types";

declare global {
  interface Window {
    __STREAMSNIP_TOKEN__?: string;
  }
}

let tokenPromise: Promise<string> | null = null;

async function getToken(): Promise<string> {
  if (window.__STREAMSNIP_TOKEN__) return window.__STREAMSNIP_TOKEN__;
  if (!tokenPromise) {
    tokenPromise = fetch("/api/session", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not establish a local app session.");
        const payload = (await response.json()) as { token: string };
        window.__STREAMSNIP_TOKEN__ = payload.token;
        return payload.token;
      })
      .catch((reason) => {
        tokenPromise = null;
        throw reason;
      });
  }
  return tokenPromise;
}

const makeWindowLeaseId = () =>
  typeof window.crypto?.randomUUID === "function"
    ? window.crypto.randomUUID()
    : "window-" + Date.now() + "-" + Math.random().toString(36).slice(2);

export function installWindowLeaseLifecycle(): () => void {
  if (typeof window === "undefined") return () => undefined;

  let leaseId = makeWindowLeaseId();
  let active = false;
  let disposed = false;
  let controller: AbortController | null = null;
  let sessionToken = window.__STREAMSNIP_TOKEN__ || "";

  const reportWindowOpen = () => {
    void apiPost("/api/window/open", {}).catch(() => undefined);
  };

  const stopLeaseStream = () => {
    active = false;
    controller?.abort();
    controller = null;
  };

  const reportWindowClosed = (closingLeaseId: string) => {
    const token = sessionToken || window.__STREAMSNIP_TOKEN__ || "";
    if (!token) return;
    void fetch("/api/window/closing?id=" + encodeURIComponent(closingLeaseId), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": token },
      body: JSON.stringify({ id: closingLeaseId }),
      keepalive: true,
    }).catch(() => undefined);
  };

  const startLeaseStream = () => {
    if (active || disposed) return;
    active = true;
    const streamController = new AbortController();
    controller = streamController;

    void (async () => {
      try {
        sessionToken = sessionToken || await getToken();
        while (active && !disposed && controller === streamController) {
          try {
            const response = await fetch(
              "/api/window/lease?id=" + encodeURIComponent(leaseId),
              {
                headers: { "X-Token": sessionToken },
                cache: "no-store",
                signal: streamController.signal,
              },
            );
            if (!response.ok || !response.body) {
              throw new Error("The app window lease could not be established.");
            }
            const reader = response.body.getReader();
            while (active && !disposed && controller === streamController) {
              const part = await reader.read();
              if (part.done) break;
            }
          } catch {
            if (!active || disposed || streamController.signal.aborted) break;
            await new Promise((resolve) => window.setTimeout(resolve, 350));
          }
        }
      } catch {
        // The normal session bootstrap will retry on the next page show.
      }
    })();
  };

  const onPageShow = () => {
    if (!active) leaseId = makeWindowLeaseId();
    reportWindowOpen();
    startLeaseStream();
  };

  const onPageHide = () => {
    const closingLeaseId = leaseId;
    stopLeaseStream();
    reportWindowClosed(closingLeaseId);
  };

  reportWindowOpen();
  startLeaseStream();
  window.addEventListener("pageshow", onPageShow);
  window.addEventListener("pagehide", onPageHide);

  return () => {
    const closingLeaseId = leaseId;
    disposed = true;
    stopLeaseStream();
    window.removeEventListener("pageshow", onPageShow);
    window.removeEventListener("pagehide", onPageHide);
    reportWindowClosed(closingLeaseId);
  };
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = (payload as { error?: string }).error || ("Request failed (" + response.status + ")");
    throw new Error(message);
  }
  return payload as T;
}

type AppToastTone = "success" | "error" | "info";
type AppToastDetail = { tone: AppToastTone; title: string; message?: string };

const actionLabels: Record<string, string> = {
  "/api/start": "Start capture",
  "/api/stop": "Stop capture",
  "/api/creators/add": "Add creator monitor",
  "/api/creators/remove": "Remove creator monitor",
  "/api/creators/start": "Start creator monitor",
  "/api/creators/stop": "Stop creator monitor",
  "/api/creators/stop-capture": "Stop creator capture",
  "/api/creators/watch-vods": "Start VOD folder watch",
  "/api/creators/stop-vod-watch": "Stop VOD folder watch",
  "/api/delete": "Delete clip",
  "/api/delete_many": "Delete selected clips",
  "/api/delete_all": "Delete clips",
  "/api/publishing/publish": "Queue publishing",
  "/api/publishing/publish-one": "Queue clip publishing",
  "/api/clip-metadata": "Save clip metadata",
  "/api/posted/mark": "Record external post",
  "/api/reveal": "Open clip location",
  "/api/ai/settings": "Save AI settings",
  "/api/ai/test": "Test AI provider",
  "/api/quit": "Quit StreamSnip AI",
};

const quietSuccessPaths = new Set([
  "/api/settings", // Debounced autosave: keep the UI quiet unless it fails.
  "/api/client-log",
  "/api/quit", // The shutdown overlay is the success feedback for this action.
  "/api/window/open",
  "/api/window/closing",
]);

export function notifyApp(tone: AppToastTone, title: string, message = "") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<AppToastDetail>("streamsnip:toast", {
    detail: { tone, title, message },
  }));
}

function actionLabel(path: string) {
  return actionLabels[path] || path.split("/").filter(Boolean).pop()?.replace(/[-_]/g, " ") || "App action";
}

function reportClientAction(token: string, level: "info" | "error", path: string, message: string) {
  if (!token || path === "/api/client-log") return;
  void fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Token": token },
    body: JSON.stringify({ level, action: path, message: message.slice(0, 400) }),
    keepalive: true,
  }).catch(() => undefined);
}

export async function apiPost<T>(path: string, body: unknown = {}): Promise<T> {
  const label = actionLabel(path);
  const shouldReportFailures = !["/api/client-log", "/api/window/open", "/api/window/closing"].includes(path);
  const shouldReportSuccess = shouldReportFailures && !quietSuccessPaths.has(path);
  let token: string;
  try {
    token = await getToken();
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "Could not establish a local app session.";
    notifyApp("error", label + " failed", message);
    throw reason;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": token },
      body: JSON.stringify(body),
    });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "The local app server could not be reached.";
    notifyApp("error", label + " failed", message);
    if (shouldReportFailures) reportClientAction(token, "error", path, message);
    throw reason;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = (payload as { error?: string }).error || ("Request failed (" + response.status + ")");
    notifyApp("error", label + " failed", message);
    if (shouldReportFailures) reportClientAction(token, "error", path, message);
    throw new Error(message);
  }

  if (!quietSuccessPaths.has(path)) {
    const message = path.startsWith("/api/publishing/")
      ? "Queued by the local engine. Check Activity for the final per-platform result."
      : path === "/api/start"
        ? "The capture engine accepted the start request."
        : path === "/api/stop"
          ? "The capture engine accepted the stop request."
          : "Completed successfully.";
    notifyApp("success", label + " accepted", message);
  }
  if (shouldReportSuccess) reportClientAction(token, "info", path, label + " accepted by the local API.");
  return payload as T;
}

export async function loadDashboard(tab: "clips" | "posted", since: number, offset = 0) {
  const [state, creatorResponse] = await Promise.all([
    apiGet<DashboardState>(
      "/api/state?since=" + since + "&clip_offset=" + offset + "&clip_tab=" + tab,
    ),
    apiGet<{ creators: Creator[] }>("/api/creators"),
  ]);
  return { state, creators: creatorResponse.creators };
}
