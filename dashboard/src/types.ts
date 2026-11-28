export interface Creator {
  id: string;
  name: string;
  target: string;
  running?: boolean;
  capture_active?: boolean;
  capture_stopping?: boolean;
  watching_vods?: boolean;
  phase?: string;
  status?: string;
  vod_status?: string;
  live_clips?: number;
  vod_clips?: number;
  vod_pending?: number;
}

export interface Clip {
  name: string;
  mtime: number;
  size_mb: number;
  source?: string;
  creator_id?: string;
  creator_name?: string;
  caption?: string;
  title?: string;
  description?: string;
  posted?: boolean;
  posted_at?: number | string | null;
  scheduled?: boolean;
  scheduled_at?: number | string | null;
  delivery_state?: "ready" | "scheduled" | "posted";

}

export interface LogEntry {
  id: number;
  t: string;
  m: string;
  level?: string;
  file_lock?: unknown;
}

export interface DashboardState {
  running: boolean;
  stopping: boolean;
  mode: string | null;
  phase: string;
  status: string;
  progress: number;
  posting: {
    active: boolean;
    total: number;
    completed: number;
    current: string;
    errors: number;
  };
  logs: LogEntry[];
  last_id: number;
  session: {
    clips: number;
    chunks: number;
    elapsed: number;
  };
  clips: Clip[];
  clip_total: number;
  posted_total: number;
  scheduled_total: number;
}
