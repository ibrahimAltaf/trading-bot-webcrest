"use client";

import React, { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import CryptoPricesPanel from "../components/layout/CryptoPricesPanel";
import {
  useStatusQuery,
  useHealthDbQuery,
  useBalancesQuery,
  usePositionsOpenQuery,
  useDecisionsRecentQuery,
  useLogsRecentQuery,
  usePerformanceQuery,
  useMlVsRulesQuery,
  useTradeEvaluationQuery,
  useLiveProofQuery,
  useMlAnalysisQuery,
} from "../apis/exchange/useExchangeQueries";
import PerformanceCard from "../components/exchange/PerformanceCard";
import { useStartupCheck } from "../apis/api-summary/useStatusSummary";
import { useExecutionModeQuery } from "../apis/safety/useSafety";
import type { ExecutionMode } from "../lib/executionMode";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function StatCard({
  title,
  value,
  subtitle,
  tone = "neutral",
}: {
  title: string;
  value: string;
  subtitle?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  const toneClass =
    tone === "positive"
      ? "bg-emerald-50 text-emerald-700"
      : tone === "negative"
        ? "bg-rose-50 text-rose-700"
        : "bg-slate-100 text-slate-700";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium text-slate-500">{title}</div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div className="text-2xl font-semibold text-slate-900">{value}</div>
        <div
          className={cn(
            "rounded-full px-2 py-1 text-xs font-semibold",
            toneClass,
          )}
        >
          {subtitle ?? "—"}
        </div>
      </div>
    </div>
  );
}

function fmtMoney(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function fmtPct(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value.toFixed(1)}%`;
}

function fmtNumber(value?: number | null, digits = 0) {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toFixed(digits);
}

function fmtDate(value?: string | null) {
  if (!value) return "—";
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

function resolveStatusLabel(payload?: Record<string, unknown>) {
  if (!payload) return null;

  const statusLike =
    payload.status ?? payload.state ?? payload.health ?? payload.message;

  if (typeof statusLike === "string" && statusLike.trim()) {
    return statusLike.toUpperCase();
  }

  if (typeof payload.ok === "boolean") {
    return payload.ok ? "OK" : "ERROR";
  }

  return null;
}

function statusTone(status?: string) {
  const s = String(status ?? "").toLowerCase();
  if (["ok", "healthy", "up", "ready", "running"].includes(s))
    return "positive" as const;
  if (["down", "error", "failed", "unhealthy"].includes(s))
    return "negative" as const;
  return "neutral" as const;
}

function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <div className="text-sm font-semibold text-slate-900">{title}</div>
        {right ? <div className="flex items-center gap-2">{right}</div> : null}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const modeQ = useExecutionModeQuery();
  const perfMode = (modeQ.data?.effective_mode ?? "live") as ExecutionMode;
  const system = useStatusQuery();
  const db = useHealthDbQuery();
  const balances = useBalancesQuery();
  const openPositions = usePositionsOpenQuery();
  const decisions = useDecisionsRecentQuery({ symbol: "BTCUSDT", limit: 20 });
  const logs = useLogsRecentQuery({ limit: 20 });
  const performance = usePerformanceQuery(perfMode);
  const mlVsRules = useMlVsRulesQuery(perfMode);
  const tradeEvaluation = useTradeEvaluationQuery(perfMode);
  const liveProof = useLiveProofQuery(200);
  const mlAnalysis = useMlAnalysisQuery(500);
  const startup = useStartupCheck();

  const isLoading =
    system.isLoading ||
    db.isLoading ||
    balances.isLoading ||
    openPositions.isLoading ||
    decisions.isLoading ||
    logs.isLoading ||
    performance.isLoading ||
    mlVsRules.isLoading ||
    tradeEvaluation.isLoading ||
    liveProof.isLoading ||
    mlAnalysis.isLoading ||
    startup.loading;

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["exchange"] });
    queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  const usdtBalance = useMemo(() => {
    const items = balances.data?.balances ?? [];
    const usdt = items.find((x) => String(x.asset).toUpperCase() === "USDT");
    if (!usdt) return null;
    const parsed = Number(usdt.total ?? usdt.free);
    return Number.isFinite(parsed) ? parsed : null;
  }, [balances.data]);

  const assetCount = balances.data
    ? (balances.data.count ?? balances.data.balances?.length ?? 0)
    : null;

  const totalOpenQty = useMemo(() => {
    if (!openPositions.data) return null;
    const items = openPositions.data?.items ?? openPositions.data?.positions ?? [];
    return items.reduce((sum: number, p: any) => {
      const qty = Number(p?.entry_qty ?? p?.qty ?? 0);
      return sum + (Number.isFinite(qty) ? qty : 0);
    }, 0);
  }, [openPositions.data]);

  const recentDecisionItems = decisions.data?.decisions ?? [];
  const buyCount = recentDecisionItems.filter((d) => d.action === "BUY").length;
  const latestDecision = recentDecisionItems[0];
  const buyRate = recentDecisionItems.length
    ? (buyCount / recentDecisionItems.length) * 100
    : null;

  const logItems = (logs.data as any)?.items ?? (logs.data as any)?.logs ?? [];
  const errorCount = logItems.filter(
    (l: any) => String(l.level).toUpperCase() === "ERROR",
  ).length;

  const apiStatusLabel = resolveStatusLabel(
    (system.data as Record<string, unknown> | undefined) ?? undefined,
  );

  const lastSync = new Date().toLocaleTimeString();
  const latestError = logItems.find(
    (l: any) => String(l.level).toUpperCase() === "ERROR",
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="USDT Balance"
          value={fmtMoney(usdtBalance)}
          subtitle={assetCount == null ? "—" : `${assetCount} assets`}
          tone="positive"
        />
        <StatCard
          title="Open Positions"
          value={fmtNumber(openPositions.data?.count ?? openPositions.data?.positions?.length ?? 0, 0)}
          subtitle={
            totalOpenQty == null
              ? "—"
              : `Total qty ${fmtNumber(totalOpenQty, 6)}`
          }
        />
        <StatCard
          title="BUY Signal Rate"
          value={fmtPct(buyRate)}
          subtitle={
            decisions.data
              ? `${recentDecisionItems.length} recent decisions`
              : "—"
          }
          tone={buyRate != null && buyRate >= 50 ? "positive" : "neutral"}
        />
        <StatCard
          title="Recent Errors"
          value={logs.data ? String(errorCount) : "-"}
          subtitle={logs.data ? `${logItems.length} recent logs` : "—"}
          tone={logs.data && errorCount > 0 ? "negative" : "positive"}
        />
      </div>

      <Panel title={`Trading performance (${perfMode})`}>
        <PerformanceCard
          data={performance.data ?? null}
          loading={performance.isLoading}
          error={performance.error?.message}
          mode={perfMode}
        />
      </Panel>

      <Panel title="ML live proof (audit API)">
        {liveProof.error ? (
          <div className="text-sm text-rose-600">{liveProof.error.message}</div>
        ) : liveProof.isLoading ? (
          <div className="flex justify-center py-6">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-slate-600" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                title="ML used % (decisions)"
                value={fmtPct(liveProof.data?.ml_used_percentage ?? null)}
                subtitle={
                  liveProof.data?.sample_size != null
                    ? `n=${liveProof.data.sample_size} recent`
                    : "—"
                }
                tone={
                  (liveProof.data?.ml_used_percentage ?? 0) >= 30
                    ? "positive"
                    : "neutral"
                }
              />
              <StatCard
                title="Avg ML softmax"
                value={
                  liveProof.data?.avg_ml_confidence != null
                    ? fmtNumber(liveProof.data.avg_ml_confidence, 3)
                    : "—"
                }
                subtitle="From /stats/live-proof"
              />
              <StatCard
                title="High ML conf (>0.7)"
                value={
                  liveProof.data?.high_confidence_ratio != null
                    ? fmtPct(
                        liveProof.data.high_confidence_ratio * 100,
                      )
                    : "—"
                }
                subtitle="Share in sample"
              />
              <StatCard
                title="Live PnL (closed sample)"
                value={fmtMoney(liveProof.data?.live_pnl_sum_usdt)}
                subtitle={
                  liveProof.data?.closed_trades_sample != null
                    ? `${liveProof.data.closed_trades_sample} trades`
                    : "—"
                }
              />
            </div>
            {mlAnalysis.data && !mlAnalysis.error && (
              <div className="rounded-lg border border-slate-100 bg-slate-50 px-4 py-3 text-xs text-slate-600">
                <span className="font-semibold text-slate-700">
                  /stats/ml-analysis
                </span>
                {" — "}samples: {mlAnalysis.data.ml_confidence_samples ?? "—"},{" "}
                avg softmax {fmtNumber(mlAnalysis.data.avg_ml_confidence, 3)}, share
                above 0.8{" "}
                {mlAnalysis.data.high_confidence_ratio_08 != null
                  ? fmtPct(mlAnalysis.data.high_confidence_ratio_08 * 100)
                  : "—"}
              </div>
            )}
            {liveProof.data?.final_source_counts &&
              Object.keys(liveProof.data.final_source_counts).length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Final source (recent)
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(liveProof.data.final_source_counts).map(
                      ([src, n]) => (
                        <span
                          key={src}
                          className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
                        >
                          {src || "—"}: {n}
                        </span>
                      ),
                    )}
                  </div>
                </div>
              )}
            {liveProof.data?.alerts?.length ? (
              <ul className="space-y-1 text-sm">
                {liveProof.data.alerts.map((a) => (
                  <li
                    key={`${a.code}-${a.message}`}
                    className={
                      a.level === "WARN"
                        ? "text-amber-700"
                        : "text-slate-600"
                    }
                  >
                    <span className="font-medium">[{a.level}]</span> {a.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </Panel>

      <Panel
        title="System health"
        right={
          <>
            <span className="text-xs text-slate-500">Last sync {lastSync}</span>
            <button
              onClick={refreshAll}
              disabled={isLoading}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              {isLoading ? "Refreshing..." : "Refresh"}
            </button>
          </>
        }
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <StatCard
            title="API Status"
            value={apiStatusLabel ?? "-"}
            subtitle={system.error?.message ? "Request failed" : "Service check"}
            tone={statusTone(apiStatusLabel ?? undefined)}
          />
          <StatCard
            title="Database"
            value={String((db.data as any)?.db ?? (db.data as any)?.status ?? "-")}
            subtitle={db.error?.message ? "Request failed" : "Service check"}
            tone={statusTone((db.data as any)?.db ?? (db.data as any)?.status ?? undefined)}
          />
          <StatCard
            title="Dashboard"
            value={startup.data?.dashboard_connected ? "REACHABLE" : "UNAVAILABLE"}
            subtitle={startup.data?.dashboard_detail ?? "Startup check"}
            tone={startup.data?.dashboard_connected ? "positive" : "negative"}
          />
          <StatCard
            title="Latest Decision"
            value={String(latestDecision?.final_action ?? latestDecision?.action ?? "N/A")}
            subtitle={
              latestDecision && latestDecision.confidence != null
                ? `Conf. ${fmtPct(latestDecision.confidence * 100)}`
                : "—"
            }
            tone={
              (latestDecision?.final_action ?? latestDecision?.action) === "BUY"
                ? "positive"
                : (latestDecision?.final_action ?? latestDecision?.action) === "SELL"
                  ? "negative"
                  : "neutral"
            }
          />
          <StatCard
            title="Last Error"
            value={latestError ? String(latestError.category ?? "ERROR") : "NONE"}
            subtitle={latestError ? fmtDate(latestError.ts) : "No recent errors"}
            tone={latestError ? "negative" : "positive"}
          />
        </div>
      </Panel>

      <Panel title="Startup check">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <StatCard
            title="Environment"
            value={startup.data?.env?.toUpperCase() ?? "-"}
            subtitle={startup.data?.app_version ?? "—"}
          />
          <StatCard
            title="Scheduler"
            value={startup.data?.scheduler_state?.toUpperCase() ?? "-"}
            subtitle={fmtDate(startup.data?.last_decision_time)}
            tone={statusTone(startup.data?.scheduler_state)}
          />
          <StatCard
            title="Last Trade Execution"
            value={fmtDate(startup.data?.last_successful_trade_execution)}
            subtitle={fmtDate(startup.data?.last_successful_market_fetch)}
          />
        </div>
      </Panel>

      <Panel title="Rule vs ML comparison">
        {mlVsRules.error ? (
          <div className="text-sm text-rose-600">{mlVsRules.error.message}</div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {(["rule_only", "combined", "ml_override", "other"] as const).map(
                (bucket) => {
                  const item = mlVsRules.data?.buckets?.[bucket];
                  return (
                    <div
                      key={bucket}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-4"
                    >
                      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {bucket.replace("_", " ")}
                      </div>
                      <div className="mt-2 text-lg font-semibold text-slate-900">
                        {item?.total_trades ?? 0} trades
                      </div>
                      <div className="mt-2 text-xs text-slate-600">
                        Win rate {fmtPct(item?.win_rate_pct)}
                      </div>
                      <div className="text-xs text-slate-600">
                        Avg return {fmtPct(item?.average_return_per_trade_pct)}
                      </div>
                      <div className="text-xs text-slate-600">
                        Drawdown {fmtPct(item?.max_drawdown_pct)}
                      </div>
                      <div className="text-xs text-slate-600">
                        Sharpe {fmtNumber(item?.sharpe_ratio, 2)}
                      </div>
                    </div>
                  );
                },
              )}
            </div>
            <div className="text-xs text-slate-500">
              Overall false signal rate:{" "}
              {fmtPct(mlVsRules.data?.overall?.false_signal_rate_pct)} | Total PnL:{" "}
              {fmtMoney(mlVsRules.data?.overall?.total_pnl_usdt)}
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Trade-by-trade evaluation">
        {tradeEvaluation.error ? (
          <div className="text-sm text-rose-600">{tradeEvaluation.error.message}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Symbol</th>
                  <th className="py-2 pr-3">Entry</th>
                  <th className="py-2 pr-3">Exit</th>
                  <th className="py-2 pr-3">PnL</th>
                  <th className="py-2 pr-3">Rule</th>
                  <th className="py-2 pr-3">ML</th>
                  <th className="py-2 pr-3">Effect</th>
                  <th className="py-2 pr-3">Exit Reason</th>
                </tr>
              </thead>
              <tbody>
                {(tradeEvaluation.data?.items ?? []).slice(0, 8).map((item) => (
                  <tr key={item.position_id} className="border-t border-slate-100">
                    <td className="py-2 pr-3 font-medium text-slate-800">{item.symbol}</td>
                    <td className="py-2 pr-3 text-slate-600">{fmtDate(item.entry_ts)}</td>
                    <td className="py-2 pr-3 text-slate-600">{fmtDate(item.exit_ts)}</td>
                    <td className="py-2 pr-3 text-slate-800">
                      {fmtMoney(item.realized_pnl)} ({fmtPct(item.realized_pnl_pct)})
                    </td>
                    <td className="py-2 pr-3 text-slate-700">{item.rule_signal ?? "—"}</td>
                    <td className="py-2 pr-3 text-slate-700">
                      {item.ml_signal ?? "—"}
                      {item.ml_confidence != null
                        ? ` (${fmtPct(item.ml_confidence * 100)})`
                        : ""}
                    </td>
                    <td className="py-2 pr-3 text-slate-700">{item.ml_effect}</td>
                    <td className="py-2 pr-3 text-slate-600">{item.exit_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!tradeEvaluation.data?.items?.length && (
              <div className="text-sm text-slate-500">No closed trades available.</div>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Crypto prices">
        <CryptoPricesPanel />
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel title="Recent decisions (BTCUSDT)">
          <div className="space-y-2">
            {recentDecisionItems.slice(0, 6).map((d) => (
              <div
                key={d.id}
                className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-semibold",
                      d.action === "BUY"
                        ? "bg-emerald-50 text-emerald-700"
                        : d.action === "SELL"
                          ? "bg-rose-50 text-rose-700"
                          : "bg-slate-100 text-slate-700",
                    )}
                  >
                    {d.action}
                  </span>
                  <span className="text-slate-600">{d.symbol}</span>
                </div>
                <div className="text-right">
                  <div className="font-medium text-slate-900">
                    Conf. {d.confidence != null ? fmtPct(d.confidence * 100) : "—"}
                  </div>
                  <div className="text-xs text-slate-500">
                    {new Date(d.timestamp).toLocaleString()}
                  </div>
                </div>
              </div>
            ))}
            {!recentDecisionItems.length && (
              <div className="text-sm text-slate-500">
                No recent decisions available.
              </div>
            )}
          </div>
        </Panel>

        <Panel title="Recent logs">
          <div className="space-y-2">
            {logItems.slice(0, 6).map((log: any) => (
              <div
                key={log.id}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-semibold",
                      String(log.level).toUpperCase() === "ERROR"
                        ? "bg-rose-50 text-rose-700"
                        : String(log.level).toUpperCase() === "WARN"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-slate-100 text-slate-700",
                    )}
                  >
                    {String(log.level).toUpperCase()}
                  </span>
                  <span className="text-xs text-slate-500">
                    {new Date(log.ts).toLocaleString()}
                  </span>
                </div>
                <div className="mt-1 text-slate-800">{log.message}</div>
              </div>
            ))}
            {!logItems.length && (
              <div className="text-sm text-slate-500">
                No recent logs available.
              </div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
