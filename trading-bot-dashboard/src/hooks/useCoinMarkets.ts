import { useEffect, useMemo, useState } from "react";
import { fetchCoinMarkets, type CoinRow } from "../lib/coingecko";

export function useCoinMarkets(opts?: {
  vsCurrency?: string;
  perPage?: number;
  page?: number;
  ttlMs?: number;
}) {
  const [data, setData] = useState<CoinRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  const params = useMemo(
    () => ({
      vsCurrency: opts?.vsCurrency ?? "usd",
      perPage: opts?.perPage ?? 50,
      page: opts?.page ?? 1,
      ttlMs: opts?.ttlMs ?? 60_000,
    }),
    [opts?.vsCurrency, opts?.perPage, opts?.page, opts?.ttlMs],
  );

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError("");

    fetchCoinMarkets({ ...params, signal: ac.signal })
      .then((rows) => {
        setData(rows);
        setLoading(false);
      })
      .catch((e: any) => {
        if (ac.signal.aborted) return;
        setError(e?.message || "Failed to fetch prices");
        setLoading(false);
      });

    return () => ac.abort();
  }, [params]);

  return { data, loading, error, refresh: () => setError("") };
}
