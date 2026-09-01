import { http } from "../../lib/http";
import type { ExecutionMode } from "../../lib/executionMode";

export type { ExecutionMode };

export type ExchangeDebugResponse = {
  binance_testnet: boolean;
  binance_spot_base_url: string;
  api_key_present: boolean;
  api_secret_present: boolean;
};

export type ExchangeBalanceItem = {
  asset: string;
  free: string; // binance returns strings
  locked: string; // strings
  total?: string; // backend seems to add this
};

export type ExchangeBalanceResponse = {
  ok: boolean;
  count: number;
  balances: ExchangeBalanceItem[];
};

export type ExchangeAssetBalanceResponse = {
  ok?: boolean;
  balance: ExchangeBalanceItem;
};

export type DecisionAction = "BUY" | "SELL" | "HOLD";

export type TradingDecision = {
  id: number;
  action: DecisionAction;
  confidence: number | null;
  symbol: string;
  timeframe: string;
  regime: string;
  price: number | null;
  timestamp: string;

  indicators: {
    adx: number | null;
    ema_fast: number | null;
    ema_slow: number | null;
    rsi: number | null;
    bb_upper: number | null;
    bb_lower: number | null;
    atr: number | null;
  };

  risk: {
    entry: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    risk_reward: number | null;
  };

  reason: string;
  signals: Record<string, unknown>;

  rule_signal: DecisionAction | null;
  ml_signal: DecisionAction | null;
  ml_confidence: number | null;
  combined_signal: DecisionAction | null;
  override_reason: string | null;
  final_action: DecisionAction | null;

  executed: boolean;
  order_id: number | string | null;

  /** Pipeline outcome (mirrors signals.final_source; duplicated for table display) */
  final_source?: string | null;

  /** Per-cycle audit (rule/ml/final confidence, hold_kind, block_reasons) */
  cycle_debug?: {
    symbol?: string;
    timeframe?: string;
    runtime_mode?: string;
    rule_confidence?: number;
    ml_confidence?: number | null;
    final_confidence?: number;
    final_source?: string;
    hold_kind?: string | null;
    block_reasons?: string[];
    execution_eligible?: boolean;
    has_open_position?: boolean;
    execution_block_reason?: string;
  };
};

export type ExchangeDecisionLatestResponse = {
  ok?: boolean;
  decision: TradingDecision;
};

export type ExchangeDecisionsRecentResponse = {
  ok?: boolean;
  count?: number;
  decisions: TradingDecision[];
};
export type EventLog = {
  id: number;
  level: "INFO" | "WARN" | "ERROR";
  category:
    | "trade"
    | "order"
    | "decision"
    | "ml"
    | "exchange"
    | "system"
    | string;
  message: string;
  symbol: string | null;
  ts: string;
};

export type ExchangeLogsRecentResponse = {
  ok?: boolean;
  count?: number;
  /** Scoped symbol when backend filters (default: TRADE_SYMBOL); or "all_symbols" */
  scope?: string;
  logs: EventLog[];
};

/** GET /exchange/performance/ai-observability */
export type AiObservabilityResponse = {
  ok: boolean;
  sample_size: number;
  symbol_filter: string | null;
  ml_usage: {
    cycles_with_ml_signal_field: number;
    cycles_with_ml_confidence: number;
    pct_with_ml_signal: number;
    pct_with_ml_confidence: number;
  };
  runtime_posture: {
    counts_by_runtime_mode: Record<string, number>;
    degraded_or_unavailable_cycles: number;
    ml_strict_failure_cycles: number;
  };
  decision_diversity: {
    distinct_rule_ml_final_patterns: number;
    pattern_top: Record<string, number>;
    final_source_entropy_bits: number;
    hold_kind_counts: Record<string, number>;
  };
  final_source_counts: Record<string, number>;
};

/** GET /status/model-health/symbols */
export type ModelHealthSymbolsResponse = {
  ok: boolean;
  ml_enabled: boolean;
  trade_timeframe: string;
  degraded?: boolean;
  note?: string;
  symbols: Array<{
    symbol: string;
    exact_match_exists: boolean;
    runtime_eligible: boolean;
    fallback_used: boolean;
    artifact_exists: boolean;
    model_dir?: string;
    reason?: string;
    last_error?: string | null;
    runtime_health?: unknown;
  }>;
};

export type Position = {
  id: number;
  symbol: string;
  entry_price: number;
  entry_qty: number;
  entry_ts: string;
  exit_price?: number;
  exit_qty?: number;
  exit_ts?: string;
  pnl?: number;
  pnl_pct?: number;
};

export type ExchangeOpenPositionsResponse = {
  ok?: boolean;
  positions: Position[];
};

export type ExchangePositionsHistoryResponse = {
  ok?: boolean;
  count?: number;
  positions: Position[];
};

export type ExchangeTrade = {
  id?: number | string;
  symbol?: string;
  order_id?: number | string;
  price?: number | string;
  qty?: number | string;
  side?: "BUY" | "SELL" | string;
  ts?: string;
  [key: string]: unknown;
};

export type ExchangeTradesResponse = {
  ok?: boolean;
  count?: number;
  trades: ExchangeTrade[];
};

export type ExchangeProofResponse = {
  ok: boolean;
  symbol: string;
  section_errors?: Record<string, string> | null;
  environment: {
    binance_testnet: boolean;
    binance_spot_base_url: string;
    app_env: string;
  };
  balances: {
    count: number;
    usdt?: ExchangeBalanceItem;
    all: ExchangeBalanceItem[];
  };
  decision_visibility: {
    latest?: TradingDecision | null;
    recent_count: number;
    recent: TradingDecision[];
    action_counts: {
      total: number;
      buy: number;
      sell: number;
      hold: number;
    };
  };
  positions: {
    open_count: number;
    open: Position[];
    history_count: number;
    history: Position[];
  };
  orders: {
    open_count: number;
    open: ExchangeOrder[];
  };
  trades: {
    count: number;
    recent: ExchangeTrade[];
    last_trade_ts: string | null;
  };
  performance: {
    realized_pnl_usdt: number;
    closed_positions_count: number;
  };
  logs: {
    recent_count: number;
    recent: EventLog[];
    last_event_ts: string | null;
  };
};

export type SystemStatusResponse = {
  status: string;
  [key: string]: unknown;
};

export type DbHealthResponse = {
  status: string;
  [key: string]: unknown;
};

export type LimitBuyIn = {
  symbol: string; // "BTCUSDT"
  price: string; // "98110.44"
  quantity: string; // "0.01"
};

export type OrderFill = {
  price: string;
  qty: string;
  commission: string;
  commissionAsset: string;
  tradeId: number;
};

export type LimitBuyResponse = {
  symbol: string;
  orderId: number;
  orderListId: number;
  clientOrderId: string;
  transactTime: number;
  price: string;
  origQty: string;
  executedQty: string;
  origQuoteOrderQty: string;
  cummulativeQuoteQty: string;
  status: string; // "FILLED" etc.
  timeInForce: string;
  type: string;
  side: "BUY" | "SELL" | string;
  workingTime: number;
  fills?: OrderFill[];
  selfTradePreventionMode?: string;
};

export type LiveRunIn = {
  symbol: string; // "BTCUSDT"
  usdt_amount: number; // 20
};

export type LiveRunResult = {
  symbol: string;
  price: number;
  qty: number;
  order_id: number;
};

export type LiveRunResponse = {
  ok: boolean;
  result: LiveRunResult;
};

export type ExchangeOrder = {
  symbol: string;
  orderId: number;
  orderListId: number;
  clientOrderId: string;

  price: string;
  origQty: string;
  executedQty: string;
  cummulativeQuoteQty: string;

  status: string; // "FILLED" | "NEW" | etc
  timeInForce: string;
  type: string; // "LIMIT"
  side: string; // "BUY"

  stopPrice?: string;
  icebergQty?: string;

  time?: number;
  updateTime?: number;
  isWorking?: boolean;
  workingTime?: number;

  origQuoteOrderQty?: string;
  selfTradePreventionMode?: string;
};

export type AutoTradeIn = {
  symbol: string;
  timeframe: string;
  risk_pct: number;
  force_signal?: "BUY" | "SELL";
};

export type AutoTradeResponse = {
  ok: boolean;
  executed: boolean;
  signal: string;
  price: number;
  quantity?: number;
  reason?: string;
  order?: any;
};

// open orders endpoint returns [] (array)
export type ExchangeOpenOrdersResponse = ExchangeOrder[];

// all orders endpoint returns [] (array)
export type ExchangeAllOrdersResponse = ExchangeOrder[];

export type KlineItem = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type KlinesResponse = {
  ok: boolean;
  symbol: string;
  interval: string;
  klines: KlineItem[];
};

export type TickerPriceResponse = {
  ok: boolean;
  symbol: string;
  price: number;
};

export type PerformanceMetricsResponse = {
  mode: string;
  positions: {
    total_closed: number;
    open: number;
    winners: number;
    losers: number;
  };
  pnl: {
    total_pnl_usdt: number;
    gross_profit_usdt: number;
    gross_loss_usdt: number;
    max_drawdown_usdt: number;
    max_drawdown_pct: number;
  };
  ratios: {
    win_rate_pct: number;
    profit_factor: number | null;
    avg_win_usdt: number;
    avg_loss_usdt: number;
    avg_trade_duration_hours: number;
  };
  decision_summary: {
    total: number;
    buy: number;
    sell: number;
    hold: number;
    hold_pct: number;
  };
};

export type PerformanceSummaryResponse = {
  total_pnl_usdt: number;
  win_rate_pct: number;
  total_trades: number;
  last_signal: string;
  last_signal_reason: string;
  last_signal_ts: string | null;
};

export type MlVsRulesBucket = {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  false_signal_rate_pct: number;
  total_pnl_usdt: number;
  average_return_per_trade_usdt: number;
  average_return_per_trade_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number | null;
  ml_changed_action_count: number;
};

export type MlVsRulesResponse = {
  mode: string;
  overall: MlVsRulesBucket;
  buckets: {
    rule_only: MlVsRulesBucket;
    combined: MlVsRulesBucket;
    ml_override: MlVsRulesBucket;
    other: MlVsRulesBucket;
  };
};

export type TradeEvaluationItem = {
  position_id: number;
  symbol: string;
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number | null;
  entry_qty: number | null;
  exit_price: number | null;
  exit_qty: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  entry_reason: string | null;
  ml_reason: string | null;
  exit_reason: string | null;
  realized_pnl: number | null;
  realized_pnl_pct: number | null;
  rule_signal: DecisionAction | null;
  ml_signal: DecisionAction | null;
  ml_confidence: number | null;
  combined_signal: DecisionAction | null;
  override_reason: string | null;
  final_action: DecisionAction | null;
  ml_effect: string;
  ml_changed_final_action: boolean;
  ml_context: Record<string, unknown>;
  indicators: {
    adx: number | null;
    ema_fast: number | null;
    ema_slow: number | null;
    rsi: number | null;
    atr: number | null;
    risk_reward: number | null;
  };
};

export type TradeEvaluationResponse = {
  mode: string;
  count: number;
  items: TradeEvaluationItem[];
};

export const exchangeApi = {
  status: async (signal?: AbortSignal) => {
    const r = await http.get<SystemStatusResponse>("/status", {
      signal,
    });
    return r.data;
  },

  healthDb: async (signal?: AbortSignal) => {
    const r = await http.get<DbHealthResponse>("/health/db", {
      signal,
    });
    return r.data;
  },

  debug: async (signal?: AbortSignal) => {
    const r = await http.get<ExchangeDebugResponse>("/exchange/_debug", {
      signal,
    });
    return r.data;
  },

  decisionLatest: async (params: { symbol: string }, signal?: AbortSignal) => {
    const r = await http.get<ExchangeDecisionLatestResponse>(
      "/exchange/decisions/latest",
      {
        params,
        signal,
      },
    );
    return r.data;
  },

  decisionsRecent: async (
    params?: {
      symbol?: string;
      limit?: number;
      action?: "BUY" | "SELL" | "HOLD";
    },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeDecisionsRecentResponse>(
      "/exchange/decisions/recent",
      {
        params,
        signal,
      },
    );
    return r.data;
  },

  logsRecent: async (
    params?: {
      limit?: number;
      category?: string;
      level?: "INFO" | "WARN" | "ERROR";
      /** Binance symbol, e.g. BTCUSDT — scopes logs to this pair (+ system rows). */
      symbol?: string;
      all_symbols?: boolean;
    },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeLogsRecentResponse>(
      "/exchange/logs/recent",
      {
        params,
        signal,
      },
    );
    return r.data;
  },

  /** ML usage, runtime posture, diversity / entropy — must match backend JSON. */
  aiObservability: async (
    params?: { limit?: number; symbol?: string },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<AiObservabilityResponse>(
      "/exchange/performance/ai-observability",
      { params, signal },
    );
    return r.data;
  },

  /** Per-symbol model resolution + last_error (GET /status/... on API prefix). */
  modelHealthSymbols: async (
    params?: { load_model?: boolean },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ModelHealthSymbolsResponse>(
      "/status/model-health/symbols",
      { params, signal },
    );
    return r.data;
  },

  balance: async (signal?: AbortSignal) => {
    const r = await http.get<ExchangeBalanceResponse>("/exchange/balances", {
      signal,
    });
    return r.data;
  },

  balanceByAsset: async (asset: string, signal?: AbortSignal) => {
    const r = await http.get<ExchangeAssetBalanceResponse>(
      `/exchange/balance/${encodeURIComponent(asset)}`,
      {
        signal,
      },
    );
    return r.data;
  },

  positionsOpen: async (
    params?: { symbol?: string; mode?: ExecutionMode },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeOpenPositionsResponse>(
      "/exchange/positions/open",
      {
        params: {
          ...(params?.symbol ? { symbol: params.symbol } : {}),
          ...(params?.mode ? { mode: params.mode } : {}),
        },
        signal,
      },
    );
    return r.data;
  },

  positionsHistory: async (
    params?: { limit?: number; symbol?: string; mode?: ExecutionMode },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangePositionsHistoryResponse>(
      "/exchange/positions/history",
      {
        params,
        signal,
      },
    );
    return r.data;
  },

  openOrders: async (
    params: { symbol: string; mode?: ExecutionMode },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeOpenOrdersResponse>(
      "/exchange/orders/open",
      { params, signal },
    );
    return r.data;
  },

  allOrders: async (
    params: { symbol: string; limit?: number; mode?: ExecutionMode },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeAllOrdersResponse>(
      "/exchange/orders/all",
      {
        params,
        signal,
      },
    );
    return r.data;
  },

  trades: async (
    params?: { symbol?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeTradesResponse>("/exchange/trades", {
      params,
      signal,
    });
    return r.data;
  },

  proof: async (
    params?: { symbol?: string; mode?: ExecutionMode },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<ExchangeProofResponse>("/exchange/proof", {
      params,
      signal,
    });
    return r.data;
  },

  tickerPrice: async (symbol: string, signal?: AbortSignal) => {
    const r = await http.get<TickerPriceResponse>("/exchange/ticker/price", {
      params: { symbol },
      signal,
    });
    return r.data;
  },

  klines: async (
    params: { symbol: string; interval?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<KlinesResponse>("/exchange/klines", {
      params: {
        symbol: params.symbol,
        interval: params.interval ?? "1h",
        limit: params.limit ?? 100,
      },
      signal,
    });
    return r.data;
  },

  limitBuy: async (body: LimitBuyIn, signal?: AbortSignal) => {
    const r = await http.post<LimitBuyResponse>(
      "/exchange/order/limit-buy",
      body,
      {
        signal,
      },
    );
    return r.data;
  },
  autoTrade: async (body: AutoTradeIn, signal?: AbortSignal) => {
    const r = await http.post<AutoTradeResponse>("/exchange/auto-trade", body, {
      signal,
    });
    return r.data;
  },

  performance: async (params?: { mode?: string }, signal?: AbortSignal) => {
    const r = await http.get<PerformanceMetricsResponse>(
      "/exchange/performance",
      {
        params: { mode: params?.mode ?? "live" },
        signal,
      },
    );
    return r.data;
  },

  performanceSummary: async (
    params?: { mode?: string },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<PerformanceSummaryResponse>(
      "/exchange/performance/summary",
      {
        params: { mode: params?.mode ?? "live" },
        signal,
      },
    );
    return r.data;
  },

  mlVsRules: async (params?: { mode?: string }, signal?: AbortSignal) => {
    const r = await http.get<MlVsRulesResponse>(
      "/exchange/performance/ml-vs-rules",
      {
        params: { mode: params?.mode ?? "live" },
        signal,
      },
    );
    return r.data;
  },

  tradeEvaluation: async (params?: { mode?: string }, signal?: AbortSignal) => {
    const r = await http.get<TradeEvaluationResponse>(
      "/exchange/performance/trades/evaluation",
      {
        params: { mode: params?.mode ?? "live" },
        signal,
      },
    );
    return r.data;
  },

  cancelOrder: async (
    body: { symbol: string; order_id: number },
    signal?: AbortSignal,
  ) => {
    const r = await http.post<{ ok: boolean; cancelled: unknown }>(
      "/exchange/order/cancel",
      body,
      { signal },
    );
    return r.data;
  },

  liveRun: async (body: LiveRunIn, signal?: AbortSignal) => {
    const r = await http.post<LiveRunResponse>("/live/run", body, { signal });
    return r.data;
  },
};
