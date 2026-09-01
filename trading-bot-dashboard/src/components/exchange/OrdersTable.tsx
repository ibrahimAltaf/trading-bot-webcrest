import { useMemo } from "react";

export type OrderRow = {
  orderId: number | string;
  symbol?: string;
  side: string;
  type?: string;
  status: string;
  price?: string | number;
  origQty?: string | number;
  executedQty?: string | number;
  cummulativeQuoteQty?: string | number;
  time?: number;
  updateTime?: number;
  [key: string]: unknown;
};

function fmt(v: unknown, digits = 2): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function statusBadge(status: string) {
  const s = (status || "").toUpperCase();
  if (s === "FILLED")
    return "bg-emerald-100 text-emerald-800 border-emerald-200";
  if (s === "NEW" || s === "PARTIALLY_FILLED")
    return "bg-amber-100 text-amber-800 border-amber-200";
  if (s === "CANCELED" || s === "EXPIRED" || s === "PENDING_CANCEL")
    return "bg-slate-100 text-slate-600 border-slate-200";
  if (s === "REJECTED") return "bg-rose-100 text-rose-800 border-rose-200";
  return "bg-slate-100 text-slate-700 border-slate-200";
}

function orderTime(o: OrderRow): string {
  const t = o.time ?? o.updateTime;
  if (typeof t !== "number") return "—";
  const d = new Date(t);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function isCancelable(status: string): boolean {
  const s = (status || "").toUpperCase();
  return s === "NEW" || s === "PARTIALLY_FILLED";
}

export default function OrdersTable({
  orders,
  symbol,
  loading,
  maxRows = 50,
  showOrderId = true,
  compact: _compact = false,
  onCancel,
  cancelLoadingOrderId,
}: {
  orders: OrderRow[];
  symbol?: string;
  loading?: boolean;
  maxRows?: number;
  showOrderId?: boolean;
  compact?: boolean;
  onCancel?: (orderId: number, symbol: string) => void;
  cancelLoadingOrderId?: number | null;
}) {
  const list = useMemo(() => {
    const byTime = (o: OrderRow) => Number(o.time ?? o.updateTime ?? 0);
    return [...orders]
      .sort((a, b) => byTime(b) - byTime(a))
      .slice(0, maxRows);
  }, [orders, maxRows]);

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
        No orders{symbol ? ` for ${symbol}` : ""}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
          <tr>
            {showOrderId && (
              <th className="whitespace-nowrap py-3 pr-3">Order ID</th>
            )}
            <th className="whitespace-nowrap py-3 pr-3">Date</th>
            <th className="whitespace-nowrap py-3 pr-3">Type</th>
            <th className="whitespace-nowrap py-3 pr-3">Side</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Price</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Amount</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Filled</th>
            <th className="whitespace-nowrap py-3 pr-3 text-right">Total</th>
            <th className="whitespace-nowrap py-3 pl-3">Status</th>
            {onCancel && symbol && (
              <th className="whitespace-nowrap py-3 pl-3 text-right">Action</th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {list.map((o, i) => (
            <tr
              key={String(o.orderId ?? i)}
              className="hover:bg-slate-50/80"
            >
              {showOrderId && (
                <td className="py-2.5 pr-3 font-mono text-xs text-slate-600">
                  {String(o.orderId)}
                </td>
              )}
              <td className="py-2.5 pr-3 text-xs text-slate-500 whitespace-nowrap">
                {orderTime(o)}
              </td>
              <td className="py-2.5 pr-3 text-slate-700">
                {(o.type ?? "—").toString()}
              </td>
              <td className="py-2.5 pr-3">
                <span
                  className={
                    String(o.side).toUpperCase() === "BUY"
                      ? "font-semibold text-emerald-600"
                      : "font-semibold text-rose-600"
                  }
                >
                  {o.side}
                </span>
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                {o.price != null ? fmt(o.price) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                {o.origQty != null ? fmt(o.origQty, 6) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                {o.executedQty != null ? fmt(o.executedQty, 6) : "—"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">
                {o.cummulativeQuoteQty != null
                  ? fmt(o.cummulativeQuoteQty, 2)
                  : "—"}
              </td>
              <td className="py-2.5 pl-3">
                <span
                  className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${statusBadge(
                    o.status,
                  )}`}
                >
                  {(o.status ?? "—").toString()}
                </span>
              </td>
              {onCancel && symbol && (
                <td className="py-2.5 pl-3 text-right">
                  {isCancelable(String(o.status)) ? (
                    <button
                      type="button"
                      onClick={() =>
                        onCancel(Number(o.orderId), symbol)
                      }
                      disabled={
                        cancelLoadingOrderId === Number(o.orderId)
                      }
                      className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-50"
                    >
                      {cancelLoadingOrderId === Number(o.orderId)
                        ? "…"
                        : "Cancel"}
                    </button>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
