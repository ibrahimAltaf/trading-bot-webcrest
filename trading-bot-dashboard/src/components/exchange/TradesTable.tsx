import { useMemo } from "react";

export type TradeRow = {
  id?: number | string;
  tradeId?: number | string;
  orderId?: number | string;
  symbol?: string;
  side?: string;
  isBuyer?: boolean;
  price?: string | number;
  qty?: string | number;
  quantity?: string | number;
  quoteQty?: string | number;
  quote_qty?: string | number;
  commission?: string | number;
  commissionAsset?: string;
  time?: number;
  ts?: string;
  [key: string]: unknown;
};

function fmt(v: unknown, digits = 2): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function tradeTime(t: TradeRow): string {
  const ts = t.time ?? (t.ts ? new Date(t.ts).getTime() : null);
  if (ts == null) return "—";
  const d = new Date(Number(ts));
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function tradeSide(t: TradeRow): string {
  if (t.side) return String(t.side).toUpperCase();
  return t.isBuyer ? "BUY" : "SELL";
}

export default function TradesTable({
  trades,
  symbol,
  loading,
  maxRows = 50,
}: {
  trades: TradeRow[];
  symbol?: string;
  loading?: boolean;
  maxRows?: number;
}) {
  const list = useMemo(() => {
    const withTs = trades.map((t) => ({
      ...t,
      _sortTime: t.time ?? (t.ts ? new Date(t.ts).getTime() : 0),
    }));
    return withTs.sort((a, b) => (b._sortTime as number) - (a._sortTime as number)).slice(0, maxRows);
  }, [trades, maxRows]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-slate-600" />
      </div>
    );
  }

  if (list.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-slate-500">
        No trades{symbol ? ` for ${symbol}` : ""}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
          <tr>
            <th className="whitespace-nowrap py-3 pr-3">Time</th>
            <th className="whitespace-nowrap py-3 pr-3">Side</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Price</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Qty</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Quote</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Fee</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {list.map((t, i) => (
            <tr key={String(t.id ?? t.tradeId ?? i)} className="hover:bg-slate-50/80">
              <td className="py-2.5 pr-3 text-xs text-slate-500 whitespace-nowrap">
                {tradeTime(t)}
              </td>
              <td className="py-2.5 pr-3">
                <span
                  className={
                    tradeSide(t) === "BUY"
                      ? "font-semibold text-emerald-600"
                      : "font-semibold text-rose-600"
                  }
                >
                  {tradeSide(t)}
                </span>
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                {t.price != null ? fmt(t.price) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                {t.qty != null ? fmt(t.qty, 6) : t.quantity != null ? fmt(t.quantity, 6) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">
                {(t.quoteQty ?? t.quote_qty) != null ? fmt(t.quoteQty ?? t.quote_qty, 2) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-600">
                {t.commission != null ? `${fmt(t.commission)} ${t.commissionAsset ?? ""}`.trim() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
