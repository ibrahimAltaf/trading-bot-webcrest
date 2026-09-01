import { useCallback, useEffect, useMemo, useState } from "react";
import { http } from "../lib/http";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

/* ============= Types ============= */

type PortfolioPoint = {
  ts: string;
  value_usdt: number;
  pnl_pct: number | null;
};

type PortfolioHistoryResponse = {
  ok: boolean;
  count: number;
  baseline: number | null;
  latest: number | null;
  pnl_abs: number | null;
  pnl_pct: number | null;
  points: PortfolioPoint[];
};

type ChartPoint = { ts: number; label: string; value: number };
type TimeRange = "today" | "7d" | "30d" | "all";

/* ============= Constants ============= */

const CHART_W = 600;
const CHART_H = 220;
const PAD = { top: 24, right: 16, bottom: 28, left: 60 };
const INNER_W = CHART_W - PAD.left - PAD.right;
const INNER_H = CHART_H - PAD.top - PAD.bottom;

const RANGES: { key: TimeRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 Days" },
  { key: "30d", label: "Month" },
  { key: "all", label: "Overall" },
];

/** Map UI range key → backend period param */
const PERIOD_MAP: Record<TimeRange, string> = {
  today: "today",
  "7d": "7days",
  "30d": "month",
  all: "overall",
};

/* ============= Helpers ============= */

function fmtUsd(n: number, precision?: number) {
  if (precision != null) {
    // Forced precision for Y-axis ticks
    if (Math.abs(n) >= 1_000_000)
      return `$${(n / 1_000_000).toFixed(precision)}M`;
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(precision)}K`;
    return `$${n.toFixed(precision)}`;
  }
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

/**
 * Pick a label format based on the actual time span of the data,
 * not the selected range pill. This prevents all labels showing "Mon"
 * when every snapshot is from the same day.
 */
function smartLabels(points: ChartPoint[]): ChartPoint[] {
  if (points.length === 0) return points;
  const first = points[0].ts;
  const last = points[points.length - 1].ts;
  const spanMs = last - first;
  const ONE_DAY = 24 * 60 * 60 * 1000;

  return points.map((p) => {
    const dt = new Date(p.ts);
    let label: string;
    if (spanMs < ONE_DAY) {
      // Same-day data → show HH:MM
      label = `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
    } else if (spanMs < 7 * ONE_DAY) {
      // Within a week → show day + time
      label =
        dt.toLocaleDateString(undefined, { weekday: "short" }) +
        " " +
        `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
    } else {
      // Longer → show date
      label = dt.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
    }
    return { ...p, label };
  });
}

/* ============= SVG Chart ============= */

function SvgLineChart({ points }: { points: ChartPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center py-14 text-sm text-zinc-400">
        No data for this period.
      </div>
    );
  }

  const values = points.map((p) => p.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;
  const paddedMin = minV - range * 0.05;
  const paddedMax = maxV + range * 0.05;
  const paddedRange = paddedMax - paddedMin;

  function x(i: number) {
    return PAD.left + (i / (points.length - 1)) * INNER_W;
  }
  function y(v: number) {
    return PAD.top + INNER_H - ((v - paddedMin) / paddedRange) * INNER_H;
  }

  const pathD = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`,
    )
    .join(" ");

  const areaD =
    pathD +
    ` L ${x(points.length - 1).toFixed(1)} ${(PAD.top + INNER_H).toFixed(1)}` +
    ` L ${x(0).toFixed(1)} ${(PAD.top + INNER_H).toFixed(1)} Z`;

  const latest = points[points.length - 1].value;
  const first = points[0].value;
  const pnl = latest - first;
  const isPositive = pnl >= 0;

  const yTicks = Array.from(
    { length: 5 },
    (_, i) => paddedMin + (paddedRange * i) / 4,
  );

  // Dynamic precision: when the range is tiny relative to the values,
  // we need more decimal places so tick labels aren't all the same.
  const yTickPrecision = (() => {
    const avg = (paddedMin + paddedMax) / 2;
    const divisor =
      Math.abs(avg) >= 1_000_000
        ? 1_000_000
        : Math.abs(avg) >= 1_000
          ? 1_000
          : 1;
    const scaledRange = paddedRange / divisor;
    if (scaledRange < 0.1) return 3;
    if (scaledRange < 1) return 2;
    return 1;
  })();

  const xTickCount = Math.min(points.length, 6);
  const xTickStep = Math.max(
    1,
    Math.floor((points.length - 1) / (xTickCount - 1)),
  );
  const xTicks: number[] = [];
  for (let i = 0; i < points.length; i += xTickStep) xTicks.push(i);
  if (xTicks[xTicks.length - 1] !== points.length - 1)
    xTicks.push(points.length - 1);

  const strokeColor = isPositive ? "#059669" : "#e11d48";
  const gradientId = isPositive ? "grad-pos" : "grad-neg";
  const hoverPt = hover != null ? points[hover] : null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="w-full h-auto"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="grad-pos" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#059669" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#059669" stopOpacity="0.01" />
          </linearGradient>
          <linearGradient id="grad-neg" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#e11d48" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#e11d48" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {yTicks.map((tick, i) => (
          <line
            key={i}
            x1={PAD.left}
            x2={CHART_W - PAD.right}
            y1={y(tick)}
            y2={y(tick)}
            stroke="#e2e8f0"
            strokeWidth="0.5"
          />
        ))}
        {yTicks.map((tick, i) => (
          <text
            key={i}
            x={PAD.left - 6}
            y={y(tick) + 3}
            textAnchor="end"
            className="text-[9px] fill-zinc-400"
          >
            {fmtUsd(tick, yTickPrecision)}
          </text>
        ))}
        {xTicks.map((idx) => (
          <text
            key={idx}
            x={x(idx)}
            y={CHART_H - 4}
            textAnchor="middle"
            className="text-[9px] fill-zinc-400"
          >
            {points[idx].label}
          </text>
        ))}

        <path d={areaD} fill={`url(#${gradientId})`} />
        <path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {points.map((_, i) => (
          <rect
            key={i}
            x={x(i) - INNER_W / points.length / 2}
            y={PAD.top}
            width={INNER_W / points.length}
            height={INNER_H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {hover != null && (
          <>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + INNER_H}
              stroke="#94a3b8"
              strokeWidth="0.5"
              strokeDasharray="3 3"
            />
            <circle
              cx={x(hover)}
              cy={y(points[hover].value)}
              r="4"
              fill="white"
              stroke={strokeColor}
              strokeWidth="2"
            />
          </>
        )}
      </svg>

      {hoverPt && (
        <div className="absolute top-1 left-1/2 -translate-x-1/2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs shadow-sm pointer-events-none">
          <span className="text-zinc-500">{hoverPt.label}</span>
          <span className="ml-2 font-semibold text-zinc-900">
            {fmtUsd(hoverPt.value)}
          </span>
        </div>
      )}
    </div>
  );
}

/* ============= Main Component ============= */

export default function BalancePortfolioChart() {
  const [history, setHistory] = useState<PortfolioHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshotting, setSnapshotting] = useState(false);
  const [range, setRange] = useState<TimeRange>("all");

  const fetchHistory = useCallback(async (period: string) => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await http.get<PortfolioHistoryResponse>(
        "/exchange/portfolio/history",
        { params: { period } },
      );
      setHistory(data);
    } catch (e: any) {
      setError(
        e?.response?.data?.detail ||
          e?.message ||
          "Failed to load portfolio history.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const takeSnapshot = useCallback(async () => {
    setSnapshotting(true);
    try {
      await http.post("/exchange/portfolio/snapshot", null, {
        params: { source: "manual" },
      });
      // Refresh chart after snapshot
      await fetchHistory(PERIOD_MAP[range]);
    } catch (e: any) {
      setError(
        e?.response?.data?.detail || e?.message || "Failed to take snapshot.",
      );
    } finally {
      setSnapshotting(false);
    }
  }, [fetchHistory]);

  // Load on mount + re-fetch when range changes
  useEffect(() => {
    fetchHistory(PERIOD_MAP[range]);
  }, [fetchHistory, range]);

  // ── Convert API points to chart format ──
  const allPoints = useMemo<ChartPoint[]>(() => {
    if (!history?.points?.length) return [];
    return history.points.map((p) => ({
      ts: new Date(p.ts).getTime(),
      label: "",
      value: p.value_usdt,
    }));
  }, [history]);

  // ── Apply smart labels (filtering is done server-side via period param) ──
  const filteredPts = useMemo(() => {
    return smartLabels(allPoints);
  }, [allPoints]);

  // ── Summary from API response ──
  const latestValue = history?.latest ?? null;
  const baselineValue = history?.baseline ?? null;
  const pnlAbs = history?.pnl_abs ?? null;
  const pnlPct = history?.pnl_pct ?? null;

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-5 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-zinc-900">
            Portfolio Balance
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            {latestValue != null && (
              <span className="text-lg font-semibold text-zinc-900">
                {fmtUsd(latestValue)}
              </span>
            )}
            {pnlAbs != null && (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs font-semibold",
                  pnlAbs >= 0
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-rose-50 text-rose-700",
                )}
              >
                {pnlAbs >= 0 ? "+" : ""}
                {fmtUsd(pnlAbs)}
                {pnlPct != null &&
                  ` (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)`}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Snapshot button */}
          <button
            onClick={takeSnapshot}
            disabled={snapshotting}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-1 text-xs font-semibold text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          >
            {snapshotting ? "Snapshotting…" : "Snapshot"}
          </button>

          {/* Time range pills */}
          <div className="flex items-center gap-0.5 rounded-lg border border-zinc-200 bg-zinc-50 p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-semibold transition-colors",
                  range === r.key
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Chart */}
      <div className="px-4 py-3">
        {loading && allPoints.length === 0 ? (
          <div className="flex items-center justify-center py-14 text-sm text-zinc-400">
            <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-700" />
            Loading portfolio history…
          </div>
        ) : (
          <SvgLineChart points={filteredPts} />
        )}
      </div>

      {/* Footer stats */}
      {filteredPts.length >= 2 && (
        <div className="flex flex-wrap items-center gap-4 border-t border-zinc-100 px-5 py-2.5 text-xs text-zinc-500">
          {baselineValue != null && (
            <span>
              Baseline:{" "}
              <span className="font-medium text-zinc-700">
                {fmtUsd(baselineValue)}
              </span>
            </span>
          )}
          {latestValue != null && (
            <span>
              Latest:{" "}
              <span className="font-medium text-zinc-700">
                {fmtUsd(latestValue)}
              </span>
            </span>
          )}
          <span>
            Snapshots:{" "}
            <span className="font-medium text-zinc-700">
              {history?.count ?? 0}
            </span>
          </span>
          <span>
            Showing:{" "}
            <span className="font-medium text-zinc-700">
              {filteredPts.length}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}
