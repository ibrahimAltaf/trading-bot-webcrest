import { useState } from "react";
import { useTradesQuery } from "../../apis/exchange/useExchangeQueries";
import TradesTable from "../../components/exchange/TradesTable";

export default function ExchangesTrades() {
  const [symbol, setSymbol] = useState("BTCUSDT");

  const trades = useTradesQuery({ symbol, limit: 100 });
  const tradesList = trades.data?.trades ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Trades</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Filled trade history (executions) for the selected symbol
            </p>
          </div>
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
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">
            Trade history — {symbol}
          </h3>
          {trades.isFetching && (
            <span className="text-xs text-slate-400">Updating…</span>
          )}
        </div>
        <div className="max-h-[600px] overflow-auto">
          <TradesTable
            trades={tradesList}
            symbol={symbol}
            loading={trades.isLoading}
            maxRows={100}
          />
        </div>
      </div>
    </div>
  );
}
