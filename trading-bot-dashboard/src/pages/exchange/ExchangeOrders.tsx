import { useEffect, useState } from "react";
import {
  useOpenOrdersQuery,
  useAllOrdersQuery,
  useCancelOrderMutation,
} from "../../apis/exchange/useExchangeQueries";
import { useExecutionModeQuery } from "../../apis/safety/useSafety";
import ModeSelector from "../../components/safety/ModeSelector";
import type { ExecutionMode } from "../../lib/executionMode";
import OrdersTable from "../../components/exchange/OrdersTable";

const PAGE_LIMIT = 100;

export default function ExchangeOrders() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const modeQ = useExecutionModeQuery();
  const serverMode = (modeQ.data?.effective_mode ?? "live") as ExecutionMode;
  const [viewMode, setViewMode] = useState<ExecutionMode>("live");
  const [cancelLoadingOrderId, setCancelLoadingOrderId] = useState<number | null>(null);

  useEffect(() => {
    if (modeQ.data?.effective_mode) {
      setViewMode(modeQ.data.effective_mode as ExecutionMode);
    }
  }, [modeQ.data?.effective_mode]);

  const cancelOrder = useCancelOrderMutation({
    onMutate: (v) => setCancelLoadingOrderId(v.order_id),
    onSettled: () => setCancelLoadingOrderId(null),
  });

  const openOrders = useOpenOrdersQuery(symbol, viewMode);
  const allOrders = useAllOrdersQuery(symbol, PAGE_LIMIT, viewMode);

  const openList = openOrders.data?.orders ?? [];
  const allList = allOrders.data?.orders ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Orders</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Open and order history — same symbol for both tables
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <ModeSelector value={viewMode} onChange={setViewMode} size="sm" />
            <div className="flex items-center gap-3">
              <label className="text-xs font-semibold text-slate-600">
                Symbol
              </label>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                className="h-10 w-28 rounded-lg border border-slate-200 px-3 text-sm font-medium uppercase"
              />
            </div>
            {viewMode !== serverMode && (
              <span className="text-xs text-amber-600">
                Server mode: {serverMode}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Open orders */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">
            Open orders — {symbol}
          </h3>
          {openOrders.isFetching && (
            <span className="text-xs text-slate-400">Updating…</span>
          )}
        </div>
        <div className="max-h-80 overflow-auto">
          <OrdersTable
            orders={openList}
            symbol={symbol}
            loading={openOrders.isLoading}
            maxRows={50}
            showOrderId={true}
            onCancel={(orderId) => cancelOrder.mutate({ symbol, order_id: orderId })}
            cancelLoadingOrderId={cancelLoadingOrderId}
          />
        </div>
      </div>

      {/* All orders (history) */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">
            Order history — {symbol}
          </h3>
          {allOrders.isFetching && (
            <span className="text-xs text-slate-400">Updating…</span>
          )}
        </div>
        <div className="max-h-[500px] overflow-auto">
          <OrdersTable
            orders={allList}
            symbol={symbol}
            loading={allOrders.isLoading}
            maxRows={PAGE_LIMIT}
            showOrderId={true}
            onCancel={(orderId) => cancelOrder.mutate({ symbol, order_id: orderId })}
            cancelLoadingOrderId={cancelLoadingOrderId}
          />
        </div>
      </div>
    </div>
  );
}
