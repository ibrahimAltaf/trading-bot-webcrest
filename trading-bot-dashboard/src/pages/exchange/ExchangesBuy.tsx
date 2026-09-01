import { useState } from "react";
import { useExchangeLimitBuy } from "../../apis/exchange/useExchange";

export default function ExchangesBuy() {
  const buy = useExchangeLimitBuy();

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      <div>
        <div className="text-sm font-semibold text-slate-900">Limit Buy</div>
        <div className="text-xs text-slate-500">Place a limit buy order</div>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Field label="Symbol" value={symbol} onChange={setSymbol} />
        <Field label="Price" value={price} onChange={setPrice} />
        <Field label="Quantity" value={quantity} onChange={setQuantity} />
      </div>

      <button
        disabled={buy.loading}
        onClick={() => buy.run({ symbol, price, quantity })}
        className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
      >
        {buy.loading ? "Placing..." : "Place Order"}
      </button>

      {buy.error && <ErrorBox text={buy.error} />}

      {buy.data && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
          <div>
            Status: <b>{buy.data.status}</b>
          </div>
          <div>Order ID: {buy.data.orderId}</div>
          <div>Executed: {buy.data.executedQty}</div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="col-span-12 md:col-span-4">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
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
