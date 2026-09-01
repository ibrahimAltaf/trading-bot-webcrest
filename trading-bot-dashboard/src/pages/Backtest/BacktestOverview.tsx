import { useEffect, useState } from "react";
import {
  useBacktestFingerprint,
  useBacktestHealth,
  useBacktestSignal,
} from "../../apis/backtest/useBacktest";
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

export default function BacktestOverview() {
  const [form] = useState<BacktestIn>(DEFAULT_BODY);

  const health = useBacktestHealth();
  const signal = useBacktestSignal();
  const fp = useBacktestFingerprint();

  const topError = health.error || signal.error || fp.error;

  // ✅ page open hote hi API hit
  useEffect(() => {
    health.run();
    signal.run(form.symbol, form.timeframe);
    fp.run(form.symbol, form.timeframe);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">Overview</div>
          <div className="mt-1 text-xs text-slate-500">
            Health, Signal, Fingerprint
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={health.run}
            className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
          >
            Health
          </button>
          <button
            onClick={() => signal.run(form.symbol, form.timeframe)}
            className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
          >
            Signal
          </button>
          <button
            onClick={() => fp.run(form.symbol, form.timeframe)}
            className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
          >
            Fingerprint
          </button>
        </div>
      </div>

      {topError && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {topError}
        </div>
      )}

      <div className="mt-3 grid grid-cols-12 gap-3">
        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-600">Health</div>
          <div className="mt-1 text-sm font-semibold text-slate-900">
            {health.loading
              ? "Loading..."
              : health.data
                ? health.data.status
                : "—"}
          </div>
        </div>

        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-600">Signal</div>
          <div className="mt-1 break-words text-sm font-semibold text-slate-900">
            {signal.loading
              ? "Loading..."
              : signal.data
                ? signal.data.signal
                : "—"}
          </div>
        </div>

        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-600">
            Fingerprint
          </div>
          <div className="mt-1 break-words text-sm font-semibold text-slate-900">
            {fp.loading ? "Loading..." : fp.data ? fp.data.path : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}
