import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toApiError } from "../../lib/http";
import {
  backtestApi,
  type BacktestIn,
  type BacktestRun,
  type HealthResponse,
} from "./backtest.api";
import type {
  FingerprintResponse,
  ListRunsResponse,
  SignalResponse,
} from "./backtest.api";

/** If you already have these types in backtest.api.ts, import them instead. */
export type ValidateResponse = {
  ok: boolean;
  batch_id: string;
  dataset_sha256: string;
  vary_seed: boolean;
  runs_count: number;
  run_ids: number[];
  message: string;
};

export type CompareResponse = {
  ok: boolean;
  ready: boolean;
  reproducible: boolean;
  message: string;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  statistics: {
    mean_return_pct: number;
    min_return_pct: number;
    max_return_pct: number;
    std_return_pct: number;
  };
  items: Array<{
    run_id: number;
    status: string;
    seed: number | null;
    final_balance: number | null;
    total_return_pct: number | null;
    max_drawdown_pct: number | null;
    trades_count: number | null;
    win_rate: number | null;
    notes: string | null;
  }>;
};

type AsyncState<T> = {
  loading: boolean;
  error?: string;
  data?: T;
};

function isAbortLike(e: any) {
  return (
    e?.name === "AbortError" ||
    e?.code === "ERR_CANCELED" ||
    e?.message === "canceled" ||
    e?.message === "cancelled"
  );
}

function parseRunId(out: any): number | null {
  const payload = out?.data ?? out; // supports axios-like {data} or plain object
  const raw =
    payload?.run_id ??
    payload?.runId ??
    payload?.id ??
    payload?.run?.id ??
    payload?.run?.run_id;

  const n = typeof raw === "string" ? Number(raw) : raw;
  return Number.isFinite(n) ? n : null;
}

/** -------------------- Health -------------------- */
export function useBacktestHealth() {
  const [state, setState] = useState<AsyncState<HealthResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const data = await backtestApi.health(acRef.current.signal);
      setState({ loading: false, data });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState({ loading: false, error: toApiError(e).message });
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return useMemo(
    () => ({ ...state, run }),
    [state.loading, state.error, state.data, run],
  );
}

/** -------------------- Signal -------------------- */
export function useBacktestSignal() {
  const [state, setState] = useState<AsyncState<SignalResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (symbol = "BTCUSDT", timeframe = "1h") => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const res = await backtestApi.signal(
        { symbol, timeframe },
        acRef.current.signal,
      );

      const data = (res as any)?.data ?? res;
      setState({ loading: false, data });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState({ loading: false, error: toApiError(e).message });
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return useMemo(
    () => ({ ...state, run }),
    [state.loading, state.error, state.data, run],
  );
}

/** -------------------- Fingerprint -------------------- */
export function useBacktestFingerprint() {
  const acRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<AsyncState<FingerprintResponse>>({
    loading: false,
  });

  const run = useCallback(async (symbol = "BTCUSDT", timeframe = "1h") => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const res = await backtestApi.datasetFingerprint(
        { symbol, timeframe },
        acRef.current.signal,
      );

      const data = (res as any)?.data ?? res;
      setState({ loading: false, data });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState({ loading: false, error: toApiError(e).message });
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return useMemo(
    () => ({ ...state, run }),
    [state.loading, state.error, state.data, run],
  );
}

/** -------------------- Run + Poll -------------------- */
export function useBacktestRunAndPoll() {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<BacktestRun | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);

  const cleanup = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
    inFlightRef.current = false;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const pollRun = useCallback(async (id: number) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    abortRef.current?.abort();
    abortRef.current = new AbortController();

    try {
      const res = await backtestApi.getRun(id, abortRef.current.signal);
      setRun(res.run);

      const done = res.run.status === "success" || res.run.status === "failed";
      if (!done) {
        timerRef.current = window.setTimeout(() => pollRun(id), 1500);
      }
    } catch (e) {
      if (isAbortLike(e)) return;
      setError(toApiError(e).message);
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  const runBacktest = useCallback(
    async (body: BacktestIn) => {
      setCreating(true);
      setError(undefined);
      setRun(null);
      setRunId(null);
      cleanup();

      abortRef.current = new AbortController();

      try {
        const out = await backtestApi.run(body, abortRef.current.signal);

        const id = parseRunId(out);
        if (!id) {
          setError(
            "Backtest started, but could not parse run_id from response.",
          );
          return;
        }

        setRunId(id);
        pollRun(id);
      } catch (e) {
        if (isAbortLike(e)) return;
        setError(toApiError(e).message);
      } finally {
        setCreating(false);
      }
    },
    [cleanup, pollRun],
  );

  return useMemo(
    () => ({ creating, error, runId, run, runBacktest }),
    [creating, error, runId, run, runBacktest],
  );
}

/** -------------------- Runs List -------------------- */
type RunItem = ListRunsResponse extends { runs: (infer R)[] }
  ? R
  : ListRunsResponse extends { items: (infer I)[] }
    ? I
    : any;

type RunsListVM = {
  total: number;
  skip: number;
  limit: number;
  items: RunItem[];
};

function pickItems(res: ListRunsResponse): RunItem[] {
  if ("runs" in res && Array.isArray((res as any).runs))
    return (res as any).runs;
  if ("items" in res && Array.isArray((res as any).items))
    return (res as any).items;
  return [];
}

function pickTotal(res: ListRunsResponse): number {
  if (typeof (res as any).total === "number") return (res as any).total;
  if (typeof (res as any).count === "number") return (res as any).count;
  return pickItems(res).length;
}

function pickSkip(res: ListRunsResponse): number {
  if (typeof (res as any).skip === "number") return (res as any).skip;
  if (typeof (res as any).offset === "number") return (res as any).offset;
  return 0;
}

function pickLimit(res: ListRunsResponse): number {
  if (typeof (res as any).limit === "number") return (res as any).limit;
  if (typeof (res as any).pageSize === "number") return (res as any).pageSize;
  return pickItems(res).length;
}

export function useBacktestRunsList() {
  const [data, setData] = useState<RunsListVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async ({
      skip,
      limit,
      status,
      symbol,
    }: {
      skip: number;
      limit: number;
      status?: string | null;
      symbol?: string | null;
    }) => {
      setLoading(true);
      setError(null);
      try {
        const res: ListRunsResponse = await backtestApi.listRuns({
          skip,
          limit,
          status: status ?? null,
          symbol: symbol ?? null,
        });

        setData({
          total: pickTotal(res),
          skip: pickSkip(res),
          limit: pickLimit(res),
          items: pickItems(res),
        });
      } catch (e: any) {
        if (isAbortLike(e)) {
          setLoading(false);
          return;
        }
        setError(toApiError(e).message);
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return useMemo(
    () => ({ data, loading, error, load }),
    [data, loading, error, load],
  );
}

/** -------------------- Validate -------------------- */
export function useBacktestValidate() {
  const [state, setState] = useState<AsyncState<ValidateResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: BacktestIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const res = await backtestApi.validate(body, acRef.current.signal);
      const data = (res as any)?.data ?? res;
      setState({ loading: false, data });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState({ loading: false, error: toApiError(e).message });
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return useMemo(
    () => ({ ...state, run }),
    [state.loading, state.error, state.data, run],
  );
}

/** -------------------- Compare -------------------- */
export function useBacktestCompare() {
  const [state, setState] = useState<AsyncState<CompareResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (run_ids: number[]) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      // your API expects: { run_ids: [...] }
      const res = await backtestApi.compare({ run_ids }, acRef.current.signal);
      const data = (res as any)?.data ?? res;
      setState({ loading: false, data });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState({ loading: false, error: toApiError(e).message });
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return useMemo(
    () => ({ ...state, run }),
    [state.loading, state.error, state.data, run],
  );
}
