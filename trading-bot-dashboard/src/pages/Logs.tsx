import { useEffect, useMemo, useState } from "react";
import { useLogsList } from "../apis/api-logs/useLogs";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function levelBadge(level?: string) {
  const lv = (level ?? "").toUpperCase();
  const base = "rounded-full px-2 py-0.5 text-xs font-semibold";
  if (lv === "ERROR") return cn(base, "bg-rose-50 text-rose-700");
  if (lv === "WARN" || lv === "WARNING")
    return cn(base, "bg-amber-50 text-amber-700");
  if (lv === "DEBUG") return cn(base, "bg-slate-100 text-slate-700");
  return cn(base, "bg-emerald-50 text-emerald-700");
}

export default function Logs() {
  const logs = useLogsList();
  const [limit, setLimit] = useState(50);

  useEffect(() => {
    logs.run(50);
  }, []);

  const items = useMemo(() => logs.data?.items ?? [], [logs.data]);

  const isInitialLoading = logs.loading && items.length === 0;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">Logs</div>
            <div className="mt-1 text-xs text-slate-500">
              Recent system events (exchange/backtest/paper)
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-slate-600">
                Limit
              </label>
              <input
                type="number"
                min={1}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value) || 50)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") logs.run(limit);
                }}
                className="h-9 w-[110px] rounded-lg border border-slate-200 px-3 text-sm font-medium"
              />
            </div>

            <button
              disabled={logs.loading}
              onClick={() => logs.run(limit)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 disabled:opacity-60"
            >
              {logs.loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {logs.error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {logs.error}
          </div>
        )}

        {/* Table */}
        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
          <div className="grid grid-cols-12 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">
            <div className="col-span-1">ID</div>
            <div className="col-span-3">Time</div>
            <div className="col-span-1">Level</div>
            <div className="col-span-2">Category</div>
            <div className="col-span-3">Message</div>
            <div className="col-span-1">Symbol</div>
            <div className="col-span-1">TF</div>
          </div>

          <div className="divide-y divide-slate-100">
            {isInitialLoading && (
              <div className="px-3 py-10 text-center text-sm text-slate-500">
                Loading logs...
              </div>
            )}

            {!isInitialLoading &&
              items.map((it) => (
                <div
                  key={it.id}
                  className="grid grid-cols-12 items-start px-3 py-2 text-sm"
                >
                  <div className="col-span-1 font-semibold text-slate-900">
                    {it.id}
                  </div>

                  <div className="col-span-3 text-slate-600">
                    {it.ts ? new Date(it.ts).toLocaleString() : "—"}
                  </div>

                  <div className="col-span-1">
                    <span className={levelBadge(it.level)}>{it.level}</span>
                  </div>

                  <div className="col-span-2 font-semibold text-slate-900">
                    {it.category}
                  </div>

                  <div className="col-span-3 break-words text-slate-700">
                    {it.message}
                  </div>

                  <div className="col-span-1 text-slate-700">
                    {it.symbol ?? "—"}
                  </div>

                  <div className="col-span-1 text-slate-700">
                    {it.timeframe ?? "—"}
                  </div>
                </div>
              ))}

            {!isInitialLoading && !logs.loading && items.length === 0 && (
              <div className="px-3 py-10 text-center text-sm text-slate-500">
                No log entries yet.
              </div>
            )}

            {logs.loading && items.length > 0 && (
              <div className="flex items-center justify-center border-t border-slate-100 px-3 py-3">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
