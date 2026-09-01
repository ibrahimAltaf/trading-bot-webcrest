import { http } from "../../lib/http";

export type HealthResponse = {
  status: string;
  service: string;
  timestamp: string;
};

export type RiskIn = {
  cooldown_minutes_after_loss: number;
  fee_pct: number;
  max_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
};

export type BacktestIn = {
  symbol: string; // "BTCUSDT"
  timeframe: string; // "1h"
  seed: number;
  initial_balance: number;
  risk: RiskIn;
};
export type FingerprintResponse = {
  ok: boolean;
  symbol: string;
  timeframe: string;
  path: string;
  sha256: string;
  bytes: number;
  mtime_utc: number;
  note?: string;
};

export type GetRunResponse = { ok: boolean; run: BacktestRun };

export type ListRunsResponse = {
  ok: boolean;
  total: number;
  skip: number;
  limit: number;
  runs: Array<{
    id: number;
    symbol: string;
    timeframe: string;
    status: string;
    started_at: string;
    final_balance?: number | null;
    total_return_pct?: number | null;
    trades_count?: number | null;
  }>;
};

export type SignalResponse = {
  ok: boolean;
  symbol: string;
  timeframe: string;
  price: number;
  signal: "BUY" | "SELL" | "HOLD" | string;
  ema_fast: number;
  ema_slow: number;
  rsi: number;
};

export type BacktestRun = {
  id: number;
  symbol: string;
  timeframe: string;
  status: string;
  started_at: string;
  final_balance?: number | null;
  total_return_pct?: number | null;
  trades_count?: number | null; // optional if some endpoints include it
  max_drawdown_pct?: number | null;
};

export type BacktestRunsListResponse = {
  ok: boolean;
  total: number;
  skip: number;
  limit: number;
  runs: BacktestRun[];
};

// what your UI wants
export type BacktestRunsListVM = {
  total: number;
  skip: number;
  limit: number;
  items: BacktestRun[];
};
export type ValidateResponse = {
  ok: boolean;
  batch_id: string;
  dataset_sha256: string;
  vary_seed: boolean;
  runs_count: number;
  run_ids: number[];
  message: string;
};

export type CompareStats = {
  mean_return_pct: number;
  min_return_pct: number;
  max_return_pct: number;
  std_return_pct: number;
};

export type CompareItem = {
  run_id: number;
  status: string;
  seed: number | null;
  final_balance: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  trades_count: number | null;
  win_rate: number | null;
  notes: string | null;
};

export type CompareResponse = {
  ok: boolean;
  ready: boolean;
  reproducible: boolean;
  message: string;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  statistics: CompareStats;
  items: CompareItem[];
};

export type CompareIn = { run_ids: number[] };
export type MessageResponse = string;

/** ---------- API ---------- */

export const backtestApi = {
  health: async (signal?: AbortSignal) => {
    const r = await http.get<HealthResponse>("/backtest/health", { signal });
    return r.data;
  },

  strategyInfo: async (signal?: AbortSignal) => {
    const r = await http.get<unknown>("/backtest/strategy/info", { signal });
    return r.data;
  },

  signal: async (
    params?: { symbol?: string; timeframe?: string },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<unknown>("/backtest/signal", { params, signal });
    return r.data;
  },

  datasetFingerprint: async (
    params?: { symbol?: string; timeframe?: string },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<unknown>("/backtest/dataset/fingerprint", {
      params,
      signal,
    });
    return r.data;
  },

  run: async (body: BacktestIn, signal?: AbortSignal) => {
    const r = await http.post<MessageResponse>("/backtest/run", body, {
      signal,
    });
    return r.data;
  },

  getRun: async (runId: number, signal?: AbortSignal) => {
    const r = await http.get<GetRunResponse>(`/backtest/${runId}`, { signal });
    return r.data;
  },

  deleteRun: async (runId: number, signal?: AbortSignal) => {
    const r = await http.delete<MessageResponse>(`/backtest/${runId}`, {
      signal,
    });
    return r.data;
  },

  listRuns: async (
    params?: {
      skip?: number;
      limit?: number;
      status?: string | null;
      symbol?: string | null;
    },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ListRunsResponse>("/backtest/runs/list", {
      params,
      signal,
    });
    return r.data;
  },

  validate: async (body: BacktestIn, signal?: AbortSignal) => {
    const r = await http.post<MessageResponse>("/backtest/validate", body, {
      signal,
    });
    return r.data;
  },

  compare: async (body: CompareIn, signal?: AbortSignal) => {
    const r = await http.post<MessageResponse>(
      "/backtest/validate/compare",
      body,
      { signal },
    );
    return r.data;
  },
  
};
