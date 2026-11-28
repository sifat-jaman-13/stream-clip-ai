import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Camera, CheckCircle2, CirclePlay, RefreshCw, ShieldCheck, Trash2, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { PublishingAccount, PublishingConnection, Workspace } from "../../workspace";
import "./MultiZernioConnections.css";

type ConnectionDraft = { id: string; label: string; apiKey: string; saved: boolean; slotNumber: number };
const EMPTY_CONNECTIONS: PublishingConnection[] = [];
const platformDetails: Record<string, { label: string; icon: LucideIcon }> = {
  facebook: { label: "Facebook", icon: Users },
  instagram: { label: "Instagram", icon: Camera },
  youtube: { label: "YouTube", icon: CirclePlay },
};

function createDrafts(connections: PublishingConnection[] = []): ConnectionDraft[] {
  const slots: Array<PublishingConnection | undefined> = Array.from({ length: 5 });
  const unplaced: PublishingConnection[] = [];

  for (const connection of connections) {
    const match = /^(?:streamsnip-zernio-)?slot-([1-5])$/i.exec(connection.id);
    const preferredSlot = match ? Number(match[1]) - 1 : -1;
    if (preferredSlot >= 0 && !slots[preferredSlot]) slots[preferredSlot] = connection;
    else unplaced.push(connection);
  }

  for (const connection of unplaced) {
    const freeSlot = slots.findIndex((slot) => !slot);
    if (freeSlot < 0) break;
    slots[freeSlot] = connection;
  }

  return slots.map((connection, index) => {
    const slotNumber = index + 1;
    if (!connection) {
      return {
        id: "streamsnip-zernio-slot-" + slotNumber,
        label: "Zernio connection " + slotNumber,
        apiKey: "",
        saved: false,
        slotNumber,
      };
    }

    const savedLabel = String(connection.label || "").trim();
    const genericLabel = /^zernio(?: api)? connection(?: [1-5])?$/i.test(savedLabel);
    return {
      id: connection.id,
      label: !savedLabel || genericLabel ? "Zernio connection " + slotNumber : savedLabel,
      apiKey: "",
      saved: Boolean(connection.api_key_set),
      slotNumber,
    };
  });
}
function accountHandle(account: PublishingAccount) {
  return account.username
    ? (account.username.startsWith("@") ? account.username : "@" + account.username)
    : account.name || account.id;
}
function showToast(tone: "success" | "error" | "info", title: string, message?: string) {
  window.dispatchEvent(new CustomEvent("streamsnip:toast", { detail: { tone, title, message } }));
}

export default function MultiZernioConnections({ workspace }: { workspace: Workspace }) {
  const remoteConnections = workspace.publishing.connections ?? EMPTY_CONNECTIONS;
  const [draftOverrides, setDraftOverrides] = useState<Record<string, Partial<ConnectionDraft>>>({});
  const drafts = useMemo(
    () => createDrafts(remoteConnections).map((draft) => ({ ...draft, ...draftOverrides[draft.id] })),
    [remoteConnections, draftOverrides],
  );
  const refreshPublishing = workspace.refreshPublishing;

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshPublishing().catch(() => undefined);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [refreshPublishing]);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingSlots, setRefreshingSlots] = useState<string[]>([]);
  const [disconnecting, setDisconnecting] = useState<string[]>([]);
  const [busyAccounts, setBusyAccounts] = useState<string[]>([]);

  const accountGroups = useMemo(() => {
    const groups = new Map<string, PublishingAccount[]>();
    for (const account of workspace.accounts) {
      const id = account.connection_id || "";
      if (!id) continue;
      groups.set(id, [...(groups.get(id) || []), account]);
    }
    return groups;
  }, [workspace.accounts]);

  const connectedCount = workspace.accounts.filter((account) =>
    account.is_active !== false && account.provider_enabled !== false,
  ).length;
  const postingCount = workspace.accounts.filter((account) =>
    account.posting_enabled && account.is_active !== false && account.provider_enabled !== false,
  ).length;

  const updateDraft = (id: string, patch: Partial<ConnectionDraft>) => {
    setDraftOverrides((current) => ({
      ...current,
      [id]: { ...current[id], ...patch },
    }));
  };

  const saveConnections = async () => {
    const connections = drafts.filter((item) => item.saved || item.apiKey.trim()).map((item) => ({
      id: item.id,
      label: item.label.trim() || item.id,
      ...(item.apiKey.trim() ? { api_key: item.apiKey.trim() } : {}),
      accounts: (accountGroups.get(item.id) || []).map((account) => ({
        id: account.id, posting_enabled: Boolean(account.posting_enabled),
      })),
    }));
    setSaving(true);
    try {
      await workspace.savePublishing({
        connections,
        auto_post: Boolean(workspace.publishing.auto_post),
        schedule_minutes: Number(workspace.publishing.schedule_minutes || 0),
        visibility: workspace.publishing.visibility || "public",
      });
      setDraftOverrides({});
      showToast("success", "Zernio connections saved", "New or replaced keys were verified. Existing connections and account selections were kept.");
    } catch (error) {
      showToast("error", "Could not save Zernio connections", error instanceof Error ? error.message : "Check the API keys and try again.");
    } finally { setSaving(false); }
  };

  const refreshAccounts = async (connectionId?: string) => {
    if (connectionId) setRefreshingSlots((items) => items.concat(connectionId));
    else setRefreshing(true);
    try {
      const accounts = await workspace.fetchAccounts(connectionId);
      const scope = connectionId ? drafts.find((item) => item.id === connectionId)?.label || "Connection" : "All connections";
      showToast("success", "Account discovery complete", `${scope}: found ${accounts.length} supported social account(s).`);
    } catch (error) {
      showToast("error", "Account discovery failed", error instanceof Error ? error.message : "Zernio could not return connected accounts.");
    } finally {
      if (connectionId) setRefreshingSlots((items) => items.filter((item) => item !== connectionId));
      else setRefreshing(false);
    }
  };

  const togglePosting = async (account: PublishingAccount, enabled: boolean) => {
    const connectionId = account.connection_id || "";
    const key = connectionId + ":" + account.id;
    setBusyAccounts((items) => items.concat(key));
    try { await workspace.setPublishingAccount(connectionId, account.id, enabled); }
    catch (error) {
      showToast("error", "Account setting was not saved", error instanceof Error ? error.message : "Try again.");
    } finally { setBusyAccounts((items) => items.filter((item) => item !== key)); }
  };

  const removeConnection = async (item: ConnectionDraft) => {
    const isSaved = remoteConnections.some((connection) => connection.id === item.id && connection.api_key_set);
    if (!isSaved) {
      updateDraft(item.id, { apiKey: "" });
      return;
    }

    setDisconnecting((items) => items.concat(item.id));
    try {
      await workspace.disconnectPublishingConnection(item.id);
      setDraftOverrides((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      showToast("success", "Zernio disconnected", `${item.label}: saved key and discovered accounts removed from this PC.`);
    } catch (error) {
      showToast("error", "Could not disconnect Zernio", error instanceof Error ? error.message : "The connection could not be removed.");
    } finally {
      setDisconnecting((items) => items.filter((id) => id !== item.id));
    }
  };

  return (
    <section className="zernio-multi panel">
      <div className="panel-heading">
        <div>
          <h2>Five Zernio connections</h2>
          <p>Each slot works the same way: save its API key, discover its connected accounts, then choose which destinations can receive clips.</p>
        </div>
        <div className="zernio-connection-actions">
          <button className="button button-secondary button-small" type="button" onClick={() => void refreshAccounts()} disabled={refreshing || !remoteConnections.length}>
            <RefreshCw size={14} className={refreshing ? "zernio-spin" : ""} />{refreshing ? "Discovering…" : "Refresh all accounts"}
          </button>
          <button className="button button-primary button-small" type="button" onClick={() => void saveConnections()} disabled={saving}>
            <ShieldCheck size={14} />{saving ? "Verifying…" : "Save & discover"}
          </button>
        </div>
      </div>

      <div className="zernio-capacity-strip">
        <span><strong>{remoteConnections.length} / 5</strong> configured connections</span>
        <span><strong>{connectedCount}</strong> connected accounts</span>
        <span><strong>{postingCount}</strong> enabled for posting</span>
      </div>
      <div className="zernio-workspace-warning" role="note">
        <AlertCircle size={15} />
        <span><strong>Zernio controls the limits.</strong> Request allowance is shared across all API keys in the same Zernio billing workspace. Zernio exposes the API user identity, not a stable billing-workspace ID, so different keys cannot be confirmed as independent workspaces. StreamSnip never treats API-key slots as separate request budgets.
        {remoteConnections.some((connection) => connection.identity_shared) ? " Some saved keys also identify the same API user." : ""}</span>
      </div>

      <div className="zernio-connection-grid">
        {drafts.map((draft, index) => {
          const accounts = accountGroups.get(draft.id) || [];
          const savedConnection = remoteConnections.find((item) => item.id === draft.id);
          const isSaved = Boolean(draft.saved && savedConnection?.api_key_set);
          return (
            <div className="zernio-connection-card" key={draft.id}>
              <div className="zernio-connection-head">
                <div>
                  <span className="zernio-slot-label">API CONNECTION {index + 1}</span>
                  <div className="zernio-connection-title">
                    <strong>{draft.label || `Connection ${index + 1}`}</strong>
                    {isSaved ? <span className="zernio-connection-state is-connected"><CheckCircle2 size={12} />Connected</span> : <span className="zernio-connection-state">Not connected</span>}
                    {isSaved && savedConnection?.identity_shared ? <span className="zernio-identity-state is-shared">Same API user</span> : null}
                    {isSaved && savedConnection?.identity_verified && !savedConnection.identity_shared ? <span className="zernio-identity-state">API user identified</span> : null}
                    {isSaved && !savedConnection?.identity_verified ? <span className="zernio-identity-state is-unverified">API user unverified</span> : null}
                  </div>
                </div>
                <div className="zernio-slot-actions">
                  <button
                    type="button"
                    className="button button-secondary button-small"
                    onClick={() => void refreshAccounts(draft.id)}
                    disabled={!isSaved || refreshingSlots.includes(draft.id)}
                    title={isSaved ? "Refresh accounts for this API key" : "Save an API key before refreshing accounts"}
                  >
                    <RefreshCw size={13} className={refreshingSlots.includes(draft.id) ? "zernio-spin" : ""} />
                    {refreshingSlots.includes(draft.id) ? "Refreshing" : "Refresh"}
                  </button>
                  {isSaved ? (
                    <button
                      type="button"
                      className="button button-secondary button-small zernio-disconnect"
                      onClick={() => void removeConnection(draft)}
                      disabled={disconnecting.includes(draft.id) || Boolean(workspace.publishing.publishing_active)}
                      aria-label={"Disconnect " + draft.label}
                    >
                      <Trash2 size={13} />{disconnecting.includes(draft.id) ? "Disconnecting" : "Disconnect"}
                    </button>
                  ) : draft.apiKey ? (
                    <button type="button" className="button button-secondary button-small" onClick={() => void removeConnection(draft)}>
                      Clear key
                    </button>
                  ) : null}
                </div>
              </div>

              <label className="zernio-field">
                <span>Connection label</span>
                <input value={draft.label} maxLength={80} onChange={(event) => updateDraft(draft.id, { label: event.target.value })} placeholder={`Zernio API connection ${index + 1}`} />
              </label>
              <label className="zernio-field">
                <span>Zernio API key</span>
                <input type="password" autoComplete="new-password" value={draft.apiKey}
                  onChange={(event) => updateDraft(draft.id, { apiKey: event.target.value })}
                  placeholder={isSaved ? "Key saved · paste to replace" : "Paste Zernio API key"} />
              </label>

              {accounts.length && isSaved ? (
                <div className="zernio-account-section">
                  <div className="zernio-account-heading"><strong>Discovered accounts</strong><span>{accounts.length} found</span></div>
                  {accounts.map((account) => {
                    const platform = platformDetails[account.platform];
                    if (!platform) return null;
                    const Icon = platform.icon;
                    const ref = (account.connection_id || draft.id) + ":" + account.id;
                    const unavailable = account.is_active === false || account.provider_enabled === false;
                    const disabled = unavailable || busyAccounts.includes(ref);
                    return (
                      <div className={"zernio-account-row" + (account.posting_enabled ? " is-enabled" : "")} key={ref}>
                        <span className={"zernio-platform-icon zernio-" + account.platform}><Icon size={15} /></span>
                        <span className="zernio-account-identity">
                          <strong>{accountHandle(account)}</strong>
                          <small>{platform.label}{account.profile_name ? " · " + account.profile_name : ""}</small>
                        </span>
                        <span className="zernio-account-state">
                          {account.rate_limited ? <span className="zernio-warning" title={account.rate_limit_until ? "Paused by Zernio. Posting can resume after " + new Date(account.rate_limit_until * 1000).toLocaleString() + ". " + (account.last_error || "") : account.last_error || "Zernio reported a rate limit."}>Paused · limit</span> : null}
                          {account.is_over_limit ? <span className="zernio-warning" title="Zernio reports this profile is over its plan limit.">Plan limit</span> : null}
                          {unavailable ? <span className="zernio-muted">Disconnected</span> : null}
                        </span>
                        <label className="zernio-switch" title={disabled ? "This account is not available for posting." : account.posting_enabled ? "Turn posting off for this account" : "Turn posting on for this account"}>
                          <input type="checkbox" aria-label={`${account.posting_enabled ? "Disable" : "Enable"} posting for ${accountHandle(account)} on ${platform.label}`} checked={Boolean(account.posting_enabled)} disabled={disabled}
                            onChange={(event) => void togglePosting(account, event.target.checked)} />
                          <span />
                        </label>
                      </div>
                    );
                  })}
                  {accounts.some((account) => account.rate_limited && account.last_error) ? (
                    <p className="zernio-account-note"><AlertCircle size={13} />Zernio limited this account, so only this destination is paused. The switch can be re-enabled manually; when Zernio supplies a reset time, StreamSnip follows it.</p>
                  ) : null}
                </div>
              ) : isSaved ? (
                <div className="zernio-empty-accounts">No supported Facebook, Instagram or YouTube accounts returned for this API key. Refresh to check again.</div>
              ) : (
                <div className="zernio-empty-accounts">Paste a key, then choose Save & discover to identify this key's accounts.</div>
              )}
            </div>
          );
        })}
      </div>

      <div className="zernio-footer-note">
        Zernio and the connected social platforms determine account availability and posting limits. StreamSnip does not add its own account quotas.
      </div>
    </section>
  );
}
