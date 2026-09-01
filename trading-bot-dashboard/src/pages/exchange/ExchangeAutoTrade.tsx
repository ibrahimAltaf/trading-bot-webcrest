import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { useExchangeAutoTrade } from "../../apis/exchange/useExchange";
import { http } from "../../lib/http";
import BalancePortfolioChart from "../../components/BalancePortfolioChart";
import {
  useExecutionModeQuery,
  useKillSwitchQuery,
} from "../../apis/safety/useSafety";
import {
  EXECUTION_MODE_LABELS,
  executionModeBadgeClass,
  type ExecutionMode,
} from "../../lib/executionMode";

const SYMBOLS = ["BTCUSDT", "ETHUSDT"] as const;
const TIMEFRAMES = ["4h", "1h", "1d"] as const;
const FORCE_SIGNALS = ["", "BUY", "SELL"] as const;

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function fmt(n: any, digits = 2) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "-";
  return x.toFixed(digits);
}

export default function ExchangeAutoTrade() {
  const autoApi = useExchangeAutoTrade();
  const modeQ = useExecutionModeQuery();
  const killQ = useKillSwitchQuery();

  const effectiveMode = (modeQ.data?.effective_mode ?? "live") as ExecutionMode;
  const isSimulated = Boolean(
    modeQ.data?.is_simulated ?? ["paper", "shadow"].includes(effectiveMode),
  );
  const killEngaged = Boolean(killQ.data?.kill_switch?.engaged);
  const isLive = effectiveMode === "live";
  const isShadow = effectiveMode === "shadow";

  const [symbol, setSymbol] = useState<(typeof SYMBOLS)[number]>("BTCUSDT");
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("1h");
  const [riskPct, setRiskPct] = useState("0.10");
  const [forceSignal, setForceSignal] =
    useState<(typeof FORCE_SIGNALS)[number]>(""); // optional
  const [localError, setLocalError] = useState<string | null>(null);

  // ── Scheduler toggle ──
  const [schedulerEnabled, setSchedulerEnabled] = useState(false);
  const [schedulerLoading, setSchedulerLoading] = useState(false);

  const fetchScheduler = useCallback(async () => {
    try {
      const { data } = await http.get("/settings/scheduler");
      setSchedulerEnabled(Boolean(data?.enabled));
    } catch {
      // silently ignore – toggle will just show "off"
    }
  }, []);

  useEffect(() => {
    fetchScheduler();
  }, [fetchScheduler]);

  async function toggleScheduler() {
    setSchedulerLoading(true);
    try {
      await http.put("/settings/scheduler", { enabled: !schedulerEnabled });
      setSchedulerEnabled((prev) => !prev);
    } catch (e: any) {
      setLocalError(e?.message || "Failed to toggle scheduler.");
    } finally {
      setSchedulerLoading(false);
    }
  }

  const risk_pct = useMemo(() => {
    const v = Number(riskPct);
    return Number.isFinite(v) ? v : 0;
  }, [riskPct]);

  const mergedError = localError ?? autoApi.error ?? null;

  async function onRun() {
    setLocalError(null);

    if (killEngaged) {
      return setLocalError(
        "Kill switch is engaged — release it in Settings before running auto-trade.",
      );
    }

    const sym = String(symbol).trim().toUpperCase();
    if (!sym) return setLocalError("Symbol is required (e.g., BTCUSDT).");
    if (!timeframe) return setLocalError("Timeframe is required.");
    if (!(risk_pct > 0 && risk_pct <= 1))
      return setLocalError("risk_pct must be between 0 and 1 (e.g., 0.10).");

    if (forceSignal && forceSignal !== "BUY" && forceSignal !== "SELL") {
      return setLocalError('force_signal must be "BUY" or "SELL".');
    }

    await autoApi.run({
      symbol: sym,
      timeframe,
      risk_pct,
      ...(forceSignal ? { force_signal: forceSignal } : {}),
    });
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-zinc-900">
              Exchange Auto-trade
            </h2>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-bold ring-1",
                executionModeBadgeClass(effectiveMode),
              )}
            >
              {EXECUTION_MODE_LABELS[effectiveMode] ?? effectiveMode}
            </span>
            {killEngaged && (
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-800">
                <ShieldAlert className="h-3.5 w-3.5" />
                KILL ON
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-zinc-600">
            {isShadow
              ? "Shadow mode: real Binance reads, simulated fills only (no live orders)."
              : isSimulated
                ? "Paper mode: fully simulated execution."
                : "Live mode: real orders on the connected exchange."}
          </p>
          <Link
            to="/settings"
            className="mt-1 inline-block text-xs font-semibold text-emerald-700 hover:underline"
          >
            Change mode / kill switch in Settings →
          </Link>
        </div>

        <div className="flex items-center gap-3">
          {/* Scheduler toggle */}
          <button
            type="button"
            onClick={toggleScheduler}
            disabled={schedulerLoading}
            className="group flex items-center gap-2 disabled:opacity-60"
            aria-label="Toggle adaptive auto-trade scheduler"
          >
            <span className="text-xs font-semibold text-zinc-600">
              {schedulerEnabled ? "Scheduler ON" : "Scheduler OFF"}
            </span>
            <span
              className={cn(
                "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200",
                schedulerEnabled ? "bg-emerald-500" : "bg-zinc-300",
                schedulerLoading && "opacity-60",
              )}
            >
              <span
                className={cn(
                  "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200",
                  schedulerEnabled ? "translate-x-5" : "translate-x-0",
                )}
              />
            </span>
          </button>

          <button
            onClick={onRun}
            disabled={autoApi.loading || killEngaged}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 hover:bg-zinc-50 disabled:opacity-60"
          >
            {autoApi.loading ? "Running…" : "Run"}
          </button>
        </div>
      </div>

      {isShadow && (
        <div className="flex gap-3 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-violet-600" />
          <div>
            <p className="font-semibold">Shadow mode active</p>
            <p className="mt-1 text-violet-800">
              Trades use real balances and filters but orders are simulated
              (order IDs like <code className="text-xs">shadow-*</code>). Use a
              low <strong>risk_pct</strong> (e.g. 0.001) if risk rejects large
              notionals. Verify in{" "}
              <Link to="/exchange/orders" className="font-semibold underline">
                Orders
              </Link>{" "}
              with mode Shadow selected.
            </p>
          </div>
        </div>
      )}

      {isLive && !killEngaged && (
        <div className="flex gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
          <div>
            <p className="font-semibold">Live execution</p>
            <p className="mt-1 text-rose-800">
              Auto-trade will place real orders. Confirm keys and limits in
              Settings before enabling the scheduler.
            </p>
          </div>
        </div>
      )}

      {killEngaged && (
        <div className="flex gap-3 rounded-xl border border-rose-300 bg-rose-100 p-4 text-sm text-rose-900">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">Kill switch engaged</p>
            <p className="mt-1">
              All trading is blocked until you release it in{" "}
              <Link to="/settings" className="font-semibold underline">
                Settings
              </Link>
              .
            </p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Symbol</div>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value as any)}
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Timeframe</div>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as any)}
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Risk % (0-1)</div>
          <input
            value={riskPct}
            onChange={(e) => setRiskPct(e.target.value)}
            placeholder="0.10"
            inputMode="decimal"
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          />
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="text-xs text-zinc-500">Force signal (optional)</div>
          <select
            value={forceSignal}
            onChange={(e) => setForceSignal(e.target.value as any)}
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-200"
          >
            <option value="">None</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
      </div>

      {/* Portfolio Chart */}
      <BalancePortfolioChart />

      {/* Error */}
      {mergedError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
          {mergedError}
        </div>
      )}

      {/* Result */}
      <div className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white p-4">
        {/* Overlay Loader */}
        {autoApi.loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60 backdrop-blur-[1px]">
            <div className="flex items-center gap-3 rounded-xl border border-zinc-200 bg-white px-5 py-3 shadow-sm">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900" />
              <span className="text-sm font-medium text-zinc-700">
                Running auto-trade…
              </span>
            </div>
          </div>
        )}

        {!autoApi.data ? (
          <div className="flex flex-col items-center justify-center gap-3 py-10 text-zinc-500">
            <span className="text-sm font-medium">No runs yet.</span>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-zinc-500 bg-zinc-50 px-4 py-3 text-sm">
              <div className="text-xs text-zinc-500">Signal</div>
              <div className="mt-1 font-semibold text-zinc-900">
                {autoApi.data.signal}
              </div>
            </div>

            <div className="rounded-xl border border-zinc-500 bg-zinc-50 px-4 py-3 text-sm">
              <div className="text-xs text-zinc-500">Executed</div>
              <div
                className={cn(
                  "mt-1 font-semibold",
                  autoApi.data.executed ? "text-emerald-700" : "text-zinc-900",
                )}
              >
                {autoApi.data.executed ? "Yes" : "No"}
              </div>
            </div>

            <div className="rounded-xl border border-zinc-500 bg-zinc-50 px-4 py-3 text-sm">
              <div className="text-xs text-zinc-500">Price</div>
              <div className="mt-1 font-semibold text-zinc-900">
                {fmt(autoApi.data.price, 2)}
              </div>
            </div>

            <div className="rounded-xl border border-zinc-500 bg-zinc-50 px-4 py-3 text-sm">
              <div className="text-xs text-zinc-500">Quantity</div>
              <div className="mt-1 font-semibold text-zinc-900">
                {autoApi.data.quantity != null
                  ? fmt(autoApi.data.quantity, 8)
                  : "—"}
              </div>
            </div>

            {!!autoApi.data.reason && (
              <div className="sm:col-span-2 rounded-xl border bg-white px-4 py-3 text-sm text-zinc-700">
                <span className="font-semibold text-zinc-900">Reason: </span>
                {autoApi.data.reason}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
