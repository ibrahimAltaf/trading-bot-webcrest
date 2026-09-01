function fmt(v: unknown, digits = 4): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export type PositionItem = {
  id: number | string;
  symbol: string;
  entry_price?: number | null;
  entry_qty?: number | null;
  entry_ts?: string | null;
  exit_price?: number | null;
  exit_qty?: number | null;
  exit_ts?: string | null;
  pnl?: number | null;
  pnl_pct?: number | null;
};

export default function PositionsCard({
  positions,
  loading,
  error,
  title = "Open positions",
}: {
  positions: PositionItem[];
  loading?: boolean;
  error?: string;
  title?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        {loading && (
          <span className="text-xs text-slate-400">Loading…</span>
        )}
      </div>
      {error ? (
        <p className="text-sm text-rose-600">{error}</p>
      ) : positions.length === 0 ? (
        <p className="text-sm text-slate-500">No open positions</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500 uppercase">
              <tr>
                <th className="py-2 pr-3">Symbol</th>
                <th className="py-2 pr-3 text-right">Entry price</th>
                <th className="py-2 pr-3 text-right">Qty</th>
                <th className="py-2 pr-3 text-right">Entry time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {positions.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50/50">
                  <td className="py-2 pr-3 font-semibold text-slate-800">
                    {p.symbol}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-700">
                    {fmt(p.entry_price, 2)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-700">
                    {fmt(p.entry_qty, 6)}
                  </td>
                  <td className="py-2 pr-3 text-right text-xs text-slate-500 whitespace-nowrap">
                    {p.entry_ts
                      ? new Date(p.entry_ts).toLocaleString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
