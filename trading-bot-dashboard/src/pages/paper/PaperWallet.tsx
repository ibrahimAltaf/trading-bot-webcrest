import { useEffect } from "react";
import { usePaperWallet } from "../../apis/paper/usePaper";

export default function PaperWallet() {
  const { data, loading, error, run } = usePaperWallet();

  useEffect(() => {
    run();
  }, [run]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-900">Paper Wallet</h2>

        <button
          onClick={() => run()}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 hover:bg-zinc-50"
        >
          Refresh
        </button>
      </div>

      {loading && (
        <div className="rounded-xl border border-zinc-200 bg-white p-4 text-zinc-700">
          Loading...
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
      )}

      {data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Card label="USDT Balance" value={data.usdt_balance ?? "-"} />
          <Card label="Equity" value={data.equity ?? "-"} />
          <Card
            label="Open Positions"
            value={data.open_positions_count ?? "-"}
          />
          <Card label="Unrealized PnL" value={data.unrealized_pnl ?? "-"} />
          <Card label="Realized PnL" value={data.realized_pnl ?? "-"} />
          <Card label="Used Margin" value={data.used_margin ?? "-"} />
        </div>
      )}
    </div>
  );
}

function Card({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-zinc-900">
        {String(value)}
      </div>
    </div>
  );
}
