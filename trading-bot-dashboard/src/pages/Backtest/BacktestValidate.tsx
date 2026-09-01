import { useState } from "react";
import type { BacktestIn } from "../../apis/backtest/backtest.api";
import { useBacktestValidate } from "../../apis/backtest/useBacktest";

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

export default function BacktestValidate() {
  const [form] = useState<BacktestIn>(DEFAULT_BODY);
  const validate = useBacktestValidate();

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      <div>
        <div className="text-sm font-semibold text-slate-900">
          Validate Strategy
        </div>
        <div className="text-xs text-slate-500">
          Run multiple backtests to check reproducibility
        </div>
      </div>

      <button
        disabled={validate.loading}
        onClick={() => validate.run(form)}
        className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
      >
        {validate.loading ? "Starting..." : "Start Validation"}
      </button>

      {validate.error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {validate.error}
        </div>
      )}

      {validate.data && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-2 text-sm">
          <div>
            <span className="font-semibold">Batch ID:</span>{" "}
            {validate.data.batch_id}
          </div>
          <div>
            <span className="font-semibold">Runs:</span>{" "}
            {validate.data.runs_count}
          </div>
          <div>
            <span className="font-semibold">Run IDs:</span>{" "}
            {validate.data.run_ids.join(", ")}
          </div>
          <div className="text-xs text-slate-500">
            Poll each run via <code>/backtest/:id</code> then compare results.
          </div>
        </div>
      )}
    </div>
  );
}
