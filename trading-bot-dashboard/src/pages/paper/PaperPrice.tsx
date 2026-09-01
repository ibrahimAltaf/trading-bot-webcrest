import { useEffect, useState } from "react";
import { usePaperPrice } from "../../apis/paper/usePaper";

export default function PaperPrice() {
  const price = usePaperPrice();
  const [symbol, setSymbol] = useState("BTCUSDT");

  // ✅ auto hit on mount + whenever symbol changes
  useEffect(() => {
    if (!symbol.trim()) return;
    price.run(symbol.trim());
  }, [symbol]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">Price</div>
          <div className="mt-1 text-xs text-slate-500">
            Fetch latest market price for a symbol
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-12 gap-3">
        <div className="col-span-12 md:col-span-4">
          <label className="text-xs font-semibold text-slate-600">Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="e.g. BTCUSDT"
            className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
          />
        </div>

        <div className="col-span-12 md:col-span-8 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-600">Value</div>
          <div className="mt-1 text-sm font-semibold text-slate-900">
            {price.loading
              ? "Loading..."
              : price.data?.ok
                ? price.data.price
                : "—"}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {price.data?.source ? `source: ${price.data.source}` : "—"}
          </div>
        </div>
      </div>

      {price.error && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {price.error}
        </div>
      )}
    </div>
  );
}
