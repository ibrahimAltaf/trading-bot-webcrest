// src/pages/Backtest/BacktestRun.tsx
  import { useState } from "react";
  import { useBacktestRunAndPoll } from "../../apis/backtest/useBacktest";
  import type { BacktestIn } from "../../apis/backtest/backtest.api";

const DEFAULT_BODY: BacktestIn = {
  symbol: "BTCUSDT",
  timeframe: "1h",
  seed: 42,
  initial_balance: 10000,
  risk: {
    cooldown_minutes_after_loss: 60,
    fee_pct: 0.001,
    max_position_pct: 0.1,
    stop_loss_pct: 0.02,
    take_profit_pct: 0.04,
  },
};

export default function BacktestRun() {
  const [form, setForm] = useState<BacktestIn>(DEFAULT_BODY);
  const run = useBacktestRunAndPoll();

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Run backtest
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Run a backtest and view its live status
          </div>
        </div>

        <button
          disabled={run.creating}
          onClick={() => run.runBacktest(form)}
          className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {run.creating ? "Starting..." : "Run"}
        </button>
      </div>

      <div className="grid grid-cols-12 gap-3">
        {/* Symbol text input */}
        <div className="col-span-12 md:col-span-3">
          <label className="text-xs font-semibold text-slate-600">Symbol</label>
          <input
            type="text"
            value={form.symbol}
            onChange={(e) => setForm((p) => ({ ...p, symbol: e.target.value }))}
            className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
          />
        </div>

        {/* Timeframe text input */}
        <div className="col-span-12 md:col-span-3">
          <label className="text-xs font-semibold text-slate-600">
            Timeframe
          </label>
          <input
            type="text"
            value={form.timeframe}
            onChange={(e) =>
              setForm((p) => ({ ...p, timeframe: e.target.value }))
            }
            className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
          />
        </div>

        <div className="col-span-12 md:col-span-3">
          <label className="text-xs font-semibold text-slate-600">Seed</label>
          <input
            type="number"
            value={form.seed}
            onChange={(e) =>
              setForm((p) => ({ ...p, seed: Number(e.target.value) || 0 }))
            }
            className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
          />
        </div>

        <div className="col-span-12 md:col-span-3">
          <label className="text-xs font-semibold text-slate-600">
            Initial balance
          </label>
          <input
            type="number"
            value={form.initial_balance}
            onChange={(e) =>
              setForm((p) => ({
                ...p,
                initial_balance: Number(e.target.value) || 0,
              }))
            }
            className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
          />
        </div>
      </div>

      {run.error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {run.error}
        </div>
      )}

      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold text-slate-600">Run status</div>
        <div className="mt-1 text-sm font-semibold text-slate-900">
          Run ID: {run.runId ?? "—"} | Status: {run.run?.status ?? "—"}
        </div>

        {run.run && (
          <div className="mt-2 grid grid-cols-12 gap-2 text-xs">
            <div className="col-span-6 md:col-span-3 text-slate-600">
              Final:{" "}
              <span className="font-semibold text-slate-900">
                {run.run.final_balance ?? "—"}
              </span>
            </div>
            <div className="col-span-6 md:col-span-3 text-slate-600">
              Return %:{" "}
              <span className="font-semibold text-slate-900">
                {run.run.total_return_pct ?? "—"}
              </span>
            </div>
            <div className="col-span-6 md:col-span-3 text-slate-600">
              DD %:{" "}
              <span className="font-semibold text-slate-900">
                {run.run.max_drawdown_pct ?? "—"}
              </span>
            </div>
            <div className="col-span-6 md:col-span-3 text-slate-600">
              Trades:{" "}
              <span className="font-semibold text-slate-900">
                {run.run.trades_count ?? "—"}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
