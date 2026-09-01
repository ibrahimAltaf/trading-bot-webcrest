import { useEffect, useMemo, useState } from "react";
import { http } from "../lib/http";

type AnyObj = Record<string, any>;

function kvRows(obj: AnyObj) {
  const entries = Object.entries(obj ?? {});
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  return entries;
}

function JsonBlock({ data }: { data: any }) {
  return (
    <pre className="text-xs leading-5 whitespace-pre-wrap break-words bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto max-h-[520px] text-slate-700">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="text-sm font-semibold text-slate-900">{title}</div>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function AdaptiveEngine() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("1h");
  const [refreshMs, setRefreshMs] = useState(2000);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastOkAt, setLastOkAt] = useState<string | null>(null);

  const endpoints = useMemo(
    () => [
      `/strategy/adaptive?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`,
    ],
    [symbol, timeframe],
  );

  async function fetchAdaptive() {
    setError(null);

    for (const url of endpoints) {
      try {
        const res = await http.get(url);
        setData(res);
        setLastOkAt(new Date().toLocaleString());
        return;
      } catch (e: any) {
        const msg = e?.message || String(e);
        if (!/404/i.test(msg)) {
          setError(msg);
          return;
        }
      }
    }

    setError(
      "Could not load /strategy/adaptive — check backend is running and TRADE_SYMBOL / API keys are valid.",
    );
  }

  useEffect(() => {
    fetchAdaptive();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe]);

  useEffect(() => {
    const id = window.setInterval(
      () => {
        fetchAdaptive();
      },
      Math.max(500, refreshMs),
    );
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshMs, symbol, timeframe]);

  const volBucket = data?.vol_bucket ?? data?.meta?.vol_bucket ?? null;
  const trendBucket = data?.trend_bucket ?? data?.meta?.trend_bucket ?? null;
  const params =
    data?.params ?? data?.meta?.params ?? data?.adaptive_params ?? null;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Adaptive Engine
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Real-time adaptive strategy parameters
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-slate-600">
                Symbol
              </label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="BTCUSDT"
                className="h-9 w-[110px] rounded-lg border border-slate-200 px-3 text-sm font-medium"
              />
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-slate-600">TF</label>
              <select
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium cursor-pointer"
              >
                {["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"].map(
                  (tf) => (
                    <option key={tf} value={tf}>
                      {tf}
                    </option>
                  ),
                )}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-slate-600">
                Refresh
              </label>
              <select
                value={String(refreshMs)}
                onChange={(e) => setRefreshMs(parseInt(e.target.value, 10))}
                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium cursor-pointer"
              >
                {[500, 1000, 2000, 5000, 10000].map((ms) => (
                  <option key={ms} value={ms}>
                    {ms} ms
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={fetchAdaptive}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 hover:bg-slate-50"
            >
              Refresh now
            </button>
          </div>
        </div>

        {lastOkAt && (
          <div className="mt-2 text-xs text-slate-500">
            آخر تحديث:{" "}
            <span className="font-medium text-slate-700">{lastOkAt}</span>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 whitespace-pre-wrap">
          {error}
        </div>
      )}

      {/* Data cards */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Panel title="Buckets (لحظيًا)">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500">vol_bucket</span>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                {String(volBucket ?? "-")}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500">trend_bucket</span>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                {String(trendBucket ?? "-")}
              </span>
            </div>
            <p className="text-xs text-slate-400">
              لو الـ Backend يرجّع القيم داخل meta، الصفحة بتقرأها تلقائيًا.
            </p>
          </div>
        </Panel>

        <Panel title="Params (EMA/RSI/BB + SL/TP)">
          {params ? (
            <div className="overflow-auto max-h-[320px]">
              <table className="w-full text-sm">
                <tbody>
                  {kvRows(params).map(([k, v]) => (
                    <tr key={k} className="border-b border-slate-100">
                      <td className="py-2 pr-3 text-slate-500">{k}</td>
                      <td className="py-2 text-right font-mono text-slate-900">
                        {String(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              لم يتم استلام params من الـ API.
            </p>
          )}
        </Panel>

        <Panel title="Raw response (debug)">
          {data ? (
            <JsonBlock data={data} />
          ) : (
            <p className="text-sm text-slate-500">لا توجد بيانات بعد.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
