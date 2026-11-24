import {
  Activity, AlertCircle, ArrowRight, BadgeCheck, Bot, Camera,
  Check, CheckCircle2, ChevronDown, CircleHelp, Clapperboard, Clock3, Cpu, Download,
  ExternalLink, FileText, Film, Folder, FolderOpen, Gauge, Home, Info, Layers,
  Loader2, MonitorPlay, MoreHorizontal, Move, Play, Plus, Radio,
  RefreshCw, Save, Search, Settings, ShieldCheck, SlidersHorizontal, Sparkles, Square,
  Palette, Trash2, Upload, Video, X, Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ButtonHTMLAttributes, FormEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  Link, NavLink, Route, Routes, useLocation, useNavigate, useSearchParams,
} from "react-router-dom";
import { apiPost, notifyApp } from "./api";
import { useWorkspace } from "./workspace";
import type { AppSettings, PublishingAccount, Workspace } from "./workspace";
import type { Clip, Creator, LogEntry } from "./types";

const navGroups: { title: string; items: { to: string; label: string; icon: LucideIcon; end?: boolean }[] }[] = [
  {
    title: "WORKSPACE",
    items: [
      { to: "/", label: "Dashboard", icon: Home, end: true },
      { to: "/live", label: "Live Studio", icon: Radio },
      { to: "/layout", label: "Layout Studio", icon: Layers },
    ],
  },
  {
    title: "CONTENT",
    items: [
      { to: "/clips", label: "Clips", icon: Film },
      { to: "/publish", label: "Publish", icon: Upload },
      { to: "/posted", label: "Published", icon: Video },
      { to: "/words", label: "Hype words", icon: Zap },
    ],
  },
  {
    title: "CONFIGURATION",
    items: [
      { to: "/settings/ai", label: "AI providers", icon: Bot },
      { to: "/settings/speech", label: "Transcription", icon: Activity },
      { to: "/settings/captions", label: "Captions", icon: FileText },
      { to: "/settings/publishing", label: "Publishing", icon: Upload },
      { to: "/settings", label: "App settings", icon: Settings, end: true },
    ],
  },
  {
    title: "SUPPORT",
    items: [
      { to: "/activity", label: "Activity", icon: Clock3 },
      { to: "/help", label: "Help centre", icon: CircleHelp },
      { to: "/about", label: "About", icon: Info },
    ],
  },
];

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/live": "Live Studio",
  "/layout": "Layout Studio",
  "/clips": "Clips",
  "/publish": "Publish clips",
  "/posted": "Published",
  "/words": "Hype words",
  "/settings": "App settings",
  "/settings/ai": "AI providers",
  "/settings/speech": "Transcription",
  "/settings/captions": "Caption settings",
  "/settings/publishing": "Publishing",
  "/activity": "Activity",
  "/help": "Help centre",
  "/about": "About StreamSnip AI",
};

type ThemeId =
  | "dark" | "light" | "midnight" | "cyberpunk" | "retrowave" | "forest"
  | "ocean" | "ume" | "terminal" | "organs" | "gpt" | "claude"
  | "cute" | "eclipse" | "porcelain" | "arcade" | "blueprint" | "monolith" | "yoyo";

type ThemePreset = {
  id: ThemeId;
  name: string;
  description: string;
  mode: "light" | "dark";
  swatches: [string, string, string, string, string];
};

const themePresets: ThemePreset[] = [
  { id: "dark", name: "Dark", description: "Charcoal · cyan · coral", mode: "dark", swatches: ["#282c34", "#9cdef2", "#111111", "#355a66", "#e06c75"] },
  { id: "light", name: "Light", description: "Cool grey · slate · berry", mode: "light", swatches: ["#f3f5f7", "#26313a", "#ffffff", "#cbd3da", "#b34d5c"] },
  { id: "midnight", name: "Midnight", description: "Near-black · mist · red", mode: "dark", swatches: ["#0d1117", "#c9d1d9", "#161b22", "#30363d", "#f85149"] },
  { id: "cyberpunk", name: "Cyberpunk", description: "Indigo-black · aqua · magenta", mode: "dark", swatches: ["#10121a", "#9bdde0", "#171a26", "#514b78", "#d45aa8"] },
  { id: "retrowave", name: "Retrowave", description: "Night purple · neon pink", mode: "dark", swatches: ["#1a1a2e", "#e94560", "#16213e", "#533483", "#e94560"] },
  { id: "forest", name: "Forest", description: "Pine · sage · leaf green", mode: "dark", swatches: ["#1b2a1b", "#a8d5a2", "#142414", "#3d6b3d", "#7cb871"] },
  { id: "ocean", name: "Ocean", description: "Deep blue · sky · bright blue", mode: "dark", swatches: ["#0b1a2c", "#64d2ff", "#091422", "#1e5074", "#4facfe"] },
  { id: "ume", name: "Ume", description: "Plum · soft pink · blossom", mode: "dark", swatches: ["#271d2b", "#f1d8e9", "#1d1721", "#66475f", "#d98bb7"] },
  { id: "terminal", name: "Terminal", description: "Black-green · mint · phosphor", mode: "dark", swatches: ["#0b1110", "#b8e6c1", "#080d0c", "#28553a", "#6bd38b"] },
  { id: "organs", name: "Organs", description: "Near-black · parchment · crimson", mode: "dark", swatches: ["#0a0406", "#efe1c8", "#15080a", "#3a1519", "#c83240"] },
  { id: "gpt", name: "GPT", description: "Neutral charcoal · soft grey", mode: "dark", swatches: ["#212121", "#ececec", "#171717", "#424242", "#949494"] },
  { id: "claude", name: "Claude", description: "Warm umber · ivory · terracotta", mode: "dark", swatches: ["#1f1e1b", "#f5f1e8", "#2b2926", "#514b43", "#d97757"] },
  { id: "cute", name: "Cute", description: "Blush · berry · rose", mode: "light", swatches: ["#fff4f7", "#63394d", "#fffafd", "#edc7d5", "#d65f88"] },
  { id: "eclipse", name: "Eclipse", description: "Graphite · warm white · teal", mode: "dark", swatches: ["#17191c", "#e8e4dc", "#0f1113", "#3c4248", "#46c2b3"] },
  { id: "porcelain", name: "Porcelain", description: "Mist · slate · blue", mode: "light", swatches: ["#edf0f2", "#252a30", "#ffffff", "#c7cdd2", "#3478c9"] },
  { id: "arcade", name: "Arcade", description: "Ink · arcade yellow · hot pink", mode: "dark", swatches: ["#15131d", "#f4e85c", "#0b1720", "#305f68", "#ff4f91"] },
  { id: "blueprint", name: "Blueprint", description: "Navy · ice · signal gold", mode: "dark", swatches: ["#10263b", "#e8f1f5", "#091a29", "#48758d", "#e6b84a"] },
  { id: "monolith", name: "Monolith", description: "Concrete · chalk · acid green", mode: "dark", swatches: ["#202020", "#d8d8d2", "#121212", "#50504b", "#b6e05c"] },
  { id: "yoyo", name: "Yoyo", description: "Smoky violet · sage · copper", mode: "dark", swatches: ["#211f23", "#dfdbd7", "#141415", "#3e5146", "#e09d6c"] },
];

function getInitialTheme(): ThemeId {
  try {
    const saved = localStorage.getItem("streamsnip.theme");
    if (themePresets.some((theme) => theme.id === saved)) return saved as ThemeId;
    if (saved === "studio" || saved === "light" || !saved) return "light";
    if (saved === "graphite") return "dark";
    return "dark";
  } catch {
    return "light";
  }
}

const asString = (value: unknown, fallback = "") => value === undefined || value === null ? fallback : String(value);
const asNumber = (value: unknown, fallback: number) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const asBool = (value: unknown) => value === true || value === "true" || value === 1;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const manualPostingTargets = [
  { id: "youtube", name: "YouTube", url: "https://www.youtube.com/upload" },
  { id: "facebook", name: "Facebook", url: "https://www.facebook.com/reels/create/" },
  { id: "instagram", name: "Instagram", url: "https://www.instagram.com/create/select/" },
  { id: "tiktok", name: "TikTok", url: "https://www.tiktok.com/upload" },
];

function formatDate(value: number | string | null | undefined) {
  if (!value) return "N/A";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

function formatDuration(totalSeconds: number) {
  const safe = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  return hours
    ? hours + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0")
    : minutes + ":" + String(seconds).padStart(2, "0");
}

function PageHeading({
  title, description, action,
}: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="page-heading">
      <div className="page-heading-copy">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="page-heading-action">{action}</div> : null}
    </div>
  );
}

function Button({
  children, variant = "secondary", className = "", ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "quiet" }) {
  return <button className={"button button-" + variant + " " + className} {...props}>{children}</button>;
}

function ThemeOptions({
  value, onChange, compact = false,
}: { value: ThemeId; onChange: (value: ThemeId) => void; compact?: boolean }) {
  return (
    <div className={"theme-options " + (compact ? "compact" : "grid")}>
      {themePresets.map((theme) => (
        <button
          type="button"
          key={theme.id}
          className={"theme-option " + (value === theme.id ? "selected" : "")}
          onClick={() => onChange(theme.id)}
          aria-pressed={value === theme.id}
        >
          <span className="theme-option-swatches" aria-hidden="true">
            {theme.swatches.map((swatch, index) => <i key={index} style={{ backgroundColor: swatch }} />)}
          </span>
          <span className="theme-option-copy">
            <strong>{theme.name}</strong>
            <small>{theme.description}</small>
          </span>
          {value === theme.id ? <CheckCircle2 size={17} className="theme-option-check" /> : null}
        </button>
      ))}
    </div>
  );
}

function StatusPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "good" | "warning" | "bad" | "neutral" }) {
  return <span className={"status-pill " + tone}><i />{children}</span>;
}

function MetricCard({
  icon: Icon, label, value, note, tone,
}: { icon: LucideIcon; label: string; value: string | number; note: string; tone: string }) {
  return (
    <article className="metric-card">
      <div className={"metric-icon " + tone}><Icon size={18} /></div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{typeof value === "number" ? value.toLocaleString() : value}</strong>
        <small>{note}</small>
      </div>
    </article>
  );
}

export default function App() {
  const workspace = useWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  const [globalSearch, setGlobalSearch] = useState("");
  const [quitting, setQuitting] = useState(false);
  const [quitError, setQuitError] = useState("");
  const [themeId, setThemeId] = useState<ThemeId>(getInitialTheme);
  const [themePickerOpen, setThemePickerOpen] = useState(false);
  const selectedTheme = themePresets.find((theme) => theme.id === themeId) || themePresets[0];
  const activeTitle = pageTitles[location.pathname] || "Workspace";

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = selectedTheme.mode;
    root.dataset.palette = selectedTheme.id;
    try { localStorage.setItem("streamsnip.theme", selectedTheme.id); }
    catch { /* Theme remains active for this session if storage is unavailable. */ }
  }, [selectedTheme]);

  const searchSubmit = (event: FormEvent) => {
    event.preventDefault();
    navigate("/clips?search=" + encodeURIComponent(globalSearch.trim()));
  };

  const quitApp = async () => {
    if (!window.confirm("Quit StreamSnip AI? This stops the main capture and all creator monitors, then closes the local server.")) return;
    setQuitting(true);
    setQuitError("");
    try {
      await apiPost("/api/quit", {});
    } catch (reason) {
      setQuitting(false);
      setQuitError(reason instanceof Error ? reason.message : "The app could not be shut down.");
    }
  };

  return (
    <div className="studio-shell">
      <aside className="studio-sidebar">
        <Link to="/" className="studio-brand">
          <span className="studio-brand-mark"><Clapperboard size={21} /></span>
          <span className="studio-brand-text"><strong>StreamSnip <em>AI</em></strong><small>CREATOR STUDIO</small></span>
        </Link>

        <div className="sidebar-workspace">
          <span className="workspace-avatar">S</span>
          <span><strong>Local workspace</strong><small>Personal instance</small></span>
          <ChevronDown size={15} />
        </div>

        <nav className="studio-nav" aria-label="Main navigation">
          {navGroups.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-group-title">{group.title}</div>
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) => "nav-item " + (isActive ? "active" : "")}
                >
                  <Icon size={18} strokeWidth={1.9} />
                  <span>{label}</span>
                  {to === "/clips" && workspace.state.clip_total > 0 ? <small>{workspace.state.clip_total}</small> : null}
                  {to === "/posted" && workspace.state.posted_total > 0 ? <small>{workspace.state.posted_total}</small> : null}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="engine-status-card">
            <div className="engine-status-heading">
              <span className={"engine-dot " + (workspace.connected ? "online" : "offline")} />
              <strong>Processing engine</strong>
              <span>{workspace.connected ? "Online" : "Offline"}</span>
            </div>
            <p>{workspace.connected ? "The local engine is responding." : "Waiting for the local Python engine."}</p>
            <button onClick={() => void workspace.refresh()}><RefreshCw size={13} /> Refresh connection</button>
          </div>
          <div className="sidebar-user">
            <span className="user-avatar">SJ</span>
            <span><strong>Local user</strong><small>On this device only</small></span>
            <MoreHorizontal size={17} />
          </div>
        </div>
      </aside>

      <main className="studio-main">
        <header className="studio-topbar">
          <div className="topbar-breadcrumb"><span>Studio</span><span>/</span><strong>{activeTitle}</strong></div>
          <div className="topbar-right">
            <form className="global-search" onSubmit={searchSubmit}>
              <Search size={16} />
              <input value={globalSearch} onChange={(event) => setGlobalSearch(event.target.value)} placeholder="Search your clips" aria-label="Search clips" />
              <kbd>↵</kbd>
            </form>
            <StatusPill tone={workspace.connected ? "good" : "warning"}>{workspace.connected ? "Engine online" : "Engine offline"}</StatusPill>
            <div className="theme-control">
              <button
                type="button"
                className="theme-toggle"
                onClick={() => setThemePickerOpen((open) => !open)}
                aria-expanded={themePickerOpen}
                aria-controls="streamsnip-theme-menu"
                aria-label="Choose workspace theme"
                title="Choose workspace theme"
              >
                <Palette size={17} />
                <span>{selectedTheme.name}</span>
                <ChevronDown size={13} />
              </button>
              {themePickerOpen ? (
                <div className="theme-picker-popover" id="streamsnip-theme-menu" role="dialog" aria-label="Choose a theme">
                  <div className="theme-picker-popover-heading"><strong>Workspace appearance</strong><small>Your choice is saved on this device</small></div>
                  <ThemeOptions value={themeId} onChange={(next) => { setThemeId(next); setThemePickerOpen(false); }} compact />
                  <Link to="/settings" className="theme-picker-settings" onClick={() => setThemePickerOpen(false)}>Appearance settings <ArrowRight size={13} /></Link>
                </div>
              ) : null}
            </div>
            <Link to="/help" className="topbar-help" aria-label="Help centre"><CircleHelp size={18} /></Link>
            <button type="button" className="quit-app-button" onClick={() => void quitApp()} disabled={quitting} title="Quit StreamSnip AI">
              <Square size={13} fill="currentColor" /> <span>{quitting ? "Quitting…" : "Quit app"}</span>
            </button>
          </div>
        </header>

        {workspace.error ? (
          <div className="connection-banner">
            <AlertCircle size={17} />
            <span>{workspace.error}</span>
            <Button onClick={() => void workspace.refresh()}><RefreshCw size={14} /> Retry</Button>
          </div>
        ) : null}

        <div className="studio-content">
          <Routes>
            <Route path="/" element={<Overview workspace={workspace} />} />
            <Route path="/live" element={<LiveStudio workspace={workspace} />} />
            <Route path="/layout" element={<LayoutStudio workspace={workspace} />} />
            <Route path="/clips" element={<ClipLibrary key="clips" workspace={workspace} tab="clips" />} />
            <Route path="/publish" element={<ClipLibrary key="publish" workspace={workspace} tab="publish" />} />
            <Route path="/posted" element={<ClipLibrary key="posted" workspace={workspace} tab="posted" />} />
            <Route path="/words" element={<WordsPage key={workspace.words.text} workspace={workspace} />} />
            <Route path="/settings" element={<SettingsPage workspace={workspace} section="general" themeId={themeId} onThemeChange={setThemeId} />} />
            <Route path="/settings/ai" element={<SettingsPage workspace={workspace} section="ai" themeId={themeId} onThemeChange={setThemeId} />} />
            <Route path="/settings/speech" element={<SettingsPage workspace={workspace} section="speech" themeId={themeId} onThemeChange={setThemeId} />} />
            <Route path="/settings/captions" element={<SettingsPage workspace={workspace} section="captions" themeId={themeId} onThemeChange={setThemeId} />} />
            <Route path="/settings/publishing" element={<SettingsPage workspace={workspace} section="publishing" themeId={themeId} onThemeChange={setThemeId} />} />
            <Route path="/activity" element={<ActivityPage workspace={workspace} />} />
            <Route path="/help" element={<HelpPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="*" element={<Overview workspace={workspace} />} />
          </Routes>
          {quitError ? <div className="quit-error-banner" role="alert"><AlertCircle size={15} /> {quitError}</div> : null}
      {quitting ? <div className="shutdown-screen" role="status"><div className="shutdown-card"><Loader2 className="spin" size={24} /><strong>StreamSnip AI is shutting down</strong><p>The capture engine and creator monitors are being stopped. You can close this tab when the server disconnects.</p></div></div> : null}
      <footer className="studio-footer">
            <span>StreamSnip AI <b>·</b> Local-first creator tools</span>
            <span>Capture and rendering stay on this PC. Hosted AI providers receive transcript text only when selected.</span>
          </footer>
        </div>
      </main>
      <ToastViewport />
    </div>
  );
}


type ToastItem = { id: number; tone: "success" | "error" | "info"; title: string; message: string };

function ToastViewport() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const receive = (event: Event) => {
      const detail = (event as CustomEvent<{ tone: ToastItem["tone"]; title: string; message?: string }>).detail;
      if (!detail) return;
      const id = ++nextId.current;
      setItems((current) => [...current.slice(-3), { id, tone: detail.tone, title: detail.title, message: detail.message || "" }]);
      const timer = window.setTimeout(() => {
        setItems((current) => current.filter((item) => item.id !== id));
        timers.current = timers.current.filter((value) => value !== timer);
      }, detail.tone === "error" ? 7000 : 4800);
      timers.current.push(timer);
    };
    window.addEventListener("streamsnip:toast", receive);
    return () => {
      window.removeEventListener("streamsnip:toast", receive);
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current = [];
    };
  }, []);

  const dismiss = (id: number) => setItems((current) => current.filter((item) => item.id !== id));

  return (
    <div className="toast-viewport" aria-live="polite" aria-relevant="additions">
      {items.map((item) => (
        <div className={"toast-card " + item.tone} key={item.id} role={item.tone === "error" ? "alert" : "status"}>
          <span className="toast-card-icon">{item.tone === "error" ? <AlertCircle size={17} /> : item.tone === "success" ? <CheckCircle2 size={17} /> : <Info size={17} />}</span>
          <div className="toast-card-copy"><strong>{item.title}</strong>{item.message ? <small>{item.message}</small> : null}</div>
          <button type="button" onClick={() => dismiss(item.id)} aria-label="Dismiss notification"><X size={15} /></button>
        </div>
      ))}
    </div>
  );
}

const defaultDashboardOrder = ["welcome", "metrics", "pipeline", "monitors", "recent", "activity"];
const defaultDashboardVisible: Record<string, boolean> = {
  welcome: true, metrics: true, pipeline: true, monitors: true, recent: true, activity: true,
};

function Overview({ workspace }: { workspace: Workspace }) {
  const { state, creators, logs } = workspace;
  const [customizing, setCustomizing] = useState(false);
  const [order, setOrder] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem("streamsnip.dashboard.layout");
      const value = saved ? JSON.parse(saved) as { order?: string[] } : null;
      if (Array.isArray(value?.order)) return [...defaultDashboardOrder.filter((id) => value.order!.includes(id)), ...value.order.filter((id) => !defaultDashboardOrder.includes(id))];
    } catch {
      // Use the default dashboard arrangement when browser storage is unavailable.
    }
    return defaultDashboardOrder;
  });
  const [visible, setVisible] = useState<Record<string, boolean>>(() => {
    try {
      const saved = localStorage.getItem("streamsnip.dashboard.layout");
      const value = saved ? JSON.parse(saved) as { visible?: Record<string, boolean> } : null;
      if (value?.visible) return { ...defaultDashboardVisible, ...value.visible };
    } catch {
      // Use the default panel visibility when browser storage is unavailable.
    }
    return defaultDashboardVisible;
  });
  const draggedId = useRef<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem("streamsnip.dashboard.layout", JSON.stringify({ order, visible }));
    } catch {
      // Layout remains editable for the current session if storage is unavailable.
    }
  }, [order, visible]);

  const activeMonitors = creators.filter((creator) => creator.running).length;
  const panelContent: Record<string, ReactNode> = {
    welcome: (
      <section className="welcome-panel">
        <div className="welcome-content">
          <div className="welcome-kicker"><span className="welcome-kicker-dot" /> STREAMSNIP AI STUDIO</div>
          <h2>{state.running ? "Your clipping session is live." : "Make every stream moment count."}</h2>
          <p>{state.status || "Capture live streams or VODs, score the moments, and turn the best parts into ready-to-publish clips."}</p>
          <div className="welcome-actions">
            <Link to="/live" className="button button-primary"><Radio size={16} /> {state.running ? "Open live session" : "Start a session"} <ArrowRight size={15} /></Link>
            <Link to="/layout" className="welcome-secondary-link">Configure clip layouts <ArrowRight size={14} /></Link>
          </div>
        </div>
        <div className="welcome-visual" aria-hidden="true">
          <div className="welcome-visual-screen"><div className="visual-screen-top" /><div className="visual-screen-bottom"><span /><span /><span /><span /><span /></div><div className="visual-play"><Play size={19} fill="currentColor" /></div></div>
          <span className="visual-tag visual-live"><i /> LIVE</span>
          <span className="visual-tag visual-ai"><Sparkles size={12} /> AI SCORING</span>
        </div>
      </section>
    ),
    metrics: (
      <section className="metric-grid">
        <MetricCard icon={Radio} label="Active monitors" value={activeMonitors} note={creators.length + " creator profile" + (creators.length === 1 ? "" : "s") + " configured"} tone="red" />
        <MetricCard icon={Film} label="Ready to review" value={state.clip_total} note="Unpublished clips in your library" tone="blue" />
        <MetricCard icon={BadgeCheck} label="Published" value={state.posted_total} note="Confirmed in the Posted registry" tone="green" />
        <MetricCard icon={Gauge} label="Session clips" value={state.session.clips} note={state.running ? "Generated in this session" : "Latest session count"} tone="amber" />
      </section>
    ),
    pipeline: (
      <section className="panel-card dashboard-pipeline">
        <div className="panel-heading">
          <div><div className="eyebrow">PROCESSING</div><h3>Live pipeline</h3></div>
          <StatusPill tone={state.running ? "good" : "neutral"}>{state.running ? "Running" : "Idle"}</StatusPill>
        </div>
        <Pipeline state={state} compact />
      </section>
    ),
    monitors: (
      <section className="panel-card dashboard-monitors">
        <div className="panel-heading">
          <div><div className="eyebrow">YOUR CHANNELS</div><h3>Creator monitors</h3></div>
          <Link to="/live" className="text-link">Manage monitors <ArrowRight size={14} /></Link>
        </div>
        {creators.length ? (
          <div className="monitor-summary-list">
            {creators.slice(0, 5).map((creator) => <CreatorSummary key={creator.id} creator={creator} />)}
          </div>
        ) : (
          <EmptyState icon={Radio} title="No creator monitors" body="Add a Twitch or YouTube channel in Live Studio to monitor it independently." action={<Link to="/live" className="button button-secondary"><Plus size={15} /> Add a monitor</Link>} />
        )}
      </section>
    ),
    recent: (
      <section className="panel-card dashboard-recent">
        <div className="panel-heading">
          <div><div className="eyebrow">LATEST OUTPUT</div><h3>Recently generated clips</h3></div>
          <Link to="/clips" className="text-link">Open library <ArrowRight size={14} /></Link>
        </div>
        {state.clips.length ? (
          <div className="recent-clip-list">
            {state.clips.slice(0, 5).map((clip) => (
              <Link key={clip.name} to="/clips" className="recent-clip-row">
                <span className="recent-clip-icon"><Video size={17} /></span>
                <span className="recent-clip-copy"><strong>{clip.title || clip.name}</strong><small>{clip.creator_name || "Stream capture"} · {formatDate(clip.mtime)}</small></span>
                <span className="recent-clip-size">{clip.size_mb.toFixed(1)} MB</span>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState icon={Clapperboard} title="Your clip library is ready" body="New clips will appear here as the engine transcribes and renders your stream." />
        )}
      </section>
    ),
    activity: (
      <section className="panel-card dashboard-activity">
        <div className="panel-heading">
          <div><div className="eyebrow">ENGINE EVENTS</div><h3>Latest activity</h3></div>
          <Link to="/activity" className="text-link">Full activity <ArrowRight size={14} /></Link>
        </div>
        {logs.length ? (
          <div className="mini-activity-list">
            {logs.slice(-5).reverse().map((entry) => <div key={entry.id} className="mini-activity-row"><time>{entry.t}</time><span>{entry.m}</span></div>)}
          </div>
        ) : <EmptyState icon={Activity} title="No events yet" body="Engine events will appear here when a capture or monitor is running." />}
      </section>
    ),
  };

  const labels: Record<string, string> = {
    welcome: "Welcome panel", metrics: "Performance cards", pipeline: "Live pipeline",
    monitors: "Creator monitors", recent: "Recent clips", activity: "Latest activity",
  };

  const reorder = (target: string) => {
    const source = draggedId.current;
    if (!source || source === target) return;
    setOrder((current) => {
      const next = current.filter((id) => id !== source);
      const targetIndex = next.indexOf(target);
      next.splice(targetIndex < 0 ? next.length : targetIndex, 0, source);
      return next;
    });
    draggedId.current = null;
  };

  return (
    <>
      <PageHeading
        eyebrow="YOUR CREATOR WORKSPACE"
        title="Dashboard"
        description="A live overview of capture, clip production, creator monitors, and publishing."
        action={<Button variant="secondary" onClick={() => setCustomizing((value) => !value)}><SlidersHorizontal size={15} /> {customizing ? "Done arranging" : "Customize layout"}</Button>}
      />
      {customizing ? (
        <section className="customize-strip">
          <div><strong>Arrange your dashboard</strong><p>Drag any panel by its top edge to change its position. Hide the panels you do not need.</p></div>
          <div className="customize-options">
            {defaultDashboardOrder.map((id) => (
              <label key={id}><input type="checkbox" checked={visible[id] !== false} onChange={(event) => setVisible((current) => ({ ...current, [id]: event.target.checked }))} />{labels[id]}</label>
            ))}
          </div>
        </section>
      ) : null}
      <div className={"dashboard-grid " + (customizing ? "is-customizing" : "")}>
        {order.filter((id) => panelContent[id] && visible[id] !== false).map((id) => (
          <div
            key={id}
            className={"dashboard-block dashboard-block-" + id}
            draggable={customizing}
            onDragStart={() => { draggedId.current = id; }}
            onDragOver={(event) => { if (customizing) event.preventDefault(); }}
            onDrop={(event) => { event.preventDefault(); if (customizing) reorder(id); }}
          >
            {customizing ? <div className="dashboard-drag-handle"><Move size={13} /> Drag to rearrange <span>{labels[id]}</span></div> : null}
            {panelContent[id]}
          </div>
        ))}
      </div>
    </>
  );
}

function Pipeline({ state, compact = false }: { state: Workspace["state"]; compact?: boolean }) {
  const stages = [
    { title: "Capture", detail: "Record stream segments", key: "recording" },
    { title: "Transcribe", detail: "Create timestamped speech", key: "transcribing" },
    { title: "Analyze", detail: "Score transcript moments", key: "analyzing" },
    { title: "Render", detail: "Compose vertical clips", key: "rendering" },
  ];
  const currentPhase = (state.phase || "").toLowerCase();
  const currentIndex = currentPhase.includes("render") ? 3 : currentPhase.includes("anal") ? 2 : currentPhase.includes("transcrib") ? 1 : currentPhase.includes("record") || currentPhase.includes("wait") ? 0 : -1;
  return (
    <div className={"pipeline-wrap " + (compact ? "compact" : "")}>
      <div className="pipeline-current">
        <div><span className="eyebrow">ENGINE STATUS</span><strong>{state.status || "Waiting for a session"}</strong></div>
        {state.running ? <span className="pipeline-live"><i /> PROCESSING</span> : <span className="pipeline-ready">READY</span>}
      </div>
      <div className="pipeline-stages">
        {stages.map((stage, index) => (
          <div key={stage.key} className={"pipeline-stage " + (index === currentIndex ? "current" : index < currentIndex ? "complete" : "")}>
            <span className="pipeline-stage-number">{index < currentIndex ? <Check size={15} /> : "0" + (index + 1)}</span>
            <span><strong>{stage.title}</strong><small>{stage.detail}</small></span>
          </div>
        ))}
      </div>
      <div className="pipeline-progress">
        <div><span>Engine-reported progress</span><strong>{state.running ? state.progress + "%" : "N/A"}</strong></div>
        <div className="progress-track"><span style={{ width: (state.running ? state.progress : 0) + "%" }} /></div>
      </div>
      {!compact ? (
        <div className="pipeline-stats">
          <span><strong>{state.session.chunks}</strong>chunks processed</span>
          <span><strong>{state.session.clips}</strong>clips generated</span>
          <span><strong>{formatDuration(state.session.elapsed)}</strong>session time</span>
        </div>
      ) : null}
    </div>
  );
}

function AIReviewPanel({ logs, threshold }: { logs: LogEntry[]; threshold: number }) {
  const events = logs.filter((entry) => /score|candidate|threshold|viral|highlight|analysis/i.test(entry.m)).slice(-8).reverse();
  return (
    <section className="panel-card ai-review-card">
      <div className="panel-heading">
        <div><div className="eyebrow">AI HIGHLIGHT REVIEW</div><h3>Scoring and threshold events</h3><p>Only actual events reported by the local engine are shown here.</p></div>
        <span className="ai-threshold-badge">Threshold · {threshold}/100</span>
      </div>
      {events.length ? (
        <div className="ai-review-events">
          {events.map((entry) => {
            const message = entry.m.toLowerCase();
            const tone = /reject|below threshold|discard/i.test(message) ? "rejected" : /accept|selected|above threshold|queued/i.test(message) ? "accepted" : "neutral";
            const score = entry.m.match(/(?:score|rating)\s*[:=]?\s*(\d{1,3})\s*(?:\/\s*100|%|\b)/i);
            return (
              <div key={entry.id} className={"ai-review-event " + tone}>
                <span className="ai-review-mark">{tone === "accepted" ? <Check size={14} /> : tone === "rejected" ? <X size={14} /> : <Sparkles size={14} />}</span>
                <time>{entry.t}</time>
                <p>{entry.m}</p>
                {score ? <strong className="ai-review-score">{score[1]}/100</strong> : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="ai-review-empty">
          <span><Bot size={20} /></span>
          <strong>Waiting for scoring events</strong>
          <p>The selected AI provider and threshold are active. Candidate-level scores will appear when the current engine reports them; no sample or simulated scores are shown.</p>
        </div>
      )}
    </section>
  );
}

function CreatorSummary({ creator }: { creator: Creator }) {
  return (
    <div className="creator-summary">
      <span className={"creator-avatar " + (creator.running ? "is-live" : "")}>{creator.name.slice(0, 1).toUpperCase()}</span>
      <span className="creator-summary-copy"><strong>{creator.name}</strong><small>{creator.target}</small></span>
      <StatusPill tone={creator.running ? "good" : "neutral"}>{creator.running ? "Monitoring" : "Idle"}</StatusPill>
      <span className="creator-summary-count">{creator.live_clips || 0} clips</span>
    </div>
  );
}

function EmptyState({
  icon: Icon, title, body, action,
}: { icon: LucideIcon; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon"><Icon size={23} /></span>
      <strong>{title}</strong>
      <p>{body}</p>
      {action ? <div className="empty-state-action">{action}</div> : null}
    </div>
  );
}

function LiveStudio({ workspace }: { workspace: Workspace }) {
  const settings = workspace.settings || {};
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [creatorName, setCreatorName] = useState("");
  const [creatorTarget, setCreatorTarget] = useState("");
  const [activeLiveTab, setActiveLiveTab] = useState<"capture" | "monitoring">("capture");

  const update = workspace.updateSettings;
  const running = workspace.state.running;

  const startSession = async () => {
    if (!workspace.settings) return;
    if (!asString(settings.target).trim()) {
      setMessage("Enter a Twitch or YouTube stream URL, or choose a VOD file.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await workspace.saveSettings({ ...settings, mode: asString(settings.mode, "live"), target: asString(settings.target) });
      await workspace.saveAI();
      await apiPost("/api/start", { ...settings, mode: asString(settings.mode, "live"), target: asString(settings.target) });
      await workspace.refresh();
      setMessage("Start request accepted. The pipeline will report each real processing stage below.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not start clipping.");
    } finally {
      setBusy(false);
    }
  };

  const stopSession = async (force: boolean) => {
    setBusy(true);
    setMessage("");
    try {
      await apiPost("/api/stop", { force });
      await workspace.refresh();
      setMessage(force ? "Immediate stop requested." : "Graceful stop requested. The engine will finish captured work.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not stop the session.");
    } finally {
      setBusy(false);
    }
  };

  const browseVideo = async () => {
    setBusy(true);
    try {
      const result = await apiPost<{ path: string }>("/api/browse");
      if (result.path) update({ target: result.path, mode: "file" });
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not open the video picker.");
    } finally {
      setBusy(false);
    }
  };

  const addCreator = async (event: FormEvent) => {
    event.preventDefault();
    if (!creatorName.trim() || !creatorTarget.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      await apiPost("/api/creators/add", { name: creatorName.trim(), target: creatorTarget.trim() });
      setCreatorName("");
      setCreatorTarget("");
      await workspace.refresh();
      setMessage("Creator monitor added.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not add the creator.");
    } finally {
      setBusy(false);
    }
  };

  const creatorAction = async (path: string, creator: Creator, folder?: string) => {
    setBusy(true);
    setMessage("");
    try {
      await apiPost(path, folder ? { id: creator.id, folder } : { id: creator.id });
      await workspace.refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Creator action failed.");
    } finally {
      setBusy(false);
    }
  };

  const activeCreatorMonitors = workspace.creators.filter((creator) => creator.running).length;

  const removeCreator = async (creator: Creator) => {
    if (!window.confirm("Remove " + creator.name + " from the monitor list? Existing recordings and clips will be kept.")) return;
    await creatorAction("/api/creators/remove", creator);
  };

  return (
    <>
      <PageHeading
        eyebrow="LIVE PRODUCTION"
        title="Live Studio"
        description="Start a live capture or VOD job, monitor the actual pipeline, and manage creator sources."
        action={<StatusPill tone={running ? "good" : "neutral"}>{running ? "Session running" : "Session idle"}</StatusPill>}
      />

      <div className="live-studio-tabs" role="tablist" aria-label="Live Studio sections">
        <button type="button" role="tab" aria-selected={activeLiveTab === "capture"} className={activeLiveTab === "capture" ? "active" : ""} onClick={() => setActiveLiveTab("capture")}>
          <Radio size={15} /> Live capture <span className="live-tab-meta">Session and pipeline</span>
        </button>
        <button type="button" role="tab" aria-selected={activeLiveTab === "monitoring"} className={activeLiveTab === "monitoring" ? "active" : ""} onClick={() => setActiveLiveTab("monitoring")}>
          <Activity size={15} /> Monitoring <span className="live-tab-count">{activeCreatorMonitors}/10 active</span>
        </button>
      </div>

      {activeLiveTab === "capture" ? (
        <>
        <div className="live-studio-grid live-control-grid">
        <div className="live-studio-main">
          <section className="panel-card session-launch-card">
            <div className="panel-heading">
              <div><h3>Capture source</h3><p>Use the main engine for a Twitch/YouTube live stream or a local video file.</p></div>
              <div className="session-launch-icon"><Radio size={20} /></div>
            </div>
            <div className="source-mode-switch">
              <button className={asString(settings.mode, "live") === "live" ? "selected" : ""} onClick={() => update({ mode: "live" })} disabled={running}><Radio size={15} /> Live stream</button>
              <button className={asString(settings.mode) === "file" ? "selected" : ""} onClick={() => update({ mode: "file" })} disabled={running}><Film size={15} /> Video / VOD</button>
            </div>
            <label className="field-label">{asString(settings.mode, "live") === "live" ? "Twitch or YouTube URL" : "Video file path"}</label>
            <div className="source-input-row">
              <input
                className="field-input"
                value={asString(settings.target)}
                onChange={(event) => update({ target: event.target.value })}
                aria-label={asString(settings.mode, "live") === "live" ? "Twitch or YouTube stream URL" : "Local video file path"}
                placeholder={asString(settings.mode, "live") === "live" ? "https://www.twitch.tv/channel" : "C:\\Videos\\recording.mp4"}
                disabled={running}
              />
              {asString(settings.mode) === "file" ? <Button onClick={() => void browseVideo()} disabled={running || busy}><FolderOpen size={15} /> Browse</Button> : null}
            </div>
            <div className="source-note"><ShieldCheck size={15} /> {asString(settings.mode, "live") === "live" ? "If the stream is offline, the engine can wait for it to go live." : "Original VOD files are preserved; clips are written to the configured output folder."}</div>

            <div className="session-options-grid">
              <label>
                <span>AI highlight engine</span>
                <select className="field-select" value={workspace.ai.provider} onChange={(event) => workspace.updateAI({ provider: event.target.value })} disabled={running}>
                  <option value="hooks">Hook words · offline</option>
                  <option value="ollama">Ollama · local AI</option>
                  <option value="gemini">Gemini API</option>
                  <option value="huggingface">Hugging Face</option>
                  <option value="custom">Custom OpenAI-compatible API</option>
                </select>
              </label>
              <label>
                <span>Viral score threshold</span>
                <div className="inline-range"><input type="range" min="0" max="100" value={asNumber(settings.min_score, 70)} onChange={(event) => update({ min_score: Number(event.target.value) })} disabled={running} /><strong>{asNumber(settings.min_score, 70)}</strong></div>
              </label>
              <label>
                <span>Analysis window</span>
                <div className="inline-range"><input type="range" min="3" max="15" value={asNumber(settings.chunk_min, 3)} onChange={(event) => update({ chunk_min: Number(event.target.value) })} disabled={running} /><strong>{asNumber(settings.chunk_min, 3)} min</strong></div>
              </label>
              <label>
                <span>Clips per chunk</span>
                <div className="inline-range"><input type="range" min="0" max="10" value={asNumber(settings.clips_per_chunk, 2)} onChange={(event) => update({ clips_per_chunk: Number(event.target.value) })} disabled={running} /><strong>{asNumber(settings.clips_per_chunk, 2) === 0 ? "No limit" : asNumber(settings.clips_per_chunk, 2)}</strong></div>
              </label>
              <label>
                <span>Pre-roll trim</span>
                <div className="inline-range"><input type="range" min="3" max="90" value={asNumber(settings.pre, 20)} onChange={(event) => update({ pre: Number(event.target.value) })} disabled={running} /><strong>{asNumber(settings.pre, 20)}s</strong></div>
              </label>
              <label>
                <span>Post-roll trim</span>
                <div className="inline-range"><input type="range" min="3" max="90" value={asNumber(settings.post, 15)} onChange={(event) => update({ post: Number(event.target.value) })} disabled={running} /><strong>{asNumber(settings.post, 15)}s</strong></div>
              </label>
            </div>

            <div className="session-primary-actions">
              {!running ? (
                <Button variant="primary" onClick={() => void startSession()} disabled={busy || !workspace.configLoaded || !asString(settings.target).trim()}><Play size={16} fill="currentColor" /> {busy ? "Starting…" : "Start clipping"}</Button>
              ) : (
                <>
                  <Button variant="danger" onClick={() => void stopSession(false)} disabled={busy}><Square size={15} fill="currentColor" /> Stop gracefully</Button>
                  <Button variant="secondary" onClick={() => void stopSession(true)} disabled={busy}><X size={15} /> Stop immediately</Button>
                </>
              )}
              <span>{workspace.saving ? "Saving session settings…" : workspace.saveError || "Session settings save automatically."}</span>
            </div>
            {message ? <p className="inline-feedback" role="status">{message}</p> : null}
          </section>

        </div>

        <aside className="live-studio-aside">
          <section className="panel-card live-session-rail">
            <div className="live-rail-header">
              <span className="session-snapshot-icon"><Activity size={20} /></span>
              <div className="live-rail-state-copy">
                <small>SESSION STATUS</small>
                <h3>{running ? "Capture is active" : "Ready to capture"}</h3>
              </div>
              <StatusPill tone={running ? "good" : "neutral"}>{running ? "Live" : "Idle"}</StatusPill>
            </div>
            <p className="live-rail-status">{workspace.state.status}</p>
            <div className="session-summary-grid">
              <div><span>Elapsed</span><strong>{formatDuration(workspace.state.session.elapsed)}</strong></div>
              <div><span>Chunks</span><strong>{workspace.state.session.chunks}</strong></div>
              <div><span>Clips created</span><strong>{workspace.state.session.clips}</strong></div>
              <div><span>Progress</span><strong>{running ? workspace.state.progress + "%" : "N/A"}</strong></div>
            </div>
            <div className="live-rail-divider" />
            <div className="live-rail-section-heading">
              <strong>Current setup</strong>
              <span>ACTIVE CONFIGURATION</span>
            </div>
            <dl className="live-rail-settings">
              <div><dt>AI engine</dt><dd>{workspace.ai.provider === "hooks" ? "Hook words" : workspace.ai.provider}</dd></div>
              <div><dt>Transcriber</dt><dd>{asString(settings.transcriber_provider, "faster-whisper")}</dd></div>
              <div><dt>Speech model</dt><dd>{asString(settings.model, "distil-large-v3")}</dd></div>
              <div><dt>Output layout</dt><dd>{asString(settings.layout, "Facecam + game (Twitch)")}</dd></div>
              <div><dt>Video format</dt><dd>{asString(settings.output_format, "9:16")}</dd></div>
            </dl>
            <div className="live-rail-links">
              <Link to="/settings/ai">AI settings <ArrowRight size={14} /></Link>
              <Link to="/layout">Layout Studio <ArrowRight size={14} /></Link>
            </div>
          </section>
        </aside>
        </div>

        <section className="panel-card pipeline-card pipeline-card-wide">
          <div className="panel-heading">
            <div><h3>Processing pipeline</h3><p>Stages update from the Python engine, not from a simulated timer.</p></div>
            <Button onClick={() => void workspace.refresh()}><RefreshCw size={14} /> Refresh</Button>
          </div>
          <Pipeline state={workspace.state} />
          <div className="pipeline-event-line">
            <span><strong>{workspace.state.session.chunks}</strong> chunks</span>
            <span><strong>{workspace.state.session.clips}</strong> clips generated</span>
            <span><strong>{formatDuration(workspace.state.session.elapsed)}</strong> elapsed</span>
            <span><strong>{workspace.state.posting.completed}/{workspace.state.posting.total}</strong> uploads done</span>
          </div>
          {workspace.state.posting.active ? (
            <div className="upload-progress-card">
              <div><strong>Publishing in progress</strong><span>{workspace.state.posting.current || "Preparing upload"} · {workspace.state.posting.completed}/{workspace.state.posting.total}</span></div>
              <div className="progress-track"><span style={{ width: (workspace.state.posting.total ? workspace.state.posting.completed / workspace.state.posting.total * 100 : 0) + "%" }} /></div>
              {workspace.state.posting.errors ? <small>{workspace.state.posting.errors} upload error(s) reported.</small> : null}
            </div>
          ) : null}
        </section>
        <AIReviewPanel logs={workspace.logs} threshold={asNumber(settings.min_score, 70)} />
        </>
      ) : (
        <div className="live-studio-monitoring">
          <section className="panel-card creator-management-card">
            <div className="panel-heading">
              <div><h3>Creator monitors</h3><p>Run up to 10 live creator monitors at the same time. Each creator keeps separate recordings, clips, and VOD inbox folders.</p></div>
              <span className="count-badge">{activeCreatorMonitors} / 10 active | {workspace.creators.length} / 100 saved</span>
            </div>
            <div className="creator-capacity-note">{activeCreatorMonitors} of 10 live monitor slots are in use. High concurrent stream counts can increase CPU, GPU, memory, and network load.</div>
            {workspace.creators.length ? (
              <div className="creator-management-list">
                {workspace.creators.map((creator) => (
                  <article className="creator-management-item" key={creator.id}>
                    <div className="creator-management-top">
                      <span className={"creator-avatar large " + (creator.running ? "is-live" : "")}>{creator.name.slice(0, 1).toUpperCase()}</span>
                      <div className="creator-management-copy"><strong>{creator.name}</strong><small>{creator.target}</small></div>
                      <StatusPill tone={creator.running ? "good" : "neutral"}>{creator.running ? (creator.phase || "Monitoring") : "Idle"}</StatusPill>
                    </div>
                    <p className="creator-management-detail">{creator.status || creator.vod_status || "Monitor is ready."}</p>
                    <div className="creator-counts">
                      <span><strong>{creator.live_clips || 0}</strong>Live clips</span>
                      <span><strong>{creator.vod_clips || 0}</strong>VOD clips</span>
                      <span><strong>{creator.vod_pending || 0}</strong>VOD pending</span>
                    </div>
                    <div className="creator-management-actions">
                      <Button variant={creator.running ? "danger" : "primary"} onClick={() => void creatorAction(creator.running ? "/api/creators/stop" : "/api/creators/start", creator)} disabled={busy || (!creator.running && activeCreatorMonitors >= 10)}>{creator.running ? <Square size={14} /> : <Play size={14} />}{creator.running ? "Stop monitor" : activeCreatorMonitors >= 10 ? "10/10 slots full" : "Start monitor"}</Button>
                      <Button onClick={() => void creatorAction(creator.watching_vods ? "/api/creators/stop-vod-watch" : "/api/creators/watch-vods", creator)} disabled={busy}><Folder size={14} />{creator.watching_vods ? "Stop VOD watch" : "Watch VOD folder"}</Button>
                      <div className="creator-management-folders">
                        <Button onClick={() => void creatorAction("/api/creators/open", creator, "live_clips")}><FolderOpen size={14} /> Live clips</Button>
                        <Button onClick={() => void creatorAction("/api/creators/open", creator, "vod_inbox")}><FolderOpen size={14} /> VOD inbox</Button>
                      </div>
                      <Button variant="quiet" onClick={() => void removeCreator(creator)} disabled={busy}><Trash2 size={14} /> Remove</Button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState icon={Radio} title="No creator monitors configured" body="Add a creator below or use the main capture source above." />
            )}
            <form className="add-creator-form" onSubmit={(event) => void addCreator(event)}>
              <div><strong>Add another creator</strong><small>Each source keeps its own clips and VOD folders.</small></div>
              <input className="field-input" value={creatorName} onChange={(event) => setCreatorName(event.target.value)} maxLength={80} placeholder="Creator name" required />
              <input className="field-input" value={creatorTarget} onChange={(event) => setCreatorTarget(event.target.value)} placeholder="Twitch or YouTube channel URL" required />
              <Button variant="primary" disabled={busy || !creatorName.trim() || !creatorTarget.trim()}><Plus size={15} /> Add monitor</Button>
            </form>
          </section>
        </div>
      )}
    </>
  );
}

const layoutPresets: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "Facecam + game (Twitch)", label: "Facecam + game", icon: Camera },
  { key: "Blur background", label: "Blur background", icon: Layers },
  { key: "Fill (crop center)", label: "Fill", icon: MonitorPlay },
  { key: "Selected crop", label: "Selected crop", icon: SlidersHorizontal },
];

type LayoutBox = { x: number; y: number; w: number; h: number };
type LayoutDrag = {
  type: "facecam" | "crop";
  mode: "move" | "resize";
  startX: number;
  startY: number;
  bounds: DOMRect;
  initial: LayoutBox;
};

function LayoutCanvas({
  settings, frame, onChange,
}: { settings: AppSettings; frame: string; onChange: (patch: Partial<AppSettings>) => void }) {
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<LayoutDrag | null>(null);
  const layout = asString(settings.layout, "Facecam + game (Twitch)");
  const isFacecam = layout.startsWith("Facecam");
  const isSelected = layout.startsWith("Selected");
  const camBox = {
    x: asNumber(settings.cam_x, 70), y: asNumber(settings.cam_y, 4),
    w: asNumber(settings.cam_w, 29), h: asNumber(settings.cam_h, 37),
  };
  const cropBox = {
    x: asNumber(settings.crop_x, 34.2), y: asNumber(settings.crop_y, 0),
    w: asNumber(settings.crop_w, 31.6), h: asNumber(settings.crop_h, 100),
  };
  const begin = (event: ReactPointerEvent<HTMLElement>, type: "facecam" | "crop", mode: "move" | "resize") => {
    if (!stage.current) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = {
      type, mode, startX: event.clientX, startY: event.clientY,
      bounds: stage.current.getBoundingClientRect(),
      initial: type === "facecam" ? camBox : cropBox,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const move = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || !current.bounds.width || !current.bounds.height) return;
    const dx = (event.clientX - current.startX) / current.bounds.width * 100;
    const dy = (event.clientY - current.startY) / current.bounds.height * 100;
    const box = { ...current.initial };
    if (current.mode === "move") {
      box.x = clamp(current.initial.x + dx, 0, 100 - box.w);
      box.y = clamp(current.initial.y + dy, 0, 100 - box.h);
    } else if (current.type === "facecam") {
      const facecamHeightPerWidth = (16 / 9) / (1080 / 768);
      let width = Math.max(10, current.initial.w + dx);
      width = Math.min(width, 100 - box.x, (100 - box.y) / facecamHeightPerWidth);
      box.w = width;
      box.h = width * facecamHeightPerWidth;
    } else {
      const outputAspect = ({ "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1, "4:5": 4 / 5 } as Record<string, number>)[asString(settings.output_format, "9:16")] || 9 / 16;
      const cropHeightPerWidth = (16 / 9) / outputAspect;
      let width = Math.max(10, current.initial.w + dx);
      width = Math.min(width, 100 - box.x, (100 - box.y) / cropHeightPerWidth);
      box.w = width;
      box.h = width * cropHeightPerWidth;
    }
    if (current.type === "facecam") {
      onChange({ cam_x: +box.x.toFixed(1), cam_y: +box.y.toFixed(1), cam_w: +box.w.toFixed(1), cam_h: +box.h.toFixed(1) });
    } else {
      onChange({ crop_x: +box.x.toFixed(1), crop_y: +box.y.toFixed(1), crop_w: +box.w.toFixed(1), crop_h: +box.h.toFixed(1) });
    }
  };

  const end = () => { drag.current = null; };

  const gameWidth = Math.min(100, (1080 / 1152) / (16 / 9) * 100);
  const gameLeft = (100 - gameWidth) * asNumber(settings.game_x, 50) / 100;

  return (
    <div
      className="source-canvas"
      ref={stage}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      style={frame ? { backgroundImage: "url(" + frame + ")" } : undefined}
    >
      {!frame ? (
        <div className="source-canvas-placeholder">
          <div className="placeholder-screen"><MonitorPlay size={37} /><span>16:9 SOURCE FRAME</span></div>
          <p>Capture a frame from your current source to place the layout accurately.</p>
        </div>
      ) : <div className="source-image-caption">CAPTURED SOURCE · 16:9</div>}

      {isFacecam ? (
        <>
          <div className="layout-game-box" style={{ left: gameLeft + "%", width: gameWidth + "%" }}>
            <span>GAME AREA</span>
          </div>
          <div
            className="layout-selection facecam-selection"
            style={{ left: camBox.x + "%", top: camBox.y + "%", width: camBox.w + "%", height: camBox.h + "%" }}
            onPointerDown={(event) => begin(event, "facecam", "move")}
          >
            <span className="selection-label">FACECAM · DRAG TO MOVE</span>
            <span className="resize-handle" onPointerDown={(event) => begin(event, "facecam", "resize")} />
          </div>
        </>
      ) : null}

      {isSelected ? (
        <div
          className="layout-selection crop-selection"
          style={{ left: cropBox.x + "%", top: cropBox.y + "%", width: cropBox.w + "%", height: cropBox.h + "%" }}
          onPointerDown={(event) => begin(event, "crop", "move")}
        >
          <span className="selection-label">OUTPUT CROP · DRAG TO MOVE</span>
          <span className="resize-handle" onPointerDown={(event) => begin(event, "crop", "resize")} />
        </div>
      ) : null}

      {!isFacecam && !isSelected ? (
        <div className="auto-layout-overlay">
          <span>{layout.startsWith("Blur") ? "BLURRED BACKGROUND" : "CENTER-FILL CROP"}</span>
          <p>This layout is calculated automatically by the rendering engine.</p>
        </div>
      ) : null}
      <div className="canvas-dimensions">SOURCE CANVAS | 1920 x 1080 REFERENCE</div>
    </div>
  );
}

function LayoutStudio({ workspace }: { workspace: Workspace }) {
  const [draftOverride, setDraftOverride] = useState<AppSettings | null>(null);
  const draft = draftOverride ?? workspace.settings ?? {};
  const [frame, setFrame] = useState("");
  const [frameBusy, setFrameBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [presets, setPresets] = useState<{ name: string; settings: Partial<AppSettings> }[]>(() => {
    try {
      const saved = localStorage.getItem("streamsnip.layout.presets");
      return saved ? JSON.parse(saved) as { name: string; settings: Partial<AppSettings> }[] : [];
    } catch {
      return [];
    }
  });
  const [presetName, setPresetName] = useState("");

  const patch = (changes: Partial<AppSettings>) => setDraftOverride((current) => ({ ...(current ?? workspace.settings ?? {}), ...changes }));
  const layout = asString(draft.layout, "Facecam + game (Twitch)");
  const format = asString(draft.output_format, "9:16");
  const ratio = ({ "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1", "4:5": "4 / 5" } as Record<string, string>)[format] || "9 / 16";
  const isFacecam = layout.startsWith("Facecam");
  const isSelected = layout.startsWith("Selected");

  const chooseFormat = (nextFormat: string) => {
    const aspect = ({ "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1, "4:5": 4 / 5 } as Record<string, number>)[nextFormat] || 9 / 16;
    const width = Math.min(100, 100 * aspect / (16 / 9));
    patch({
      output_format: nextFormat,
      crop_w: +width.toFixed(1),
      crop_h: 100,
      crop_x: +((100 - width) / 2).toFixed(1),
      crop_y: 0,
    });
  };

  const captureFrame = async () => {
    setFrameBusy(true);
    setMessage("");
    try {
      const result = await apiPost<{ image: string }>("/api/frame", {
        mode: asString(draft.mode, "live"),
        target: asString(draft.target),
      });
      setFrame(result.image);
      setMessage("Source frame captured. Drag the highlighted region to position it.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not capture a source frame.");
    } finally {
      setFrameBusy(false);
    }
  };

  const saveLayout = async () => {
    try {
      await workspace.saveSettings(draft);
      setMessage("Layout saved to your StreamSnip settings.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save the layout.");
    }
  };

  const savePreset = () => {
    const name = presetName.trim() || window.prompt("Name this layout preset");
    if (!name) return;
    const values: Partial<AppSettings> = {};
    ["layout", "output_format", "cam_x", "cam_y", "cam_w", "cam_h", "game_x", "crop_x", "crop_y", "crop_w", "crop_h"].forEach((key) => {
      if (draft[key] !== undefined) values[key] = draft[key];
    });
    const next = [...presets.filter((item) => item.name !== name), { name, settings: values }];
    setPresets(next);
    setPresetName("");
    try { localStorage.setItem("streamsnip.layout.presets", JSON.stringify(next)); } catch { /* browser storage is optional */ }
    setMessage("Preset saved in this browser.");
  };

  const applyPreset = (preset: { name: string; settings: Partial<AppSettings> }) => {
    patch(preset.settings);
    setMessage("Loaded \"" + preset.name + "\". Save layout to apply it to new clips.");
  };

  const deletePreset = (name: string) => {
    const next = presets.filter((item) => item.name !== name);
    setPresets(next);
    try { localStorage.setItem("streamsnip.layout.presets", JSON.stringify(next)); } catch { /* browser storage is optional */ }
  };

  return (
    <>
      <PageHeading
        eyebrow="VIDEO COMPOSITION"
        title="Layout Studio"
        description="Design the source frame, facecam/game split, crop, and final output ratio before rendering clips."
        action={<Button variant="primary" onClick={() => void saveLayout()}><Save size={15} /> Save layout</Button>}
      />

      <div className="layout-presets-bar">
        <div><strong>Layout presets</strong><small>Choose a composition, then refine it on the canvas.</small></div>
        <div className="layout-preset-buttons">
          {layoutPresets.map(({ key, label, icon: Icon }) => (
            <button key={key} className={layout === key ? "layout-preset selected" : "layout-preset"} onClick={() => patch({ layout: key })}><Icon size={17} /><span>{label}</span></button>
          ))}
        </div>
      </div>

      <div className="layout-editor-grid">
        <section className="panel-card layout-canvas-card">
          <div className="panel-heading">
            <div><div className="eyebrow">SOURCE COMPOSITION</div><h3>Drag to position your frame</h3><p>{isFacecam ? "Move the pink facecam window. Resize it from the lower-right handle. The dashed area shows the gameplay crop." : isSelected ? "Move the crop window or resize it from the lower-right handle. Its aspect ratio follows the selected output format." : "This layout uses automatic scaling and does not require manual positioning."}</p></div>
            <Button onClick={() => void captureFrame()} disabled={frameBusy || !asString(draft.target).trim()}><Camera size={15} />{frameBusy ? "Capturing…" : "Capture source frame"}</Button>
          </div>
          <LayoutCanvas settings={draft} frame={frame} onChange={patch} />
          <div className="canvas-help"><span><i className="legend-pink" /> Facecam</span><span><i className="legend-blue" /> Gameplay source</span><span><Move size={13} /> Drag the selection to move</span></div>
          {message ? <p className="inline-feedback">{message}</p> : null}
        </section>

        <aside className="layout-inspector">
          <section className="panel-card inspector-card">
            <div className="eyebrow">OUTPUT</div><h3>Frame settings</h3>
            <label className="field-label">Video aspect ratio</label>
            <select className="field-select" value={format} onChange={(event) => chooseFormat(event.target.value)}>
              <option value="9:16">9:16 · Shorts / Reels / TikTok</option>
              <option value="16:9">16:9 · YouTube landscape</option>
              <option value="1:1">1:1 · Square</option>
              <option value="4:5">4:5 · Instagram portrait</option>
            </select>
            <div className="output-size-note"><strong>{format}</strong><span>{format === "9:16" ? "1080 x 1920" : format === "16:9" ? "1920 x 1080" : format === "1:1" ? "1080 x 1080" : "1080 x 1350"}</span></div>
            {isFacecam && format !== "9:16" ? <p className="warning-note"><AlertCircle size={14} /> The facecam + game render is designed for 9:16 output. Choose 9:16 to use the split composition.</p> : null}
          </section>

          <section className="panel-card inspector-card">
            <div className="eyebrow">POSITION & SCALE</div><h3>{isFacecam ? "Facecam controls" : isSelected ? "Crop controls" : "Automatic layout"}</h3>
            {isFacecam ? (
              <>
                <ValueSlider label="Horizontal position" value={asNumber(draft.cam_x, 70)} min={0} max={90} onChange={(value) => patch({ cam_x: value })} suffix="%" />
                <ValueSlider label="Vertical position" value={asNumber(draft.cam_y, 4)} min={0} max={90} onChange={(value) => patch({ cam_y: value })} suffix="%" />
                <ValueSlider label="Facecam width" value={asNumber(draft.cam_w, 29)} min={10} max={100} onChange={(value) => {
                  const width = clamp(value, 10, 100 - asNumber(draft.cam_x, 70));
                  patch({ cam_w: width, cam_h: +(width * ((16 / 9) / (1080 / 768))).toFixed(1) });
                }} suffix="%" />
                <ValueSlider label="Gameplay horizontal crop" value={asNumber(draft.game_x, 50)} min={0} max={100} onChange={(value) => patch({ game_x: value })} suffix="%" />
              </>
            ) : isSelected ? (
              <>
                <ValueSlider label="Crop horizontal position" value={asNumber(draft.crop_x, 34.2)} min={0} max={90} onChange={(value) => patch({ crop_x: value })} suffix="%" />
                <ValueSlider label="Crop vertical position" value={asNumber(draft.crop_y, 0)} min={0} max={90} onChange={(value) => patch({ crop_y: value })} suffix="%" />
                <ValueSlider label="Crop width" value={asNumber(draft.crop_w, 31.6)} min={10} max={100} onChange={(value) => {
                  const aspect = ({ "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1, "4:5": 4 / 5 } as Record<string, number>)[format] || 9 / 16;
                  const width = clamp(value, 10, 100 - asNumber(draft.crop_x, 34.2));
                  patch({ crop_w: width, crop_h: +(Math.min(100, width * (16 / 9) / aspect)).toFixed(1) });
                }} suffix="%" />
              </>
            ) : (
              <p className="panel-description">The engine scales the entire source and either fills the output or places the source over a blurred background. Use Selected crop when you need to choose a specific frame region.</p>
            )}
            <Button className="full-width" onClick={() => {
              if (isFacecam) patch({ cam_x: 70, cam_y: 4, cam_w: 29, cam_h: 37, game_x: 50 });
              else patch({ crop_x: 34.2, crop_y: 0, crop_w: 31.6, crop_h: 100 });
            }}>Reset positioning</Button>
          </section>

          <section className="panel-card inspector-card">
            <div className="eyebrow">OUTPUT PREVIEW</div><h3>Rendered composition</h3>
            <div className="rendered-preview" style={{ aspectRatio: ratio }}>
              {isFacecam ? <><div className="render-preview-face"><Camera size={18} /><span>FACECAM</span></div><div className="render-preview-game"><MonitorPlay size={19} /><span>GAMEPLAY</span></div></> : (
                <div className={"render-preview-auto " + (layout.startsWith("Blur") ? "blur-preview" : "fill-preview")}><Video size={23} /><span>{layout.startsWith("Blur") ? "Blur background" : layout.startsWith("Selected") ? "Selected crop" : "Fill frame"}</span></div>
              )}
              <div className="render-preview-caption">YOUR CAPTIONS</div>
            </div>
            <p className="panel-description">Illustrative preview of the selected render mode. The source canvas above controls the actual crop coordinates used by FFmpeg.</p>
          </section>

          <section className="panel-card inspector-card">
            <div className="eyebrow">YOUR PRESETS</div><h3>Saved layouts</h3>
            <div className="save-preset-row"><input className="field-input" aria-label="Preset name" value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Preset name" /><Button onClick={savePreset}><Plus size={14} /> Save</Button></div>
            {presets.length ? <div className="saved-preset-list">{presets.map((preset) => <div key={preset.name}><button onClick={() => applyPreset(preset)}>{preset.name}<ArrowRight size={13} /></button><button className="preset-delete" onClick={() => deletePreset(preset.name)} aria-label={"Delete " + preset.name}><X size={13} /></button></div>)}</div> : <p className="muted-note">No custom presets saved yet. Presets are stored in this browser; the active layout is saved in StreamSnip settings.</p>}
          </section>
        </aside>
      </div>
    </>
  );
}

function ValueSlider({
  label, value, min, max, suffix = "", onChange,
}: { label: string; value: number; min: number; max: number; suffix?: string; onChange: (value: number) => void }) {
  return (
    <label className="value-slider">
      <span>{label}<strong>{value.toFixed(1).replace(".0", "")}{suffix}</strong></span>
      <input type="range" min={min} max={max} step="0.5" value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}


function ClipLibrary({ workspace, tab }: { workspace: Workspace; tab: "clips" | "publish" | "posted" }) {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(() => params.get("search") || "");
  const [activeClip, setActiveClip] = useState<Clip | null>(null);
  const [busy, setBusy] = useState(false);
  const { state } = workspace;

  const setClipTab = workspace.setClipTab;
  useEffect(() => {
    setClipTab(tab === "posted" ? "posted" : "clips");
  }, [tab, setClipTab]);

  const filtered = useMemo(() => state.clips.filter((clip) => {
    const haystack = [clip.title, clip.name, clip.description, clip.creator_name, clip.caption].join(" ").toLowerCase();
    return !query.trim() || haystack.includes(query.trim().toLowerCase());
  }), [state.clips, query]);

  const accountIds = workspace.publishing.providers?.zernio?.accounts || workspace.publishing.accounts || {};

  const doDelete = async (names: string[]) => {
    const label = names.length === 1 ? names[0] : names.length + " selected clips";
    if (!window.confirm("Permanently delete " + label + " and their TXT metadata sidecars? This cannot be undone.")) return;
    setBusy(true);
    try {
      for (const name of names) await apiPost("/api/delete", { name });
      setActiveClip(null);
      await workspace.refresh();
    } catch (reason) {
      notifyApp("error", "Delete failed", reason instanceof Error ? reason.message : "Could not delete the selected clips.");
    } finally {
      setBusy(false);
    }
  };

  const pageSize = 60;
  const pageNumber = Math.floor(workspace.clipOffset / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(state.clip_total / pageSize));

  return (
    <>
      <PageHeading
        eyebrow={tab === "clips" ? "CONTENT LIBRARY" : tab === "publish" ? "POST YOUR CLIPS" : "PUBLISHING HISTORY"}
        title={tab === "clips" ? "Clips" : tab === "publish" ? "Post your clips" : "Published"}
        description={tab === "clips" ? "Preview saved clips or delete them from your library." : tab === "publish" ? "Choose a clip, select the social platforms, and prepare its AI-generated post copy for review." : "Your publishing history, including confirmed Zernio posts and posts you mark as published."}
        action={tab === "clips" || tab === "publish" ? <Button onClick={() => void workspace.refresh()}><RefreshCw size={14} /> Refresh</Button> : <StatusPill tone="good">{state.posted_total} confirmed</StatusPill>}
      />

      {workspace.state.posting.active ? (
        <section className="upload-progress-card library-upload-progress">
          <div><strong>Publishing batch in progress</strong><span>{workspace.state.posting.current || "Preparing upload"} · {workspace.state.posting.completed} of {workspace.state.posting.total} complete</span></div>
          <div className="progress-track"><span style={{ width: (workspace.state.posting.total ? workspace.state.posting.completed / workspace.state.posting.total * 100 : 0) + "%" }} /></div>
          {workspace.state.posting.errors ? <small>{workspace.state.posting.errors} upload error(s) have been reported.</small> : null}
        </section>
      ) : null}

      <section className="library-toolbar-studio">
        <div className="library-tabs-studio">
          <Link to="/clips" className={tab === "clips" ? "active" : ""}>Clips <span>{Math.max(0, state.clip_total)}</span></Link>
          <Link to="/publish" className={tab === "publish" ? "active" : ""}>Publish</Link>
          <Link to="/posted" className={tab === "posted" ? "active" : ""}>Published <span>{state.posted_total}</span></Link>
        </div>
        <form className="library-search" onSubmit={(event) => {
          event.preventDefault();
          setParams(query.trim() ? { search: query.trim() } : {});
        }}>
          <Search size={16} />
          <input aria-label="Search clips by title, creator, or metadata" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search titles, creators, metadata…" />
          {query ? <button type="button" onClick={() => { setQuery(""); setParams({}); }} aria-label="Clear search"><X size={14} /></button> : null}
        </form>
      </section>


      <section className="panel-card clip-table-card">
        {filtered.length ? (
          <div className="clip-table-heading">
            <span>VIDEO</span><span>CREATOR / SOURCE</span><span>FILE SIZE</span><span>{tab === "posted" ? "PUBLISHED" : "CREATED"}</span><span>STATUS</span><span />
          </div>
        ) : null}
        {filtered.length ? filtered.map((clip) => (
          <div className="clip-table-row" key={clip.name}>
            <button className="clip-table-video" onClick={() => setActiveClip(clip)}>
              <span className="clip-table-thumb"><video src={"/clips/" + encodeURIComponent(clip.name)} preload="metadata" muted playsInline /></span>
              <span className="clip-table-title"><strong>{clip.title || clip.name.replace(/\.mp4$/i, "")}</strong><small>{clip.name}</small></span>
            </button>
            <span className="clip-table-creator"><strong>{clip.creator_name || "Main workspace"}</strong><small>{clip.source || "Local capture"}</small></span>
            <span className="clip-table-size">{clip.size_mb.toFixed(1)} MB</span>
            <span className="clip-table-date">{formatDate(tab === "posted" ? (clip.posted_at || clip.mtime) : clip.mtime)}</span>
            <span><StatusPill tone={tab === "posted" ? "good" : "neutral"}>{tab === "posted" ? "Published" : "Ready"}</StatusPill></span>
            <span className="clip-row-actions">
              {tab === "clips" ? <button className="clip-row-publish" title="Delete clip" aria-label={"Delete " + clip.name} onClick={() => void doDelete([clip.name])}><Trash2 size={15} /></button> : null}
              {tab === "publish" ? <button className="clip-row-publish" title="Prepare this clip for posting" aria-label={"Prepare post for " + clip.name} onClick={() => setActiveClip(clip)}><Upload size={14} /> Post</button> : null}
              {tab === "posted" ? <button title="View published clip" aria-label={"Open details for " + clip.name} onClick={() => setActiveClip(clip)}><MoreHorizontal size={17} /></button> : null}
            </span>
          </div>
        )) : (
          <div className="clip-table-empty">
            <EmptyState
              icon={tab === "posted" ? BadgeCheck : tab === "publish" ? Upload : Film}
              title={query ? "No matching clips" : tab === "posted" ? "Nothing published yet" : tab === "publish" ? "No clips ready to post" : "No saved clips yet"}
              body={query ? "Try another search term." : tab === "posted" ? "Posts you confirm or send through Zernio will appear here." : tab === "publish" ? "Clips appear here when they are ready. Open one to choose manual platforms or optional Zernio Auto Posting." : "Your saved clips appear here. Open one to preview it or delete it."}
              action={tab === "clips" ? <Link to="/live" className="button button-primary"><Radio size={15} /> Open Live Studio</Link> : <Link to="/clips" className="button button-secondary">Browse clips</Link>}
            />
          </div>
        )}
      </section>

      <div className="library-pagination">
        <span>Showing {state.clip_total ? Math.min(workspace.clipOffset + 1, state.clip_total) : 0}–{Math.min(workspace.clipOffset + state.clips.length, state.clip_total)} of {state.clip_total}</span>
        <div><Button onClick={() => workspace.setClipOffset(Math.max(0, workspace.clipOffset - pageSize))} disabled={workspace.clipOffset <= 0}><ArrowRight className="icon-flip" size={14} /> Newer</Button><span>Page {pageNumber} of {totalPages}</span><Button onClick={() => workspace.setClipOffset(workspace.clipOffset + pageSize)} disabled={workspace.clipOffset + state.clips.length >= state.clip_total}>Older <ArrowRight size={14} /></Button></div>
      </div>

      {activeClip ? (
        <ClipDetail
          clip={activeClip}
          tab={tab}
          accountIds={accountIds}
          configured={!!workspace.publishing.configured}
          onClose={() => setActiveClip(null)}
          onDelete={() => void doDelete([activeClip.name])}
          onSaveMetadata={async (title, description) => {
            await apiPost("/api/clip-metadata", { name: activeClip.name, title, description });
            await workspace.refresh();
          }}
          onPublish={async (title, description, selectedAccounts) => {
            if (!workspace.publishing.configured) throw new Error("Configure Zernio in Settings → Publishing first.");
            if (!Object.keys(selectedAccounts).length) throw new Error("Select at least one platform before publishing.");
            await apiPost("/api/publishing/publish-one", { name: activeClip.name, title, description, account_ids: selectedAccounts });
            await workspace.refresh();
          }}
          onRecordPosted={async (platform) => {
            await apiPost("/api/posted/mark", { name: activeClip.name, platform, accounts: Object.keys(accountIds) });
            await workspace.refresh();
            setActiveClip(null);
          }}
          onReveal={async () => apiPost("/api/reveal", { name: activeClip.name })}
        />
      ) : null}
      {busy ? <div className="busy-shade"><Loader2 className="spin" size={18} /> Processing request…</div> : null}
    </>
  );
}

function ClipDetail({
  clip, tab, accountIds, configured, onClose, onDelete, onSaveMetadata, onPublish, onRecordPosted, onReveal,
}: {
  clip: Clip;
  tab: "clips" | "publish" | "posted";
  accountIds: Record<string, string>;
  configured: boolean;
  onClose: () => void;
  onDelete: () => void;
  onSaveMetadata: (title: string, description: string) => Promise<void>;
  onPublish: (title: string, description: string, selectedAccounts: Record<string, string>) => Promise<void>;
  onRecordPosted: (platform: string) => Promise<void>;
  onReveal: () => Promise<unknown>;
}) {
  const [title, setTitle] = useState(clip.title || clip.name.replace(/\.mp4$/i, ""));
  const [description, setDescription] = useState(clip.description || clip.caption || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [useZernio, setUseZernio] = useState(false);
  const [browserChoice, setBrowserChoice] = useState("default");
  const selectedAccounts = accountIds;

  const saveMetadata = async () => {
    setBusy(true);
    setMessage("");
    try {
      await onSaveMetadata(title.trim(), description.trim());
      setMessage("AI post copy saved beside the clip.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save post copy.");
    } finally {
      setBusy(false);
    }
  };

  const copyPostField = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(label + " copied. Paste it into the matching field on the platform.");
    } catch {
      setMessage("Clipboard access was blocked. Select and copy the text directly from this panel.");
    }
  };

  const openManualPost = async () => {
    if (selectedPlatforms.length !== 1) throw new Error("Choose one manual platform at a time. The browser stays on that upload so you can review it before preparing the next platform.");
    await onSaveMetadata(title.trim(), description.trim());
    const result = await apiPost<{ platform: string; file: string; file_selected: boolean; title_filled: boolean; description_filled: boolean; ready_for_review: boolean }>("/api/browser/prepare", {
      name: clip.name,
      platform: selectedPlatforms[0],
      title: title.trim(),
      description: (description.trim() || clip.caption || "").trim(),
      browser: browserChoice,
    });
    const filled = [result.title_filled ? "title" : "title needs review", result.description_filled ? "description" : "description needs review"].join(" and ");
    setMessage(result.file_selected
      ? result.platform + " upload prepared for " + result.file + ". The video was selected automatically; " + filled + ". Review the platform page and press its final Publish button yourself."
      : result.platform + " opened, but its upload control was not detected. Select the video manually, then review the metadata and publish yourself.");
  };

  const submitPost = async () => {
    setBusy(true);
    setMessage("");
    try {
      if (!selectedPlatforms.length && !useZernio) throw new Error("Select one or more social platforms, or enable Zernio Auto Posting.");
      if (selectedPlatforms.length) await openManualPost();
      if (useZernio) {
        if (!configured || !Object.keys(accountIds).length) throw new Error("Configure Zernio and connect at least one account in Settings → Publishing.");
        await onPublish(title.trim(), description.trim(), selectedAccounts);
        setMessage((selectedPlatforms.length ? "Manual upload pages opened. " : "") + "Zernio Auto Posting queued this clip. Review and completion are shown by the publishing status.");
      }
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not prepare this post.");
    } finally {
      setBusy(false);
    }
  };

  const recordExternal = async () => {
    const platform = window.prompt("Which platform did you publish this clip to?", "YouTube");
    if (!platform?.trim()) return;
    setBusy(true);
    try {
      await onRecordPosted(platform.trim());
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not record the external post.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="clip-detail-modal" role="dialog" aria-modal="true" aria-label="Clip details">
        <div className="modal-heading">
          <div><div className="eyebrow">CLIP DETAILS</div><h2>{clip.title || clip.name}</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Close details"><X size={18} /></button>
        </div>
        <div className="clip-detail-grid">
          <div className="clip-detail-video"><video src={"/clips/" + encodeURIComponent(clip.name)} controls playsInline /></div>
          <div className="clip-detail-fields">
            {tab === "clips" ? (
              <>
                <div className="clip-detail-meta">
                  <span><strong>Creator</strong>{clip.creator_name || "Main workspace"}</span>
                  <span><strong>Created</strong>{formatDate(clip.mtime)}</span>
                  <span><strong>Size</strong>{clip.size_mb.toFixed(1)} MB</span>
                </div>
                <Button variant="danger" onClick={onDelete}><Trash2 size={14} /> Delete clip</Button>
              </>
            ) : (
              <>
                <label className="field-label">Title<input className="field-input" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={100} /></label>
                <label className="field-label">Description / caption<textarea className="field-input field-textarea" value={description} onChange={(event) => setDescription(event.target.value)} rows={7} maxLength={2200} /></label>
                <div className="clip-detail-meta">
                  <span><strong>Creator</strong>{clip.creator_name || "Main workspace"}</span>
                  <span><strong>Created</strong>{formatDate(clip.mtime)}</span>
                  <span><strong>Size</strong>{clip.size_mb.toFixed(1)} MB</span>
                </div>
                {tab === "publish" ? (
                  <div className="clip-publish-targets">
                    <div className="clip-publish-targets-heading"><strong>Where do you want to post?</strong><span>Prepare one platform at a time</span></div>
                    <div className="clip-publish-targets-options">
                      {manualPostingTargets.map((target) => (
                        <label key={target.id}>
                          <input type="checkbox" checked={selectedPlatforms.includes(target.id)} onChange={() => setSelectedPlatforms((current) => current.includes(target.id) ? current.filter((item) => item !== target.id) : [...current, target.id])} disabled={busy} />
                          <span>{target.name}</span>
                        </label>
                      ))}
                    </div>
                    <label className="field-label">Browser for manual upload
                      <select className="field-input" value={browserChoice} onChange={(event) => setBrowserChoice(event.target.value)} disabled={busy}>
                        <option value="default">Windows default browser</option>
                        <option value="chrome">Google Chrome</option>
                        <option value="edge">Microsoft Edge</option>
                        <option value="firefox">Mozilla Firefox</option>
                      </select>
                    </label>
                    <div className="clip-publish-targets-heading"><strong>Zernio Auto Posting</strong><span>{Object.keys(accountIds).length} connected</span></div>
                    <label className="zernio-destination-option">
                      <input type="checkbox" checked={useZernio} onChange={(event) => setUseZernio(event.target.checked)} disabled={busy || !configured || !Object.keys(accountIds).length} />
                      <span>Also send this clip through Zernio</span>
                    </label>
                    {!configured || !Object.keys(accountIds).length ? <p className="field-help">Optional: configure Zernio and connect accounts in <a href="/settings/publishing">Settings → Publishing</a>. Manual posting above does not need Zernio.</p> : <p className="field-help">Zernio uses only the accounts connected to your Zernio plan. This is separate from manual platform posting.</p>}
                  </div>
                ) : null}
                <div className="clip-detail-actions">
                  <Button onClick={() => void saveMetadata()} disabled={busy || !title.trim()}><Save size={14} /> Save post copy</Button>
                  {tab === "publish" ? <Button onClick={() => void copyPostField(title.trim(), "Title")} disabled={!title.trim()}>Copy title</Button> : null}
                  {tab === "publish" ? <Button onClick={() => void copyPostField(description.trim(), "Description / hashtags")} disabled={!description.trim()}>Copy caption</Button> : null}
                  {tab === "publish" ? <Button variant="primary" onClick={() => void submitPost()} disabled={busy || !title.trim() || (!selectedPlatforms.length && !useZernio)}><Upload size={14} /> Post</Button> : null}
                  {tab === "publish" ? <Button onClick={() => void recordExternal()} disabled={busy}>Mark as published</Button> : null}
                  <Button onClick={() => void onReveal()}><FolderOpen size={14} /> Show video file</Button>
                  <a className="button button-secondary" href={"/clips/" + encodeURIComponent(clip.name.replace(/\.mp4$/i, "")) + ".txt"} target="_blank" rel="noreferrer"><FileText size={14} /> Open AI post copy</a>
                  <Button variant="danger" onClick={onDelete}><Trash2 size={14} /> Delete clip</Button>
                </div>
                <p className="muted-note">Manual Post uses the local browser automation profile to select the clip and fill supported fields. Sign in once in that dedicated browser profile. StreamSnip AI never presses the final Publish button. Prepare one manual platform at a time; Zernio remains a separate optional automated route.</p>
              </>
            )}
            {message ? <p className="inline-feedback">{message}</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function SettingsPage({ workspace, section, themeId, onThemeChange }: {
  workspace: Workspace;
  section: "general" | "ai" | "speech" | "captions" | "publishing";
  themeId: ThemeId;
  onThemeChange: (value: ThemeId) => void;
}) {
  const headings = {
    general: ["GENERAL", "Application settings", "Local storage, performance, and application behavior."],
    ai: ["AI & MODELS", "AI providers", "Choose how StreamSnip scores moments and creates post metadata."],
    speech: ["SPEECH RECOGNITION", "Transcription", "Configure the speech engine and timestamped transcript model."],
    captions: ["VIDEO STYLING", "Caption settings", "Tune the on-video captions, profanity filter, and creator credit."],
    publishing: ["DISTRIBUTION", "Publishing", "Connect Zernio accounts and control how finished clips are published."],
  } as const;
  const [eyebrow, title, description] = headings[section];

  return (
    <>
      <PageHeading eyebrow={eyebrow} title={title} description={description} />
      <div className="settings-layout">
        <nav className="settings-subnav" aria-label="Settings categories">
          <div className="settings-subnav-title">SETTINGS</div>
          <NavLink to="/settings" end className={({ isActive }) => isActive ? "active" : ""}><Settings size={16} /> General</NavLink>
          <NavLink to="/settings/ai" className={({ isActive }) => isActive ? "active" : ""}><Bot size={16} /> AI providers</NavLink>
          <NavLink to="/settings/speech" className={({ isActive }) => isActive ? "active" : ""}><Activity size={16} /> Transcription</NavLink>
          <NavLink to="/settings/captions" className={({ isActive }) => isActive ? "active" : ""}><FileText size={16} /> Captions</NavLink>
          <NavLink to="/settings/publishing" className={({ isActive }) => isActive ? "active" : ""}><Upload size={16} /> Publishing</NavLink>
          <div className="settings-subnav-foot">
            <span className={workspace.saving ? "saving-dot busy" : workspace.saveError ? "saving-dot error" : "saving-dot"} />
            <span>{workspace.saving ? "Saving changes…" : workspace.saveError ? "Save failed" : workspace.savedAt ? "Saved to this device" : "Local settings"}</span>
          </div>
        </nav>
        <div className="settings-main">
          {section === "general" ? <GeneralSettings workspace={workspace} themeId={themeId} onThemeChange={onThemeChange} /> : null}
          {section === "ai" ? <AISettingsPage workspace={workspace} /> : null}
          {section === "speech" ? <SpeechSettings workspace={workspace} /> : null}
          {section === "captions" ? <CaptionSettings workspace={workspace} /> : null}
          {section === "publishing" ? <PublishingSettings key={JSON.stringify([workspace.publishing.providers?.zernio?.accounts, workspace.publishing.accounts, workspace.publishing.auto_post, workspace.publishing.schedule_minutes, workspace.publishing.visibility])} workspace={workspace} /> : null}
        </div>
      </div>
    </>
  );
}

function GeneralSettings({ workspace, themeId, onThemeChange }: {
  workspace: Workspace;
  themeId: ThemeId;
  onThemeChange: (value: ThemeId) => void;
}) {
  const settings = workspace.settings || {};
  const [browseBusy, setBrowseBusy] = useState("");

  const browseFolder = async (key: "rec_dir" | "out_dir") => {
    setBrowseBusy(key);
    try {
      const result = await apiPost<{ path: string }>("/api/browse_folder");
      if (result.path) workspace.updateSettings({ [key]: result.path });
    } catch (reason) {
      notifyApp("error", "Folder picker failed", reason instanceof Error ? reason.message : "Could not open the folder picker.");
    } finally {
      setBrowseBusy("");
    }
  };

  return (
    <>
      <section className="settings-section-card appearance-settings-card">
        <div className="settings-section-heading">
          <div><h3>Workspace appearance</h3><p>Choose a complete colour palette for the whole studio. Your selection is remembered on this device.</p></div>
          <Palette size={19} />
        </div>
        <ThemeOptions value={themeId} onChange={onThemeChange} />
        <p className="field-help">Themes change the workspace surfaces, contrast, and accent colour. They do not change your clips or capture settings.</p>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Storage folders</h3><p>Choose where original recordings and rendered clips are saved.</p></div><Folder size={19} /></div>
        <label className="field-label">Recording folder</label>
        <div className="folder-field-row"><input className="field-input" aria-label="Recording folder path" value={asString(settings.rec_dir)} onChange={(event) => workspace.updateSettings({ rec_dir: event.target.value })} placeholder="Default application data folder" disabled={workspace.state.running} /><Button onClick={() => void browseFolder("rec_dir")} disabled={workspace.state.running || !!browseBusy}>{browseBusy === "rec_dir" ? <Loader2 className="spin" size={14} /> : <FolderOpen size={14} />} Browse</Button></div>
        <label className="field-label">Output / clips folder</label>
        <div className="folder-field-row"><input className="field-input" aria-label="Output and clips folder path" value={asString(settings.out_dir)} onChange={(event) => workspace.updateSettings({ out_dir: event.target.value })} placeholder="Default application data folder" disabled={workspace.state.running} /><Button onClick={() => void browseFolder("out_dir")} disabled={workspace.state.running || !!browseBusy}>{browseBusy === "out_dir" ? <Loader2 className="spin" size={14} /> : <FolderOpen size={14} />} Browse</Button></div>
        <p className="field-help">Stop clipping before changing storage locations. Creator-specific recordings and VOD inboxes remain managed by their own monitor folders.</p>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Processing hardware</h3><p>Hardware selection is automatic and follows the current engine behavior.</p></div><Cpu size={19} /></div>
        <div className="settings-readonly-row"><div><strong>Automatic GPU acceleration</strong><small>NVIDIA CUDA for speech and NVENC for video when supported.</small></div><StatusPill tone="good">Automatic</StatusPill></div>
        <div className="settings-readonly-row"><div><strong>CPU fallback</strong><small>Used by the engine only when a compatible GPU is unavailable.</small></div><StatusPill>Available</StatusPill></div>
        <label className="field-label">Live capture bitrate target <strong className="field-value">{asNumber(settings.capture_bitrate_kbps, 6000).toLocaleString()} kbps</strong></label>
        <input className="wide-range" aria-label="Live capture bitrate target in kilobits per second" type="range" min="6000" max="50000" step="1000" value={asNumber(settings.capture_bitrate_kbps, 6000)} onChange={(event) => workspace.updateSettings({ capture_bitrate_kbps: Number(event.target.value) })} />
        <div className="range-ends"><span>6,000 kbps</span><span>50,000 kbps</span></div>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Application state</h3><p>Connection and settings are stored locally on this computer.</p></div><ShieldCheck size={19} /></div>
        <div className="settings-readonly-row"><div><strong>Local processing engine</strong><small>Python capture and FFmpeg render pipeline</small></div><StatusPill tone={workspace.connected ? "good" : "warning"}>{workspace.connected ? "Connected" : "Offline"}</StatusPill></div>
        <div className="settings-readonly-row"><div><strong>Settings autosave</strong><small>{workspace.savedAt ? "Last saved " + formatDate(workspace.savedAt / 1000) : "Changes are saved automatically."}</small></div><StatusPill tone={workspace.saveError ? "bad" : workspace.saving ? "warning" : "good"}>{workspace.saveError ? "Error" : workspace.saving ? "Saving" : "Enabled"}</StatusPill></div>
        {workspace.saveError ? <p className="inline-feedback error">{workspace.saveError}</p> : null}
      </section>
    </>
  );
}

function AISettingsPage({ workspace }: { workspace: Workspace }) {
  const { ai } = workspace;
  const [geminiKey, setGeminiKey] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [customKey, setCustomKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  const update = workspace.updateAI;
  const extra = () => {
    const payload: Record<string, string | boolean> = {};
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (hfToken.trim()) payload.huggingface_token = hfToken.trim();
    if (customKey.trim()) payload.custom_api_key = customKey.trim();
    return payload;
  };

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await workspace.saveAI(extra());
      setGeminiKey("");
      setHfToken("");
      setCustomKey("");
      setMessage("AI provider settings saved locally. Credential values are not sent back to the browser.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save AI settings.");
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setMessage("Testing provider connection…");
    try {
      const result = await workspace.testAI(extra());
      setMessage(result.message);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "AI provider test failed.");
    } finally {
      setBusy(false);
    }
  };

  const clearSecret = async (flag: string, label: string) => {
    if (!window.confirm("Clear the saved " + label + " from this computer?")) return;
    setBusy(true);
    setMessage("");
    try {
      const updated = await apiPost("/api/ai/settings", {
        provider: ai.provider,
        ollama_url: ai.ollama_url,
        ollama_model: ai.ollama_model,
        gemini_model: ai.gemini_model,
        huggingface_model: ai.huggingface_model,
        custom_api_base: ai.custom_api_base,
        custom_api_model: ai.custom_api_model,
        metadata_copy_enabled: ai.metadata_copy_enabled,
        [flag]: true,
      });
      workspace.updateAI(updated as Partial<typeof ai>);
      if (flag === "clear_gemini_key") setGeminiKey("");
      if (flag === "clear_hf_token") setHfToken("");
      if (flag === "clear_custom_api_key") setCustomKey("");
      setMessage(label + " removed from local settings.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not clear the credential.");
    } finally {
      setBusy(false);
    }
  };

  const detectModels = async () => {
    setBusy(true);
    setMessage("Checking installed Ollama models…");
    try {
      const result = await workspace.detectOllama();
      setOllamaModels(result.models);
      if (result.models.length && !result.models.includes(ai.ollama_model)) update({ ollama_model: result.models[0] });
      setMessage(result.models.length ? result.models.length + " installed model(s) found." : "Ollama responded, but no local models were found.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not reach Ollama.");
    } finally {
      setBusy(false);
    }
  };

  const providers = [
    { id: "hooks", name: "Hook words", detail: "Free · Offline · Built-in", icon: Zap },
    { id: "ollama", name: "Ollama local AI", detail: "Local model · Private", icon: Cpu },
    { id: "gemini", name: "Gemini API", detail: "Hosted · Uses Google quota", icon: Sparkles },
    { id: "huggingface", name: "Hugging Face", detail: "Hosted · Provider credits", icon: Bot },
    { id: "custom", name: "Custom API", detail: "OpenAI-compatible endpoint", icon: Settings },
  ];

  return (
    <>
      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Highlight analysis provider</h3><p>This provider scores candidate moments and, when supported, writes the title and post description.</p></div><Bot size={19} /></div>
        <div className="provider-choice-grid">
          {providers.map((provider) => {
            const Icon = provider.icon;
            return (
              <button key={provider.id} className={ai.provider === provider.id ? "provider-choice active" : "provider-choice"} onClick={() => update({ provider: provider.id })}>
                <Icon size={19} /><span><strong>{provider.name}</strong><small>{provider.detail}</small></span>{ai.provider === provider.id ? <CheckCircle2 size={17} /> : null}
              </button>
            );
          })}
        </div>
        <div className="ai-provider-panel">
          {ai.provider === "hooks" ? (
            <div className="provider-explanation"><Zap size={20} /><div><strong>Built-in hook-word detection</strong><p>Runs locally and combines your custom phrases with audio energy and speech-rate signals. It does not call a hosted text model, so titles and descriptions use transcript-based fallback copy.</p></div></div>
          ) : null}
          {ai.provider === "ollama" ? (
            <>
              <label className="field-label">Ollama address<input className="field-input" value={ai.ollama_url} onChange={(event) => update({ ollama_url: event.target.value })} placeholder="http://127.0.0.1:11434" /></label>
              <div className="field-label-row"><label className="field-label">Installed model</label><Button onClick={() => void detectModels()} disabled={busy}><RefreshCw size={14} /> Detect models</Button></div>
              <select className="field-select" value={ai.ollama_model} onChange={(event) => update({ ollama_model: event.target.value })}>
                <option value="">Choose a detected model</option>
                {[...new Set([ai.ollama_model, ...ollamaModels].filter(Boolean))].map((model) => <option key={model}>{model}</option>)}
              </select>
              <p className="field-help">Install Ollama and pull a model before testing. Example: <code>ollama pull qwen3.5:9b</code>.</p>
            </>
          ) : null}
          {ai.provider === "gemini" ? (
            <>
              <div className="field-label-row"><label className="field-label">Gemini API key</label><StatusPill tone={ai.gemini_key_set ? "good" : "warning"}>{ai.gemini_key_set ? "Saved locally" : "Not saved"}</StatusPill></div>
              <input className="field-input" type="password" autoComplete="new-password" value={geminiKey} onChange={(event) => setGeminiKey(event.target.value)} placeholder={ai.gemini_key_set ? "Enter a new key to replace the saved key" : "Paste your Gemini API key"} />
              <label className="field-label">Preferred Gemini model<input className="field-input" value={ai.gemini_model} onChange={(event) => update({ gemini_model: event.target.value })} placeholder="gemini-3.8-flash" /></label>
              <div className="credential-actions"><Button variant="quiet" onClick={() => void clearSecret("clear_gemini_key", "Gemini API key")} disabled={!ai.gemini_key_set || busy}><Trash2 size={14} /> Clear saved key</Button></div>
            </>
          ) : null}
          {ai.provider === "huggingface" ? (
            <>
              <label className="field-label">Hugging Face model<input className="field-input" value={ai.huggingface_model} onChange={(event) => update({ huggingface_model: event.target.value })} placeholder="deepseek-ai/DeepSeek-V4.1-Flash:fastest" /></label>
              <div className="field-label-row"><label className="field-label">Access token</label><StatusPill tone={ai.huggingface_token_set ? "good" : "warning"}>{ai.huggingface_token_set ? "Saved locally" : "Not saved"}</StatusPill></div>
              <input className="field-input" type="password" autoComplete="new-password" value={hfToken} onChange={(event) => setHfToken(event.target.value)} placeholder={ai.huggingface_token_set ? "Enter a new token to replace the saved token" : "hf_… token with Inference Providers access"} />
              <div className="credential-actions"><Button variant="quiet" onClick={() => void clearSecret("clear_hf_token", "Hugging Face token")} disabled={!ai.huggingface_token_set || busy}><Trash2 size={14} /> Clear saved token</Button></div>
              <p className="field-help">The token may also be used for authenticated Whisper model downloads. Use an account with the required Inference Providers access and available credits.</p>
            </>
          ) : null}
          {ai.provider === "custom" ? (
            <>
              <label className="field-label">OpenAI-compatible base URL<input className="field-input" value={ai.custom_api_base} onChange={(event) => update({ custom_api_base: event.target.value })} placeholder="https://provider.example/v1" /></label>
              <label className="field-label">Model ID<input className="field-input" value={ai.custom_api_model} onChange={(event) => update({ custom_api_model: event.target.value })} placeholder="Exact provider model ID" /></label>
              <div className="field-label-row"><label className="field-label">API key</label><StatusPill tone={ai.custom_api_key_set ? "good" : "neutral"}>{ai.custom_api_key_set ? "Saved locally" : "Optional for local/free endpoints"}</StatusPill></div>
              <input className="field-input" type="password" autoComplete="new-password" value={customKey} onChange={(event) => setCustomKey(event.target.value)} placeholder="Enter a new key if the endpoint requires one" />
              <div className="credential-actions"><Button variant="quiet" onClick={() => void clearSecret("clear_custom_api_key", "custom API key")} disabled={!ai.custom_api_key_set || busy}><Trash2 size={14} /> Clear saved key</Button></div>
            </>
          ) : null}
        </div>
        <div className="settings-save-row"><div><Button variant="primary" onClick={() => void save()} disabled={busy}><Save size={15} /> Save AI settings</Button><Button onClick={() => void test()} disabled={busy || ai.provider === "hooks"}><Activity size={15} /> Test connection</Button></div><span>{message}</span></div>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Generated clip metadata</h3><p>Titles and descriptions are generated using the selected text-capable provider. Hook-word mode uses transcript fallback copy.</p></div><FileText size={19} /></div>
        <div className="settings-readonly-row"><div><strong>TXT post metadata</strong><small>Always enabled. Each clip receives a title and description sidecar for review and publishing.</small></div><StatusPill tone="good">Always on</StatusPill></div>
        <p className="field-help">When a hosted provider is selected, transcript text is sent to that provider for analysis and metadata generation. The API key itself remains stored by the local backend and is never returned to this page.</p>
      </section>
    </>
  );
}

function SpeechSettings({ workspace }: { workspace: Workspace }) {
  const settings = workspace.settings || {};
  const models = ["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"];
  const update = workspace.updateSettings;
  const custom = asString(settings.transcriber_provider) === "custom-command";

  return (
    <>
      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Transcription engine</h3><p>Speech recognition is separate from AI highlight scoring. It creates the timestamped word transcript used by the editor.</p></div><Activity size={19} /></div>
        <label className="field-label">Transcriber</label>
        <select className="field-select" value={asString(settings.transcriber_provider, "faster-whisper")} onChange={(event) => update({ transcriber_provider: event.target.value })}>
          <option value="faster-whisper">Faster-Whisper · local</option>
          <option value="custom-command">Custom command / CLI</option>
        </select>
        {!custom ? (
          <>
            <label className="field-label">Speech model</label>
            <select className="field-select" value={asString(settings.model, "distil-large-v3")} onChange={(event) => update({ model: event.target.value })}>
              {models.map((model) => <option key={model} value={model}>{model}{model === "distil-large-v3" ? " · fast, English" : model === "large-v3-turbo" ? " · fast, multilingual" : model === "large-v3" ? " · highest accuracy" : ""}</option>)}
            </select>
            <div className="model-info-grid">
              <div><strong>distil-large-v3</strong><span>Fast English transcription</span></div>
              <div><strong>large-v3-turbo</strong><span>Fast multilingual transcription</span></div>
              <div><strong>large-v3</strong><span>Higher accuracy, heavier compute</span></div>
            </div>
          </>
        ) : (
          <>
            <label className="field-label">Custom transcriber command<input className="field-input" value={asString(settings.transcriber_command)} onChange={(event) => update({ transcriber_command: event.target.value })} placeholder={'whisper-cli -f "{input}" -oj -of "{output}"'} /></label>
            <label className="field-label">Language placeholder<input className="field-input" value={asString(settings.transcriber_language, "auto")} onChange={(event) => update({ transcriber_language: event.target.value })} maxLength={20} placeholder="auto" /></label>
            <div className="help-note"><strong>Command placeholders</strong><p><code>{"{input}"}</code> is the source audio/video file, <code>{"{output}"}</code> is the JSON destination, and <code>{"{language}"}</code> is the selected language. Return timestamped word data in JSON or stdout. Do not paste credentials into this command field; use environment variables or your own secure local configuration.</p></div>
          </>
        )}
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Runtime behavior</h3><p>StreamSnip chooses supported hardware automatically.</p></div><Cpu size={19} /></div>
        <div className="settings-readonly-row"><div><strong>Compute device</strong><small>CUDA when a supported NVIDIA GPU is detected; NVENC when FFmpeg supports it.</small></div><StatusPill tone="good">Automatic</StatusPill></div>
        <div className="settings-readonly-row"><div><strong>Source handling</strong><small>Live capture and VOD processing remain managed by the existing Python engine.</small></div><StatusPill>Engine managed</StatusPill></div>
        <p className="field-help">The local engine reports transcription and rendering progress in Live Studio and Activity. Provider credentials for custom transcription remain under your own executable's control.</p>
      </section>
    </>
  );
}

function CaptionSettings({ workspace }: { workspace: Workspace }) {
  const settings = workspace.settings || {};
  const update = workspace.updateSettings;
  const colorChoices = [
    ["Yellow", "#FFE600"], ["Green", "#00D084"], ["Cyan", "#00D5F2"], ["Orange", "#FF8A35"], ["Pink", "#FF40D4"],
  ];
  const custom = asBool(settings.subtitle_custom);

  return (
    <>
      <section className="settings-section-card caption-studio-card">
        <div className="settings-section-heading"><div><h3>Caption preview</h3><p>Preview changes as you adjust the base style and custom subtitle settings.</p></div><FileText size={19} /></div>
        <div className="caption-preview-layout">
          <div className="caption-phone" style={{ aspectRatio: ({ "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1", "4:5": "4 / 5" } as Record<string, string>)[asString(settings.output_format, "9:16")] || "9 / 16" }}>
            <div className={"caption-phone-visual " + (asString(settings.layout).startsWith("Facecam") ? "facecam" : "")}>
              {asString(settings.layout).startsWith("Facecam") ? <><span>FACECAM</span><span>GAMEPLAY</span></> : <Video size={23} />}
            </div>
            <div className="caption-preview-text" style={{
              color: custom ? asString(settings.subtitle_text_color, "#FFFFFF") : "#FFFFFF",
              fontFamily: custom ? "Arial Black, sans-serif" : asString(settings.font, "Impact"),
              fontSize: (asNumber(custom ? settings.subtitle_font_size : settings.caption_size, 100) / 100 * 15) + "px",
              bottom: custom && asString(settings.subtitle_position) === "Top" ? "auto" : custom && asString(settings.subtitle_position) === "Center" ? "50%" : "12%",
              top: custom && asString(settings.subtitle_position) === "Top" ? "12%" : "auto",
            }}>
              <span>THAT WAS</span> <b style={{ color: colorChoices.find((item) => item[0] === asString(settings.color, "Yellow"))?.[1] || "#FFE600" }}>INSANE</b>
            </div>
          </div>
          <div className="caption-preview-info"><strong>Live style preview</strong><p>This is a visual guide only. Actual word timing and subtitle rendering are handled by the existing FFmpeg subtitle pipeline.</p><div className="caption-preview-tags"><span>{asString(settings.font, "Impact")}</span><span>{asString(settings.position, "Lower third")}</span><span>{asNumber(settings.words_per_line, 3)} words / line</span></div></div>
        </div>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Base caption style</h3><p>Controls the animated word highlight used by the existing caption renderer.</p></div><SlidersHorizontal size={19} /></div>
        <label className="field-label">Highlight color</label>
        <div className="caption-color-options">
          {colorChoices.map(([name, color]) => <button key={name} className={asString(settings.color, "Yellow") === name ? "active" : ""} onClick={() => update({ color: name })} title={name}><i style={{ background: color }} /><span>{name}</span>{asString(settings.color, "Yellow") === name ? <Check size={13} /> : null}</button>)}
        </div>
        <label className="field-label">Caption position</label>
        <div className="segmented-options">
          {["Low", "Lower third", "Middle"].map((position) => <button key={position} className={asString(settings.position, "Lower third") === position ? "active" : ""} onClick={() => update({ position })}>{position}</button>)}
        </div>
        <ValueSlider label="Words per line" value={asNumber(settings.words_per_line, 3)} min={1} max={4} suffix="" onChange={(value) => update({ words_per_line: Math.round(value) })} />
        <ValueSlider label="Caption size" value={asNumber(settings.caption_size, 100)} min={60} max={150} suffix="%" onChange={(value) => update({ caption_size: Math.round(value) })} />
        <label className="field-label">Font family<input className="field-input" list="streamsnip-font-list" value={asString(settings.font, "Impact")} onChange={(event) => update({ font: event.target.value })} /></label>
        <datalist id="streamsnip-font-list"><option value="Impact" /><option value="Arial Black" /><option value="Segoe UI Black" /><option value="Bahnschrift" /><option value="Franklin Gothic Heavy" /><option value="Verdana" /></datalist>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Advanced subtitle styling</h3><p>Enable this only when you want to override server-default subtitle styling.</p></div><label className="switch-control"><input type="checkbox" checked={custom} onChange={(event) => update({ subtitle_custom: event.target.checked })} /><span /></label></div>
        {custom ? (
          <>
            <div className="two-fields">
              <label className="field-label">Subtitle mode<select className="field-select" value={asString(settings.subtitle_mode, "Karaoke")} onChange={(event) => update({ subtitle_mode: event.target.value })}><option>Karaoke</option><option>Classic</option></select></label>
              <label className="field-label">Style preset<select className="field-select" value={asString(settings.subtitle_style, "Classic")} onChange={(event) => update({ subtitle_style: event.target.value })}>{["Classic", "Hormozi", "Neon", "MrBeast", "Minimal", "Fire"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="field-label">Text color<input className="color-input" type="color" value={asString(settings.subtitle_text_color, "#FFFFFF")} onChange={(event) => update({ subtitle_text_color: event.target.value.toUpperCase() })} /></label>
              <label className="field-label">Stroke color<input className="color-input" type="color" value={asString(settings.subtitle_stroke_color, "#000000")} onChange={(event) => update({ subtitle_stroke_color: event.target.value.toUpperCase() })} /></label>
              <label className="field-label">Subtitle position<select className="field-select" value={asString(settings.subtitle_position, "Bottom")} onChange={(event) => update({ subtitle_position: event.target.value })}><option>Top</option><option>Center</option><option>Bottom</option></select></label>
              <label className="field-label">Text alignment<select className="field-select" value={asString(settings.subtitle_alignment, "Center")} onChange={(event) => update({ subtitle_alignment: event.target.value })}><option>Left</option><option>Center</option></select></label>
            </div>
            <ValueSlider label="Subtitle font size" value={asNumber(settings.subtitle_font_size, 100)} min={60} max={180} suffix="%" onChange={(value) => update({ subtitle_font_size: Math.round(value) })} />
            <ValueSlider label="Vertical nudge" value={asNumber(settings.subtitle_nudge, 0)} min={-400} max={400} suffix=" px" onChange={(value) => update({ subtitle_nudge: Math.round(value) })} />
          </>
        ) : <p className="field-help">Advanced subtitle fields are currently off. Turn them on to customize mode, style, size, color, stroke, vertical placement, and alignment.</p>}
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Profanity censor</h3><p>Filter rendered audio, captions, and generated post text.</p></div><label className="switch-control"><input type="checkbox" checked={settings.profanity_filter_enabled !== false} onChange={(event) => update({ profanity_filter_enabled: event.target.checked })} /><span /></label></div>
        <label className="field-label">Additional words or phrases<textarea className="field-input field-textarea" rows={4} value={asString(settings.profanity_filter_words)} onChange={(event) => update({ profanity_filter_words: event.target.value.slice(0, 4000) })} placeholder="One word or phrase per line" /></label>
        <p className="field-help">Censoring does not remove a clip, lower its score, or block publishing. Existing clips must be rendered again to apply changed censor settings. Speech recognition can miss words, so review each clip before posting.</p>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Creator credit</h3><p>Choose the tag written into the clip metadata and whether the credit appears on the video.</p></div><BadgeCheck size={19} /></div>
        <label className="field-label">Creator tag<input className="field-input" value={asString(settings.streamer_tag)} onChange={(event) => update({ streamer_tag: event.target.value })} placeholder="Leave blank to detect from the stream URL" maxLength={80} /></label>
        <label className="switch-row"><span><strong>Show credit on the video</strong><small>Render the creator handle on the clip.</small></span><label className="switch-control"><input type="checkbox" checked={settings.show_tag_video !== false} onChange={(event) => update({ show_tag_video: event.target.checked })} /><span /></label></label>
      </section>
    </>
  );
}

function PublishingSettings({ workspace }: { workspace: Workspace }) {
  const status = workspace.publishing.providers?.zernio || workspace.publishing;
  const autoLoaded = useRef(false);
  const [apiKey, setApiKey] = useState("");
  const [selected, setSelected] = useState<Record<string, string>>(status.accounts || {});
  const [autoPost, setAutoPost] = useState(!!status.auto_post);
  const [delay, setDelay] = useState(asNumber(status.schedule_minutes, 0));
  const [visibility, setVisibility] = useState(asString(status.visibility, "public"));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const groups = useMemo(() => workspace.accounts.reduce<Record<string, PublishingAccount[]>>((all, account) => {
    const platform = asString(account.platform, "other").toLowerCase();
    if (!all[platform]) all[platform] = [];
    all[platform].push(account);
    return all;
  }, {}), [workspace.accounts]);

  const fetchAccounts = workspace.fetchAccounts;
  useEffect(() => {
    if (status.configured && !autoLoaded.current) {
      autoLoaded.current = true;
      void fetchAccounts().catch(() => undefined);
    }
  }, [status.configured, fetchAccounts]);

  const loadAccounts = async () => {
    setBusy(true);
    setMessage("Loading connected social accounts…");
    try {
      const result = await workspace.fetchAccounts();
      setMessage(result.length ? result.length + " connected account(s) loaded. Select one account per platform." : "No connected social accounts were returned.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not load publishing accounts.");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await workspace.savePublishing({
        api_key: apiKey.trim(),
        account_ids: selected,
        auto_post: autoPost,
        schedule_minutes: delay,
        visibility,
      });
      setApiKey("");
      setMessage("Publishing settings saved locally.");
      await loadAccounts();
      await workspace.refreshPublishing();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save publishing settings.");
    } finally {
      setBusy(false);
    }
  };

  const platformNames: Record<string, string> = {
    twitter: "X / Twitter", instagram: "Instagram", facebook: "Facebook", linkedin: "LinkedIn",
    tiktok: "TikTok", youtube: "YouTube", pinterest: "Pinterest", reddit: "Reddit",
    bluesky: "Bluesky", threads: "Threads", googlebusiness: "Google Business",
  };

  return (
    <>
      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Zernio connection</h3><p>Publishing uses the connected Zernio service. Your API key is saved by the local engine and is never displayed again.</p></div><Upload size={19} /></div>
        <div className="settings-readonly-row"><div><strong>Connection status</strong><small>{status.available === false ? "Publishing adapter is unavailable." : "Zernio integration status from the local backend."}</small></div><StatusPill tone={status.configured ? "good" : status.available === false ? "bad" : "warning"}>{status.configured ? "API key saved" : status.available === false ? "Unavailable" : "Not configured"}</StatusPill></div>
        <label className="field-label">Zernio API key</label>
        <input className="field-input" aria-label="Zernio API key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={status.configured ? "Enter a new key to replace the saved key" : "Paste your Zernio API key"} />
        <p className="field-help">Leave this blank to keep the already-saved key. The frontend receives only a configured/not-configured flag, never the stored secret.</p>
        <div className="settings-save-row">
          <div><Button variant="primary" onClick={() => void save()} disabled={busy || (!status.configured && !apiKey.trim())}><Save size={15} /> Save publishing settings</Button><Button onClick={() => void loadAccounts()} disabled={busy || !status.configured}><RefreshCw size={14} /> Identify accounts</Button></div>
          <span>{message}</span>
        </div>
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Connected accounts</h3><p>Select the account StreamSnip should use for each supported platform.</p></div><BadgeCheck size={19} /></div>
        {Object.keys(groups).length ? (
          <div className="publishing-account-grid">
            {Object.entries(groups).map(([platform, items]) => (
              <div className="publishing-platform" key={platform}>
                <strong>{platformNames[platform] || platform}</strong>
                {items.map((account) => (
                  <label key={account.id} className="publishing-account-option">
                    <input type="radio" name={"account-" + platform} checked={selected[platform] === account.id} onChange={() => setSelected((current) => ({ ...current, [platform]: account.id }))} />
                    <span>{account.name || account.username || account.id}</span>
                  </label>
                ))}
              </div>
            ))}
          </div>
        ) : <EmptyState icon={Upload} title="No connected accounts loaded" body="Save the Zernio key, then identify accounts to select the channels you want to publish to." />}
        {Object.keys(selected).length ? <Button onClick={() => setSelected({})} variant="quiet"><X size={14} /> Clear account selection</Button> : null}
      </section>

      <section className="settings-section-card">
        <div className="settings-section-heading"><div><h3>Publishing behavior</h3><p>Choose whether clips are uploaded automatically and which YouTube visibility to use.</p></div><Settings size={19} /></div>
        <label className="switch-row"><span><strong>Auto-post new clips</strong><small>Automatically submit newly rendered clips to the selected accounts.</small></span><label className="switch-control"><input type="checkbox" checked={autoPost} onChange={(event) => setAutoPost(event.target.checked)} /><span /></label></label>
        {autoPost ? <div className="warning-note"><AlertCircle size={14} /> Auto-post can publish every qualifying clip without a manual review step. Review your selected accounts before enabling it.</div> : null}
        <label className="field-label">Schedule delay (minutes)<input className="field-input" type="number" min="0" max="10080" value={delay} onChange={(event) => setDelay(clamp(Number(event.target.value), 0, 10080))} /></label>
        <label className="field-label">YouTube visibility<select className="field-select" value={visibility} onChange={(event) => setVisibility(event.target.value)}><option value="public">Public</option><option value="unlisted">Unlisted</option><option value="private">Private</option></select></label>
        <p className="field-help">The schedule delay and visibility are passed to the existing publishing adapter. Actual account capabilities are determined by Zernio.</p>
        <div className="settings-save-row"><div><Button variant="primary" onClick={() => void save()} disabled={busy || !status.configured}><Save size={15} /> Save publishing behavior</Button></div><span>{message}</span></div>
      </section>
    </>
  );
}

function WordsPage({ workspace }: { workspace: Workspace }) {
  const [text, setText] = useState(workspace.words.text);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const result = await workspace.saveWords(text);
      setMessage("Saved " + result.entries + " custom phrase(s). Updates apply to the next analysis chunk.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save hype words.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeading eyebrow="HIGHLIGHT SIGNALS" title="Hype words" description="Add the phrases your streamers actually use. Custom phrases influence local hook-word analysis." action={<Button variant="primary" onClick={() => void save()} disabled={saving}><Save size={15} /> Save phrases</Button>} />
      <div className="words-layout">
        <section className="panel-card words-editor-card">
          <div className="panel-heading"><div><div className="eyebrow">CUSTOM DICTIONARY</div><h3>Your words and phrases</h3></div><span className="count-badge">{text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")).length} entries</span></div>
          <p className="panel-description">One word or phrase per line. Add a weight after a pipe, such as <code>no chance | 3</code>. Lines beginning with <code>#</code> are comments. Default weight is 2.</p>
          <textarea className="words-textarea" aria-label="Custom hype words and phrases, one per line" spellCheck={false} value={text} onChange={(event) => setText(event.target.value)} placeholder={"oh my days\nno chance | 3\nhe actually did it"} />
          <div className="settings-save-row"><div><Button variant="primary" onClick={() => void save()} disabled={saving}><Save size={15} /> {saving ? "Saving…" : "Save hype words"}</Button></div><span>{message}</span></div>
        </section>
        <aside className="panel-card builtin-words-card">
          <div className="eyebrow">BUILT-IN DICTIONARY</div><h3>Default reactions</h3>
          <p className="panel-description">The engine also includes a built-in list of common reactions and emphasis phrases.</p>
          <div className="builtin-chip-cloud">{workspace.words.words.slice(0, 120).map((word) => <span key={word}>{word}</span>)}</div>
          {workspace.words.phrases.length ? <><h4>Phrase patterns</h4><div className="builtin-chip-cloud">{workspace.words.phrases.slice(0, 60).map((phrase) => <span key={phrase}>{phrase}</span>)}</div></> : null}
        </aside>
      </div>
    </>
  );
}

function ActivityPage({ workspace }: { workspace: Workspace }) {
  const [pausedLogs, setPausedLogs] = useState<LogEntry[] | null>(null);
  const [filter, setFilter] = useState<"all" | "problems">("all");
  const logs = pausedLogs === null ? workspace.logs : pausedLogs;
  const isProblem = (entry: LogEntry) => /\b(error|failed|failure|exception|traceback|critical|denied|timeout|timed out|could not|unable to|not found|invalid|unavailable)\b/i.test(entry.m);
  const problemCount = logs.filter(isProblem).length;
  const visibleLogs = filter === "problems" ? logs.filter(isProblem) : logs;

  return (
    <>
      <PageHeading eyebrow="SYSTEM DIAGNOSTICS" title="Activity" description="A live diagnostic timeline for UI actions, capture, transcription, AI, rendering, creator monitors, and publishing." action={<a className="button button-secondary" href="/api/log/download" download="streamsnip.log"><Download size={15} /> Download diagnostic log</a>} />
      <section className="panel-card activity-page-card">
        <div className="panel-heading">
          <div><div className="eyebrow">ENGINE TIMELINE</div><h3>Live activity log</h3><p>{problemCount} problem event(s) in the current log window. Client actions, backend validation errors, exceptions, capture failures and publishing outcomes are included.</p></div>
          <div className="activity-toolbar">
            <StatusPill tone={problemCount ? "bad" : pausedLogs === null ? "good" : "warning"}>{problemCount ? problemCount + " problem(s)" : pausedLogs === null ? "Live updates" : "Paused snapshot"}</StatusPill>
            <Button variant={filter === "all" ? "primary" : "secondary"} onClick={() => setFilter("all")}>All events</Button>
            <Button variant={filter === "problems" ? "danger" : "secondary"} onClick={() => setFilter("problems")}>Problems only</Button>
            <Button onClick={() => setPausedLogs((current) => current === null ? [...workspace.logs] : null)}>{pausedLogs === null ? <PauseIcon /> : <Play size={14} />} {pausedLogs === null ? "Pause" : "Resume"}</Button>
            <Button onClick={() => setPausedLogs([])}><X size={14} /> Clear view</Button>
          </div>
        </div>
        {visibleLogs.length ? (
          <div className="activity-event-list">
            {[...visibleLogs].reverse().map((entry) => {
              const message = entry.m.toLowerCase();
              const tone = isProblem(entry) ? "error" : message.includes("clip ready") || message.includes("complete") || message.includes("ui info") ? "success" : "normal";
              return <div key={entry.id} className={"activity-event " + tone}><span className="activity-event-icon"><Activity size={15} /></span><time>{entry.t}</time><p>{entry.m}</p><small>#{entry.id}</small></div>;
            })}
          </div>
        ) : <EmptyState icon={filter === "problems" ? CheckCircle2 : Activity} title={filter === "problems" ? "No problems in the current log" : "No events in this view"} body={filter === "problems" ? "No errors have been reported in the events currently loaded." : "The local engine will report events here when actions run, streams are processed, or a problem occurs."} />}
      </section>
    </>
  );
}

function PauseIcon() {
  return <span className="pause-glyph">Ⅱ</span>;
}

function HelpPage() {
  const items = [
    ["Start clipping a live stream", "Open Live Studio, choose Live stream, paste a Twitch or YouTube URL, choose the highlight provider and score threshold, then select Start clipping. The engine reports the actual capture and processing stages in the pipeline."],
    ["Process a local VOD", "Choose Video / VOD in Live Studio, browse to a supported video file, and start clipping. The original VOD is preserved; rendered clips are written to your configured clips folder."],
    ["Configure video layouts", "Open Layout Studio. Choose Facecam + game, Blur background, Fill, or Selected crop. Capture a frame from your source, drag the highlighted area, resize it with the corner handle, and save the layout."],
    ["Understand AI and transcription", "Speech recognition creates the timestamped transcript. The selected highlight provider scores transcript moments separately. Hook words and Ollama are local; Gemini, Hugging Face, and custom hosted APIs can receive transcript text."],
    ["Review and publish clips", "Open Clips to preview a video and inspect its TXT metadata. Publishing through Zernio is queued separately; a clip moves to Published only when the backend receives confirmation. You can also record a post published outside StreamSnip."],
    ["Manage creator monitors", "Add a Twitch or YouTube creator from Live Studio. Each monitor has separate live clips, a recorded-VOD inbox, and VOD output folders. Start the folder watcher before placing VOD files into the inbox."],
  ];
  return (
    <>
      <PageHeading eyebrow="DOCUMENTATION" title="Help centre" description="Practical guidance for the main StreamSnip AI workflows." />
      <div className="help-page-grid">
        {items.map(([title, body], index) => <details className="help-accordion" key={title} open={index === 0}><summary><span className="help-step">{String(index + 1).padStart(2, "0")}</span><strong>{title}</strong><ChevronDown size={16} /></summary><p>{body}</p></details>)}
      </div>
      <section className="panel-card help-support-card"><CircleHelp size={21} /><div><h3>Need to inspect a problem?</h3><p>Use Activity to inspect engine events and download the diagnostic log. Your capture and render backend remains the existing local Python engine.</p><Link to="/activity" className="button button-secondary">Open Activity <ArrowRight size={14} /></Link></div></section>
    </>
  );
}

function AboutPage() {
  return (
    <>
      <PageHeading eyebrow="PROJECT INFORMATION" title="About StreamSnip AI" description="A local-first creator workspace for stream capture, transcription, highlight analysis, clip production, and publishing." />
      <section className="about-hero-card">
        <div className="about-brand-icon"><Clapperboard size={28} /></div>
        <div><div className="eyebrow">CREATED BY SCARZERO</div><h2>StreamSnip AI</h2><p>Created and maintained by Sifat Jaman / ScarZero. Capture, edit, and publish standout moments from streams and video files.</p></div>
      </section>
      <div className="about-info-grid">
        <section className="panel-card"><div className="eyebrow">LOCAL-FIRST</div><h3>Your engine, your files</h3><p>Capture, local transcription, FFmpeg rendering, clip metadata, and settings are stored on this computer. Hosted AI and publishing services are optional integrations.</p></section>
        <section className="panel-card"><div className="eyebrow">WORKFLOW</div><h3>From stream to short</h3><p>StreamSnip monitors a source, transcribes speech, scores candidate moments, applies the selected layout and captions, and writes clip files with post metadata.</p></section>
        <section className="panel-card"><div className="eyebrow">CURRENT RELEASE</div><h3>3.0.0</h3><p>As documented by the existing project README. The creator workspace is the redesigned interface for the current local engine.</p></section>
      </div>
      <section className="panel-card about-links-card">
        <h3>Project links</h3>
        <div className="about-links-list">
          <a href="https://github.com/sifat-jaman-13/stream-clip-ai" target="_blank" rel="noreferrer"><ExternalLink size={15} /> GitHub source</a>
          <a href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest" target="_blank" rel="noreferrer"><ExternalLink size={15} /> Latest release</a>
          <a href="https://sifat-jaman-13.github.io/stream-clip-ai/" target="_blank" rel="noreferrer"><ExternalLink size={15} /> Project website</a>
        </div>
        <p className="field-help">The project uses a proprietary non-commercial-use license. Review the repository LICENSE before redistribution or commercial use.</p>
      </section>
    </>
  );
}
