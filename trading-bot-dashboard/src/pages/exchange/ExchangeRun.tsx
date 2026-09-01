import { useEffect, useMemo, useState } from "react";
import {
  useExchangeBalance,
  useLiveRun,
} from "../../apis/exchange/useExchange";

export default function ExchangesLiveRun() {
  const balance = useExchangeBalance();
  const liveRun = useLiveRun();

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [usdtAmount, setUsdtAmount] = useState("20"); // keep string for input

  // run balance FIRST (on mount)
  useEffect(() => {
    balance.run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = () => {
    const amt = Number(usdtAmount);

    if (!symbol || symbol.length < 5) return;
    if (!Number.isFinite(amt) || amt <= 0) return;

    liveRun.run({ symbol, usdt_amount: amt });
  };

  const result = liveRun.data?.result;

  // Only show USDT + BTC
  const filteredBalances = useMemo(() => {
    const items = balance.data?.balances ?? [];
    const keep = new Set(["USDT", "BTC"]);
    return items.filter((b) => keep.has((b.asset || "").toUpperCase()));
  }, [balance.data]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      <div>
        <div className="text-sm font-semibold text-slate-900">
          Live Run (Binance Testnet)
        </div>
        <div className="text-xs text-slate-500">
          Places a real MARKET order via <code>/live/run</code> and returns a
          Binance <b>order_id</b>.
        </div>
      </div>

      {/* Balances (USDT + BTC only) */}
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-semibold text-slate-900">
            Balances (USDT, BTC)
          </div>

          <button
            disabled={balance.loading}
            onClick={() => balance.run()}
            className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-900 disabled:opacity-60"
          >
            {balance.loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {balance.error && <ErrorBox text={balance.error} />}

        {!balance.error && filteredBalances.length === 0 && (
          <div className="text-sm text-slate-600">
            {balance.loading ? "Loading..." : "No USDT/BTC balances found."}
          </div>
        )}

        {filteredBalances.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="py-2 pr-3">Asset</th>
                  <th className="py-2 pr-3">Free</th>
                  <th className="py-2 pr-3">Locked</th>
                  <th className="py-2 pr-3">Total</th>
                </tr>
              </thead>
              <tbody>
                {filteredBalances.map((b) => {
                  const total =
                    b.total ?? (Number(b.free) + Number(b.locked)).toString();

                  return (
                    <tr key={b.asset} className="border-t border-slate-200">
                      <td className="py-2 pr-3 font-semibold text-slate-900">
                        {b.asset}
                      </td>
                      <td className="py-2 pr-3">{b.free}</td>
                      <td className="py-2 pr-3">{b.locked}</td>
                      <td className="py-2 pr-3">{total}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Field label="Symbol" value={symbol} onChange={setSymbol} />
        <Field
          label="USDT Amount"
          value={usdtAmount}
          onChange={setUsdtAmount}
          inputMode="decimal"
        />
      </div>

      <button
        disabled={liveRun.loading}
        onClick={onSubmit}
        className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
      >
        {liveRun.loading ? "Placing..." : "Place Market Buy"}
      </button>

      {liveRun.error && <ErrorBox text={liveRun.error} />}

      {result && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm space-y-1">
          <div>
            Status: <b>{liveRun.data?.ok ? "OK" : "FAILED"}</b>
          </div>
          <div>Symbol: {result.symbol}</div>
          <div>
            Order ID: <b>{result.order_id}</b>
          </div>
          <div>Price: {result.price}</div>
          <div>Qty: {result.qty}</div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
}) {
  return (
    <div className="col-span-12 md:col-span-6">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={inputMode}
        className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm"
      />
    </div>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {text}
    </div>
  );
}
