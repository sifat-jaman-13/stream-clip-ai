import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, loadDashboard } from "./api";
import type { Clip, Creator, DashboardState, LogEntry } from "./types";

export type SettingValue = string | number | boolean | undefined;
export type AppSettings = Record<string, SettingValue>;

export interface AISettings {
  provider: string;
  ollama_url: string;
  ollama_model: string;
  gemini_model: string;
  huggingface_model: string;
  custom_api_base: string;
  custom_api_model: string;
  custom_api_key_set: boolean;
  gemini_key_set: boolean;
  huggingface_token_set: boolean;
  metadata_copy_enabled: boolean;
}

export interface PublishingAccount {
  id: string;
  platform: string;
  name?: string;
  username?: string;
}

export interface PublishingStatus {
  provider: string;
  configured?: boolean;
  api_key_set?: boolean;
  available?: boolean;
  auto_post?: boolean;
  schedule_minutes?: number;
  visibility?: "public" | "private" | "unlisted";
  accounts?: Record<string, string>;
  providers?: Record<string, PublishingStatus>;
}

export interface ConfigResponse {
  settings: AppSettings;
  ai: AISettings;
  transcriber_models: string[];
  layouts: string[];
  output_formats: string[];
}

export interface WordsResponse {
  text: string;
  words: string[];
  phrases: string[];
}

const emptyState: DashboardState = {
  running: false,
  stopping: false,
  mode: null,
  phase: "idle",
  status: "Connecting to StreamSnip AIâ€¦",
  progress: 0,
  posting: { active: false, total: 0, completed: 0, current: "", errors: 0 },
  logs: [],
  last_id: 0,
  session: { clips: 0, chunks: 0, elapsed: 0 },
  clips: [],
  clip_total: 0,
  posted_total: 0,
};

const emptyAI: AISettings = {
  provider: "gemini",
  ollama_url: "http://127.0.0.1:11434",
  ollama_model: "",
  gemini_model: "gemini-3.8-flash",
  huggingface_model: "deepseek-ai/DeepSeek-V4.1-Flash:fastest",
  custom_api_base: "https://api.openai.com/v1",
  custom_api_model: "",
  custom_api_key_set: false,
  gemini_key_set: false,
  huggingface_token_set: false,
  metadata_copy_enabled: true,
};

export function useWorkspace() {
  const [state, setState] = useState<DashboardState>(emptyState);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [ai, setAI] = useState<AISettings>(emptyAI);
  const [publishing, setPublishing] = useState<PublishingStatus>({ provider: "zernio" });
  const [accounts, setAccounts] = useState<PublishingAccount[]>([]);
  const [words, setWords] = useState<WordsResponse>({ text: "", words: [], phrases: [] });
  const [connected, setConnected] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [saveError, setSaveError] = useState("");
  const [error, setError] = useState("");
  const [clipTabState, setClipTabState] = useState<"clips" | "posted">("clips");
  const [clipOffset, setClipOffsetState] = useState(0);

  const lastId = useRef(0);
  const settingsRef = useRef<AppSettings | null>(null);
  const aiRef = useRef<AISettings>(emptyAI);
  const settingsTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await loadDashboard(clipTabState, lastId.current, clipOffset);
      setState(result.state);
      setCreators(result.creators);
      if (result.state.last_id > lastId.current) lastId.current = result.state.last_id;
      if (result.state.logs.length) {
        setLogs((current) => [...current, ...result.state.logs].slice(-500));
      }
      setConnected(true);
      setError("");
    } catch (reason) {
      setConnected(false);
      setError(reason instanceof Error ? reason.message : "Could not connect to the local engine.");
    }
  }, [clipTabState, clipOffset]);

  const loadConfig = useCallback(async () => {
    try {
      const cfg = await apiGet<ConfigResponse>("/api/config");
      settingsRef.current = cfg.settings;
      setSettings(cfg.settings);
      aiRef.current = cfg.ai || emptyAI;
      setAI(cfg.ai || emptyAI);
      setConfigLoaded(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load application settings.");
    }
    try {
      const status = await apiGet<PublishingStatus>("/api/publishing/status");
      setPublishing(status);
    } catch {
      setPublishing({ provider: "zernio", available: false });
    }
    try {
      const value = await apiGet<Partial<WordsResponse> & { custom_text?: string; custom?: string; builtin?: string[]; patterns?: string[] }>("/api/words");
      setWords({
        text: typeof value.text === "string" ? value.text : typeof value.custom_text === "string" ? value.custom_text : typeof value.custom === "string" ? value.custom : "",
        words: Array.isArray(value.words) ? value.words : Array.isArray(value.builtin) ? value.builtin : [],
        phrases: Array.isArray(value.phrases) ? value.phrases : Array.isArray(value.patterns) ? value.patterns : [],
      });
    } catch {
      // The rest of the workspace remains usable when the optional words panel fails.
    }
  }, []);

  // This effect starts asynchronous API hydration; loadConfig updates state only after its requests resolve.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- loadConfig is asynchronous API hydration, not a synchronous state derivation.
    void loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1800);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => () => {
    if (settingsTimer.current !== null) window.clearTimeout(settingsTimer.current);
  }, []);

  const updateSettings = useCallback((patch: Partial<AppSettings>) => {
    const next = { ...(settingsRef.current || {}), ...patch };
    settingsRef.current = next;
    setSettings(next);
    if (settingsTimer.current !== null) window.clearTimeout(settingsTimer.current);
    setSaving(true);
    settingsTimer.current = window.setTimeout(() => {
      void apiPost("/api/settings", next)
        .then(() => {
          setSavedAt(Date.now());
          setSaveError("");
        })
        .catch((reason) => {
          setSaveError(reason instanceof Error ? reason.message : "Settings could not be saved.");
        })
        .finally(() => setSaving(false));
    }, 650);
  }, []);

  const saveSettings = useCallback(async (nextSettings?: AppSettings) => {
    const value = nextSettings || settingsRef.current;
    if (!value) throw new Error("Settings have not finished loading.");
    if (settingsTimer.current !== null) {
      window.clearTimeout(settingsTimer.current);
      settingsTimer.current = null;
    }
    settingsRef.current = value;
    setSettings(value);
    setSaving(true);
    try {
      await apiPost("/api/settings", value);
      setSavedAt(Date.now());
      setSaveError("");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Settings could not be saved.";
      setSaveError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  }, []);

  const updateAI = useCallback((patch: Partial<AISettings>) => {
    const next = { ...aiRef.current, ...patch };
    aiRef.current = next;
    setAI(next);
  }, []);

  const saveAI = useCallback(async (extra: Record<string, string | boolean> = {}) => {
    const current = aiRef.current;
    const result = await apiPost<AISettings>("/api/ai/settings", {
      provider: current.provider,
      ollama_url: current.ollama_url,
      ollama_model: current.ollama_model,
      gemini_model: current.gemini_model,
      huggingface_model: current.huggingface_model,
      custom_api_base: current.custom_api_base,
      custom_api_model: current.custom_api_model,
      ...extra,
    });
    aiRef.current = result;
    setAI(result);
    return result;
  }, []);

  const testAI = useCallback(async (extra: Record<string, string | boolean> = {}) => {
    const current = aiRef.current;
    return apiPost<{ ok?: boolean; message: string }>("/api/ai/test", {
      provider: current.provider,
      ollama_url: current.ollama_url,
      ollama_model: current.ollama_model,
      gemini_model: current.gemini_model,
      huggingface_model: current.huggingface_model,
      custom_api_base: current.custom_api_base,
      custom_api_model: current.custom_api_model,
      ...extra,
    });
  }, []);

  const detectOllama = useCallback(async (url?: string) => {
    return apiPost<{ models: string[] }>("/api/ai/ollama/models", {
      ollama_url: url || aiRef.current.ollama_url,
    });
  }, []);

  const fetchAccounts = useCallback(async () => {
    const result = await apiPost<{ accounts: PublishingAccount[] }>("/api/publishing/accounts", { provider: "zernio" });
    setAccounts(result.accounts || []);
    return result.accounts || [];
  }, []);

  const savePublishing = useCallback(async (payload: Record<string, string | number | boolean | Record<string, string>>) => {
    const result = await apiPost<PublishingStatus>("/api/publishing", { provider: "zernio", ...payload });
    setPublishing(result);
    return result;
  }, []);

  const refreshPublishing = useCallback(async () => {
    const result = await apiGet<PublishingStatus>("/api/publishing/status");
    setPublishing(result);
    return result;
  }, []);

  const saveWords = useCallback(async (text: string) => {
    const result = await apiPost<{ ok: boolean; entries: number }>("/api/words", { text });
    setWords((current) => ({ ...current, text }));
    return result;
  }, []);

  const setClipTab = useCallback((tab: "clips" | "posted") => {
    setClipTabState(tab);
    setClipOffsetState(0);
  }, []);

  const setClipOffset = useCallback((offset: number) => {
    setClipOffsetState(Math.max(0, offset));
  }, []);

  return {
    state,
    creators,
    logs,
    settings,
    ai,
    publishing,
    accounts,
    words,
    connected,
    configLoaded,
    saving,
    savedAt,
    saveError,
    error,
    clipTab: clipTabState,
    clipOffset,
    refresh,
    loadConfig,
    updateSettings,
    saveSettings,
    updateAI,
    saveAI,
    testAI,
    detectOllama,
    fetchAccounts,
    savePublishing,
    refreshPublishing,
    saveWords,
    setClipTab,
    setClipOffset,
  };
}

export type Workspace = ReturnType<typeof useWorkspace>;
export type { Clip, Creator, DashboardState, LogEntry };
