"use client";

import { useMemo, useState } from "react";
import { useCoinMarkets } from "../../hooks/useCoinMarkets";
import { TrendingDown, TrendingUp } from "lucide-react";

function money(n: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    Number.isFinite(n) ? n : 0,
  );
}

function compact(n: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(
    Number.isFinite(n) ? n : 0,
  );
}

export default function CryptoPricesPanel() {
  const [q, setQ] = useState("");
  const currency = "USD" as const;

  // live data (cache 60s by default)
  const {
    data: coins,
    loading,
    error,
  } = useCoinMarkets({
    vsCurrency: "usd",
    perPage: 50,
    page: 1,
    ttlMs: 60_000, // bump to 2-5 min if you want fewer calls
  });

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return coins;
    return coins.filter(
      (c) =>
        c.name.toLowerCase().includes(s) || c.symbol.toLowerCase().includes(s),
    );
  }, [q, coins]);

  return (
    <div className="relative rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">
            Crypto prices (live)
          </div>
          <div className="mt-1 text-base font-semibold text-slate-900">
            Market snapshot
          </div>
        </div>

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search (BTC, ETH...)"
          className="h-9 w-56 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 shadow-sm outline-none focus:border-slate-300"
        />
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-800">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="grid grid-cols-12 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">
          <div className="col-span-5">Coin</div>
          <div className="col-span-3 text-right">Price</div>
          <div className="col-span-2 text-right">24h</div>
          <div className="col-span-2 text-right">Mkt Cap</div>
        </div>

        <div className="divide-y divide-slate-100">
          {loading && (
            <div className="px-3 py-10 text-center text-sm text-slate-500">
              Loading live prices…
            </div>
          )}

          {!loading &&
            filtered.map((c) => {
              const pct = c.price_change_percentage_24h;
              const pctClass = pct >= 0 ? "text-emerald-700" : "text-rose-700";
              const badgeBg = pct >= 0 ? "bg-emerald-50" : "bg-rose-50";

              return (
                <div
                  key={c.id}
                  className="grid grid-cols-12 items-center px-3 py-2"
                >
                  <div className="col-span-5 flex items-center gap-2">
                    <img
                      src={c.image}
                      alt={c.name}
                      className="h-7 w-7 rounded-full"
                      loading="lazy"
                    />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-900">
                        {c.name}
                      </div>
                      <div className="text-[11px] font-semibold text-slate-500">
                        {c.symbol.toUpperCase()}
                      </div>
                    </div>
                  </div>

                  <div className="col-span-3 text-right text-sm font-semibold text-slate-900">
                    {money(c.current_price, currency)}
                  </div>

                  <div className="col-span-2 flex justify-end">
                    <span
                      className={`inline-flex items-center rounded-full ${badgeBg} px-2 py-0.5 text-xs font-semibold ${pctClass}`}
                    >
                      {pct >= 0 ? (
                        <TrendingUp className="mr-1 h-3.5 w-3.5" />
                      ) : (
                        <TrendingDown className="mr-1 h-3.5 w-3.5" />
                      )}
                      {Math.abs(pct).toFixed(2)}%
                    </span>
                  </div>

                  <div className="col-span-2 text-right text-xs font-semibold text-slate-700">
                    {compact(c.market_cap)}
                  </div>
                </div>
              );
            })}

          {!loading && filtered.length === 0 && (
            <div className="px-3 py-10 text-center text-sm text-slate-500">
              No coins found.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
