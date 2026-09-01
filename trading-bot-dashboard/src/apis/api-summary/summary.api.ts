import { http } from "../../lib/http";

export type StatusSummaryResponse = {
  app_version: string;
  env?: string;
  binance_testnet?: boolean;
  binance_spot_base_url?: string;
  scheduler_state: string;
  last_decision_time: string | null;
  latest_decision?: {
    action: string;
    confidence: number | null;
    reason: string;
    symbol: string;
    timeframe: string;
    executed: boolean;
    order_id: number | null;
  } | null;
  last_successful_market_fetch: string | null;
  last_successful_trade_execution: string | null;
  model_loaded: boolean;
  database_connected: boolean;
  exchange_connected: boolean;
  exchange_detail: string | null;
  observability?: {
    recent_decisions_count: number;
    recent_trades_count: number;
  };
};

export type StartupCheckResponse = {
  ok: boolean;
  env: string;
  binance_testnet?: boolean;
  binance_spot_base_url?: string;
  app_version: string;
  scheduler_state: string;
  database_connected: boolean;
  exchange_connected: boolean;
  dashboard_url: string | null;
  dashboard_connected: boolean;
  dashboard_detail: string | null;
  last_decision_time: string | null;
  last_successful_market_fetch: string | null;
  last_successful_trade_execution: string | null;
  latest_decision?: StatusSummaryResponse["latest_decision"];
  observability?: StatusSummaryResponse["observability"];
};

/** GET /stats/live-proof — audit: ML participation %, softmax stats, alerts */
export type LiveProofResponse = {
  ok: boolean;
  ml_used_percentage: number;
  avg_ml_confidence: number | null;
  high_confidence_ratio: number | null;
  avg_confidence: number | null;
  buy_sell_ratio?: number;
  buy_count?: number;
  sell_count?: number;
  hold_count?: number;
  sample_size?: number;
  final_source_counts?: Record<string, number>;
  live_pnl_sum_usdt?: number;
  closed_trades_sample?: number;
  runtime_status?: string;
  ml_status_summary?: {
    ml_used_percentage: number;
    non_rule_only_sources: Record<string, number>;
  };
  alerts?: Array<{
    level: string;
    code: string;
    message: string;
  }>;
};

/** GET /stats/ml-analysis — softmax distribution over recent decisions */
export type MlAnalysisResponse = {
  ok: boolean;
  sample_size: number;
  avg_ml_confidence: number | null;
  high_confidence_ratio: number | null;
  high_confidence_ratio_08?: number | null;
  ml_confidence_samples?: number;
  ml_used_percentage?: number;
};

export const statusApi = {
  summary: async (signal?: AbortSignal) => {
    try {
      const r = await http.get<StatusSummaryResponse>("/status/summary", {
        signal,
      });
      return r.data;
    } catch {
      const r = await http.get<StatusSummaryResponse>("/status-summary", {
        signal,
      });
      return r.data;
    }
  },
  startupCheck: async (signal?: AbortSignal) => {
    const r = await http.get<StartupCheckResponse>("/status/startup-check", {
      signal,
    });
    return r.data;
  },
};

/** Backend `/stats/*` (same base URL as exchange — FastAPI root routes). */
export const statsApi = {
  liveProof: async (params?: { limit?: number }, signal?: AbortSignal) => {
    const r = await http.get<LiveProofResponse>("/stats/live-proof", {
      params: { limit: params?.limit ?? 200 },
      signal,
    });
    return r.data;
  },
  mlAnalysis: async (params?: { limit?: number }, signal?: AbortSignal) => {
    const r = await http.get<MlAnalysisResponse>("/stats/ml-analysis", {
      params: { limit: params?.limit ?? 500 },
      signal,
    });
    return r.data;
  },
};
