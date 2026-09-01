import { useState } from "react";
import type { PaperRunIn } from "../../apis/paper/paper.api";
import { usePaperRun } from "../../apis/paper/usePaper";

const DEFAULT_BODY: PaperRunIn = {
  symbol: "BTCUSDT",
  timeframe: "1h",
  mode: "simulate",
  balance: 1000,
  max_position_pct: 0.1,
  stop_loss_pct: 0.02,
  take_profit_pct: 0.04,
  fee_pct: 0.001,
  entry_offset_pct: 0.001,
  override_usdt_balance: 1,
};

export default function PaperRun() {
  const [form, setForm] = useState<PaperRunIn>(DEFAULT_BODY);
  const run = usePaperRun();

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Run paper trade
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Execute a single paper trade (simulate) and view plan + result
          </div>
        </div>

        <button
          disabled={run.loading}
          onClick={() => run.run(form)}
          className="h-9 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {run.loading ? "Running..." : "Run"}
        </button>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <FieldText
          label="Symbol"
          value={form.symbol}
          onChange={(v) => setForm((p) => ({ ...p, symbol: v }))}
        />
        <FieldText
          label="Timeframe"
          value={form.timeframe}
          onChange={(v) => setForm((p) => ({ ...p, timeframe: v }))}
        />

        <FieldText
          label="Mode"
          value={String(form.mode)}
          onChange={(v) => setForm((p) => ({ ...p, mode: v }))}
        />

        <FieldNumber
          label="Balance"
          value={form.balance}
          onChange={(n) => setForm((p) => ({ ...p, balance: n }))}
        />

        <FieldNumber
          label="Max position %"
          value={form.max_position_pct}
          step="0.01"
          onChange={(n) => setForm((p) => ({ ...p, max_position_pct: n }))}
        />

        <FieldNumber
          label="Stop loss %"
          value={form.stop_loss_pct}
          step="0.001"
          onChange={(n) => setForm((p) => ({ ...p, stop_loss_pct: n }))}
        />

        <FieldNumber
          label="Take profit %"
          value={form.take_profit_pct}
          step="0.001"
          onChange={(n) => setForm((p) => ({ ...p, take_profit_pct: n }))}
        />

        <FieldNumber
          label="Fee %"
          value={form.fee_pct}
          step="0.0001"
          onChange={(n) => setForm((p) => ({ ...p, fee_pct: n }))}
        />

        <FieldNumber
          label="Entry offset %"
          value={form.entry_offset_pct}
          step="0.0001"
          onChange={(n) => setForm((p) => ({ ...p, entry_offset_pct: n }))}
        />

        <FieldNumber
          label="Override USDT balance"
          value={form.override_usdt_balance ?? 0}
          step="1"
          onChange={(n) =>
            setForm((p) => ({
              ...p,
              override_usdt_balance: n,
            }))
          }
        />
      </div>

      {run.error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {run.error}
        </div>
      )}

      {/* Result */}
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold text-slate-600">Output</div>

        {!run.loading && !run.data && (
          <div className="mt-1 text-sm text-slate-600">—</div>
        )}

        {run.loading && (
          <div className="mt-1 text-sm font-semibold text-slate-900">
            Running...
          </div>
        )}

        {run.data?.ok && (
          <div className="mt-2 grid grid-cols-12 gap-2 text-xs">
            <div className="col-span-12 md:col-span-3 text-slate-600">
              Status:{" "}
              <span className="font-semibold text-slate-900">
                {run.data.result.status}
              </span>
            </div>
            <div className="col-span-12 md:col-span-3 text-slate-600">
              Price:{" "}
              <span className="font-semibold text-slate-900">
                {run.data.result.price}
              </span>
            </div>
            <div className="col-span-12 md:col-span-3 text-slate-600">
              Qty:{" "}
              <span className="font-semibold text-slate-900">
                {run.data.result.qty}
              </span>
            </div>
            <div className="col-span-12 md:col-span-3 text-slate-600">
              Balance:{" "}
              <span className="font-semibold text-slate-900">
                {run.data.result.balance}
              </span>
            </div>

            <div className="col-span-12 mt-2 rounded-lg border border-slate-200 bg-white p-3">
              <div className="text-[11px] font-semibold text-slate-600">
                Plan
              </div>
              <div className="mt-1 grid grid-cols-12 gap-2 text-xs">
                <div className="col-span-6 md:col-span-3 text-slate-600">
                  Spend:{" "}
                  <span className="font-semibold text-slate-900">
                    {run.data.plan.spend}
                  </span>
                </div>
                <div className="col-span-6 md:col-span-3 text-slate-600">
                  Limit entry:{" "}
                  <span className="font-semibold text-slate-900">
                    {run.data.plan.limit_entry_price}
                  </span>
                </div>
                <div className="col-span-6 md:col-span-3 text-slate-600">
                  SL:{" "}
                  <span className="font-semibold text-slate-900">
                    {run.data.plan.stop_loss_price}
                  </span>
                </div>
                <div className="col-span-6 md:col-span-3 text-slate-600">
                  TP:{" "}
                  <span className="font-semibold text-slate-900">
                    {run.data.plan.take_profit_price}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FieldText({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="col-span-12 md:col-span-3">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
      />
    </div>
  );
}

function FieldNumber({
  label,
  value,
  onChange,
  step,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: string;
}) {
  return (
    <div className="col-span-12 md:col-span-3">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step ?? "1"}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-medium"
      />
    </div>
  );
}
