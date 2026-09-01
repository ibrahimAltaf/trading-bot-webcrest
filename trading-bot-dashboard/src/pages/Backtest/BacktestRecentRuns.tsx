import React, { useEffect, useMemo, useRef, useState } from "react";
import { useBacktestRunsList } from "../../apis/backtest/useBacktest";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

const PAGE_SIZE = 10;

export default function BacktestRecentRuns() {
  const runs = useBacktestRunsList();

  const didInit = useRef(false);

  const [page, setPage] = useState(1); // 1-based
  const [symbol, setSymbol] = useState<string>("");
  const [status, setStatus] = useState<string>(""); // "", "success", "failed", etc.

  const skip = useMemo(() => (page - 1) * PAGE_SIZE, [page]);
  const limit = PAGE_SIZE;

  const total = runs.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const load = (p: number) => {
    const safePage = Math.min(Math.max(1, p), totalPages);
    setPage(safePage);

    runs.load({
      skip: (safePage - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      symbol: symbol.trim() ? symbol.trim() : null,
      status: status.trim() ? status.trim() : null,
    });
  };

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    load(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If filters change, reset to page 1 and reload
  useEffect(() => {
    if (!didInit.current) return;
    load(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, status]);

  const canPrev = page > 1;
  const canNext = page < totalPages;

  const pageNumbers = useMemo(() => {
    // show: 1 ... (p-1) p (p+1) ... last
    const out: number[] = [];
    const add = (n: number) => {
      if (!out.includes(n)) out.push(n);
    };

    add(1);
    add(page - 1);
    add(page);
    add(page + 1);
    add(totalPages);

    return out.filter((n) => n >= 1 && n <= totalPages).sort((a, b) => a - b);
  }, [page, totalPages]);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Recent runs
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Filter + paginate backtest runs
            </div>
          </div>

          <button
            onClick={() => load(page)}
            className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
          >
            Refresh
          </button>
        </div>

        {/* Filters */}
        <div className="mt-4 grid grid-cols-12 gap-3">
          <div className="col-span-12 md:col-span-4">
            <label className="text-xs font-semibold text-slate-600">
              Symbol
            </label>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="e.g. BTCUSDT"
              className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
            />
          </div>

          <div className="col-span-12 md:col-span-4">
            <label className="text-xs font-semibold text-slate-600">
              Status
            </label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-1 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium"
            >
              <option value="">All</option>
              <option value="success">success</option>
              <option value="failed">failed</option>
              <option value="running">running</option>
              <option value="queued">queued</option>
            </select>
          </div>

          <div className="col-span-12 md:col-span-4 flex items-end gap-2">
            <button
              onClick={() => {
                setSymbol("");
                setStatus("");
              }}
              className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
            >
              Clear
            </button>
          </div>
        </div>

        {runs.error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {runs.error}
          </div>
        )}

        {/* Table */}
        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
          <div className="grid grid-cols-12 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">
            <div className="col-span-1">ID</div>
            <div className="col-span-2">Symbol</div>
            <div className="col-span-1">TF</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-3">Started</div>
            <div className="col-span-1 text-right">Final</div>
            <div className="col-span-2 text-right">Return %</div>
          </div>

          <div className="divide-y divide-slate-100">
            {(runs.data?.items ?? []).map((r) => (
              <div
                key={r.id}
                className="grid grid-cols-12 items-center px-3 py-2 text-sm"
              >
                <div className="col-span-1 font-semibold text-slate-900">
                  {r.id}
                </div>
                <div className="col-span-2 font-semibold text-slate-900">
                  {r.symbol}
                </div>
                <div className="col-span-1 text-slate-600">{r.timeframe}</div>

                <div className="col-span-2">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
                    {r.status}
                  </span>
                </div>

                <div className="col-span-3 text-slate-600">
                  {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                </div>

                <div className="col-span-1 text-right font-semibold text-slate-900">
                  {typeof r.final_balance === "number"
                    ? r.final_balance.toFixed(2)
                    : "—"}
                </div>

                <div className="col-span-2 text-right font-semibold text-slate-900">
                  {typeof r.total_return_pct === "number"
                    ? `${r.total_return_pct.toFixed(2)}%`
                    : "—"}
                </div>
              </div>
            ))}

            {runs.loading && (
              <div className="px-3 py-10 text-center text-sm text-slate-500">
                Loading...
              </div>
            )}

            {!runs.loading && (runs.data?.items?.length ?? 0) === 0 && (
              <div className="px-3 py-10 text-center text-sm text-slate-500">
                No runs found.
              </div>
            )}
          </div>
        </div>

        {/* Pagination */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-600">
            Showing{" "}
            <span className="font-semibold text-slate-900">
              {total === 0 ? 0 : skip + 1}
            </span>{" "}
            -{" "}
            <span className="font-semibold text-slate-900">
              {Math.min(skip + limit, total)}
            </span>{" "}
            of <span className="font-semibold text-slate-900">{total}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              disabled={!canPrev || runs.loading}
              onClick={() => load(page - 1)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 disabled:opacity-60"
            >
              Prev
            </button>

            {pageNumbers.map((n, idx) => {
              const prev = pageNumbers[idx - 1];
              const showDots = idx > 0 && prev !== undefined && n - prev > 1;

              return (
                <React.Fragment key={n}>
                  {showDots && (
                    <span className="px-1 text-sm font-semibold text-slate-400">
                      …
                    </span>
                  )}
                  <button
                    disabled={runs.loading}
                    onClick={() => load(n)}
                    className={cn(
                      "h-9 w-9 rounded-lg border text-sm font-semibold",
                      n === page
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-800",
                      runs.loading && "opacity-60",
                    )}
                  >
                    {n}
                  </button>
                </React.Fragment>
              );
            })}

            <button
              disabled={!canNext || runs.loading}
              onClick={() => load(page + 1)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 disabled:opacity-60"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
