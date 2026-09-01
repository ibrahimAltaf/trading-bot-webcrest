import type { PerformanceMetricsResponse, PerformanceSummaryResponse } from "../../apis/exchange/exchange.api";

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function fmtUsdt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value >= 0 ? "" : "−";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

type PropsFull = {
  data: PerformanceMetricsResponse | null | undefined;
  loading?: boolean;
  error?: string;
  mode?: string;
  compact?: false;
};

type PropsSummary = {
  data: PerformanceSummaryResponse | null | undefined;
  loading?: boolean;
  error?: string;
  mode?: string;
  compact: true;
};

export default function PerformanceCard(
  props: PropsFull | PropsSummary,
) {
  const { loading, error, mode = "live" } = props;

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 text-sm font-semibold text-slate-900">
          Performance ({mode})
        </div>
        <div className="flex items-center justify-center py-8">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-slate-600" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 text-sm font-semibold text-slate-900">
          Performance ({mode})
        </div>
        <p className="text-sm text-rose-600">{error}</p>
      </div>
    );
  }

  if (props.compact && "total_trades" in (props.data ?? {})) {
    const s = props.data as PerformanceSummaryResponse;
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 text-sm font-semibold text-slate-900">
          Performance summary ({mode})
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <div className="text-xs text-slate-500">Total PnL</div>
            <div
              className={`font-semibold ${
                (s.total_pnl_usdt ?? 0) >= 0
                  ? "text-emerald-600"
                  : "text-rose-600"
              }`}
            >
              {fmtUsdt(s.total_pnl_usdt)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Win rate</div>
            <div className="font-semibold text-slate-900">
              {fmtNum(s.win_rate_pct, 1)}%
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Trades</div>
            <div className="font-semibold text-slate-900">
              {s.total_trades ?? "—"}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Last signal</div>
            <div className="font-medium text-slate-800">
              {s.last_signal ?? "—"}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const d = props.data as PerformanceMetricsResponse | null | undefined;
  if (!d) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 text-sm font-semibold text-slate-900">
          Performance ({mode})
        </div>
        <p className="text-sm text-slate-500">No data</p>
      </div>
    );
  }

  const pnl = d.pnl ?? {};
  const ratios = d.ratios ?? {};
  const pos = d.positions ?? {};
  const dec = d.decision_summary ?? {};

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 text-sm font-semibold text-slate-900">
        Performance ({mode})
      </div>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <div className="text-xs text-slate-500">Total PnL</div>
            <div
              className={`font-semibold ${
                (pnl.total_pnl_usdt ?? 0) >= 0
                  ? "text-emerald-600"
                  : "text-rose-600"
              }`}
            >
              {fmtUsdt(pnl.total_pnl_usdt)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Win rate</div>
            <div className="font-semibold text-slate-900">
              {fmtNum(ratios.win_rate_pct, 1)}%
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Profit factor</div>
            <div className="font-semibold text-slate-900">
              {ratios.profit_factor != null
                ? fmtNum(ratios.profit_factor, 2)
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Max drawdown</div>
            <div className="font-semibold text-rose-600">
              {fmtUsdt(-(pnl.max_drawdown_usdt ?? 0))} ({fmtNum(pnl.max_drawdown_pct, 1)}%)
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <span className="text-slate-500">Closed</span>{" "}
            <span className="font-medium text-slate-800">{pos.total_closed ?? 0}</span>
          </div>
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <span className="text-slate-500">Winners</span>{" "}
            <span className="font-medium text-emerald-600">{pos.winners ?? 0}</span>
          </div>
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <span className="text-slate-500">Losers</span>{" "}
            <span className="font-medium text-rose-600">{pos.losers ?? 0}</span>
          </div>
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <span className="text-slate-500">Avg duration</span>{" "}
            <span className="font-medium text-slate-800">
              {fmtNum(ratios.avg_trade_duration_hours, 1)}h
            </span>
          </div>
        </div>
        <div className="border-t border-slate-100 pt-3">
          <div className="text-xs font-medium text-slate-500">Decisions</div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
              BUY {dec.buy ?? 0}
            </span>
            <span className="rounded-full bg-rose-50 px-2 py-0.5 font-medium text-rose-700">
              SELL {dec.sell ?? 0}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
              HOLD {dec.hold ?? 0} ({fmtNum(dec.hold_pct, 0)}%)
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
