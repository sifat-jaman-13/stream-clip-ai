import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertCircle, ArrowRight, ArrowUpRight, BadgeCheck, Check, CheckCircle2,
  ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Clapperboard, CloudUpload, Cpu, Download,
  ExternalLink, Eye, FileText, FileVideo, FolderOpen, HardDrive, Info, LayoutDashboard,
  Menu, MoreHorizontal, Palette, Pause, Play, Plus, Radio,
  RadioTower, RefreshCw, Search, Send, Settings, ShieldCheck, SlidersHorizontal, Sparkles, Square, Trash2,
  Users, Video, WandSparkles, X, Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { apiGet, apiPost, installWindowLeaseLifecycle } from "./api";
import { useWorkspace, type AppSettings, type Workspace } from "./workspace";
import type { Clip, Creator, LogEntry } from "./types";
import "./App.css";

type PageId = "overview" | "live" | "creators" | "clips" | "post-clips" | "published" | "publishing" | "words" | "activity" | "settings" | "help" | "about";
type ThemeId = "odysseus" | "studio-light" | "studio-dark" | "github" | "nord" | "odysseas";
type FontId = "google-sans" | "inter" | "roboto" | "open-sans" | "montserrat" | "poppins" | "lato" | "nunito-sans" | "dm-sans" | "ibm-plex-sans" | "space-grotesk" | "fira-code" | "jetbrains-mono";
type StudioSetupTab = "capture" | "ai" | "speech" | "captions";
type RecordLike = Record<string, any>;
type ToastDetail = { tone: "success" | "error" | "info"; title: string; message?: string };

const themes: Array<{ id: ThemeId; name: string; description: string; colors: string[] }> = [
  { id: "odysseus", name: "Odysseus", description: "Graphite · arctic cyan · coral", colors: ["#282c34", "#111111", "#355a66", "#9cdef2", "#e06c75"] },
  { id: "studio-light", name: "Studio Light", description: "YouTube Studio · clean neutral surfaces", colors: ["#ffffff", "#f5f5f5", "#0f0f0f", "#cc0000"] },
  { id: "studio-dark", name: "Studio Dark", description: "YouTube Studio · low-light workspace", colors: ["#0f0f0f", "#212121", "#f1f1f1", "#ff0033"] },
  { id: "github", name: "GitHub Dark", description: "Midnight · mist · signal red", colors: ["#0d1117", "#161b22", "#30363d", "#f85149"] },
  { id: "nord", name: "Nord", description: "Arctic blue-gray · soft cyan", colors: ["#2e3440", "#3b4252", "#4c566a", "#88c0d0", "#bf616a"] },
  { id: "odysseas", name: "Odysseus Paper", description: "Navy · chalk · signal orange", colors: ["#142838", "#edf0ec", "#fffefa", "#ef6a42"] },
];

const fontOptions: Array<{ id: FontId; name: string; family: string; kind: string }> = [
  { id: "jetbrains-mono", name: "JetBrains Mono", family: '"JetBrains Mono", Consolas, monospace', kind: "Monospace" },
  { id: "google-sans", name: "Google Sans", family: '"Google Sans Flex", "Google Sans", "Segoe UI", Arial, sans-serif', kind: "Sans serif" },
  { id: "inter", name: "Inter", family: '"Inter", Arial, sans-serif', kind: "Sans serif" },
  { id: "roboto", name: "Roboto", family: '"Roboto", Arial, sans-serif', kind: "Sans serif" },
  { id: "open-sans", name: "Open Sans", family: '"Open Sans", Arial, sans-serif', kind: "Sans serif" },
  { id: "montserrat", name: "Montserrat", family: '"Montserrat", Arial, sans-serif', kind: "Sans serif" },
  { id: "poppins", name: "Poppins", family: '"Poppins", Arial, sans-serif', kind: "Sans serif" },
  { id: "lato", name: "Lato", family: '"Lato", Arial, sans-serif', kind: "Sans serif" },
  { id: "nunito-sans", name: "Nunito Sans", family: '"Nunito Sans", Arial, sans-serif', kind: "Sans serif" },
  { id: "dm-sans", name: "DM Sans", family: '"DM Sans", Arial, sans-serif', kind: "Sans serif" },
  { id: "ibm-plex-sans", name: "IBM Plex Sans", family: '"IBM Plex Sans", Arial, sans-serif', kind: "Sans serif" },
  { id: "space-grotesk", name: "Space Grotesk", family: '"Space Grotesk", Arial, sans-serif', kind: "Sans serif" },
  { id: "fira-code", name: "Fira Code", family: '"Fira Code", Consolas, monospace', kind: "Monospace" },
];

const pageInfo: Record<PageId, { title: string; description: string }> = {
  overview: { title: "Studio overview", description: "Your capture activity, creator sources, and clips in one place." },
  live: { title: "Live Studio", description: "Choose a source and control capture from your local engine." },
  creators: { title: "Creators", description: "Manage independent live monitors and recorded-VOD folders." },
  clips: { title: "Clip library", description: "Review generated clips and edit metadata." },
  "post-clips": { title: "Post Your Clips", description: "Choose destinations for finished clips and prepare each upload." },
  published: { title: "Published", description: "Clips recorded in your local posted registry." },
  publishing: { title: "Publishing", description: "Connect Zernio or prepare a manual upload in your browser." },
  words: { title: "Hype words", description: "Tune the phrase list used by the local highlight scorer." },
  activity: { title: "Activity", description: "Recent engine events and actionable processing errors." },
  settings: { title: "Settings", description: "Manage application storage and workspace appearance. Prepare sessions in Live Studio." },
  help: { title: "Help", description: "How the local capture and clip workflow behaves." },
  about: { title: "About StreamSnip AI", description: "Application details and project resources." },
};

const navGroups: Array<{ label: string; items: Array<{ id: PageId; label: string; icon: LucideIcon }> }> = [
  { label: "Studio", items: [
    { id: "overview", label: "Dashboard", icon: LayoutDashboard },
    { id: "live", label: "Live Studio", icon: Radio },
    { id: "creators", label: "Creators", icon: Users },
  ] },
  { label: "Content", items: [
    { id: "clips", label: "Clip library", icon: Clapperboard },
    { id: "post-clips", label: "Post Your Clips", icon: CloudUpload },
    { id: "published", label: "Published", icon: BadgeCheck },
    { id: "words", label: "Hype words", icon: WandSparkles },
  ] },
  { label: "Manage", items: [
    { id: "publishing", label: "Publishing", icon: CloudUpload },
    { id: "settings", label: "Settings", icon: Settings },
    { id: "activity", label: "Activity", icon: Activity },
  ] },
];

const clipUrl = (name: string) => "/clips/" + encodeURIComponent(name);
const num = (value: unknown, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const count = (value: unknown) => new Intl.NumberFormat().format(num(value));
const duration = (value: number) => {
  const total = Math.max(0, Math.floor(value || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours ? hours + "h " + String(minutes).padStart(2, "0") + "m" : minutes + "m " + String(seconds).padStart(2, "0") + "s";
};
const dateLabel = (value?: number | string | null) => {
  if (value === undefined || value === null || value === "") return "—";
  const numeric = Number(value);
  const date = new Date(Number.isFinite(numeric) ? numeric * 1000 : String(value));
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
};
const sizeLabel = (value?: number) => {
  const mb = num(value);
  return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb.toFixed(mb < 10 ? 1 : 0) + " MB";
};
const creatorTargetKey = (value: string) => {
  const target = value.trim();
  if (!target) return "";
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(target) ? target : "https://" + target);
    return url.hostname.toLowerCase().replace(/^www\./, "") + url.pathname.replace(/\/+$/, "").toLowerCase();
  } catch {
    return target.replace(/\/+$/, "").toLowerCase();
  }
};
const isCreatorCaptureActive = (creator: Creator, workspace: Workspace) => {
  if (creator.capture_active) return true;
  const activeTarget = String(workspace.settings?.target || "");
  return workspace.state.running
    && workspace.state.mode === "live"
    && !!activeTarget
    && creatorTargetKey(activeTarget) === creatorTargetKey(creator.target);
};
const inferCreatorTag = (value: string) => {
  const target = value.trim();
  if (!target) return "";
  let url: URL;
  try {
    url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(target) ? target : "https://" + target);
  } catch {
    return "";
  }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  const parts = url.pathname.split("/").filter(Boolean).map((part) => {
    try { return decodeURIComponent(part); } catch { return part; }
  });
  if (host === "clips.twitch.tv") return "";
  if (host === "twitch.tv" || host.endsWith(".twitch.tv")) {
    const handle = parts[0] || "";
    if (["videos", "directory", "search", "clip", "downloads", "settings"].includes(handle.toLowerCase())) return "";
    const clean = handle.replace(/[^a-z0-9_]/gi, "").slice(0, 80);
    return clean ? "@" + clean : "";
  }
  if (host === "youtube.com" || host.endsWith(".youtube.com")) {
    const first = parts[0] || "";
    const handle = first.startsWith("@") ? first.slice(1) : ["c", "user"].includes(first.toLowerCase()) ? parts[1] || "" : "";
    const clean = handle.replace(/[^a-z0-9_.-]/gi, "").slice(0, 80);
    return clean ? "@" + clean : "";
  }
  return "";
};
const phaseLabel = (phase: string) => ({
  idle: "Idle", offline: "Offline", waiting: "Connecting", recording: "Recording", stopping: "Stopping",
  transcribing: "Transcribing", analyzing: "Finding highlights", rendering: "Rendering clips",
  queued: "Queued", done: "Complete", error: "Error",
} as Record<string, string>)[phase] || (phase ? phase.replace(/[_-]/g, " ") : "Idle");
const initialTheme = (): ThemeId => {
  try {
    const saved = localStorage.getItem("streamsnip.theme") || "";
    const aliases: Record<string, ThemeId> = {
      light: "studio-light", studio: "studio-light", dark: "studio-dark",
      midnight: "github", graphite: "github", odyssey: "odysseus", odysseas: "odysseas",
    };
    const resolved = aliases[saved] || saved;
    if (themes.some((item) => item.id === resolved)) return resolved as ThemeId;
  } catch { /* Local storage may be disabled. */ }
  return "odysseus";
};
const initialFont = (): FontId => {
  try {
    const saved = localStorage.getItem("streamsnip.font") || "";
    if (fontOptions.some((item) => item.id === saved)) return saved as FontId;
  } catch { /* Local storage may be disabled. */ }
  return "jetbrains-mono";
};
const toneFor = (phase: string, running = false): "neutral" | "success" | "warning" | "danger" | "live" => {
  if (phase === "error") return "danger";
  if (["waiting", "stopping", "transcribing", "analyzing", "rendering"].includes(phase)) return "warning";
  return running || phase === "recording" ? "live" : "neutral";
};

export default function App() {
  const workspace = useWorkspace();
  const [page, setPage] = useState<PageId>("overview");
  const [theme, setTheme] = useState<ThemeId>(initialTheme);
  const [font, setFont] = useState<FontId>(initialFont);
  const [themeOpen, setThemeOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [globalSearch, setGlobalSearch] = useState("");
  const [clipSearch, setClipSearch] = useState("");
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [publishClip, setPublishClip] = useState<Clip | null>(null);
  const [bulkNames, setBulkNames] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [quitting, setQuitting] = useState(false);
  const [toast, setToast] = useState<ToastDetail | null>(null);
  const [browserStatus, setBrowserStatus] = useState<RecordLike>({});

  useEffect(() => installWindowLeaseLifecycle(), []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("streamsnip.theme", theme); } catch { /* Local storage may be disabled. */ }
  }, [theme]);

  useEffect(() => {
    const selected = fontOptions.find((item) => item.id === font) || fontOptions[0];
    document.documentElement.style.setProperty("--font-family", selected.family);
    try { localStorage.setItem("streamsnip.font", font); } catch { /* Local storage may be disabled. */ }
  }, [font]);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<ToastDetail>).detail;
      if (detail) setToast(detail);
    };
    window.addEventListener("streamsnip:toast", listener);
    return () => window.removeEventListener("streamsnip:toast", listener);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.tone === "error" ? 5200 : 3300);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let cancelled = false;
    apiGet<RecordLike>("/api/browser/status").then((value) => { if (!cancelled) setBrowserStatus(value); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!themeOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setThemeOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [themeOpen]);

  const setClipTab = workspace.setClipTab;
  const refreshWorkspace = workspace.refresh;
  const navigate = useCallback((next: PageId) => {
    setPage(next);
    setMobileOpen(false);
    setThemeOpen(false);
    if (next === "clips") setClipTab("clips");
    if (next === "published") setClipTab("posted");
  }, [setClipTab]);

  const post = useCallback(async <T,>(key: string, path: string, body: RecordLike = {}): Promise<T | null> => {
    setBusy(key);
    try {
      const result = await apiPost<T>(path, body);
      await refreshWorkspace();
      return result;
    } catch {
      return null;
    } finally { setBusy(""); }
  }, [refreshWorkspace]);

  const requestQuit = useCallback(async () => {
    if (quitting || !window.confirm("Quit StreamSnip AI? Active capture and creator monitors will be stopped.")) return;
    setQuitting(true);
    try {
      // Do not refresh the workspace after this request: the API is intentionally shutting down.
      await apiPost("/api/quit", {});
    } catch {
      setQuitting(false);
    }
  }, [quitting]);

  const openForPublishing = (clip: Clip) => {
    setPublishClip(clip);
    setBulkNames([]);
    navigate("publishing");
  };
  const openBulkPublishing = (names: string[]) => {
    setPublishClip(null);
    setBulkNames(names);
    navigate("publishing");
  };
  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setClipSearch(globalSearch.trim());
    navigate("clips");
  };
  const connected = workspace.connected;
  const running = workspace.state.running;
  const title = pageInfo[page].title;
  const selectedTheme = themes.find((item) => item.id === theme) || themes[0];

  return <div className="app-shell">
    <Sidebar page={page} navigate={navigate} connected={connected} running={running} mobileOpen={mobileOpen} close={() => setMobileOpen(false)} />
    {mobileOpen ? <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}
    <div className="main-shell">
      <header className="topbar">
        <div className="topbar-start">
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={19} /></button>
          <div className="breadcrumbs"><span>StreamSnip AI</span><span className="crumb-divider">/</span><strong>{title}</strong></div>
        </div>
        <div className="topbar-tools">
          <form className="global-search" onSubmit={handleSearch}>
            <Search size={16} />
            <input aria-label="Search clips" placeholder="Search clips" value={globalSearch} onChange={(event) => setGlobalSearch(event.target.value)} />
            <kbd>Enter</kbd>
          </form>
          <EnginePill connected={connected} running={running} stopping={workspace.state.stopping} />
          <div className="theme-control">
            <button className="theme-trigger" aria-label={"Appearance: " + selectedTheme.name} aria-expanded={themeOpen} onClick={() => setThemeOpen((value) => !value)}><Palette size={16} /><span>{selectedTheme.name}</span><ChevronDown size={13} /></button>
            {themeOpen ? <div className="theme-popover" role="dialog" aria-label="Workspace appearance">
              <div className="theme-popover-title"><strong>Appearance</strong><span>Saved on this device</span></div>
              {themes.map((item) => <ThemeOption key={item.id} item={item} selected={theme === item.id} select={() => { setTheme(item.id); }} />)}
              <div className="theme-font-picker">
                <label htmlFor="workspace-font">Font family</label>
                <select id="workspace-font" value={font} onChange={(event) => setFont(event.target.value as FontId)}>
                  {fontOptions.map((item) => <option key={item.id} value={item.id}>{item.name}{item.kind === "Monospace" ? " · Monospace" : ""}</option>)}
                </select>
                <small>Saved on this device. JetBrains Mono is the default.</small>
                <span className="theme-font-preview" style={{ fontFamily: (fontOptions.find((item) => item.id === font) || fontOptions[0]).family }}>StreamSnip AI · Creator Studio</span>
              </div>
            </div> : null}
          </div>
          <button className="icon-button" aria-label="Help" onClick={() => navigate("help")}><CircleHelp size={17} /></button>
          <button className="topbar-quit" onClick={() => void requestQuit()} disabled={quitting}>{quitting ? "Shutting down..." : "Quit"}</button>
        </div>
      </header>

      {workspace.error ? <div className="connection-alert" role="alert"><AlertCircle size={16} /><span>{workspace.error}</span><button onClick={() => void workspace.refresh()}><RefreshCw size={14} />Retry</button></div> : null}

      <main className="page-content">
        {page === "overview" ? <OverviewPage workspace={workspace} navigate={navigate} openClip={(clip) => { setSelectedClip(clip); navigate("clips"); }} /> : null}
        {page === "live" ? <LivePage key={String(workspace.settings?.mode || "") + "|" + String(workspace.settings?.target || "")} workspace={workspace} busy={busy} post={post} navigate={navigate} /> : null}
        {page === "creators" ? <CreatorsPage workspace={workspace} busy={busy} post={post} navigate={navigate} /> : null}
        {page === "post-clips" ? <PostYourClipsPage workspace={workspace} busy={busy} post={post} /> : null}
        {page === "clips" || page === "published" ? <ClipLibraryPage key={page + "|" + workspace.clipOffset} workspace={workspace} published={page === "published"} navigate={navigate} query={clipSearch} setQuery={setClipSearch} selectedClip={selectedClip} setSelectedClip={setSelectedClip} openForPublishing={openForPublishing} openBulkPublishing={openBulkPublishing} busy={busy} post={post} /> : null}
        {page === "publishing" ? <PublishingPage key={(publishClip?.name || "bulk") + "|" + bulkNames.join(",") + "|" + JSON.stringify(workspace.publishing)} workspace={workspace} clip={publishClip} bulkNames={bulkNames} browserStatus={browserStatus} setBrowserStatus={setBrowserStatus} busy={busy} post={post} openLibrary={() => navigate("clips")} /> : null}
        {page === "words" ? <HypeWordsPage key={workspace.words.text} workspace={workspace} /> : null}
        {page === "activity" ? <ActivityPage workspace={workspace} busy={busy} post={post} /> : null}
        {page === "settings" ? <SettingsPage workspace={workspace} theme={theme} setTheme={setTheme} busy={busy} post={post} navigate={navigate} /> : null}
        {page === "help" ? <HelpPage navigate={navigate} /> : null}
        {page === "about" ? <AboutPage /> : null}
      </main>
      <footer className="app-footer"><span>StreamSnip AI</span><i>·</i><span>Capture and rendering stay on this PC.</span><span className="footer-spacer" /><span>{workspace.saving ? "Saving settings…" : workspace.saveError || "Local workspace"}</span></footer>
    </div>
    {toast ? <Toast toast={toast} close={() => setToast(null)} /> : null}
  </div>;
}

function Sidebar({ page, navigate, connected, running, mobileOpen, close }: {
  page: PageId; navigate: (page: PageId) => void; connected: boolean; running: boolean; mobileOpen: boolean; close: () => void;
}) {
  return <aside className={"sidebar" + (mobileOpen ? " sidebar-open" : "")}>
    <div className="brand-row">
      <span className="brand-mark"><Clapperboard size={20} /></span>
      <span className="brand-copy"><strong>StreamSnip AI</strong><small>Creator Studio</small></span>
      <button className="icon-button sidebar-close" aria-label="Close navigation" onClick={close}><X size={17} /></button>
    </div>
    <div className="workspace-card"><span className="workspace-avatar">S</span><span className="workspace-copy"><strong>Local workspace</strong><small>On this device</small></span><ChevronDown size={15} /></div>
    <nav className="sidebar-nav" aria-label="Main navigation">
      {navGroups.map((group) => <div className="nav-group" key={group.label}>
        <span className="nav-group-title">{group.label}</span>
        {group.items.map((item) => {
          const Icon = item.icon;
          return <button key={item.id} className={"nav-item" + (page === item.id ? " active" : "")} aria-current={page === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><Icon size={18} /><span>{item.label}</span></button>;
        })}
      </div>)}
    </nav>
    <div className="sidebar-bottom">
      <div className={"sidebar-engine" + (running ? " engine-running" : "")}><i /><span><strong>{!connected ? "Connecting to engine" : running ? "Capture active" : "Engine connected"}</strong><small>{connected ? "Local processing" : "Waiting for local API"}</small></span><ShieldCheck size={15} /></div>
      <button className={"nav-item" + (page === "help" ? " active" : "")} onClick={() => navigate("help")}><CircleHelp size={18} /><span>Help</span></button>
      <button className={"nav-item" + (page === "about" ? " active" : "")} onClick={() => navigate("about")}><Info size={18} /><span>About</span></button>
    </div>
  </aside>;
}

function EnginePill({ connected, running, stopping }: { connected: boolean; running: boolean; stopping: boolean }) {
  const label = !connected ? "Engine unavailable" : stopping ? "Stopping" : running ? "Capture running" : "Engine ready";
  return <span className={"engine-pill" + (!connected ? " is-offline" : running ? " is-running" : "")}><i />{label}</span>;
}
function ThemeOption({ item, selected, select }: { item: typeof themes[number]; selected: boolean; select: () => void }) {
  return <button className={"theme-option" + (selected ? " selected" : "")} onClick={select}>
    <span className="theme-swatches">{item.colors.map((color) => <i key={color} style={{ background: color }} />)}</span>
    <span className="theme-option-copy"><strong>{item.name}</strong><small>{item.description}</small></span>
    {selected ? <Check size={16} /> : null}
  </button>;
}
function PageHeading({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1>{description ? <p>{description}</p> : null}</div>{actions ? <div className="page-heading-actions">{actions}</div> : null}</div>;
}
function Panel({ title, description, action, children, className = "" }: { title: string; description?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={"panel " + className}><div className="panel-heading"><div><h2>{title}</h2>{description ? <p>{description}</p> : null}</div>{action ? <div className="panel-action">{action}</div> : null}</div>{children}</section>;
}
function Button({ children, kind = "secondary", onClick, disabled, size = "normal", type = "button" }: {
  children: ReactNode; kind?: "primary" | "secondary" | "quiet" | "danger"; onClick?: () => void; disabled?: boolean; size?: "normal" | "small"; type?: "button" | "submit";
}) {
  return <button type={type} className={"button button-" + kind + (size === "small" ? " button-small" : "")} onClick={onClick} disabled={disabled}>{children}</button>;
}
function StatusPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" | "live" }) {
  return <span className={"status-pill status-" + tone}><i />{children}</span>;
}
function Field({ label, hint, children, className = "" }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return <label className={"field " + className}><span className="field-label">{label}</span>{children}{hint ? <small className="field-hint">{hint}</small> : null}</label>;
}
function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (value: boolean) => void; label: string; description?: string }) {
  return <label className="toggle-row"><span><strong>{label}</strong>{description ? <small>{description}</small> : null}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>;
}
function Stat({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return <div className="summary-stat"><span>{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div>;
}
function EmptyState({ icon: Icon = FileVideo, title, description, action }: { icon?: LucideIcon; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={22} /></span><strong>{title}</strong><p>{description}</p>{action ? <div>{action}</div> : null}</div>;
}
function Toast({ toast, close }: { toast: ToastDetail; close: () => void }) {
  const Icon = toast.tone === "error" ? AlertCircle : toast.tone === "success" ? CheckCircle2 : Info;
  return <div className={"toast toast-" + toast.tone} role="status"><Icon size={17} /><div><strong>{toast.title}</strong>{toast.message ? <small>{toast.message}</small> : null}</div><button aria-label="Dismiss notification" onClick={close}><X size={15} /></button></div>;
}

function OverviewPage({ workspace, navigate, openClip }: { workspace: Workspace; navigate: (page: PageId) => void; openClip: (clip: Clip) => void }) {
  const state = workspace.state;
  const recent = state.clips.slice(0, 5);
  const creators = workspace.creators;
  const active = creators.filter((creator) => creator.running || isCreatorCaptureActive(creator, workspace));
  return <div className="page-stack">
    <PageHeading title="Studio overview" description="Monitor sources, review the latest clips, and keep your workflow moving." actions={<Button kind="primary" onClick={() => navigate("live")}><Radio size={16} />Open Live Studio</Button>} />
    <div className="summary-strip">
      <Stat label="Ready to review" value={count(state.clip_total)} detail="Unpublished clips" />
      <Stat label="Published" value={count(state.posted_total)} detail="In your local registry" />
      <Stat label="Active creators" value={count(active.length)} detail={count(creators.length) + " configured"} />
      <Stat label="Current session" value={duration(state.session.elapsed)} detail={count(state.session.clips) + " clips · " + count(state.session.chunks) + " chunks"} />
    </div>
    <div className="overview-grid">
      <div className="overview-main">
        <Panel title="Capture status" description="Your local engine and current source." action={<StatusPill tone={toneFor(state.phase, state.running)}>{phaseLabel(state.phase)}</StatusPill>}>
          <div className="capture-status">
            <span className={"capture-symbol" + (state.running ? " capture-symbol-live" : "")}><RadioTower size={23} /></span>
            <span className="capture-copy"><strong>{state.running ? state.status : "No active capture"}</strong><small>{state.running ? (state.mode === "file" ? "Processing a video file" : "Recording a live stream") + " · " + duration(state.session.elapsed) : "Choose a live source or a recorded video to begin."}</small></span>
            <Button kind="primary" onClick={() => navigate("live")}>{state.running ? "View session" : "Configure capture"}<ArrowRight size={15} /></Button>
          </div>
          <WorkflowStrip phase={state.phase} running={state.running} />
          {state.running ? <div className="progress-line"><div><span>{state.status}</span><b>{Math.max(0, Math.min(100, state.progress))}%</b></div><i><span style={{ width: Math.max(2, Math.min(100, state.progress)) + "%" }} /></i></div> : null}
        </Panel>
        <Panel title="Recent clips" description="Latest output from your capture and VOD workflows." action={<Button kind="quiet" size="small" onClick={() => navigate("clips")}>Open library<ArrowUpRight size={14} /></Button>}>
          {recent.length ? <div className="recent-clip-list">{recent.map((clip) => <ClipCompact key={clip.name} clip={clip} click={() => openClip(clip)} />)}</div> : <EmptyState icon={Clapperboard} title="No clips yet" description="Generated clips appear here after the engine finds and renders a highlight." action={<Button onClick={() => navigate("live")}>Choose a source</Button>} />}
        </Panel>
      </div>
      <aside className="overview-side">
        <Panel title="Creator activity" description="Live Studio captures and background monitors." action={<Button kind="quiet" size="small" onClick={() => navigate("creators")}>Manage<ArrowUpRight size={14} /></Button>}>
          {creators.length ? <div className="monitor-compact-list">{creators.slice(0, 5).map((creator) => {
            const captureActive = isCreatorCaptureActive(creator, workspace);
            const activeNow = creator.running || captureActive;
            return <div className="monitor-compact-row" key={creator.id}>
              <span className="creator-initial">{creator.name.trim().slice(0, 1).toUpperCase() || "C"}</span>
              <span className="creator-compact-copy"><strong>{creator.name}</strong><small>{captureActive ? "Recording in Live Studio" : creator.status || creator.phase || "Saved source"}</small></span>
              <StatusPill tone={activeNow ? "live" : "neutral"}>{captureActive ? "Recording" : creator.running ? "Monitoring" : "Idle"}</StatusPill>
            </div>;
          })}</div> : <EmptyState icon={Users} title="No creator sources" description="Add a channel to monitor live streams and recorded VODs." action={<Button onClick={() => navigate("creators")}>Add creator</Button>} />}
        </Panel>
        <Panel title="Latest activity" description="Recent local engine events." action={<Button kind="quiet" size="small" onClick={() => navigate("activity")}>Full activity<ArrowUpRight size={14} /></Button>}>
          {workspace.logs.length ? <div className="mini-log-list">{workspace.logs.slice(-6).reverse().map((log) => <div className="mini-log-row" key={log.id}><time>{log.t}</time><span>{log.m}</span></div>)}</div> : <div className="inline-empty">Engine events appear here when work begins.</div>}
        </Panel>
        <div className="storage-note"><ShieldCheck size={16} /><span><strong>Local-first processing</strong><small>Capture and rendering stay on this PC. Hosted AI providers receive transcript text when selected.</small></span></div>
      </aside>
    </div>
  </div>;
}

function WorkflowStrip({ phase, running }: { phase: string; running: boolean }) {
  const stages = [
    { id: "capture", label: "Capture", phases: ["waiting", "recording", "stopping"] },
    { id: "transcribe", label: "Transcribe", phases: ["transcribing"] },
    { id: "analyze", label: "Analyze", phases: ["analyzing"] },
    { id: "render", label: "Render", phases: ["rendering"] },
    { id: "publish", label: "Publish", phases: ["queued"] },
  ];
  const active = stages.find((stage) => stage.phases.includes(phase))?.id;
  const activeIndex = stages.findIndex((stage) => stage.id === active);
  return <div className="workflow-strip" aria-label="Capture workflow">
    {stages.map((stage, index) => <div className={"workflow-stage" + (active === stage.id ? " current" : "") + (activeIndex > index ? " passed" : "")} key={stage.id}>
      <span>{activeIndex > index ? <Check size={13} /> : index + 1}</span><strong>{stage.label}</strong>
    </div>)}
    {!running && !active ? <small>Ready</small> : null}
  </div>;
}
function ClipCompact({ clip, click }: { clip: Clip; click: () => void }) {
  return <button className="recent-clip-row" onClick={click}>
    <span className="recent-clip-icon"><FileVideo size={18} /></span>
    <span className="recent-clip-copy"><strong>{clip.title || clip.name}</strong><small>{clip.creator_name || clip.source || "Generated clip"} · {dateLabel(clip.mtime)}</small></span>
    <span className="recent-clip-size">{sizeLabel(clip.size_mb)}</span><ArrowUpRight size={14} className="recent-clip-arrow" />
  </button>;
}

function LivePage({ workspace, busy, post, navigate }: { workspace: Workspace; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>; navigate: (page: PageId) => void }) {
  const settings = workspace.settings || {};
  const [mode, setMode] = useState(String(settings.mode || "live"));
  const [target, setTarget] = useState(String(settings.target || ""));
  const [setupTab, setSetupTab] = useState<StudioSetupTab>("capture");
  const [frame, setFrame] = useState("");
  const [outputPreview, setOutputPreview] = useState("");
  const [outputPreviewCreator, setOutputPreviewCreator] = useState("");
  const [frameSize, setFrameSize] = useState({ width: 16, height: 9 });
  const [facecamBox, setFacecamBox] = useState({ x: Number(settings.cam_x ?? 70), y: Number(settings.cam_y ?? 4), w: Number(settings.cam_w ?? 29), h: Number(settings.cam_h ?? 37) });
  const [gameBox, setGameBox] = useState({ x: Number(settings.game_area_x ?? 23.6), y: Number(settings.game_area_y ?? 0), w: Number(settings.game_area_w ?? 52.8), h: Number(settings.game_area_h ?? 100) });
  const [facecamResult, setFacecamResult] = useState<RecordLike | null>(null);
  const [detectingFacecam, setDetectingFacecam] = useState(false);
  const [drag, setDrag] = useState<{ region: "facecam" | "game"; mode: "move" | "resize"; startX: number; startY: number; box: typeof facecamBox } | null>(null);
  const [selectedCreatorId, setSelectedCreatorId] = useState(() => workspace.creators.find((creator) => creator.id === String(settings.creator_id || "") || creatorTargetKey(creator.target) === creatorTargetKey(String(settings.target || "")))?.id || "");
  const selectedCreator = workspace.creators.find((creator) => creator.id === selectedCreatorId)
    || workspace.creators.find((creator) => creator.id === String(settings.creator_id || ""))
    || workspace.creators.find((creator) => creatorTargetKey(creator.target) === creatorTargetKey(target))
    || null;
  const sourceTarget = mode === "live" ? (target.trim() || selectedCreator?.target || "") : target;
  const running = workspace.state.running;
  const loadCreatorSettings = workspace.loadCreatorSettings;
  useEffect(() => {
    if (!selectedCreatorId || running) return;
    void loadCreatorSettings(selectedCreatorId).catch(() => undefined);
  }, [selectedCreatorId, running, loadCreatorSettings]);
  const update = (patch: Partial<AppSettings>) => { setOutputPreview(""); workspace.updateSettings(patch); };
  const detectedCreator = mode === "live" ? (selectedCreator?.name || inferCreatorTag(sourceTarget)) : "";
  const providerLabel = ({ gemini: "Gemini API", ollama: "Ollama", hooks: "Built-in hooks", huggingface: "Hugging Face", custom: "Custom API" } as Record<string, string>)[workspace.ai.provider] || "AI provider";
  const browse = async () => {
    const result = await post<{ path: string }>("browse-source", "/api/browse", {});
    if (result?.path) {
      setTarget(result.path);
      setMode("file");
      setOutputPreview("");
      update({ target: result.path, mode: "file" });
    }
  };
  const changeMode = (value: string) => {
    setMode(value);
    setOutputPreview("");
    update({ mode: value });
  };
  const changeTarget = (value: string) => {
    setTarget(value);
    setOutputPreview("");
    update({ target: value });
  };
  const start = async () => {
    const source = sourceTarget.trim();
    if (!source || running || busy || !workspace.configLoaded) return;
    const matchingCreator = mode === "live"
      ? workspace.creators.find((creator) => creatorTargetKey(creator.target) === creatorTargetKey(source))
      : undefined;
    const captureConfig: AppSettings = { ...(workspace.settings || settings), mode, target: source };
    delete captureConfig.creator_id;
    if (matchingCreator) captureConfig.creator_id = matchingCreator.id;
    if (workspace.ai.provider === "gemini" && !workspace.ai.gemini_key_set) {
      setSetupTab("ai");
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: {
        tone: "error",
        title: "Gemini API key required",
        message: "Add your Gemini API key and save AI settings before starting capture, or choose another provider.",
      } }));
      return;
    }
    try {
      await workspace.saveSettings(captureConfig);
      await workspace.saveAI();
    } catch {
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: {
        tone: "error",
        title: "Session settings could not be saved",
        message: workspace.saveError || "Review the settings and try again.",
      } }));
      return;
    }
    await post("start-capture", "/api/start", captureConfig);
  };
  const stop = async () => {
    if (workspace.state.stopping || !running) return;
    await post("stop-capture", "/api/stop", { force: false });
  };
  const preview = async () => {
    const result = await post<{ image: string }>("preview-source", "/api/frame", { mode, target: sourceTarget });
    if (result?.image) setFrame(result.image);
  };
  const previewOutput = async () => {
    const previewSettings = {
      ...settings,
      cam_x: facecamBox.x, cam_y: facecamBox.y, cam_w: facecamBox.w, cam_h: facecamBox.h,
      game_area_x: gameBox.x, game_area_y: gameBox.y, game_area_w: gameBox.w, game_area_h: gameBox.h,
    };
    const result = await post<{ video: string }>("preview-output", "/api/output-preview", {
      mode, target: sourceTarget, settings: previewSettings,
    });
    if (result?.video) {
      setOutputPreview(result.video);
      setOutputPreviewCreator(mode === "live"
        ? (selectedCreator?.target === sourceTarget ? selectedCreator.name : inferCreatorTag(sourceTarget) || "Live source")
        : "Local video");
    } else {
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: {
        tone: "error", title: "Output preview unavailable",
        message: "Check that the selected creator is live or choose a readable video file, then try again.",
      } }));
    }
  };
  const tabs: Array<{ id: StudioSetupTab; label: string; icon: LucideIcon }> = [
    { id: "capture", label: "Capture", icon: Radio },
    { id: "ai", label: "AI provider", icon: Sparkles },
    { id: "speech", label: "Transcription", icon: FileText },
    { id: "captions", label: "Captions", icon: Clapperboard },
  ];
  return <div className="page-stack live-studio-page">
    <PageHeading title="Live Studio" description="Choose your source, tune the clip pipeline, then start when everything is ready." actions={<StatusPill tone={toneFor(workspace.state.phase, running)}>{phaseLabel(workspace.state.phase)}</StatusPill>} />
    <Panel title="Source" description="Paste a Twitch or YouTube channel link, or choose a local VOD.">
      <div className="segmented-control">
        <button className={mode === "live" ? "selected" : ""} onClick={() => changeMode("live")} disabled={running}><Radio size={15} />Live stream</button>
        <button className={mode === "file" ? "selected" : ""} onClick={() => changeMode("file")} disabled={running}><Video size={15} />Video file / VOD</button>
      </div>
      {mode === "live" ? <div className="live-creator-picker">
        <div className="live-creator-picker-heading"><div><strong>Choose a creator</strong><small>Saved creators keep their live recordings and clips in their own folders.</small></div><Button size="small" onClick={() => navigate("creators")}><Users size={14} />Manage creators</Button></div>
        {workspace.creators.length ? <div className="live-creator-list" role="listbox" aria-label="Saved creators">
          {workspace.creators.map((creator) => <button type="button" role="option" aria-selected={selectedCreator?.id === creator.id} key={creator.id} className={"live-creator-option" + (selectedCreator?.id === creator.id ? " selected" : "")} onClick={() => { setSelectedCreatorId(creator.id); setTarget(creator.target); setOutputPreview(""); setFacecamResult(null); }}>
            <span className="creator-initial">{creator.name.trim().slice(0, 1).toUpperCase() || "C"}</span><span className="live-creator-option-copy"><strong>{creator.name}</strong><small>{isCreatorCaptureActive(creator, workspace) ? "Recording in Live Studio" : creator.status || creator.phase || creator.target}</small></span><StatusPill tone={isCreatorCaptureActive(creator, workspace) || creator.running ? "live" : "neutral"}>{isCreatorCaptureActive(creator, workspace) ? "Recording" : creator.running ? "Monitoring" : "Saved"}</StatusPill><span className="creator-select-mark"><Check size={15}/></span>
          </button>)}
        </div> : <EmptyState icon={Users} title="No saved creators yet" description="Add a Twitch or YouTube creator first. Your saved channels will appear here." action={<Button onClick={() => navigate("creators")}>Add a creator</Button>} />}
        {selectedCreator ? <div className="studio-source-meta"><div className="studio-channel-detection"><span>Selected creator</span><strong>{selectedCreator.name}</strong><small>{selectedCreator.target}</small></div><StatusPill tone={isCreatorCaptureActive(selectedCreator, workspace) || selectedCreator.running ? "live" : "success"}>{isCreatorCaptureActive(selectedCreator, workspace) ? "Capture active" : selectedCreator.running ? "Monitoring" : "Ready"}</StatusPill></div> : null}
      </div> : <Field label="Video file path" hint="Choose a local video supported by FFmpeg.">
        <div className="field-with-action"><input value={target} onChange={(event) => changeTarget(event.target.value)} disabled={running} placeholder="Choose a video file" /><Button onClick={() => void browse()} disabled={running || !!busy}><FolderOpen size={15} />Browse</Button></div>
      </Field>}
    </Panel>

    <Panel title="Facecam detection and layout" description="Find the webcam from multiple video frames, then inspect and adjust its exact region before rendering.">
      <div className="facecam-toolbar">
        <div><strong>Automatic facecam finder</strong><small>Local YuNet face detection + stable-border analysis. No cloud AI required.</small></div>
        <div className="facecam-toolbar-actions">
          <Button onClick={() => void preview()} disabled={!sourceTarget.trim() || !!busy}><Eye size={15}/>Load framing preview</Button>
          <Button kind="primary" onClick={async () => {
            if (!sourceTarget.trim() || detectingFacecam || !!busy) return;
            setDetectingFacecam(true); setFacecamResult(null);
            try {
              const previewResult = await post<{ image: string }>("facecam-frame", "/api/frame", { mode, target: sourceTarget });
              if (previewResult?.image) setFrame(previewResult.image);
              const result = await post<RecordLike>("facecam-detect", "/api/facecam/detect", { mode, target: sourceTarget });
              if (result) {
                setFacecamResult(result);
                if (result.found && result.cam) setFacecamBox({ x: result.cam.x * 100, y: result.cam.y * 100, w: result.cam.w * 100, h: result.cam.h * 100 });
              }
            } finally { setDetectingFacecam(false); }
          }} disabled={!sourceTarget.trim() || detectingFacecam || !!busy}><WandSparkles size={15}/>{detectingFacecam ? "Analyzing frames…" : "Find facecam automatically"}</Button>
        </div>
      </div>
      {facecamResult ? <div className={"facecam-result " + (facecamResult.found ? "found" : "not-found")}><StatusPill tone={facecamResult.found ? "success" : "warning"}>{facecamResult.found ? "Facecam detected" : "No confident match"}</StatusPill><span>{facecamResult.found ? "Method: " + String(facecamResult.method || "multi-frame analysis") + " · Confidence: " + Math.round(Number(facecamResult.confidence || 0) * 100) + "%" : String(facecamResult.reason || "Try another section of the video or adjust the region manually.")}</span></div> : null}
      {frame ? <div className="facecam-editor-wrap"><div className="facecam-editor-stage" style={{ aspectRatio: `${frameSize.width} / ${frameSize.height}`, maxWidth: `min(100%, ${(440 * frameSize.width / frameSize.height).toFixed(1)}px)` }} onPointerMove={(event) => {
        if (!drag) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const dx = (event.clientX - drag.startX) / rect.width * 100;
        const dy = (event.clientY - drag.startY) / rect.height * 100;
        const setBox = drag.region === "facecam" ? setFacecamBox : setGameBox;
        setBox(drag.mode === "move"
          ? { ...drag.box, x: Math.max(0, Math.min(100 - drag.box.w, drag.box.x + dx)), y: Math.max(0, Math.min(100 - drag.box.h, drag.box.y + dy)) }
          : { ...drag.box, w: Math.max(5, Math.min(100 - drag.box.x, drag.box.w + dx)), h: Math.max(5, Math.min(100 - drag.box.y, drag.box.h + dy)) });
      }} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
        <img src={frame} alt="Video frame used to inspect the facecam region" onLoad={(event) => setFrameSize({ width: event.currentTarget.naturalWidth || 16, height: event.currentTarget.naturalHeight || 9 })}/>
        <div className="facecam-selection game-region" style={{ left: gameBox.x + "%", top: gameBox.y + "%", width: gameBox.w + "%", height: gameBox.h + "%" }} onPointerDown={(event) => { event.stopPropagation(); setOutputPreview(""); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ region: "game", mode: "move", startX: event.clientX, startY: event.clientY, box: gameBox }); }}>
          <span>GAME CAPTURE</span><button type="button" aria-label="Resize game capture region" className="facecam-resize game-resize" onPointerDown={(event) => { event.stopPropagation(); setOutputPreview(""); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ region: "game", mode: "resize", startX: event.clientX, startY: event.clientY, box: gameBox }); }} />
        </div>
        <div className="facecam-selection camera-region" style={{ left: facecamBox.x + "%", top: facecamBox.y + "%", width: facecamBox.w + "%", height: facecamBox.h + "%" }} onPointerDown={(event) => { event.stopPropagation(); setOutputPreview(""); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ region: "facecam", mode: "move", startX: event.clientX, startY: event.clientY, box: facecamBox }); }}>
          <span>FACECAM</span><button type="button" aria-label="Resize facecam region" className="facecam-resize" onPointerDown={(event) => { event.stopPropagation(); setOutputPreview(""); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ region: "facecam", mode: "resize", startX: event.clientX, startY: event.clientY, box: facecamBox }); }} />
        </div>
      </div><small className="facecam-editor-hint"><b>Pink:</b> facecam (top panel). <b>Cyan:</b> gameplay capture (bottom panel). Drag either box to move; use its corner handle to resize.</small>
      <div className="facecam-editor-actions">
        <Button onClick={() => { setFacecamBox({ x: 70, y: 4, w: 29, h: 37 }); setGameBox({ x: 23.6, y: 0, w: 52.8, h: 100 }); setOutputPreview(""); setFacecamResult(null); }}>Reset both regions</Button>
        <Button kind="primary" onClick={() => { update({ cam_x: Number(facecamBox.x.toFixed(1)), cam_y: Number(facecamBox.y.toFixed(1)), cam_w: Number(facecamBox.w.toFixed(1)), cam_h: Number(facecamBox.h.toFixed(1)), game_area_x: Number(gameBox.x.toFixed(1)), game_area_y: Number(gameBox.y.toFixed(1)), game_area_w: Number(gameBox.w.toFixed(1)), game_area_h: Number(gameBox.h.toFixed(1)) } as Partial<AppSettings>); window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: { tone: "success", title: "Framing saved", message: "Both facecam and game capture regions will be used by the renderer." } })); }}>Save framing</Button>
      </div></div> : <div className="facecam-empty"><Video size={22}/><strong>Load a frame to set up both regions</strong><small>Automatic detection finds the facecam; the game capture region can be moved and resized independently.</small></div>}
      <div className="facecam-layout-values"><span>Facecam <b>{facecamBox.x.toFixed(1)}%, {facecamBox.y.toFixed(1)}% · {facecamBox.w.toFixed(1)} × {facecamBox.h.toFixed(1)}%</b></span><span>Game <b>{gameBox.x.toFixed(1)}%, {gameBox.y.toFixed(1)}% · {gameBox.w.toFixed(1)} × {gameBox.h.toFixed(1)}%</b></span></div>
    </Panel>

    <div className="studio-workspace-layout">
      <section className="studio-setup" aria-label="Session setup">
        <div className="studio-setup-heading">
          <div><h2>Session setup</h2><p>All processing options are available here before you start a capture.</p></div>
          <span className="studio-save-state">{workspace.saving ? "Saving changes..." : workspace.saveError || "Saved on this PC"}</span>
        </div>
        <nav className="studio-tabs" role="tablist" aria-label="Session configuration">
          {tabs.map((tab, index) => {
            const Icon = tab.icon;
            return <button key={tab.id} type="button" role="tab" id={"studio-tab-" + tab.id} aria-controls="studio-setup-panel" aria-selected={setupTab === tab.id} tabIndex={setupTab === tab.id ? 0 : -1} className={"studio-tab" + (setupTab === tab.id ? " selected" : "")} onClick={() => setSetupTab(tab.id)} onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              event.preventDefault();
              const nextIndex = (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
              const next = tabs[nextIndex];
              setSetupTab(next.id);
              document.getElementById("studio-tab-" + next.id)?.focus();
            }}>
              <Icon size={16} /><span>{tab.label}</span>
              {tab.id === "ai" ? <small>{providerLabel}</small> : null}
            </button>;
          })}
        </nav>
        <div className="studio-tab-panel" id="studio-setup-panel" role="tabpanel" aria-labelledby={"studio-tab-" + setupTab}>
          {setupTab === "capture" ? <CaptureSettings workspace={workspace} /> : null}
          {setupTab === "ai" ? <AISettings workspace={workspace} /> : null}
          {setupTab === "speech" ? <SpeechSettings workspace={workspace} /> : null}
          {setupTab === "captions" ? <CaptionSettings workspace={workspace} mode={mode} target={target} /> : null}
        </div>
      </section>

      <aside className="studio-session-column">
        <Panel title="Session status" description="Live progress reported by the local engine.">
          <div className="session-state">
            <span className={"session-state-icon" + (running ? " is-active" : "")}><RadioTower size={22} /></span>
            <span><strong>{running ? workspace.state.status : "No active session"}</strong><small>{running ? (workspace.state.mode === "file" ? "Processing a video file" : "Recording a live stream") + " · " + duration(workspace.state.session.elapsed) : "Progress appears here after capture starts."}</small></span>
            <StatusPill tone={toneFor(workspace.state.phase, running)}>{phaseLabel(workspace.state.phase)}</StatusPill>
          </div>
          {running ? <><WorkflowStrip phase={workspace.state.phase} running={running} /><div className="progress-line"><div><span>{workspace.state.status}</span><b>{Math.max(0, Math.min(100, workspace.state.progress))}%</b></div><i><span style={{ width: Math.max(2, Math.min(100, workspace.state.progress)) + "%" }} /></i></div></> : null}
          <div className="session-facts"><div><span>Clips created</span><strong>{count(workspace.state.session.clips)}</strong></div><div><span>Segments processed</span><strong>{count(workspace.state.session.chunks)}</strong></div><div><span>Elapsed</span><strong>{duration(workspace.state.session.elapsed)}</strong></div></div>
        </Panel>
        <Panel title="Processing tools" description="The local components used for each session.">
          <ToolRow icon={Cpu} title="NVIDIA GPU" detail="CUDA is selected automatically when available." />
          <ToolRow icon={HardDrive} title="FFmpeg" detail="Video cutting, encoding, and caption rendering." />
          <ToolRow icon={Radio} title="Streamlink" detail="Live Twitch and YouTube capture." />
        </Panel>
        <div className="storage-note"><ShieldCheck size={16} /><span><strong>Capture is user-controlled</strong><small>Opening Live Studio never starts a recording. Your settings are saved before capture begins.</small></span></div>
      </aside>
    </div>

    <div className="studio-runbar" role="region" aria-label="Capture actions">
      <div className="studio-runbar-copy">
        <span className={"studio-runbar-indicator" + (running ? " running" : "")} />
        <span><strong>{running ? "Capture is running" : "Ready when you are"}</strong><small>{running ? (workspace.state.mode === "file" ? "Processing the selected video" : "Recording " + (detectedCreator || "the selected stream")) : (detectedCreator || (target.trim() ? "Source added" : "Choose a source")) + " · " + providerLabel + " · " + (workspace.saving ? "Saving settings" : "Settings ready")}</small></span>
      </div>
      <div className="studio-runbar-actions">
        <span className="studio-runbar-save">{workspace.saving ? "Saving..." : workspace.saveError || ""}</span>
        <Button onClick={() => void previewOutput()} disabled={!sourceTarget.trim() || !!busy}><Eye size={15} />Preview clip</Button>
        {!running ? <Button kind="primary" onClick={() => void start()} disabled={!sourceTarget.trim() || !!busy || workspace.saving || !workspace.configLoaded}><Play size={15} fill="currentColor" />Start capture</Button> : <Button kind="danger" onClick={() => void stop()} disabled={!!busy || workspace.state.stopping}><Square size={14} fill="currentColor" />{workspace.state.stopping ? "Finishing..." : "Stop capture"}</Button>}
      </div>
    </div>
    {outputPreview ? <Panel title={outputPreviewCreator + " · Rendered clip preview"} action={<Button kind="quiet" size="small" onClick={() => setOutputPreview("")}>Close</Button>}>
      <div className="clip-output-preview">
        <div className="clip-output-preview-viewport"><video src={outputPreview} controls autoPlay loop muted playsInline preload="auto" aria-label={"Rendered clip preview for " + outputPreviewCreator} /></div>
        <div className="clip-output-preview-copy">
          <span className="clip-output-preview-kicker">PLAYABLE OUTPUT PREVIEW · 2.5 SEC</span>
          <strong>{String(settings.output_format || "9:16")} · {String(settings.layout || "Facecam + game (Twitch)")}</strong>
          <p>This short video is rendered from the selected creator's own source using the same crop, layout, and caption-rendering pipeline as saved clips.</p>
          <p>The sample words are illustrative. Real clips use detected speech and your selected caption style and position. Preview audio is muted; the final clip keeps its processed audio.</p>
        </div>
      </div>
    </Panel> : null}
  </div>;
}

function ToolRow({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return <div className="tool-row"><Icon size={17} /><span><strong>{title}</strong><small>{detail}</small></span></div>;
}

function CreatorsPage({ workspace, busy, post, navigate }: { workspace: Workspace; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>; navigate: (page: PageId) => void }) {
  const creators = workspace.creators;
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const [target, setTarget] = useState("");
  const [folderOpen, setFolderOpen] = useState("");
  const [removing, setRemoving] = useState<Creator | null>(null);
  const folders = [["live_clips", "Live clips"], ["live_recordings", "Live recordings"], ["vod_inbox", "Recorded VOD inbox"], ["vod_clips", "VOD clips"], ["vod_processed", "Processed VODs"], ["vod_failed", "Failed VODs"]];
  const activeSources = creators.filter((creator) => creator.running || isCreatorCaptureActive(creator, workspace)).length;
  const add = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = await post<{ creator?: Creator }>("add-creator", "/api/creators/add", { name, target });
    if (result) { setName(""); setNameEdited(false); setTarget(""); setFormOpen(false); }
  };
  return <div className="page-stack">
    <PageHeading title="Creators" description="Track Live Studio captures, background monitors, and recorded-VOD folders for each creator." actions={<Button kind="primary" onClick={() => setFormOpen((value) => !value)}><Plus size={16} />Add creator</Button>} />
    {formOpen ? <Panel title="Add a creator" description="Paste a Twitch or YouTube channel or stream URL."><form className="add-creator-form" onSubmit={(event) => void add(event)}>
      <Field label="Creator name" hint={nameEdited ? "Name entered manually." : "Filled from supported Twitch and YouTube channel links; you can edit it."}><input value={name} onChange={(event) => { setName(event.target.value); setNameEdited(true); }} maxLength={80} required placeholder="Auto-detected from channel URL" /></Field>
      <Field label="Twitch or YouTube URL"><input value={target} onChange={(event) => { const value = event.target.value; setTarget(value); if (!nameEdited) setName(inferCreatorTag(value).replace(/^@/, "")); }} required placeholder="https://www.twitch.tv/channel" /></Field>
      <div className="form-actions"><Button kind="primary" type="submit" disabled={!name.trim() || !target.trim() || !!busy}><Plus size={15} />Save creator</Button><Button onClick={() => { setFormOpen(false); setName(""); setNameEdited(false); setTarget(""); }}>Cancel</Button></div>
    </form></Panel> : null}
    <div className="creator-toolbar"><span>{count(creators.length)} configured creator{creators.length === 1 ? "" : "s"}</span><span>{count(activeSources)} active live source{activeSources === 1 ? "" : "s"}</span></div>
    {creators.length ? <div className="creator-table">
      <div className="creator-table-head"><span>Creator</span><span>Live activity</span><span>VOD inbox</span><span>Library</span><span>Actions</span></div>
      {creators.map((creator) => {
        const captureActive = isCreatorCaptureActive(creator, workspace);
        const activeNow = creator.running || captureActive;
        const liveDetail = captureActive
          ? (creator.running ? "Live Studio capture and background monitor are active." : "Recording in Live Studio · Background monitor stopped.")
          : creator.status || "Saved source";
        return <div className="creator-table-row" key={creator.id}>
          <div className="creator-identity"><span className={"creator-avatar" + (activeNow ? " active" : "")}>{creator.name.trim().slice(0, 1).toUpperCase() || "C"}</span><span><strong>{creator.name}</strong><small title={creator.target}>{creator.target}</small></span></div>
          <div className="creator-status-cell"><StatusPill tone={activeNow ? "live" : creator.phase === "stopping" ? "warning" : "neutral"}>{captureActive ? "Capture active" : creator.running ? "Monitoring" : phaseLabel(creator.phase || "idle")}</StatusPill><small>{liveDetail}</small></div>
          <div className="creator-status-cell"><StatusPill tone={creator.watching_vods ? "success" : "neutral"}>{creator.watching_vods ? "Watching" : "Paused"}</StatusPill><small>{creator.vod_status || count(creator.vod_pending) + " files waiting"}</small></div>
          <div className="creator-counts"><span>{count(creator.live_clips)} live</span><span>{count(creator.vod_clips)} VOD</span></div>
          <div className="creator-actions">
            {creator.running ? <Button size="small" kind="danger" onClick={() => void post("stop-" + creator.id, "/api/creators/stop", { id: creator.id })} disabled={!!busy || creator.phase === "stopping"}><Square size={13} />{creator.phase === "stopping" ? "Finishing..." : "Stop monitor"}</Button> : <Button size="small" kind="primary" onClick={() => void post("start-" + creator.id, "/api/creators/start", { id: creator.id })} disabled={!!busy}><Play size={13} />Monitor</Button>}
            {captureActive ? <><Button size="small" onClick={() => navigate("live")}><Radio size={13} />View capture</Button><Button size="small" kind="danger" onClick={() => void post("stop-capture-" + creator.id, "/api/creators/stop-capture", { id: creator.id, force: false })} disabled={!!busy || !!creator.capture_stopping}><Square size={13} />{creator.capture_stopping ? "Finishing..." : "Stop capture"}</Button></> : null}
            {creator.watching_vods ? <Button size="small" onClick={() => void post("stop-vod-" + creator.id, "/api/creators/stop-vod-watch", { id: creator.id })} disabled={!!busy}><Pause size={13} />Stop VOD</Button> : <Button size="small" onClick={() => void post("watch-vod-" + creator.id, "/api/creators/watch-vods", { id: creator.id })} disabled={!!busy}><FolderOpen size={13} />Watch VODs</Button>}
            <div className="folder-menu"><button className="icon-button" aria-label={"Open " + creator.name + " folders"} aria-expanded={folderOpen === creator.id} onClick={() => setFolderOpen(folderOpen === creator.id ? "" : creator.id)}><MoreHorizontal size={17} /></button>
              {folderOpen === creator.id ? <div className="folder-popover">{folders.map(([folder, label]) => <button key={folder} onClick={() => { void post("folder-" + creator.id, "/api/creators/open", { id: creator.id, folder }); setFolderOpen(""); }}><FolderOpen size={14} />{label}</button>)}<button className="folder-danger" onClick={() => { setRemoving(creator); setFolderOpen(""); }}><Trash2 size={14} />Remove creator</button></div> : null}
            </div>
          </div>
        </div>;
      })}
    </div> : <EmptyState icon={Users} title="No creator sources yet" description="Add a Twitch or YouTube channel. Live Studio captures, background monitors, and recorded-VOD clips will be tracked separately." action={<Button kind="primary" onClick={() => setFormOpen(true)}><Plus size={15} />Add creator</Button>} />}
    {removing ? <div className="inline-confirm"><span>Remove {removing.name}? Existing recordings and clips will be kept.</span><Button size="small" kind="danger" onClick={() => { void post("remove-" + removing.id, "/api/creators/remove", { id: removing.id }).then(() => setRemoving(null)); }}>Remove creator</Button><Button size="small" onClick={() => setRemoving(null)}>Cancel</Button></div> : null}
  </div>;
}

function ClipLibraryPage({ workspace, published, navigate, query, setQuery, selectedClip, setSelectedClip, openForPublishing, openBulkPublishing, busy, post }: {
  workspace: Workspace; published: boolean; navigate: (page: PageId) => void; query: string; setQuery: (value: string) => void; selectedClip: Clip | null;
  setSelectedClip: (clip: Clip | null) => void; openForPublishing: (clip: Clip) => void; openBulkPublishing: (names: string[]) => void;
  busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>;
}) {
  const [selectedNames, setSelectedNames] = useState<string[]>([]);
  const [metadataDraft, setMetadataDraft] = useState<{ name: string; title: string; description: string } | null>(null);
  const title = metadataDraft && metadataDraft.name === selectedClip?.name ? metadataDraft.title : selectedClip?.title || "";
  const description = metadataDraft && metadataDraft.name === selectedClip?.name ? metadataDraft.description : selectedClip?.description || "";
  const setTitle = (value: string) => {
    if (!selectedClip) return;
    setMetadataDraft((current) => ({
      name: selectedClip.name,
      title: value,
      description: current?.name === selectedClip.name ? current.description : selectedClip.description || "",
    }));
  };
  const setDescription = (value: string) => {
    if (!selectedClip) return;
    setMetadataDraft((current) => ({
      name: selectedClip.name,
      title: current?.name === selectedClip.name ? current.title : selectedClip.title || "",
      description: value,
    }));
  };
  const [platform, setPlatform] = useState("youtube");
  const [confirm, setConfirm] = useState<"selected" | "all" | null>(null);
  const clips = workspace.state.clips;
  const filtered = useMemo(() => clips.filter((clip) => (clip.title || "").concat(" ", clip.name, " ", clip.creator_name || "", " ", clip.source || "").toLowerCase().includes(query.toLowerCase())), [clips, query]);
  const total = published ? workspace.state.posted_total : workspace.state.clip_total;
  const pageSize = 60;
  const currentPage = Math.floor(workspace.clipOffset / pageSize) + 1;
  const maxPages = Math.max(1, Math.ceil(total / pageSize));
  const toggleAll = () => setSelectedNames(selectedNames.length === filtered.length ? [] : filtered.map((clip) => clip.name));
  const toggleOne = (name: string) => setSelectedNames((items) => items.includes(name) ? items.filter((item) => item !== name) : items.concat(name));
  const deleteNow = async () => {
    if (confirm === "all") await post("delete-all", "/api/delete_all", { clip_tab: published ? "posted" : "clips" });
    else if (selectedClip && selectedNames.length === 0) await post("delete-one", "/api/delete", { name: selectedClip.name });
    else if (selectedNames.length) await post("delete-many", "/api/delete_many", { names: selectedNames });
    setConfirm(null); setSelectedNames([]); setSelectedClip(null);
  };
  const saveMetadata = async () => {
    if (!selectedClip || !title.trim()) return;
    const result = await post<{ ok: boolean }>("save-clip-metadata", "/api/clip-metadata", { name: selectedClip.name, title, description });
    if (result) {
      setSelectedClip({ ...selectedClip, title, description });
      setMetadataDraft(null);
    }
  };
  return <div className="page-stack">
    <PageHeading title={published ? "Published" : "Clip library"} description={published ? "Clips recorded in your local posted registry." : "Review generated clips, edit post metadata, and prepare a publishing handoff."} actions={<Button onClick={() => void post("open-clips-folder", "/api/open_folder", {})}><FolderOpen size={15} />Open folder</Button>} />
    <div className="library-toolbar">
      <div className="library-tabs">
        <button className={!published ? "selected" : ""} onClick={() => { navigate("clips"); setSelectedClip(null); }}><Video size={15} />Ready to review <b>{count(workspace.state.clip_total)}</b></button>
        <button className={published ? "selected" : ""} onClick={() => { navigate("published"); setSelectedClip(null); }}><BadgeCheck size={15} />Published <b>{count(workspace.state.posted_total)}</b></button>
      </div>
      <label className="library-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter this page by title or creator" /></label>
    </div>
    {selectedNames.length ? <div className="selection-bar"><strong>{count(selectedNames.length)} selected</strong><Button size="small" onClick={() => openBulkPublishing(selectedNames)} disabled={published}><Send size={14} />Publish selected</Button><Button size="small" kind="danger" onClick={() => setConfirm("selected")}><Trash2 size={14} />Delete</Button><Button size="small" kind="quiet" onClick={() => setSelectedNames([])}>Clear</Button></div> : null}
    <div className={"clip-library-layout" + (selectedClip ? " has-inspector" : "")}>
      <section className="clip-list-panel">
        <div className="clip-list-head"><label><input type="checkbox" checked={filtered.length > 0 && selectedNames.length === filtered.length} onChange={toggleAll} /><span>{filtered.length ? "Select this page" : "Clips"}</span></label><span>{count(total)} total</span><button className="text-button danger-text" onClick={() => setConfirm("all")} disabled={!total}>Delete all</button></div>
        {filtered.length ? <div className="clip-list">{filtered.map((clip) => <div className={"clip-row" + (selectedClip?.name === clip.name ? " selected" : "")} key={clip.name}>
          <input className="clip-checkbox" type="checkbox" aria-label={"Select " + (clip.title || clip.name)} checked={selectedNames.includes(clip.name)} onChange={() => toggleOne(clip.name)} />
          <button className="clip-thumb" onClick={() => setSelectedClip(clip)} aria-label={"Preview " + (clip.title || clip.name)}>
            <video src={clipUrl(clip.name)} muted playsInline preload="metadata" onLoadedMetadata={(event) => { try { event.currentTarget.currentTime = 0.35; } catch { /* This file may not seek on metadata load. */ } }} />
            <span className="thumb-play"><Play size={15} fill="currentColor" /></span>
          </button>
          <button className="clip-main-copy" onClick={() => setSelectedClip(clip)}><strong>{clip.title || clip.name}</strong><span>{clip.creator_name || clip.source || "Generated clip"}</span><small>{dateLabel(clip.mtime)} · {sizeLabel(clip.size_mb)}</small></button>
          <button className="icon-button clip-row-open" aria-label={"Open " + clip.name} onClick={() => setSelectedClip(clip)}><ArrowUpRight size={16} /></button>
        </div>)}</div> : <EmptyState icon={published ? BadgeCheck : Clapperboard} title={query ? "No matching clips" : published ? "Nothing published yet" : "Your clip library is empty"} description={query ? "Try another title, file name, or creator." : "Clips appear here after a source has been processed and a highlight rendered."} action={query ? <Button onClick={() => setQuery("")}>Clear search</Button> : undefined} />}
        <div className="pagination-row"><span>Page {currentPage} of {maxPages}</span><div><Button size="small" disabled={workspace.clipOffset <= 0} onClick={() => workspace.setClipOffset(Math.max(0, workspace.clipOffset - pageSize))}><ChevronLeft size={15} />Previous</Button><Button size="small" disabled={workspace.clipOffset + pageSize >= total} onClick={() => workspace.setClipOffset(workspace.clipOffset + pageSize)}>Next<ChevronRight size={15} /></Button></div></div>
      </section>
      {selectedClip ? <aside className="clip-inspector">
        <div className="inspector-head"><strong>Clip details</strong><button className="icon-button" aria-label="Close clip details" onClick={() => setSelectedClip(null)}><X size={16} /></button></div>
        <video className="inspector-video" controls playsInline preload="metadata" src={clipUrl(selectedClip.name)} />
        <div className="inspector-file"><strong>{selectedClip.name}</strong><span>{sizeLabel(selectedClip.size_mb)}</span></div>
        <Field label="Post title"><input maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Add a title" /></Field>
        <Field label="Post description"><textarea rows={5} maxLength={2200} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Write a description" /></Field>
        <div className="inspector-actions"><Button kind="primary" onClick={() => void saveMetadata()} disabled={!title.trim() || !!busy}><Check size={15} />Save details</Button><Button onClick={() => openForPublishing(selectedClip)} disabled={published}><Send size={15} />Publish</Button></div>
        <div className="inspector-subactions"><a href={clipUrl(selectedClip.name)} download><Download size={14} />Download clip</a><button onClick={() => void post("reveal-clip", "/api/reveal", { name: selectedClip.name })}><FolderOpen size={14} />Show in folder</button></div>
        {!published ? <div className="mark-posted"><label>Record an external post<select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="youtube">YouTube</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="tiktok">TikTok</option><option value="manual">Other / manual</option></select></label><Button size="small" onClick={() => void post("mark-posted", "/api/posted/mark", { name: selectedClip.name, platform, accounts: [platform] })}><BadgeCheck size={14} />Mark as published</Button></div> : <StatusPill tone="success">Recorded as published · {dateLabel(selectedClip.posted_at)}</StatusPill>}
        <Button kind="danger" size="small" onClick={() => setConfirm("selected")}><Trash2 size={14} />Delete clip</Button>
      </aside> : null}
    </div>
    {confirm ? <div className="inline-confirm"><span>{confirm === "all" ? "Permanently delete all " + count(total) + " clips in this tab?" : "Permanently delete the selected clip(s) and their caption files?"}</span><Button kind="danger" size="small" onClick={() => void deleteNow()}>Confirm delete</Button><Button size="small" onClick={() => setConfirm(null)}>Cancel</Button></div> : null}
  </div>;
}

function PublishingPage({ workspace, clip, bulkNames, browserStatus, setBrowserStatus, busy, post, openLibrary }: {
  workspace: Workspace; clip: Clip | null; bulkNames: string[]; browserStatus: RecordLike; setBrowserStatus: (value: RecordLike) => void;
  busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>; openLibrary: () => void;
}) {
  const pub = workspace.publishing.providers?.zernio || workspace.publishing;
  const [apiKey, setApiKey] = useState("");
  const [autoPost, setAutoPost] = useState(Boolean(pub.auto_post));
  const [schedule, setSchedule] = useState(num(pub.schedule_minutes, 0));
  const [visibility, setVisibility] = useState(String(pub.visibility || "public"));
  const [accountsByPlatform, setAccountsByPlatform] = useState<Record<string, string>>(pub.accounts || {});
  const [platform, setPlatform] = useState("youtube");
  const [title, setTitle] = useState(clip?.title || "");
  const [description, setDescription] = useState(clip?.description || "");
  const [manualMessage, setManualMessage] = useState("");
  const selectedCount = Object.keys(accountsByPlatform).length;
  const toggleAccount = (account: { id: string; platform: string }) => setAccountsByPlatform((current) => {
    const next = { ...current };
    if (next[account.platform] === account.id) delete next[account.platform];
    else next[account.platform] = account.id;
    return next;
  });
  const loadAccounts = async () => { try { await workspace.fetchAccounts(); } catch { /* The API layer reports failures. */ } };
  const saveSettings = async () => {
    try {
      await workspace.savePublishing({ api_key: apiKey, account_ids: accountsByPlatform, auto_post: autoPost, schedule_minutes: schedule, visibility });
      setApiKey("");
    } catch { /* The API layer reports failures. */ }
  };
  const publish = async () => {
    if (!selectedCount) return;
    if (bulkNames.length) await post("publish-batch", "/api/publishing/publish", { names: bulkNames, account_ids: accountsByPlatform });
    else if (clip) await post("publish-one", "/api/publishing/publish-one", { name: clip.name, title, description, account_ids: accountsByPlatform });
  };
  const manualUpload = async () => {
    if (!clip) return;
    const result = await post<RecordLike>("manual-upload", "/api/browser/prepare", { name: clip.name, platform, title, description, browser: "default" });
    if (result) {
      setManualMessage("Opened " + platform + " in your system default browser. Select the video and complete the final publish step there.");
      try { setBrowserStatus(await apiGet<RecordLike>("/api/browser/status")); } catch { /* Keep the handoff message. */ }
    }
  };
  return <div className="page-stack">
    <PageHeading title="Publishing" description="Connect a social account, queue clips through Zernio, or prepare a manual upload." actions={<Button onClick={() => void workspace.refreshPublishing()}><RefreshCw size={15} />Refresh status</Button>} />
    <div className="publishing-layout">
      <div className="publishing-main">
        <Panel title="Zernio connection" description="Use your Zernio API key to load connected social accounts.">
          <div className="provider-summary"><span className="provider-logo">Z</span><span><strong>Zernio</strong><small>Social account connection and scheduled publishing.</small></span><StatusPill tone={pub.api_key_set ? "success" : "warning"}>{pub.api_key_set ? "Key saved" : "Not configured"}</StatusPill></div>
          <Field label="Zernio API key" hint={pub.api_key_set ? "A key is saved locally. Leave this blank to keep using it." : "Stored in local publishing settings and never returned to the interface."}><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={pub.api_key_set ? "Saved key · enter a new key to replace" : "Paste Zernio API key"} /></Field>
          <div className="form-actions"><Button kind="primary" onClick={() => void saveSettings()} disabled={!!busy}><Check size={15} />Save connection</Button><Button onClick={() => void loadAccounts()} disabled={!!busy || (!pub.api_key_set && !apiKey.trim())}><RefreshCw size={15} />Load accounts</Button></div>
          <div className="account-list"><div className="account-list-heading"><strong>Connected accounts</strong><span>{count(workspace.accounts.length)} found</span></div>
            {workspace.accounts.length ? workspace.accounts.map((account) => <label className="account-row" key={account.id}>
              <input type="checkbox" checked={accountsByPlatform[account.platform] === account.id} onChange={() => toggleAccount(account)} />
              <span className={"account-platform account-" + account.platform}>{account.platform.slice(0, 1).toUpperCase()}</span>
              <span className="account-details"><strong>{account.name || account.platform}</strong><small>{account.username ? "@" + account.username : account.platform}</small></span>
              <span className="account-selection">{accountsByPlatform[account.platform] === account.id ? "Selected" : "Select"}</span>
            </label>) : <div className="inline-empty">Load connected accounts after saving your API key.</div>}
          </div>
          {workspace.accounts.length ? <Button onClick={() => void saveSettings()} disabled={!!busy}><Check size={15} />Save selected accounts</Button> : null}
        </Panel>
        <Panel title="Publishing defaults" description="These options apply to Zernio jobs.">
          <div className="settings-grid"><Field label="YouTube visibility"><select value={visibility} onChange={(event) => setVisibility(event.target.value)}><option value="public">Public</option><option value="unlisted">Unlisted</option><option value="private">Private</option></select></Field><Field label="Schedule interval (minutes)"><input type="number" min="0" max="1440" value={schedule} onChange={(event) => setSchedule(Number(event.target.value))} /></Field></div>
          <Toggle checked={autoPost} onChange={setAutoPost} label="Automatically submit finished clips" description="When enabled and configured, the local publisher submits completed clips to selected accounts." />
          <div className="form-actions"><Button kind="primary" onClick={() => void saveSettings()} disabled={!!busy}><Check size={15} />Save publishing defaults</Button></div>
        </Panel>
      </div>
      <aside className="publishing-aside">
        <Panel title="Selected clip" description={bulkNames.length ? count(bulkNames.length) + " clips selected for publishing." : "Choose a clip from the library to prepare a post."}>
          {clip ? <div className="publish-clip-card"><video src={clipUrl(clip.name)} muted playsInline preload="metadata" /><strong>{clip.title || clip.name}</strong><small>{clip.creator_name || clip.source || "Generated clip"} · {sizeLabel(clip.size_mb)}</small></div> : bulkNames.length ? <div className="bulk-selected"><Clapperboard size={20} /><strong>{count(bulkNames.length)} clips</strong><small>Publishing uses the saved caption metadata for each clip.</small></div> : <EmptyState icon={Video} title="No clip selected" description="Select one or more clips in the library to prepare a publishing job." action={<Button onClick={openLibrary}>Open clip library</Button>} />}
          {clip || bulkNames.length ? <div className="publishing-job-actions">
            {clip ? <><Field label="Post title"><input maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} /></Field><Field label="Post description"><textarea rows={5} maxLength={2200} value={description} onChange={(event) => setDescription(event.target.value)} /></Field></> : null}
            <Button kind="primary" onClick={() => void publish()} disabled={!selectedCount || !!busy}><Send size={15} />Queue with Zernio</Button>
            <div className="manual-upload-box"><strong>Manual upload</strong><small>Opens the platform in your default browser. You select the video and complete publishing there.</small>
              <Field label="Platform"><select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="youtube">YouTube</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="tiktok">TikTok</option></select></Field>
              <Button onClick={() => void manualUpload()} disabled={!clip || !!busy}><ExternalLink size={14} />Open upload page</Button>
              {manualMessage ? <div className="inline-success"><CheckCircle2 size={15} />{manualMessage}</div> : null}
            </div>
          </div> : null}
        </Panel>
        <Panel title="Browser handoff" description="Manual upload uses your normal browser session.">
          <div className="browser-status-row"><span>Default browser</span><strong>{browserStatus.browser || "System default"}</strong></div>
          <div className="browser-status-row"><span>File selection</span><strong>Manual</strong></div>
          <div className="browser-status-row"><span>Final publish</span><strong>Manual confirmation</strong></div>
          <small className="field-hint">StreamSnip AI does not reuse a private browser profile or click Publish for you.</small>
        </Panel>
      </aside>
    </div>
  </div>;
}

function PostYourClipsPage({ workspace, busy, post }: {
  workspace: Workspace; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>;
}) {
  const platforms = [
    { id: "youtube", label: "YouTube" },
    { id: "facebook", label: "Facebook" },
    { id: "instagram", label: "Instagram" },
    { id: "tiktok", label: "TikTok" },
  ];
  const clips = workspace.state.clips.filter((item) => !item.posted);
  const [destinations, setDestinations] = useState<Record<string, string[]>>({});
  const [activeClip, setActiveClip] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, string>>({});
  const toggle = (name: string, platform: string) => setDestinations((current) => {
    const selected = current[name] || [];
    return { ...current, [name]: selected.includes(platform) ? selected.filter((value) => value !== platform) : [...selected, platform] };
  });
  const selectedTotal = Object.values(destinations).reduce((sum, values) => sum + values.length, 0);
  const prepare = async (clip: Clip) => {
    const selected = destinations[clip.name] || [];
    if (!selected.length) return;
    setActiveClip(clip.name);
    for (const platform of selected) {
      const key = clip.name + "::" + platform;
      setResults((current) => ({ ...current, [key]: "Opening upload and attaching clip…" }));
      const result = await post<RecordLike>("post-clip-" + platform, "/api/browser/prepare", {
        name: clip.name, platform, title: clip.title || clip.name, description: clip.description || "",
      });
      setResults((current) => ({ ...current, [key]: result?.ready_for_review && result?.file_selected && result?.title_filled && result?.description_filled ? "Video attached and metadata verified — review, then Publish" : result?.error || "Automation could not confirm the upload" }));
    }
    setActiveClip(null);
  };
  return <div className="page-stack">
    <PageHeading title="Post Your Clips" description="Every finished clip appears here. Choose one or more destinations, then prepare its upload." actions={<Button onClick={() => void workspace.refresh()}><RefreshCw size={15} />Refresh clips</Button>} />
    <div className="storage-note"><ShieldCheck size={17} /><span><strong>Your final say stays yours</strong><small>A dedicated browser profile keeps your platform sign-in. StreamSnip attaches the clip and verifies the title/caption before showing Ready. You click Publish yourself.</small></span></div>
    <Panel title="Ready to post" description={count(clips.length) + " clips available · " + count(selectedTotal) + " destinations selected"}>
      {clips.length ? <div className="post-clip-list">{clips.map((clip) => <article className="post-clip-card" key={clip.name}>
        <video className="post-clip-preview" src={clipUrl(clip.name)} muted playsInline preload="metadata" />
        <div className="post-clip-details"><strong>{clip.title || clip.name}</strong><small>{clip.name} · {sizeLabel(clip.size_mb)}</small>
          <div className="post-platforms">{platforms.map((platform) => <label key={platform.id} className="post-platform-option"><input type="checkbox" checked={(destinations[clip.name] || []).includes(platform.id)} onChange={() => toggle(clip.name, platform.id)} /><span>{platform.label}</span></label>)}</div>
          <small className="post-metadata-preview">Title: {clip.title || "No generated title yet"}<br />Description: {clip.description || "No generated description yet"}</small>
          <Button kind="primary" onClick={() => void prepare(clip)} disabled={!!busy || activeClip !== null || !(destinations[clip.name] || []).length}><ExternalLink size={14} />{activeClip === clip.name ? "Preparing…" : "Attach video + fill details"}</Button>
          {(destinations[clip.name] || []).map((platform) => results[clip.name + "::" + platform] ? <div className="post-result" key={platform}><span>{platforms.find((item) => item.id === platform)?.label}</span><small>{results[clip.name + "::" + platform]}</small></div> : null)}
        </div>
      </article>)}</div> : <EmptyState icon={Clapperboard} title="No clips ready to post" description="Newly rendered clips will appear here automatically." />}
    </Panel>
  </div>;
}

function HypeWordsPage({ workspace }: { workspace: Workspace }) {
  const [text, setText] = useState(workspace.words.text);
  const [saving, setSaving] = useState(false);
  const lines = text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#"));
  const save = async () => { setSaving(true); try { await workspace.saveWords(text); } catch { /* API layer reports errors. */ } finally { setSaving(false); } };
  return <div className="page-stack">
    <PageHeading title="Hype words" description="Custom phrases can help the highlight scorer notice creator-specific reactions." actions={<Button kind="primary" onClick={() => void save()} disabled={saving}><Check size={15} />Save phrase list</Button>} />
    <div className="settings-layout">
      <div className="settings-main-column"><Panel title="Custom words and phrases" description="One phrase per line. Add an optional score after a vertical bar, for example: no way bro | 3">
        <Field label="Custom phrase list"><textarea className="words-editor" rows={18} value={text} onChange={(event) => setText(event.target.value)} /></Field>
        <div className="save-status"><span>{count(lines.length)} custom entries</span><span>{saving ? "Saving…" : "Save changes when ready."}</span></div>
        <Button kind="primary" onClick={() => void save()} disabled={saving}><Check size={15} />Save phrase list</Button>
      </Panel></div>
      <aside className="settings-side-column"><Panel title="Built-in vocabulary" description="The engine includes streamer reactions and phrases.">
        <div className="vocabulary-counts"><div><strong>{count(workspace.words.words.length)}</strong><span>Words</span></div><div><strong>{count(workspace.words.phrases.length)}</strong><span>Phrases</span></div></div>
        <div className="chip-cloud">{workspace.words.words.slice(0, 24).map((word) => <span key={word}>{word}</span>)}</div>
      </Panel><div className="storage-note"><Info size={16} /><span><strong>How scoring works</strong><small>Transcript phrases contribute to moment detection. AI providers can also evaluate wider context when configured.</small></span></div></aside>
    </div>
  </div>;
}

function ActivityPage({ workspace, busy, post }: { workspace: Workspace; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null> }) {
  const [filter, setFilter] = useState("");
  const filtered = workspace.logs.filter((log) => (log.m + " " + log.t).toLowerCase().includes(filter.toLowerCase()));
  return <div className="page-stack">
    <PageHeading title="Activity" description="Messages from capture, transcription, rendering, creator monitors, and publishing." actions={<a className="button button-secondary" href="/api/log/download"><Download size={15} />Download log</a>} />
    <Panel title="Engine events" description={count(filtered.length) + " messages shown."} action={<label className="library-search"><Search size={15} /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter events" /></label>}>
      {filtered.length ? <div className="activity-list">{filtered.slice().reverse().map((log) => <ActivityRow key={log.id} log={log} post={post} busy={busy} />)}</div> : <EmptyState icon={Activity} title="No activity found" description="Engine messages appear here when capture, processing, or publishing work begins." action={filter ? <Button onClick={() => setFilter("")}>Clear filter</Button> : undefined} />}
    </Panel>
  </div>;
}
function ActivityRow({ log, post, busy }: { log: LogEntry; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>; busy: string }) {
  const lock = log.file_lock as RecordLike | undefined;
  return <div className="activity-row"><time>{log.t}</time><i /><div><p>{log.m}</p>{lock ? <div className="file-lock-warning"><AlertCircle size={14} /><span>{lock.message || "A process is holding this file open."}</span><Button size="small" onClick={() => void post("stop-file-holder", "/api/stop_file_holder", { name: lock.file, pid: lock.pid })} disabled={!!busy}>Close locking app</Button></div> : null}</div></div>;
}

function SettingsPage({ workspace, theme, setTheme, busy, post, navigate }: { workspace: Workspace; theme: ThemeId; setTheme: (theme: ThemeId) => void; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null>; navigate: (page: PageId) => void }) {
  const [section, setSection] = useState("general");
  const sections: Array<[string, string, LucideIcon]> = [
    ["general", "General", Settings], ["appearance", "Appearance", Palette],
  ];
  return <div className="page-stack"><PageHeading title="Settings" description="Manage application storage and workspace appearance. Prepare each capture session in Live Studio." />
    <div className="settings-layout"><nav className="settings-subnav" aria-label="Application settings">{sections.map(([id, label, Icon]) => <button key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)}><Icon size={16} />{label}</button>)}</nav>
      <div className="settings-main-column">
        {section === "general" ? <><GeneralSettings workspace={workspace} busy={busy} post={post} /><Panel title="Session setup lives in Studio" description="Capture behavior, AI provider, transcription, and caption design sit beside the source controls so they can be checked before a session starts."><Button kind="primary" onClick={() => navigate("live")}><Radio size={15} />Open Live Studio setup</Button></Panel></> : null}
        {section === "appearance" ? <AppearanceSettings theme={theme} setTheme={setTheme} /> : null}
      </div>
    </div>
  </div>;
}
function GeneralSettings({ workspace, busy, post }: { workspace: Workspace; busy: string; post: <T,>(key: string, path: string, body?: RecordLike) => Promise<T | null> }) {
  const settings = workspace.settings || {};
  const [componentCheck, setComponentCheck] = useState<RecordLike | null>(null);
  const [componentCheckBusy, setComponentCheckBusy] = useState(false);
  const [componentCheckError, setComponentCheckError] = useState("");
  const checkComponents = async () => {
    setComponentCheckBusy(true);
    setComponentCheckError("");
    try { setComponentCheck(await apiPost<RecordLike>("/api/check_updates", {})); }
    catch (error) { setComponentCheckError(error instanceof Error ? error.message : "Component check failed."); }
    finally { setComponentCheckBusy(false); }
  };
  const update = (key: string, value: string | number | boolean) => workspace.updateSettings({ [key]: value });
  const browse = async (key: "out_dir" | "rec_dir") => {
    const result = await post<{ path: string }>("browse-" + key, "/api/browse_folder", {});
    if (result?.path) update(key, result.path);
  };
  return <>
    <Panel title="Storage folders" description="Choose where generated clips and temporary recordings are stored.">
      <div className="path-field"><Field label="Clip output folder"><input value={String(settings.out_dir || "")} placeholder="Default application output folder" onChange={(event) => update("out_dir", event.target.value)} /></Field><Button onClick={() => void browse("out_dir")} disabled={!!busy}><FolderOpen size={14} />Browse</Button></div>
      <div className="path-field"><Field label="Recording folder"><input value={String(settings.rec_dir || "")} placeholder="Default application recording folder" onChange={(event) => update("rec_dir", event.target.value)} /></Field><Button onClick={() => void browse("rec_dir")} disabled={!!busy}><FolderOpen size={14} />Browse</Button></div>
      <Toggle checked={Boolean(settings.delete_rec)} onChange={(value) => update("delete_rec", value)} label="Delete temporary live recordings after processing" description="Completed live recording chunks may be removed after their clips have rendered." />
      <div className="form-actions"><Button onClick={() => void post("open-output-folder", "/api/open_folder", {})}><FolderOpen size={15} />Open clip folder</Button></div>
    </Panel>
    <Panel title="Application updates" description="Check the repository and local components for available updates.">
      <div className="update-actions"><Button onClick={async () => { const result = await post<RecordLike>("check-app-updates", "/api/check_app_update", {}); if (!result) return; if (!result.update) { window.alert("StreamSnip AI is up to date (v" + String(result.current) + ")."); return; } const release = String(result.url || "https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"); const installer = String(result.installer_url || ""); const prompt = "StreamSnip AI v" + String(result.latest) + " is available (you have v" + String(result.current) + ").\\n\\n" + (installer ? "Download the installer and run it to update the existing installation. It uses the same Windows installer identity and install folder, so it upgrades over the current app." : "No Windows setup installer was attached to this release yet. Open the release page to download it when available.") + "\\n\\nOpen the download now?"; if (window.confirm(prompt)) window.open(installer || release, "_blank", "noopener,noreferrer"); }} disabled={!!busy}><RefreshCw size={15} />Check app update</Button><Button onClick={() => void checkComponents()} disabled={componentCheckBusy || !!busy}><RefreshCw size={15} />{componentCheckBusy ? "Checking components…" : "Check components"}</Button><Button onClick={() => void post("update-components", "/api/update_components", {})} disabled={!!busy}><Download size={15} />Update components</Button></div>{componentCheckError ? <div className="inline-error" role="alert">{componentCheckError}</div> : null}{componentCheck ? <div className="component-check-results" role="status"><div className="component-check-heading"><strong>Component check complete</strong><small>{String(componentCheck.checked_at || "")}</small></div>{Array.isArray(componentCheck.items) ? componentCheck.items.map((item: RecordLike) => <div className="component-check-row" key={String(item.name)}><span><strong>{String(item.name)}</strong><small>{String(item.current || "Unknown")} {item.latest && item.latest !== "Unknown" ? "→ " + String(item.latest) : ""}{item.note ? " · " + String(item.note) : ""}</small></span><StatusPill tone={item.update ? "warning" : item.current === "Not installed" || item.current === "Not available" ? "danger" : "success"}>{item.update ? "Update available" : item.current === "Not installed" || item.current === "Not available" ? "Missing" : "Checked"}</StatusPill></div>) : <small>No component details returned.</small>}</div> : null}
    </Panel>
    <div className="save-status">{workspace.saving ? "Saving…" : workspace.savedAt ? "Saved " + dateLabel(workspace.savedAt / 1000) : "Settings save automatically."}{workspace.saveError ? <span className="danger-text">{workspace.saveError}</span> : null}</div>
  </>;
}
function CaptureSettings({ workspace }: { workspace: Workspace }) {
  const settings = workspace.settings || {};
  const update = (patch: Partial<AppSettings>) => workspace.updateSettings(patch);
  return <Panel title="Capture defaults" description="Used when you start a new live or VOD session.">
    <div className="settings-grid">
      <Field label="Clips per batch"><input type="number" min="0" max="10" value={num(settings.clips_per_chunk, 2)} onChange={(event) => update({ clips_per_chunk: Number(event.target.value) })} /></Field>
      <Field label="Batch length (minutes)"><input type="number" min="3" max="15" value={num(settings.chunk_min, 3)} onChange={(event) => update({ chunk_min: Number(event.target.value) })} /></Field>
      <Field label="Seconds before highlight"><input type="number" min="3" max="90" value={num(settings.pre, 20)} onChange={(event) => update({ pre: Number(event.target.value) })} /></Field>
      <Field label="Seconds after highlight"><input type="number" min="3" max="90" value={num(settings.post, 15)} onChange={(event) => update({ post: Number(event.target.value) })} /></Field>
      <Field label="Minimum highlight score"><input type="number" min="0" max="100" step="0.5" value={num(settings.min_score, 70)} onChange={(event) => update({ min_score: Number(event.target.value) })} /></Field>
      <Field label="Capture bitrate (Kbps)"><input type="number" min="8000" max="50000" step="500" value={num(settings.capture_bitrate_kbps, 8000)} onChange={(event) => update({ capture_bitrate_kbps: Number(event.target.value) })} /></Field>
    </div>
    <div className="save-status">{workspace.saving ? "Saving changes…" : "Capture defaults save automatically."}</div>
  </Panel>;
}
function AISettings({ workspace }: { workspace: Workspace }) {
  const ai = workspace.ai;
  const [secrets, setSecrets] = useState({ gemini_api_key: "", huggingface_token: "", custom_api_key: "" });
  const [models, setModels] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (key: keyof typeof ai, value: string | boolean) => workspace.updateAI({ [key]: value });
  const setSecret = (key: keyof typeof secrets, value: string) => setSecrets((current) => ({ ...current, [key]: value }));
  const test = async () => {
    setTesting(true);
    setTestResult({ ok: true, message: "Testing provider connection…" });
    try {
      const result = await workspace.testAI(secrets);
      const next = { ok: result.ok !== false, message: result.message || "Provider test completed." };
      setTestResult(next);
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: { tone: next.ok ? "success" : "error", title: next.message } }));
    } catch (reason) {
      const next = { ok: false, message: reason instanceof Error ? reason.message : "Provider test failed. Check the model, API key, and network." };
      setTestResult(next);
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: { tone: "error", title: next.message } }));
    } finally { setTesting(false); }
  };
  const save = async () => {
    setSaving(true);
    try { await workspace.saveAI(secrets); setSecrets({ gemini_api_key: "", huggingface_token: "", custom_api_key: "" }); }
    catch { /* API layer reports errors. */ } finally { setSaving(false); }
  };
  const detect = async () => {
    try {
      const result = await workspace.detectOllama();
      setModels(result.models || []);
      if (!ai.ollama_model && result.models.length) set("ollama_model", result.models[0]);
      window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: { tone: "success", title: result.models.length + " Ollama model(s) found." } }));
    } catch { /* API layer reports errors. */ }
  };
  return <div className="page-stack compact-stack">
    <Panel title="Highlight analysis provider" description="Gemini is the first-run default. Choose a local or hosted provider for highlight evaluation.">
      <Field label="Provider"><select value={ai.provider} onChange={(event) => set("provider", event.target.value)}><option value="gemini">Google Gemini · recommended default</option><option value="ollama">Ollama · local</option><option value="hooks">Built-in hook words · offline</option><option value="huggingface">Hugging Face</option><option value="custom">Custom OpenAI-compatible API</option></select></Field>
      {ai.provider === "gemini" ? <div className="provider-info"><StatusPill tone={ai.gemini_key_set ? "success" : "warning"}>{ai.gemini_key_set ? "Gemini key saved" : "Gemini API key required"}</StatusPill><small>Transcript text is sent to Google Gemini for highlight analysis. API usage counts against your Google AI quota.</small></div> : null}
      {ai.provider === "ollama" ? <><div className="settings-grid"><Field label="Ollama URL"><input value={ai.ollama_url} onChange={(event) => set("ollama_url", event.target.value)} /></Field><Field label="Model name"><input value={ai.ollama_model} onChange={(event) => set("ollama_model", event.target.value)} /></Field></div><Button onClick={() => void detect()}><RefreshCw size={14} />Detect installed models</Button>{models.length ? <div className="chip-cloud">{models.map((model) => <button key={model} onClick={() => set("ollama_model", model)}>{model}</button>)}</div> : null}</> : null}
      {ai.provider === "gemini" ? <><Field label="Gemini model" hint="Choose a model ID or select Custom to enter another model supported by your API key."><select value={["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-2.5-flash"].includes(ai.gemini_model) ? ai.gemini_model : "custom"} onChange={(event) => set("gemini_model", event.target.value === "custom" ? "" : event.target.value)}><option value="gemini-3.8-flash">Gemini 3.8 Flash · recommended</option><option value="gemini-3.6-flash">Gemini 3.6 Flash</option><option value="gemini-3.5-flash-lite">Gemini 3.5 Flash-Lite · economical</option><option value="gemini-3.1-flash-lite">Gemini 3.1 Flash-Lite · low cost</option><option value="gemini-3.1-pro-preview">Gemini 3.1 Pro Preview · advanced reasoning</option><option value="gemini-2.5-flash">Gemini 2.5 Flash · legacy / access restricted</option><option value="custom">Custom model ID…</option></select></Field>{!["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-2.5-flash"].includes(ai.gemini_model) ? <Field label="Custom Gemini model ID"><input value={ai.gemini_model} onChange={(event) => set("gemini_model", event.target.value)} placeholder="e.g. model ID from Google AI Studio" /></Field> : null}<Field label="Gemini API key" hint={ai.gemini_key_set ? "A key is already saved. Leave blank to keep it." : "Stored locally and never returned to the interface."}><input type="password" autoComplete="new-password" value={secrets.gemini_api_key} onChange={(event) => setSecret("gemini_api_key", event.target.value)} placeholder={ai.gemini_key_set ? "Saved key" : "Enter API key"} /></Field></> : null}
      {ai.provider === "huggingface" ? <><Field label="Hugging Face model"><input value={ai.huggingface_model} onChange={(event) => set("huggingface_model", event.target.value)} /></Field><Field label="Hugging Face token" hint={ai.huggingface_token_set ? "A token is already saved. Leave blank to keep it." : "Stored locally and never returned to the interface."}><input type="password" autoComplete="new-password" value={secrets.huggingface_token} onChange={(event) => setSecret("huggingface_token", event.target.value)} placeholder={ai.huggingface_token_set ? "Saved token" : "Enter token"} /></Field></> : null}
      {ai.provider === "custom" ? <><div className="settings-grid"><Field label="API base URL"><input value={ai.custom_api_base} onChange={(event) => set("custom_api_base", event.target.value)} /></Field><Field label="Model"><input value={ai.custom_api_model} onChange={(event) => set("custom_api_model", event.target.value)} /></Field></div><Field label="API key" hint={ai.custom_api_key_set ? "A key is already saved. Leave blank to keep it." : "Optional for local or unauthenticated endpoints."}><input type="password" autoComplete="new-password" value={secrets.custom_api_key} onChange={(event) => setSecret("custom_api_key", event.target.value)} placeholder={ai.custom_api_key_set ? "Saved key" : "Enter API key"} /></Field></> : null}
      <div className="form-actions"><Button kind="primary" onClick={() => void save()} disabled={saving}><Check size={15} />Save AI settings</Button><Button onClick={() => void test()} disabled={testing}><Zap size={15} />{testing ? "Testing…" : "Test provider"}</Button></div>
      {testResult ? <div className="provider-info" role={testResult.ok ? "status" : "alert"}><StatusPill tone={testing ? "warning" : testResult.ok ? "success" : "danger"}>{testing ? "Testing" : testResult.ok ? "Test passed" : "Test failed"}</StatusPill><small>{testResult.message}</small></div> : null}
      <p className="field-hint">Provider secrets are not returned by the public configuration endpoint.</p>
    </Panel>
    <Panel title="Clip metadata" description="AI-generated titles and descriptions are enabled for supported providers."><ToolRow icon={Sparkles} title="AI post copy" detail="Uses transcript text to prepare title and description fields." /><StatusPill tone={workspace.ai.metadata_copy_enabled ? "success" : "neutral"}>{workspace.ai.metadata_copy_enabled ? "Enabled" : "Disabled"}</StatusPill></Panel>
  </div>;
}
function SpeechSettings({ workspace }: { workspace: Workspace }) {
  const settings = workspace.settings || {};
  const update = (patch: Partial<AppSettings>) => workspace.updateSettings(patch);
  return <Panel title="Transcription" description="Faster-Whisper runs locally by default. A custom command can be supplied when needed.">
    <Field label="Transcription provider"><select value={String(settings.transcriber_provider || "faster-whisper")} onChange={(event) => update({ transcriber_provider: event.target.value })}><option value="faster-whisper">Faster-Whisper</option><option value="custom-command">Custom command</option></select></Field>
    <div className="settings-grid"><Field label="Language"><input value={String(settings.transcriber_language || "auto")} onChange={(event) => update({ transcriber_language: event.target.value })} placeholder="auto" /><small className="field-hint">Use a language code, or auto for detection.</small></Field><Field label="Whisper model"><select value={String(settings.model || "distil-large-v3")} onChange={(event) => update({ model: event.target.value })}>{["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"].map((model) => <option key={model}>{model}</option>)}</select></Field></div>
    {settings.transcriber_provider === "custom-command" ? <Field label="Custom transcription command" hint="Executed by the local engine."><textarea rows={4} value={String(settings.transcriber_command || "")} onChange={(event) => update({ transcriber_command: event.target.value })} /></Field> : null}
    <ToolRow icon={Cpu} title="GPU acceleration" detail="CUDA is selected automatically when a compatible NVIDIA GPU is available." />
  </Panel>;
}
function RangeSetting({ label, value, min, max, step = 1, onChange }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (value: number) => void;
}) {
  const display = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return <label className="range-setting"><span><span>{label}</span><strong>{display}%</strong></span><input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function CaptionSettings({ workspace, mode, target }: { workspace: Workspace; mode: string; target: string }) {
  const settings = workspace.settings || {};
  const update = (patch: Partial<AppSettings>) => workspace.updateSettings(patch);
  const layout = String(settings.layout || "Facecam + game (Twitch)");
  const cropX = num(settings.crop_x, 34.2);
  const cropY = num(settings.crop_y, 0);
  const cropW = num(settings.crop_w, 31.6);
  const cropH = num(settings.crop_h, 100);
  const detectedTag = mode === "live" ? inferCreatorTag(target) : "";
  const highlightColors: Record<string, string> = {
    Yellow: "#EFFF43", Green: "#7CFF5B", Cyan: "#50E8FF", Orange: "#FF9B42", Pink: "#FF45A8",
  };
  const previewHighlightColor = highlightColors[String(settings.color || "Yellow")] || highlightColors.Yellow;
  const setRange = (key: string, value: number) => update({ [key]: value });
  return <div className="page-stack compact-stack">
    <Panel title="Video layout" description="Set the output aspect ratio and framing preset used when rendering clips.">
      <div className="settings-grid"><Field label="Output format"><select value={String(settings.output_format || "9:16")} onChange={(event) => update({ output_format: event.target.value })}>{["9:16", "16:9", "1:1", "4:5"].map((format) => <option key={format}>{format}</option>)}</select></Field><Field label="Layout preset"><select value={String(settings.layout || "Facecam + game (Twitch)")} onChange={(event) => update({ layout: event.target.value })}>{["Facecam + game (Twitch)", "Blur background", "Fill (crop center)", "Selected crop"].map((layout) => <option key={layout}>{layout}</option>)}</select></Field></div>
    </Panel>
    {layout === "Selected crop" ? <Panel title="Selected crop area" description="Set the crop rectangle as percentages of the source frame.">
      <div className="framing-range-grid">
        <RangeSetting label="Left" value={cropX} min={0} max={90} step={0.5} onChange={(value) => setRange("crop_x", value)} />
        <RangeSetting label="Top" value={cropY} min={0} max={90} step={0.5} onChange={(value) => setRange("crop_y", value)} />
        <RangeSetting label="Width" value={cropW} min={10} max={Math.max(10, 100 - cropX)} step={0.5} onChange={(value) => setRange("crop_w", value)} />
        <RangeSetting label="Height" value={cropH} min={10} max={Math.max(10, 100 - cropY)} step={0.5} onChange={(value) => setRange("crop_h", value)} />
      </div>
      <div className="form-actions"><Button onClick={() => update({ crop_x: 34.2, crop_y: 0, crop_w: 31.6, crop_h: 100 })}>Reset crop area</Button></div>
    </Panel> : null}
    <Panel title="Caption style" description="Preset captions are the default. Switch to Custom caption only when you want to override the standard styling and placement.">
      <div className="caption-mode-switch" role="group" aria-label="Caption editing mode">
        <button type="button" className={!settings.subtitle_custom ? "selected" : ""} onClick={() => update({ subtitle_custom: false })}><Check size={14}/>Preset captions <small>Default</small></button>
        <button type="button" className={settings.subtitle_custom ? "selected" : ""} onClick={() => update({ subtitle_custom: true })}><SlidersHorizontal size={14}/>Custom caption</button>
      </div>
      <div className="settings-grid">
        <Field label="Subtitle mode"><select value={String(settings.subtitle_mode || "Karaoke")} onChange={(event) => update({ subtitle_mode: event.target.value })}><option>Karaoke</option><option>Classic</option></select></Field>
        <Field label="Subtitle style"><select value={String(settings.subtitle_style || "GTA Neon")} onChange={(event) => update({ subtitle_style: event.target.value })}>{["GTA Neon", "Classic", "Hormozi", "Neon", "MrBeast", "Minimal", "Fire"].map((style) => <option key={style}>{style}</option>)}</select></Field>
        <Field label="Caption animation"><select value={String(settings.subtitle_animation || "highlight")} onChange={(event) => update({ subtitle_animation: event.target.value })}><option value="highlight">Highlight — keep phrase visible</option><option value="pop_in">Pop-in — build phrase word by word</option><option value="pop_in_line">Pop-in line — animate the whole phrase</option><option value="one_by_one">One by one — show only the current word</option><option value="build_up">Build up — accumulate words without popping</option><option value="full_line">Full line — show the complete phrase</option></select></Field>
        <Field label="Base font size"><input type="number" min="60" max="150" value={num(settings.caption_size, 82)} onChange={(event) => update({ caption_size: Number(event.target.value) })} /></Field>
        <Field label="Words per line"><input type="number" min="1" max="4" value={num(settings.words_per_line, 3)} onChange={(event) => update({ words_per_line: Number(event.target.value) })} /></Field>
        <Field label="Highlight color"><select value={String(settings.color || "Yellow")} onChange={(event) => update({ color: event.target.value })}>{["Yellow", "Green", "Cyan", "Orange", "Pink"].map((color) => <option key={color}>{color}</option>)}</select></Field>
        {!settings.subtitle_custom ? <Field label="Caption location preset"><select value={String(settings.position || "Lower third")} onChange={(event) => update({ position: event.target.value })}><option>Top</option><option>Upper third</option><option>Middle</option><option>Lower third</option><option>Bottom</option></select></Field> : null}
      </div>
      {settings.subtitle_custom ? <div className="settings-grid custom-caption-controls">
        <Field label="Font family"><input value={String(settings.font || "Impact")} onChange={(event) => update({ font: event.target.value })} /></Field>
        <Field label="Custom font size"><input type="number" min="60" max="180" value={num(settings.subtitle_font_size, 100)} onChange={(event) => update({ subtitle_font_size: Number(event.target.value) })} /></Field>
        <Field label="Vertical nudge"><input type="number" min="-400" max="400" value={num(settings.subtitle_nudge, 0)} onChange={(event) => update({ subtitle_nudge: Number(event.target.value) })} /></Field>
        <Field label="Text color"><input type="color" value={String(settings.subtitle_text_color || "#FFFFFF")} onChange={(event) => update({ subtitle_text_color: event.target.value })} /></Field>
        <Field label="Stroke color"><input type="color" value={String(settings.subtitle_stroke_color || "#000000")} onChange={(event) => update({ subtitle_stroke_color: event.target.value })} /></Field>
        <Field label="Position"><select value={String(settings.subtitle_position || "Bottom")} onChange={(event) => update({ subtitle_position: event.target.value })}><option>Top</option><option>Center</option><option>Bottom</option></select></Field>
        <Field label="Alignment"><select value={String(settings.subtitle_alignment || "Center")} onChange={(event) => update({ subtitle_alignment: event.target.value })}><option>Left</option><option>Center</option></select></Field>
      </div> : null}
      <div className="caption-preview-layout">
        <div className="caption-preview-copy">
          <strong>Caption preview</strong>
          <p>{settings.subtitle_custom ? "Custom position and styling are active." : "This preview follows the selected location preset."} The sample updates as you change settings.</p>
          <span className="caption-preview-meta">{String(settings.subtitle_style || "GTA Neon")} ? {String(settings.position || "Lower third")} ? {String(settings.subtitle_animation || "highlight").replace(/_/g, " ")}</span>
        </div>
        <div className="caption-preview-phone" aria-label="Caption placement preview">
          <div className="caption-preview-top"><span>FACECAM</span></div>
          <div className="caption-preview-game"><span>GAME CAPTURE</span></div>
          <div className={"caption-preview-words style-" + String(settings.subtitle_style || "GTA Neon").toLowerCase().replace(/\s+/g, "-") + " location-" + (settings.subtitle_custom ? String(settings.subtitle_position || "Bottom").toLowerCase() : String(settings.position || "Lower third").toLowerCase().replace(/\s+/g, "-"))}
            style={{ color: settings.subtitle_custom ? String(settings.subtitle_text_color || "#FFFFFF") : "inherit", WebkitTextStroke: settings.subtitle_custom ? "0.5px " + String(settings.subtitle_stroke_color || "#000000") : "0.5px #301045", fontFamily: String(settings.font || "Impact"), fontSize: Math.max(11, num(settings.subtitle_custom ? settings.subtitle_font_size : settings.caption_size, 82) * 0.15) + "px" }}>
            <span>NO WAY</span> <b style={{ color: settings.subtitle_custom ? String(settings.subtitle_text_color || "#FFFFFF") : previewHighlightColor }}>THAT JUST HAPPENED</b>
          </div>
        </div>
      </div>
    </Panel>
    <Panel title="Creator credit and profanity filter" description="Control the credit overlay and how detected profanity is treated.">
      <Field label="Creator credit" hint={settings.streamer_tag ? "Manual creator credit override." : detectedTag ? "Auto-detected as " + detectedTag + ". Edit to set an override; clear the field to return to automatic detection." : "A channel handle is inferred when the source URL exposes one."}><input maxLength={80} value={String(settings.streamer_tag || detectedTag)} onChange={(event) => update({ streamer_tag: event.target.value })} placeholder="Auto-detected from source URL" /></Field>
      <Toggle checked={Boolean(settings.show_tag_video)} onChange={(value) => update({ show_tag_video: value })} label="Show creator tag in the video" />
      <Toggle checked={Boolean(settings.profanity_filter_enabled)} onChange={(value) => update({ profanity_filter_enabled: value })} label="Filter detected profanity" description="Detected words become **** in captions. Only the matching word is replaced in audio; surrounding speech stays unchanged." />
      {settings.profanity_filter_enabled ? <Field label="Audio treatment"><select value={String(settings.profanity_audio_mode || "beep")} onChange={(event) => update({ profanity_audio_mode: event.target.value })}><option value="beep">Beep — replace the word with a tone</option><option value="mute">Mute — silence the word</option></select><small className="field-hint">Applied only to detected word timestamps. Beep is the default.</small></Field> : null}
      <Field label="Additional words and phrases to filter"><textarea rows={5} value={String(settings.profanity_filter_words || "")} onChange={(event) => update({ profanity_filter_words: event.target.value })} placeholder="Add one word or phrase per line" /><small className="field-hint">Built-in profanity coverage is included automatically. Add streamer-specific spellings or phrases here, one per line.</small></Field>
    </Panel>
  </div>;
}
function AppearanceSettings({ theme, setTheme }: { theme: ThemeId; setTheme: (theme: ThemeId) => void }) {
  return <Panel title="Workspace appearance" description="Choose a palette saved on this device. Theme selection does not change capture or publishing behavior.">
    <div className="theme-grid">{themes.map((item) => <button key={item.id} className={"theme-card" + (theme === item.id ? " selected" : "")} onClick={() => setTheme(item.id)}>
      <span className={"theme-preview theme-preview-" + item.id}><i /><i /><i /></span><span className="theme-card-copy"><strong>{item.name}</strong><small>{item.description}</small></span>{theme === item.id ? <CheckCircle2 size={17} /> : null}
    </button>)}</div>
  </Panel>;
}
function HelpPage({ navigate }: { navigate: (page: PageId) => void }) {
  return <div className="page-stack">
    <PageHeading title="Help & how-to" description="Setup walkthroughs, workflow guides, troubleshooting, and what each part of StreamSnip AI does." />
    <Panel title="Quick start: first clip" description="Follow this order the first time you use the app.">
      <ol className="help-steps">
        <li><strong>Connect your source.</strong> Open Live Studio, choose Live stream or Video file, then paste a Twitch/YouTube URL or select a local video.</li>
        <li><strong>Set up AI.</strong> In the AI tab, choose Gemini (recommended API provider), add your Google AI Studio API key, choose a model, and use Test provider. Keep a model that passes; it remains selected for future jobs.</li>
        <li><strong>Choose transcription.</strong> Faster-Whisper runs locally. Select a model and language (Auto detects); the speech model may download the first time.</li>
        <li><strong>Set framing and captions.</strong> Load a still frame in Facecam detection and layout. Drag the pink facecam box and cyan game-capture box independently, then save both regions. In Captions, choose one of four location presets or switch to Custom caption and review the placement preview.</li>
        <li><strong>Start processing.</strong> Confirm the source and settings, then explicitly press Start. Watch progress in Studio and Activity.</li>
        <li><strong>Review and publish.</strong> Open Clip library, edit the TXT-backed title/description, then use Publishing for Zernio or manual browser upload.</li>
      </ol>
      <Button kind="primary" onClick={() => navigate("live")}>Open Live Studio setup <ArrowRight size={14} /></Button>
    </Panel>
    <div className="help-grid">
      <Panel title="Live stream capture" description="Monitor a live Twitch or YouTube stream."><p>Paste the channel or stream URL. The engine records in chunks, transcribes each chunk, scores highlight moments, and renders clips with your caption layout. Stop capture from Live Studio; graceful stop finishes current work where possible.</p><Button onClick={() => navigate("live")}>Live Studio</Button></Panel>
      <Panel title="Recorded video / VOD" description="Process a local video file."><p>Choose the file source, set the desired processing options, and start. The engine transcribes the video, analyzes transcript windows, then renders selected moments. Keep enough disk space for source and output files.</p><Button onClick={() => navigate("live")}>File processing setup</Button></Panel>
      <Panel title="Selected Gemini model & automatic fallback" description="Your selected model is always tried first. Temporary failures are retried, then the engine moves to the next available model."><p>The exact Gemini model selected in AI settings gets up to three attempts first. If it keeps failing, StreamSnip moves to the next available Gemini model and tries that model up to three times. It makes one ordered pass through available Gemini models, then uses configured fallback providers (local Ollama first, followed by configured Hugging Face or custom API). A fallback is announced in Activity and does not overwrite your selection: your chosen Gemini model is tried first again on the next clip/task.</p><p>For the best fallback coverage, install Ollama and download a model, or configure another provider in AI settings.</p></Panel>
      <Panel title="Creators & multi-monitor" description="Save channels and run independent monitor jobs."><p>Add a Twitch or YouTube channel in Creators. Each creator has isolated live/VOD folders and status. Start or stop each monitor individually; stop all before closing the app. Removing a profile does not delete its existing media.</p><Button onClick={() => navigate("creators")}>Manage creators</Button></Panel>
      <Panel title="Transcription & captions" description="Speech recognition and visual subtitle rendering."><p>Faster-Whisper uses your PC and compatible NVIDIA GPU acceleration. Larger models can improve recognition but use more VRAM and time. Facecam (pink) and game capture (cyan) are independent source-frame regions in Live Studio. Caption placement offers Top, Upper third, Lower third, and Bottom presets; Custom caption exposes manual size, color, stroke, alignment, and nudge controls.</p><Button onClick={() => navigate("live")}>Configure framing and captions</Button></Panel>
      <Panel title="Clip library & metadata" description="Find, edit, and organize generated clips."><p>Clips include a video and matching text metadata. Gemini, Ollama, Hugging Face, and compatible custom models generate both title and description from the clip transcript. Built-in Hook words mode uses its strongest matched phrase as the title and a conservative transcript-based description. Search the library, preview, edit title/description, open the containing folder, download, or mark a clip published. Published is a local registry; it does not prove a platform post unless publishing reports success.</p><Button onClick={() => navigate("clips")}>Open clip library</Button></Panel>
      <Panel title="Publishing" description="Automated scheduling or manual upload."><p>Save your Zernio key, load connected accounts, select accounts, and save defaults. Queueing sends a job through Zernio. Manual upload opens the platform in your default browser; select the file and complete the final publish action yourself.</p><Button onClick={() => navigate("publishing")}>Publishing settings</Button></Panel>
      <Panel title="Settings & component checks" description="Storage, app updates, and runtime versions."><p>Settings controls output/recording folders and appearance. Check app update queries the latest GitHub release. Check components reads installed FFmpeg, Python package versions and the selected Whisper model cache; it is read-only and does not install anything. Update components changes packages and may download the speech model—review the confirmation first.</p><Button onClick={() => navigate("settings")}>Open Settings</Button></Panel>
      <Panel title="Troubleshooting" description="Common issues and where to look."><p><strong>Source won’t open:</strong> verify the URL, stream is live/public, and Streamlink/FFmpeg are available. <strong>AI test fails:</strong> check API key, model availability, quota, and network; review Activity. <strong>Clips are missing:</strong> check output folder and Activity errors. <strong>Slow processing:</strong> use a smaller Whisper model, reduce parallel workload, and check GPU/VRAM. <strong>Disk full:</strong> move output/recording folders in Settings.</p><Button onClick={() => navigate("activity")}>Open Activity log</Button></Panel>
    </div>
  </div>;
}
function AboutPage() {
  return <div className="page-stack">
    <PageHeading title="About StreamSnip AI" description="A local-first creator clipping workspace." />
    <Panel title="Application" description="StreamSnip AI connects live monitoring, transcription, AI-assisted highlight detection, video rendering, and publishing handoff.">
      <div className="about-brand"><span className="brand-mark"><Clapperboard size={22} /></span><span><strong>StreamSnip AI</strong><small>Creator Studio · Local workspace</small></span></div>
      <p>The Python engine handles capture and processing on this computer. The interface reads engine state from the local API; provider credentials stay in local configuration.</p>
      <div className="project-links"><a href="https://github.com/sifat-jaman-13/stream-clip-ai" target="_blank" rel="noreferrer"><ExternalLink size={15} />GitHub source</a><a href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest" target="_blank" rel="noreferrer"><ExternalLink size={15} />Latest release</a></div>
    </Panel>
  </div>;
}
