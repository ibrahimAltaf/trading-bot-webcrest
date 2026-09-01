function fmt(v: unknown, digits = 4): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export type BalanceItem = {
  asset: string;
  free: string;
  locked: string;
  total?: string;
};

export default function BalancesCard({
  balances,
  loading,
  error,
  title = "Balances",
  maxItems = 10,
}: {
  balances: BalanceItem[];
  loading?: boolean;
  error?: string;
  title?: string;
  maxItems?: number;
}) {
  const list = balances.slice(0, maxItems);

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
      ) : list.length === 0 ? (
        <p className="text-sm text-slate-500">No balances</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500 uppercase">
              <tr>
                <th className="py-2 pr-3">Asset</th>
                <th className="py-2 pr-3 text-right">Free</th>
                <th className="py-2 pr-3 text-right">Locked</th>
                <th className="py-2 pr-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.map((b) => {
                const free = Number(b.free);
                const locked = Number(b.locked);
                const total = b.total ?? String(free + locked);
                return (
                  <tr key={b.asset} className="hover:bg-slate-50/50">
                    <td className="py-2 pr-3 font-semibold text-slate-800">
                      {b.asset}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-slate-700">
                      {fmt(b.free, 6)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-slate-600">
                      {fmt(b.locked, 6)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums font-medium text-slate-800">
                      {fmt(total, 6)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
