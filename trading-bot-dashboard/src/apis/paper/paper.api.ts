// src/apis/paper/paper.api.ts
import { http } from "../../lib/http";

export type PaperMode = "simulate" | "live" | string;

export type PaperRunIn = {
  symbol: string; // "BTCUSDT"
  timeframe: string; // "1h"
  mode: PaperMode; // "simulate"
  balance: number; // 1000
  max_position_pct: number; // 0.1
  stop_loss_pct: number; // 0.02
  take_profit_pct: number; // 0.04
  fee_pct: number; // 0.001
  entry_offset_pct: number; // 0.001
  override_usdt_balance?: number; // 1 (optional)
};

export type PaperPlan = {
  balance_used: number;
  max_position_pct: number;
  spend: number;
  limit_entry_price: number;
  raw_qty: number;
  stop_loss_price: number;
  take_profit_price: number;
  fee_pct: number;
};

export type PaperResult = {
  status: string; // "filled" | "rejected" | "partial" | etc.
  price: number;
  qty: number;
  balance: number;
};

export type PaperRunResponse = {
  ok: boolean;
  mode: PaperMode;
  symbol: string;
  market_price: number;
  plan: PaperPlan;
  result: PaperResult;
};

export type PaperPriceResponse = {
  ok: boolean;
  symbol: string;
  price: number;
  source?: string; // "binance_testnet"
};

/** NEW: /paper/positions */
export type PaperPosition = {
  // Backend shape wasn’t provided in swagger snippet (it shows "string"),
  // so keep it flexible but still typed enough for UI.
  id?: string;
  symbol?: string;
  is_open?: boolean;

  side?: "long" | "short" | string;
  qty?: number;
  entry_price?: number;
  current_price?: number;

  pnl?: number;
  pnl_pct?: number;

  opened_at?: string; // ISO
  closed_at?: string | null; // ISO
  meta?: Record<string, any>;
};

export type PaperPositionsResponse = {
  ok?: boolean;
  symbol?: string | null;
  is_open?: boolean | null;
  positions: PaperPosition[];
  summary?: Record<string, any>;
};

/** NEW: /paper/wallet */
export type PaperWalletResponse = {
  ok?: boolean;
  usdt_balance: number;
  equity?: number;
  open_positions_count?: number;
  used_margin?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  summary?: Record<string, any>;
};

/** NEW: /paper/reset-wallet */
export type PaperResetWalletIn = {
  initial_balance: number; // 1000
};
export type PaperResetWalletResponse = {
  ok?: boolean;
  usdt_balance?: number;
  message?: string;
  wallet?: PaperWalletResponse;
};

// ✅ NEW: /paper/close
export type PaperCloseIn = {
  position_id: number; // 2773
  exit_price?: number; // optional; if omitted backend uses market price
};

export type PaperCloseResponse = {
  ok: boolean;
  position_id: number;
  symbol: string;

  entry_price: number;
  entry_qty: number;
  entry_ts: string; // ISO

  exit_price: number;
  exit_qty: number;
  exit_ts: string; // ISO

  pnl: number;
  pnl_pct: number;

  entry_cost: number;
  exit_value: number;
};

export const paperApi = {
  run: async (body: PaperRunIn, signal?: AbortSignal) => {
    const r = await http.post<PaperRunResponse>("/paper/run", body, { signal });
    return r.data;
  },

  price: async (symbol: string, signal?: AbortSignal) => {
    const r = await http.get<PaperPriceResponse>(`/paper/price/${symbol}`, {
      signal,
    });
    return r.data;
  },

  // ✅ NEW: positions with query params
  positions: async (
    params?: { symbol?: string | null; is_open?: boolean | null },
    signal?: AbortSignal,
  ) => {
    const r = await http.get<PaperPositionsResponse>("/paper/positions", {
      params: {
        symbol: params?.symbol ?? undefined,
        is_open: params?.is_open ?? undefined,
      },
      signal,
    });
    return r.data;
  },

  // ✅ NEW: wallet
  wallet: async (signal?: AbortSignal) => {
    const r = await http.get<PaperWalletResponse>("/paper/wallet", { signal });
    return r.data;
  },

  // ✅ NEW: reset wallet
  resetWallet: async (body: PaperResetWalletIn, signal?: AbortSignal) => {
    const r = await http.post<PaperResetWalletResponse>(
      "/paper/reset-wallet",
      body,
      { signal },
    );
    return r.data;
  },

  // ✅ NEW: close position
  close: async (body: PaperCloseIn, signal?: AbortSignal) => {
    const r = await http.post<PaperCloseResponse>("/paper/close", body, {
      signal,
    });
    return r.data;
  },
};
