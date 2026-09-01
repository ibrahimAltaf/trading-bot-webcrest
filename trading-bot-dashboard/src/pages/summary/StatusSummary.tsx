import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useStartupCheck,
  useStatusSummary,
} from "../../apis/api-summary/useStatusSummary";
import { http, toApiError } from "../../lib/http";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function statusBadge(ok: boolean) {
  return cn(
    "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold",
    ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
  );
}

function schedulerBadge(state?: string | null) {
  const value = (state ?? "").toLowerCase();

  if (value === "running" || value === "enabled" || value === "active") {
    return "inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700";
  }

  if (value === "paused" || value === "stopped" || value === "disabled") {
    return "inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700";
  }

  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700";
}

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

function InfoCard({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div
        className={cn(
          "mt-2 text-sm font-semibold text-slate-900",
          mono && "font-mono text-[13px]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

export default function StatusSummary() {
  const summary = useStatusSummary();
  const startup = useStartupCheck();
  const [checklist, setChecklist] = useState<
    Array<{
      endpoint: string;
      ok: boolean;
      detail: string;
    }>
  >([]);
  const [checking, setChecking] = useState(false);

  const runChecklist = useCallback(async () => {
    setChecking(true);
    const endpoints = [
      "/status",
      "/status/summary",
      "/status/startup-check",
      "/status/model-health",
      "/status/model-health/symbols",
      "/status/runtime-paths",
      "/exchange/performance/ai-observability?symbol=BTCUSDT&limit=500",
      "/exchange/decisions/latest?symbol=BTCUSDT",
      "/exchange/decisions/recent?symbol=BTCUSDT&limit=20",
      "/exchange/balances",
      "/exchange/positions/open",
      "/exchange/positions/history?symbol=BTCUSDT&limit=20",
      "/exchange/orders/open?symbol=BTCUSDT",
      "/exchange/logs/recent?symbol=BTCUSDT&limit=50",
      "/exchange/proof?symbol=BTCUSDT",
      "/safety/status",
      "/safety/live-readiness",
      "/safety/kill-switch",
      "/safety/limits",
      "/safety/reconcile",
      "/safety/exchange-reconcile?mode=shadow",
      "/safety/shadow-audit?symbol=BTCUSDT",
      "/safety/operational-readiness",
      "/execution/mode",
      "/admin/binance-keys",
      "/exchange/proof?symbol=BTCUSDT&mode=shadow",
      "/exchange/orders/all?symbol=BTCUSDT&limit=5&mode=shadow",
    ] as const;

    // Sequential checks: avoids nginx/worker stampede during long client audits (100h+).
    const results: Array<{ endpoint: string; ok: boolean; detail: string }> =
      [];
    for (const endpoint of endpoints) {
      try {
        const res = await http.get(endpoint);
        const data = res?.data ?? {};
        const detail =
          typeof data?.count === "number"
            ? `count=${data.count}`
            : typeof data?.ok === "boolean"
              ? `ok=${String(data.ok)}`
              : `http=${res.status}`;
        results.push({ endpoint, ok: true, detail });
      } catch (e) {
        const err = toApiError(e);
        results.push({
          endpoint,
          ok: false,
          detail: err.status ? `${err.status}: ${err.message}` : err.message,
        });
      }
    }

    setChecklist(results);
    setChecking(false);
  }, []);

  const exportChecklistCsv = useCallback(() => {
    if (!checklist.length) return;
    const header = ["Endpoint", "Status", "Detail"];
    const rows = checklist.map((r) => [
      `/api${r.endpoint}`,
      r.ok ? "OK" : "FAILED",
      r.detail.replaceAll('"', '""'),
    ]);
    const csv = [header, ...rows]
      .map((cols) => cols.map((c) => `"${String(c)}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `validation-checklist-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [checklist]);

  const copyAuditReport = useCallback(async () => {
    if (!checklist.length) return;
    const okCount = checklist.filter((x) => x.ok).length;
    const failCount = checklist.length - okCount;
    const lines = [
      "Technical Review Update",
      "",
      `Checklist results: ${okCount}/${checklist.length} endpoints OK, ${failCount} failed.`,
      "",
      ...checklist.map(
        (r) =>
          `- /api${r.endpoint} | ${r.ok ? "OK" : "FAILED"} | ${r.detail || "-"}`,
      ),
      "",
      "This report was generated from the deployed dashboard validation checklist.",
    ];
    await navigator.clipboard.writeText(lines.join("\n"));
  }, [checklist]);

  useEffect(() => {
    summary.run();
    startup.run();
    runChecklist();
  }, []);

  const data = useMemo(() => summary.data, [summary.data]);
  const startupData = useMemo(() => startup.data, [startup.data]);
  const isInitialLoading = summary.loading && !data;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Status Summary
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Live system health, scheduler, model, database, and exchange
              status
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              disabled={summary.loading || startup.loading}
              onClick={() => {
                summary.run();
                startup.run();
                runChecklist();
              }}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 disabled:opacity-60"
            >
              {summary.loading || startup.loading || checking
                ? "Refreshing..."
                : "Refresh"}
            </button>
          </div>
        </div>

        {summary.error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {summary.error}
          </div>
        )}

        {startup.error && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Startup check: {startup.error}
          </div>
        )}

        {isInitialLoading && (
          <div className="mt-4 flex items-center justify-center px-3 py-10">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
          </div>
        )}

        {!isInitialLoading && data && (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <InfoCard
              label="App Version"
              value={startupData?.app_version || data.app_version || "—"}
              mono
            />

            <InfoCard
              label="Environment"
              value={startupData?.env || "—"}
              mono
            />

            <InfoCard
              label="Testnet Mode"
              value={
                <span
                  className={statusBadge(Boolean(startupData?.binance_testnet))}
                >
                  {startupData?.binance_testnet ? "Enabled" : "Disabled"}
                </span>
              }
            />

            <InfoCard
              label="Exchange Base URL"
              value={
                startupData?.binance_spot_base_url ||
                data.binance_spot_base_url ||
                "—"
              }
              mono
            />

            <InfoCard
              label="Scheduler State"
              value={
                <span className={schedulerBadge(data.scheduler_state)}>
                  {data.scheduler_state || "Unknown"}
                </span>
              }
            />

            <InfoCard
              label="Model Loaded"
              value={
                <span className={statusBadge(data.model_loaded)}>
                  {data.model_loaded ? "Loaded" : "Not Loaded"}
                </span>
              }
            />

            <InfoCard
              label="Database"
              value={
                <span className={statusBadge(data.database_connected)}>
                  {data.database_connected ? "Connected" : "Disconnected"}
                </span>
              }
            />

            <InfoCard
              label="Exchange"
              value={
                <span className={statusBadge(data.exchange_connected)}>
                  {data.exchange_connected ? "Connected" : "Disconnected"}
                </span>
              }
            />

            <InfoCard
              label="Exchange Detail"
              value={data.exchange_detail || "—"}
            />

            <InfoCard
              label="Dashboard URL"
              value={startupData?.dashboard_url || "Not configured"}
            />

            <InfoCard
              label="Dashboard Reachability"
              value={
                <span
                  className={statusBadge(
                    Boolean(startupData?.dashboard_connected),
                  )}
                >
                  {startupData?.dashboard_connected
                    ? "Reachable"
                    : "Unavailable"}
                </span>
              }
            />

            <InfoCard
              label="Dashboard Detail"
              value={startupData?.dashboard_detail || "—"}
            />

            <InfoCard
              label="Last Decision Time"
              value={formatDateTime(data.last_decision_time)}
            />

            <InfoCard
              label="Latest Decision"
              value={
                data.latest_decision
                  ? `${data.latest_decision.action} · ${data.latest_decision.symbol} (${data.latest_decision.timeframe})`
                  : "—"
              }
            />

            <InfoCard
              label="Decision Reason"
              value={data.latest_decision?.reason || "—"}
            />

            <InfoCard
              label="Last Successful Market Fetch"
              value={formatDateTime(data.last_successful_market_fetch)}
            />

            <InfoCard
              label="Last Successful Trade Execution"
              value={formatDateTime(data.last_successful_trade_execution)}
            />

            <InfoCard
              label="Recent Activity (100)"
              value={`Decisions: ${data.observability?.recent_decisions_count ?? 0} · Trades: ${data.observability?.recent_trades_count ?? 0}`}
            />
          </div>
        )}

        {!summary.loading && !summary.error && !data && (
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-8 text-center text-sm text-slate-500">
            No status summary available.
          </div>
        )}

        <div className="mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">
              Client Validation Checklist
            </h3>
            <div className="flex items-center gap-2">
              {checking && (
                <span className="text-xs text-slate-500">Checking...</span>
              )}
              <button
                type="button"
                onClick={exportChecklistCsv}
                disabled={!checklist.length}
                className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 disabled:opacity-50"
              >
                Export CSV
              </button>
              <button
                type="button"
                onClick={() => {
                  copyAuditReport().catch(() => undefined);
                }}
                disabled={!checklist.length}
                className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 disabled:opacity-50"
              >
                Copy Audit Report
              </button>
            </div>
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="min-w-full bg-white text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">
                    Endpoint
                  </th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">Detail</th>
                </tr>
              </thead>
              <tbody>
                {checklist.map((row) => (
                  <tr key={row.endpoint} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">
                      /api{row.endpoint}
                    </td>
                    <td className="px-3 py-2">
                      <span className={statusBadge(row.ok)}>
                        {row.ok ? "OK" : "FAILED"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {row.detail}
                    </td>
                  </tr>
                ))}
                {!checklist.length && !checking && (
                  <tr>
                    <td
                      className="px-3 py-5 text-center text-slate-500"
                      colSpan={3}
                    >
                      No checklist results yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
