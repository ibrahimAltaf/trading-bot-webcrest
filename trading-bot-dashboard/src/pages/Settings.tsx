import { useEffect, useState } from "react";
import { toApiError } from "../lib/http";
import {
  EXECUTION_MODE_LABELS,
  executionModeBadgeClass,
  type ExecutionMode,
} from "../lib/executionMode";
import ModeSelector from "../components/safety/ModeSelector";
import {
  useClearExecutionModeMutation,
  useEngageKillSwitchMutation,
  useExchangeReconcileQuery,
  useExecutionModeQuery,
  useLiveReadinessQuery,
  useReleaseKillSwitchMutation,
  useSafetyLimitsQuery,
  useSafetyReconcileQuery,
  useSafetyStatusQuery,
  useSetExecutionModeMutation,
  useShadowAuditQuery,
  useOperationalReadinessQuery,
  usePhase2cStatusQuery,
  useActivatePhase2cMutation,
  useDeactivatePhase2cMutation,
} from "../apis/safety/useSafety";
import {
  useBinanceKeysQuery,
  useClearBinanceKeysMutation,
  usePutBinanceKeysMutation,
  useVerifyBinanceKeysMutation,
} from "../apis/admin/useAdmin";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export default function Settings() {
  const status = useSafetyStatusQuery();
  const modeQ = useExecutionModeQuery();
  const readiness = useLiveReadinessQuery();
  const limits = useSafetyLimitsQuery();
  const dbRecon = useSafetyReconcileQuery();
  const keys = useBinanceKeysQuery();
  const shadowAudit = useShadowAuditQuery("BTCUSDT");
  const opsReady = useOperationalReadinessQuery();
  const phase2c = usePhase2cStatusQuery();

  const [reconMode, setReconMode] = useState<ExecutionMode>("shadow");
  const exchangeRecon = useExchangeReconcileQuery(reconMode);

  const setMode = useSetExecutionModeMutation();
  const clearMode = useClearExecutionModeMutation();
  const engageKs = useEngageKillSwitchMutation();
  const releaseKs = useReleaseKillSwitchMutation();
  const putKeys = usePutBinanceKeysMutation();
  const verifyKeys = useVerifyBinanceKeysMutation();
  const clearKeys = useClearBinanceKeysMutation();
  const activateP2c = useActivatePhase2cMutation();
  const deactivateP2c = useDeactivatePhase2cMutation();

  const [modeReason, setModeReason] = useState("");
  const [ksReason, setKsReason] = useState("");
  const [p2cReason, setP2cReason] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [testnet, setTestnet] = useState(true);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const effective = (modeQ.data?.effective_mode ?? "paper") as ExecutionMode;
  const killEngaged = Boolean(status.data?.kill_switch?.engaged);

  useEffect(() => {
    if (keys.data?.effective_testnet != null) {
      setTestnet(Boolean(keys.data.effective_testnet));
    }
  }, [keys.data?.effective_testnet]);

  async function runAction(label: string, fn: () => Promise<unknown>) {
    setActionMsg(null);
    setActionErr(null);
    try {
      await fn();
      setActionMsg(label);
    } catch (e) {
      setActionErr(toApiError(e).message);
    }
  }

  return (
    <div className="space-y-6">
      {/* Live readiness banner */}
      <div
        className={cn(
          "rounded-2xl border p-5 shadow-sm",
          readiness.data?.ready_for_live_capital
            ? "border-emerald-200 bg-emerald-50"
            : "border-amber-200 bg-amber-50",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Live readiness</h2>
            <p className="mt-1 text-sm text-slate-600">
              {readiness.data?.ready_for_live_capital_reason ??
                "Loading safety checks…"}
            </p>
          </div>
          <span
            className={cn(
              "rounded-full px-3 py-1 text-sm font-bold",
              readiness.data?.ready_for_live_capital
                ? "bg-emerald-600 text-white"
                : "bg-amber-600 text-white",
            )}
          >
            {readiness.isLoading
              ? "…"
              : readiness.data?.ready_for_live_capital
                ? "READY"
                : "NOT READY"}
          </span>
        </div>
        {readiness.data?.checks?.length ? (
          <ul className="mt-4 grid gap-2 sm:grid-cols-2">
            {readiness.data.checks.map((c) => (
              <li
                key={c.name}
                className="rounded-lg border border-white/60 bg-white/70 px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-800">{c.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-semibold",
                      c.ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800",
                    )}
                  >
                    {c.ok ? "ok" : "fail"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-600">
                  {typeof c.detail === "string"
                    ? c.detail
                    : JSON.stringify(c.detail)}
                </p>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {/* Phase 2C Micro-Live */}
      <div
        className={cn(
          "rounded-2xl border p-5 shadow-sm",
          phase2c.data?.micro_live_enabled
            ? "border-rose-300 bg-rose-50"
            : "border-blue-200 bg-blue-50",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              Phase 2C — Controlled Micro-Live
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {phase2c.data?.status_label ?? "Loading…"}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Limits: 5 USDT/trade · max 2 positions · 6 USDT exposure ·
              1.50 USDT daily loss · 3 USDT cumulative loss. Adaptive AI
              thresholds unchanged — caps apply at risk layer only.
            </p>
          </div>
          <span
            className={cn(
              "rounded-full px-3 py-1 text-sm font-bold",
              phase2c.data?.micro_live_enabled
                ? "bg-rose-600 text-white"
                : "bg-blue-600 text-white",
            )}
          >
            {phase2c.data?.micro_live_enabled ? "LIVE ON" : "DISABLED"}
          </span>
        </div>
        {phase2c.data?.risk_state && (
          <div className="mt-4 grid gap-2 sm:grid-cols-4">
            {Object.entries(phase2c.data.risk_state).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-white/80 px-3 py-2 text-sm">
                <div className="text-xs text-slate-500">{k}</div>
                <div className="font-semibold">{String(v)}</div>
              </div>
            ))}
          </div>
        )}
        <input
          value={p2cReason}
          onChange={(e) => setP2cReason(e.target.value)}
          placeholder="Reason (required for activate/deactivate)"
          className="mt-4 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={
              activateP2c.isPending || !p2cReason.trim() || killEngaged
            }
            onClick={() =>
              runAction("Micro-live activated", () =>
                activateP2c.mutateAsync({
                  reason: p2cReason.trim(),
                  by: "dashboard",
                }),
              )
            }
            className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            Activate Micro-Live
          </button>
          <button
            type="button"
            disabled={deactivateP2c.isPending || !p2cReason.trim()}
            onClick={() =>
              runAction("Micro-live deactivated", () =>
                deactivateP2c.mutateAsync({
                  reason: p2cReason.trim(),
                  by: "dashboard",
                }),
              )
            }
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-white disabled:opacity-50"
          >
            Deactivate Micro-Live
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Execution mode */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-bold text-slate-900">Execution mode</h3>
          <p className="mt-1 text-xs text-slate-500">
            Paper / shadow / live — persisted on server (Phase 2A)
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-3 py-1 text-sm font-bold ring-1",
                executionModeBadgeClass(effective),
              )}
            >
              {EXECUTION_MODE_LABELS[effective] ?? effective}
            </span>
            {status.data?.is_simulated && (
              <span className="text-xs text-violet-600 font-semibold">
                simulated
              </span>
            )}
          </div>
          {modeQ.data?.override_active && (
            <p className="mt-2 text-xs text-slate-500">
              Runtime override active
            </p>
          )}
          <div className="mt-4">
            <ModeSelector
              value={effective}
              onChange={(m) =>
                runAction(`Mode set to ${m}`, () =>
                  setMode.mutateAsync({
                    mode: m,
                    reason: modeReason || `dashboard:${m}`,
                  }),
                )
              }
              disabled={setMode.isPending}
            />
          </div>
          <input
            value={modeReason}
            onChange={(e) => setModeReason(e.target.value)}
            placeholder="Reason (optional)"
            className="mt-3 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm"
          />
          <button
            type="button"
            disabled={clearMode.isPending}
            onClick={() =>
              runAction("Mode override cleared", () => clearMode.mutateAsync())
            }
            className="mt-3 text-xs font-semibold text-slate-600 underline hover:text-slate-900"
          >
            Clear override (use .env default)
          </button>
        </section>

        {/* Kill switch */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-bold text-slate-900">Kill switch</h3>
          <p className="mt-1 text-xs text-slate-500">
            Engage stops all trading immediately
          </p>
          <div className="mt-4">
            <span
              className={cn(
                "inline-flex rounded-full px-3 py-1 text-sm font-bold",
                killEngaged
                  ? "bg-rose-100 text-rose-800"
                  : "bg-emerald-100 text-emerald-800",
              )}
            >
              {killEngaged ? "ENGAGED" : "RELEASED"}
            </span>
            {status.data?.kill_switch?.reason && (
              <p className="mt-2 text-xs text-slate-600">
                {String(status.data.kill_switch.reason)}
              </p>
            )}
          </div>
          <input
            value={ksReason}
            onChange={(e) => setKsReason(e.target.value)}
            placeholder="Reason (required)"
            className="mt-3 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={engageKs.isPending || !ksReason.trim()}
              onClick={() =>
                runAction("Kill switch engaged", () =>
                  engageKs.mutateAsync({ reason: ksReason.trim() }),
                )
              }
              className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
            >
              Engage
            </button>
            <button
              type="button"
              disabled={releaseKs.isPending || !ksReason.trim()}
              onClick={() =>
                runAction("Kill switch released", () =>
                  releaseKs.mutateAsync({ reason: ksReason.trim() }),
                )
              }
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Release
            </button>
          </div>
        </section>
      </div>

      {/* Binance keys — Mainnet API */}
      <section className="rounded-xl border border-amber-200 bg-amber-50/30 p-5 shadow-sm">
        <h3 className="text-base font-bold text-slate-900">
          Binance API Keys (Mainnet / Testnet)
        </h3>
        <p className="mt-1 text-xs text-slate-600">
          Paste your Binance Spot API key &amp; secret here. Uncheck testnet for
          <strong> mainnet (real money)</strong>. Withdrawal permission must stay
          disabled on Binance. No server restart needed.
        </p>
        {keys.isLoading ? (
          <p className="mt-4 text-sm text-slate-500">Loading…</p>
        ) : keys.isError ? (
          <p className="mt-4 text-sm text-rose-600">
            {toApiError(keys.error).message}
          </p>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg bg-slate-50 p-3 text-sm">
              <div className="text-xs text-slate-500">Source</div>
              <div className="font-semibold">{keys.data?.source ?? "—"}</div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm">
              <div className="text-xs text-slate-500">Effective key</div>
              <div className="font-mono text-xs">
                {keys.data?.effective_api_key_masked ?? "—"}
              </div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm">
              <div className="text-xs text-slate-500">Secret set</div>
              <div className="font-semibold">
                {keys.data?.effective_api_secret_set ? "yes" : "no"}
              </div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm">
              <div className="text-xs text-slate-500">Testnet</div>
              <div className="font-semibold">
                {keys.data?.effective_testnet ? "yes" : "mainnet"}
              </div>
            </div>
          </div>
        )}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="New API key (optional)"
            className="h-10 rounded-lg border border-slate-200 px-3 text-sm font-mono"
            autoComplete="off"
          />
          <input
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            placeholder="New API secret (optional)"
            type="password"
            className="h-10 rounded-lg border border-slate-200 px-3 text-sm font-mono"
            autoComplete="off"
          />
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={testnet}
            onChange={(e) => setTestnet(e.target.checked)}
          />
          Use Binance testnet (uncheck for mainnet — real USDT)
        </label>
        {!testnet && (
          <p className="mt-2 rounded-lg bg-rose-100 px-3 py-2 text-xs font-semibold text-rose-800">
            Mainnet selected — real money. Ensure Phase 2C micro-live is activated
            and execution mode is Live before any real orders.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={putKeys.isPending}
            onClick={() =>
              runAction("Keys saved", () =>
                putKeys.mutateAsync({
                  ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                  ...(apiSecret.trim()
                    ? { api_secret: apiSecret.trim() }
                    : {}),
                  testnet,
                }),
              )
            }
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save overlay
          </button>
          <button
            type="button"
            disabled={verifyKeys.isPending}
            onClick={() =>
              runAction("Verify complete", async () => {
                const r = await verifyKeys.mutateAsync({
                  ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                  ...(apiSecret.trim()
                    ? { api_secret: apiSecret.trim() }
                    : {}),
                  testnet,
                });
                if (!r.ok) {
                  throw new Error(
                    typeof r.error === "string"
                      ? r.error
                      : JSON.stringify(r.error ?? r.stage),
                  );
                }
              })
            }
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50"
          >
            Verify against Binance
          </button>
          <button
            type="button"
            disabled={clearKeys.isPending}
            onClick={() =>
              runAction("Overlay cleared", () => clearKeys.mutateAsync())
            }
            className="rounded-lg border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
          >
            Clear overlay
          </button>
        </div>
        {verifyKeys.data && (
          <div className="mt-3">
            <JsonBlock data={verifyKeys.data} />
          </div>
        )}
      </section>

      {/* Shadow audit (Saad / 7-day soak) */}
      <section className="rounded-xl border border-violet-200 bg-violet-50/50 p-5 shadow-sm">
        <h3 className="text-base font-bold text-slate-900">Shadow execution audit</h3>
        <p className="mt-1 text-xs text-slate-600">
          Order IDs, client IDs, and why zero shadow trades may appear (HOLD vs executed BUY).
        </p>
        {shadowAudit.isLoading ? (
          <p className="mt-3 text-sm text-slate-500">Loading…</p>
        ) : shadowAudit.data ? (
          <div className="mt-4 space-y-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="rounded-lg bg-white px-3 py-2 text-sm">
                <div className="text-xs text-slate-500">Shadow order IDs</div>
                <div className="font-bold">
                  {String(shadowAudit.data.unique_shadow_order_ids_count ?? 0)}
                </div>
              </div>
              <div className="rounded-lg bg-white px-3 py-2 text-sm">
                <div className="text-xs text-slate-500">Client order IDs</div>
                <div className="font-bold">
                  {String(shadowAudit.data.unique_client_order_ids_count ?? 0)}
                </div>
              </div>
              <div className="rounded-lg bg-white px-3 py-2 text-sm">
                <div className="text-xs text-slate-500">Sizing fallback</div>
                <div className="font-bold">
                  {shadowAudit.data.shadow_sizing_used_fallback ? "yes" : "no"}
                </div>
              </div>
            </div>
            {shadowAudit.data.zero_orders_explanation ? (
              <p className="text-sm text-violet-900">
                {String(shadowAudit.data.zero_orders_explanation)}
              </p>
            ) : null}
            <JsonBlock data={shadowAudit.data} />
          </div>
        ) : null}
      </section>

      {/* Operational readiness */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-base font-bold text-slate-900">
          Operational readiness
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Restart recovery, duplicate prevention, alerts config
        </p>
        <div className="mt-3">
          {opsReady.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <JsonBlock data={opsReady.data} />
          )}
        </div>
      </section>

      {/* Risk limits */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-base font-bold text-slate-900">Risk limits</h3>
        {limits.data?.limits ? (
          <dl className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(limits.data.limits).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-slate-50 px-3 py-2">
                <dt className="text-xs text-slate-500">{k}</dt>
                <dd className="text-sm font-semibold text-slate-900">
                  {String(v)}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-2 text-sm text-slate-500">Loading…</p>
        )}
      </section>

      {/* Reconciliation */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-bold text-slate-900">DB reconcile</h3>
          <p className="mt-1 text-xs text-slate-500">
            Paper tracker vs database drift
          </p>
          <div className="mt-3">
            {dbRecon.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <JsonBlock data={dbRecon.data} />
            )}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-bold text-slate-900">
            Exchange reconcile
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            DB vs Binance (read-only)
          </p>
          <div className="mt-3">
            <ModeSelector
              value={reconMode}
              onChange={setReconMode}
              size="sm"
            />
          </div>
          <div className="mt-3">
            {exchangeRecon.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <JsonBlock data={exchangeRecon.data} />
            )}
          </div>
        </section>
      </div>

      {(actionMsg || actionErr) && (
        <div
          className={cn(
            "rounded-lg px-4 py-3 text-sm font-medium",
            actionErr
              ? "bg-rose-50 text-rose-800"
              : "bg-emerald-50 text-emerald-800",
          )}
        >
          {actionErr ?? actionMsg}
        </div>
      )}
    </div>
  );
}
