import { useState } from "react";
import { usePaperResetWallet } from "../../apis/paper/usePaper";

export default function PaperResetWallet() {
  const { data, loading, error, run } = usePaperResetWallet();
  const [initial, setInitial] = useState<number>(1000);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-zinc-900">
          Reset Paper Wallet
        </h2>
        <p className="text-sm text-zinc-600">
          This will clear paper positions/trades and start fresh.
        </p>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-4 space-y-3">
        <div className="text-xs text-zinc-500">Initial balance (USDT)</div>

        <input
          type="number"
          value={initial}
          onChange={(e) => setInitial(Number(e.target.value))}
          className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-zinc-200"
          min={0}
        />

        <button
          disabled={loading}
          onClick={() => run({ initial_balance: initial })}
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 hover:bg-red-100 disabled:opacity-60"
        >
          {loading ? "Resetting..." : "Reset Wallet"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
      )}

      {data && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-green-700">
          {data.message}
        </div>
      )}
    </div>
  );
}
