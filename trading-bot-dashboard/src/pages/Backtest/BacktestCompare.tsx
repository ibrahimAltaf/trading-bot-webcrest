// src/pages/Backtest/BacktestCompare.tsx
import { useState } from "react";
import { useBacktestCompare } from "../../apis/backtest/useBacktest";

export default function BacktestCompare() {
  const compare = useBacktestCompare();
  const [runIdsInput, setRunIdsInput] = useState("");

  const runIds = runIdsInput
    .split(",")
    ?.map((x) => Number(x.trim()))
    .filter((x) => Number.isFinite(x));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      <div>
        <div className="text-sm font-semibold text-slate-900">
          Compare Validation Runs
        </div>
        <div className="text-xs text-slate-500">
          Check if strategy results are reproducible
        </div>
      </div>

      <div>
        <label className="text-xs font-semibold text-slate-600">
          Run IDs (comma separated)
        </label>
        <input
          value={runIdsInput}
          onChange={(e) => setRunIdsInput(e.target.value)}
          placeholder="e.g. 80,81,82,83,84"
          className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
        />
      </div>

      <button
        disabled={compare.loading || runIds.length === 0}
        onClick={() => compare.run(runIds)}
        className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
      >
        {compare.loading ? "Comparing..." : "Compare"}
      </button>

      {compare.error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {compare.error}
        </div>
      )}

      {compare.data && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm space-y-1">
            <div>
              <span className="font-semibold">Reproducible:</span>{" "}
              {compare.data.reproducible ? "Yes ✅" : "No ❌"}
            </div>
            <div>
              <span className="font-semibold">Successful:</span>{" "}
              {compare.data.successful_runs} / {compare.data.total_runs}
            </div>
            <div className="text-slate-600">{compare.data.message}</div>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <div className="grid grid-cols-12 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">
              <div className="col-span-1">Run</div>
              <div className="col-span-2 text-right">Final</div>
              <div className="col-span-2 text-right">Return %</div>
              <div className="col-span-2 text-right">DD %</div>
              <div className="col-span-2 text-right">Trades</div>
              <div className="col-span-3">Status</div>
            </div>

            <div className="divide-y divide-slate-100">
              {compare.data.items.map((r) => (
                <div
                  key={r.run_id}
                  className="grid grid-cols-12 items-center px-3 py-2 text-sm"
                >
                  <div className="col-span-1 font-semibold">{r.run_id}</div>
                  <div className="col-span-2 text-right">
                    {r.final_balance?.toFixed(2) ?? "—"}
                  </div>
                  <div className="col-span-2 text-right">
                    {r.total_return_pct?.toFixed(2)}%
                  </div>
                  <div className="col-span-2 text-right">
                    {r.max_drawdown_pct?.toFixed(2)}%
                  </div>
                  <div className="col-span-2 text-right">
                    {r.trades_count ?? "—"}
                  </div>
                  <div className="col-span-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold">
                      {r.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
