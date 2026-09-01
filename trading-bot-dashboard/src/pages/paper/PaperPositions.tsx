import { useEffect, useMemo, useState } from "react";
import { usePaperPositions, usePaperClose } from "../../apis/paper/usePaper";
import type { PaperPosition } from "../../apis/paper/paper.api";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function fmt(n: any, digits = 2) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "-";
  return x.toFixed(digits);
}

export default function PaperPositions() {
  const { data, loading, error, run } = usePaperPositions();
  const closeApi = usePaperClose();

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [openOnly, setOpenOnly] = useState<boolean | null>(true);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [selected, setSelected] = useState<PaperPosition | null>(null);

  // 🔁 fetch positions
  useEffect(() => {
    run({
      symbol: symbol.trim() || null,
      is_open: openOnly,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, openOnly]);

  const rows = useMemo<PaperPosition[]>(() => data?.positions ?? [], [data]);

  // ---------- Close flow ----------
  function openCloseModal(p: PaperPosition) {
    setSelected(p);
    setConfirmOpen(true);
  }

  function closeModal() {
    if (closeApi.loading) return;
    setConfirmOpen(false);
    setSelected(null);
  }

  async function confirmClose() {
    const id = Number(selected?.id);
    if (!Number.isFinite(id)) return;

    await closeApi.run({ position_id: id });

    setConfirmOpen(false);
    setSelected(null);

    run({
      symbol: symbol.trim() || null,
      is_open: openOnly,
    });
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900">
            Paper Positions
          </h2>
          <p className="text-sm text-zinc-600">
            Filter by symbol and open/closed
          </p>
        </div>

        <button
          onClick={() =>
            run({ symbol: symbol.trim() || null, is_open: openOnly })
          }
          disabled={loading}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 hover:bg-zinc-50 disabled:opacity-60"
        >
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Symbol</div>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="BTCUSDT"
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          />
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Status</div>
          <select
            value={openOnly === null ? "all" : openOnly ? "open" : "closed"}
            onChange={(e) => {
              const v = e.target.value;
              setOpenOnly(v === "all" ? null : v === "open");
            }}
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          >
            <option value="open">Open only</option>
            <option value="closed">Closed only</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white">
        {/* 🔄 Overlay Loader */}
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60 backdrop-blur-[1px]">
            <div className="flex items-center gap-3 rounded-xl border border-zinc-200 bg-white px-5 py-3 shadow-sm">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900" />
              <span className="text-sm font-medium text-zinc-700">
                Fetching positions…
              </span>
            </div>
          </div>
        )}

        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-700">
            <tr>
              <th className="px-4 py-3 text-left">Symbol</th>
              <th className="px-4 py-3 text-left">Side</th>
              <th className="px-4 py-3 text-left">Qty</th>
              <th className="px-4 py-3 text-left">Entry</th>
              <th className="px-4 py-3 text-left">Current</th>
              <th className="px-4 py-3 text-left">PnL</th>
              <th className="px-4 py-3 text-left">Open?</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-zinc-200">
            {loading && rows.length === 0
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {Array.from({ length: 8 }).map((__, j) => (
                      <td key={j} className="px-4 py-4">
                        <div className="h-3 w-full rounded bg-zinc-200" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((p, idx) => (
                  <tr key={p.id ?? idx} className="text-zinc-900">
                    <td className="px-4 py-3">{p.symbol}</td>
                    <td className="px-4 py-3">{p.side ?? "-"}</td>
                    <td className="px-4 py-3">{fmt(p.qty, 8)}</td>
                    <td className="px-4 py-3">{fmt(p.entry_price, 2)}</td>
                    <td className="px-4 py-3">{fmt(p.current_price, 2)}</td>
                    <td
                      className={cn(
                        "px-4 py-3 font-semibold",
                        Number(p.pnl) >= 0
                          ? "text-emerald-700"
                          : "text-red-700",
                      )}
                    >
                      {fmt(p.pnl, 2)}
                    </td>
                    <td className="px-4 py-3">
                      {p.is_open ? "true" : "false"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {p.is_open ? (
                        <button
                          onClick={() => openCloseModal(p)}
                          disabled={closeApi.loading}
                          className={cn(
                            "rounded-lg px-3 py-1.5 text-xs font-semibold text-white",
                            closeApi.loading
                              ? "bg-zinc-400 cursor-not-allowed"
                              : "bg-zinc-900 hover:bg-zinc-800",
                          )}
                        >
                          Close
                        </button>
                      ) : (
                        <span className="text-zinc-400 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}

            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10">
                  <div className="flex flex-col items-center justify-center gap-3 text-zinc-500">
                    <span className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900" />
                    <span className="text-sm font-medium">
                      Loading positions…
                    </span>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Close Modal */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <button
            className="absolute inset-0 bg-black/30"
            onClick={closeModal}
          />

          <div className="relative w-[92%] max-w-md rounded-2xl border bg-white p-5 shadow-xl">
            <div className="text-lg font-semibold">Close position?</div>

            <div className="mt-2 text-sm text-zinc-600">
              You are about to close{" "}
              <span className="font-semibold">{selected?.symbol}</span>
            </div>

            <div className="mt-4 rounded-xl border bg-zinc-50 px-4 py-3 text-sm">
              <div className="flex justify-between">
                <span>Entry</span>
                <span className="font-semibold">
                  {fmt(selected?.entry_price, 2)}
                </span>
              </div>
              <div className="mt-2 flex justify-between">
                <span>Qty</span>
                <span className="font-semibold">{fmt(selected?.qty, 8)}</span>
              </div>
            </div>

            {closeApi.error && (
              <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {closeApi.error}
              </div>
            )}

            <div className="mt-5 flex gap-2">
              <button
                onClick={closeModal}
                className="w-full rounded-xl border px-4 py-2 text-sm"
              >
                Cancel
              </button>

              <button
                onClick={confirmClose}
                disabled={closeApi.loading}
                className="w-full rounded-xl bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {closeApi.loading ? "Closing..." : "Yes, Close"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
