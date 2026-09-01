import { http } from "../../lib/http";
import type { ExecutionMode } from "../../lib/executionMode";

export type KillSwitchState = {
  engaged: boolean;
  reason?: string | null;
  engaged_at?: string | null;
  engaged_by?: string | null;
  released_at?: string | null;
  released_by?: string | null;
  history?: Array<Record<string, unknown>>;
};

export type ExecutionModeSnapshot = {
  effective_mode: string;
  is_simulated?: boolean;
  env_default?: string;
  override?: Record<string, unknown> | null;
  override_active?: boolean;
};

export type RiskLimits = {
  max_trade_notional_usdt: number;
  max_open_positions: number;
  max_daily_loss_usdt: number;
  max_daily_orders: number;
  max_exposure_pct_of_balance: number;
  min_order_notional_usdt: number;
  cooldown_seconds_after_loss: number;
  duplicate_window_seconds: number;
  require_kill_switch_release: boolean;
  min_ml_confidence_for_live: number;
  max_total_exposure_usdt?: number | null;
  max_cumulative_loss_usdt?: number | null;
  allowed_symbols?: string[] | null;
};

export type Phase2CStatus = {
  ok?: boolean;
  phase?: string;
  micro_live_enabled: boolean;
  status_label: string;
  can_place_live_orders: boolean;
  limits?: RiskLimits;
  risk_state?: Record<string, unknown>;
  adaptive_ai_note?: string;
};

export type LiveReadinessCheck = {
  name: string;
  ok: boolean;
  detail: string | Record<string, unknown>;
  severity?: "info" | "warn" | null;
};

export type LiveReadinessResponse = {
  ok: boolean;
  ready_for_live_capital: boolean;
  ready_for_live_capital_reason: string;
  checks: LiveReadinessCheck[];
  blocking_checks: string[];
  warnings: string[];
  snapshot?: Record<string, unknown>;
};

export const safetyApi = {
  status: async (signal?: AbortSignal) => {
    const r = await http.get<{
      ok: boolean;
      execution_mode: ExecutionModeSnapshot;
      is_simulated: boolean;
      kill_switch: KillSwitchState;
      limits: RiskLimits;
      reconcile: Record<string, unknown>;
    }>("/safety/status", { signal });
    return r.data;
  },

  killSwitch: async (signal?: AbortSignal) => {
    const r = await http.get<{ ok: boolean; kill_switch: KillSwitchState }>(
      "/safety/kill-switch",
      { signal },
    );
    return r.data;
  },

  engageKillSwitch: async (body: { reason: string; by?: string }) => {
    const r = await http.post<{
      ok: boolean;
      engaged: boolean;
      kill_switch: KillSwitchState;
    }>("/safety/kill-switch/engage", body);
    return r.data;
  },

  releaseKillSwitch: async (body: { reason: string; by?: string }) => {
    const r = await http.post<{
      ok: boolean;
      engaged: boolean;
      kill_switch: KillSwitchState;
    }>("/safety/kill-switch/release", body);
    return r.data;
  },

  limits: async (signal?: AbortSignal) => {
    const r = await http.get<{ ok: boolean; limits: RiskLimits }>(
      "/safety/limits",
      { signal },
    );
    return r.data;
  },

  reconcile: async (signal?: AbortSignal) => {
    const r = await http.get<Record<string, unknown>>("/safety/reconcile", {
      signal,
    });
    return r.data;
  },

  exchangeReconcile: async (
    params?: { mode?: ExecutionMode; symbols?: string },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<Record<string, unknown>>(
      "/safety/exchange-reconcile",
      { params: { mode: params?.mode ?? "shadow", symbols: params?.symbols }, signal },
    );
    return r.data;
  },

  executionMode: async (signal?: AbortSignal) => {
    const r = await http.get<{ ok: boolean } & ExecutionModeSnapshot>(
      "/execution/mode",
      { signal },
    );
    return r.data;
  },

  setExecutionMode: async (body: {
    mode: ExecutionMode;
    reason?: string;
    by?: string;
  }) => {
    const r = await http.post<
      { ok: boolean; mode: string; override?: Record<string, unknown> } & ExecutionModeSnapshot
    >("/execution/mode", body);
    return r.data;
  },

  clearExecutionModeOverride: async () => {
    const r = await http.delete<
      { ok: boolean; removed: boolean } & ExecutionModeSnapshot
    >("/execution/mode/override");
    return r.data;
  },

  liveReadiness: async (signal?: AbortSignal) => {
    const r = await http.get<LiveReadinessResponse>("/safety/live-readiness", {
      signal,
    });
    return r.data;
  },

  shadowAudit: async (
    params?: { symbol?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<Record<string, unknown>>("/safety/shadow-audit", {
      params,
      signal,
    });
    return r.data;
  },

  operationalReadiness: async (signal?: AbortSignal) => {
    const r = await http.get<Record<string, unknown>>(
      "/safety/operational-readiness",
      { signal },
    );
    return r.data;
  },

  phase2cStatus: async (signal?: AbortSignal) => {
    const r = await http.get<Phase2CStatus>("/safety/phase2c/status", {
      signal,
    });
    return r.data;
  },

  phase2cEvidence: async (
    params?: { symbol?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<Record<string, unknown>>("/safety/phase2c/evidence", {
      params,
      signal,
    });
    return r.data;
  },

  activatePhase2c: async (body: { reason: string; by?: string }) => {
    const r = await http.post<Phase2CStatus & { activated: boolean }>(
      "/safety/phase2c/activate",
      body,
    );
    return r.data;
  },

  deactivatePhase2c: async (body: { reason: string; by?: string }) => {
    const r = await http.post<Phase2CStatus & { activated: boolean }>(
      "/safety/phase2c/deactivate",
      body,
    );
    return r.data;
  },
};
