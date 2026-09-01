import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError } from "../../lib/http";
import {
  exchangeApi,
  type DbHealthResponse,
  type EventLog,
  type ExchangeAllOrdersResponse,
  type ExchangeAssetBalanceResponse,
  type ExchangeBalanceResponse,
  type ExchangeDecisionLatestResponse,
  type ExchangeDecisionsRecentResponse,
  type ExchangeDebugResponse,
  type ExchangeOpenOrdersResponse,
  type ExchangeOpenPositionsResponse,
  type ExchangePositionsHistoryResponse,
  type ExchangeTrade,
  type ExchangeTradesResponse,
  type LimitBuyIn,
  type LimitBuyResponse,
  type ExchangeOrder,
  type AutoTradeIn,
  type AutoTradeResponse,
  type LiveRunIn,
  type LiveRunResponse,
  type SystemStatusResponse,
} from "./exchange.api";

type AsyncState<T> = {
  loading: boolean;
  error?: string;
  data?: T;
};

function unwrap<T>(res: any): T {
  return (res?.data ?? res) as T;
}

function isAbortLike(e: any) {
  return (
    e?.name === "AbortError" ||
    e?.code === "ERR_CANCELED" ||
    e?.message === "canceled" ||
    e?.message === "cancelled"
  );
}

/** -------------------------
 *  Simple fetch hooks
 *  ------------------------- */

export function useExchangeDebug() {
  const [state, setState] = useState<AsyncState<ExchangeDebugResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.debug(acRef.current.signal);
      const data = unwrap<ExchangeDebugResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useSystemStatus() {
  const [state, setState] = useState<AsyncState<SystemStatusResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.status(acRef.current.signal);
      const data = unwrap<SystemStatusResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useDbHealth() {
  const [state, setState] = useState<AsyncState<DbHealthResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.healthDb(acRef.current.signal);
      const data = unwrap<DbHealthResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useExchangeDecisionLatest() {
  const [state, setState] = useState<
    AsyncState<ExchangeDecisionLatestResponse>
  >({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (symbol = "BTCUSDT") => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.decisionLatest(
        { symbol },
        acRef.current.signal,
      );
      const data = unwrap<ExchangeDecisionLatestResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useExchangeDecisionsRecent() {
  const [state, setState] = useState<
    AsyncState<ExchangeDecisionsRecentResponse>
  >({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (params?: {
      symbol?: string;
      limit?: number;
      action?: "BUY" | "SELL" | "HOLD";
    }) => {
      acRef.current?.abort();
      acRef.current = new AbortController();

      setState((p) => ({ ...p, loading: true, error: undefined }));
      try {
        const res = await exchangeApi.decisionsRecent(
          params,
          acRef.current.signal,
        );
        const data = unwrap<ExchangeDecisionsRecentResponse>(res);
        setState({ loading: false, data, error: undefined });
      } catch (e) {
        if (isAbortLike(e)) {
          setState((p) => ({ ...p, loading: false }));
          return;
        }
        setState((p) => ({
          ...p,
          loading: false,
          error: toApiError(e).message,
        }));
      }
    },
    [],
  );

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

type ExchangeLogsRecentVM = {
  count: number;
  items: EventLog[];
};

function pickLogItems(res: any): EventLog[] {
  if (Array.isArray(res)) return res as EventLog[];
  if (Array.isArray(res?.logs)) return res.logs as EventLog[];
  if (Array.isArray(res?.items)) return res.items as EventLog[];
  return [];
}

export function useExchangeLogsRecent() {
  const [data, setData] = useState<ExchangeLogsRecentVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (params?: {
      limit?: number;
      category?: string;
      level?: "INFO" | "WARN" | "ERROR";
    }) => {
      acRef.current?.abort();
      acRef.current = new AbortController();

      setLoading(true);
      setError(null);
      try {
        const res = await exchangeApi.logsRecent(params, acRef.current.signal);
        const items = pickLogItems(res);

        setData({
          count:
            typeof (res as any)?.count === "number"
              ? (res as any).count
              : items.length,
          items,
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

  useEffect(() => () => acRef.current?.abort(), []);

  return { data, loading, error, load };
}

export function useExchangeBalance() {
  const [state, setState] = useState<AsyncState<ExchangeBalanceResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.balance(acRef.current.signal);
      const data = unwrap<ExchangeBalanceResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useExchangeBalanceByAsset() {
  const [state, setState] = useState<AsyncState<ExchangeAssetBalanceResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (asset: string) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.balanceByAsset(asset, acRef.current.signal);
      const data = unwrap<ExchangeAssetBalanceResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

type ExchangePositionsVM = {
  count: number;
  items: ExchangeOpenPositionsResponse extends { positions: (infer P)[] }
    ? P[]
    : never;
};

function pickPositionItems(res: any) {
  if (Array.isArray(res)) return res;
  if (Array.isArray(res?.positions)) return res.positions;
  if (Array.isArray(res?.items)) return res.items;
  return [];
}

export function useExchangeOpenPositions() {
  const [data, setData] = useState<ExchangePositionsVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setLoading(true);
    setError(null);
    try {
      const res = await exchangeApi.positionsOpen(
        undefined,
        acRef.current.signal,
      );
      const items = pickPositionItems(res);
      setData({
        count:
          typeof (res as any)?.count === "number"
            ? (res as any).count
            : items.length,
        items,
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
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { data, loading, error, load };
}

export function useExchangePositionHistory() {
  const [data, setData] = useState<ExchangePositionsVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);

  const load = useCallback(async (limit = 50) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setLoading(true);
    setError(null);
    try {
      const res: ExchangePositionsHistoryResponse =
        await exchangeApi.positionsHistory({ limit }, acRef.current.signal);

      const items = pickPositionItems(res);
      setData({
        count:
          typeof (res as any)?.count === "number"
            ? (res as any).count
            : items.length,
        items,
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
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { data, loading, error, load };
}

export function useExchangeOpenOrders() {
  const [state, setState] = useState<AsyncState<ExchangeOpenOrdersResponse>>({
    loading: false,
  });
  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (symbol = "BTCUSDT") => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.openOrders(
        { symbol },
        acRef.current.signal,
      );
      const data = unwrap<ExchangeOpenOrdersResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

/** -------------------------
 *  Orders list (like backtest listRuns)
 *  ------------------------- */

type OrdersListVM = {
  total: number;
  limit: number;
  items: ExchangeOrder[];
};

function pickItems(res: any): ExchangeOrder[] {
  if (Array.isArray(res)) return res as ExchangeOrder[];
  if (Array.isArray(res?.orders)) return res.orders as ExchangeOrder[];
  if (Array.isArray(res?.items)) return res.items as ExchangeOrder[];
  return [];
}

function pickTotal(res: any): number {
  if (typeof res?.count === "number") return res.count;
  if (typeof res?.total === "number") return res.total;
  return pickItems(res).length;
}

function pickLimit(res: any, fallback = 200): number {
  if (typeof res?.limit === "number") return res.limit;
  if (typeof res?.pageSize === "number") return res.pageSize;
  // arrays don't provide limit; use fallback that caller used
  return fallback;
}

export function useExchangeAllOrders() {
  const [data, setData] = useState<OrdersListVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async ({ symbol, limit }: { symbol: string; limit?: number }) => {
      acRef.current?.abort();
      acRef.current = new AbortController();

      const usedLimit = limit ?? 200;

      setLoading(true);
      setError(null);
      try {
        const res: ExchangeAllOrdersResponse = await exchangeApi.allOrders(
          { symbol, limit: usedLimit },
          acRef.current.signal,
        );

        // backend currently returns an array; but adapter supports other shapes too
        setData({
          total: pickTotal(res),
          limit: pickLimit(res, usedLimit),
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

  useEffect(() => () => acRef.current?.abort(), []);

  return { data, loading, error, load };
}

type ExchangeTradesVM = {
  count: number;
  items: ExchangeTrade[];
};

function pickTradeItems(res: any): ExchangeTrade[] {
  if (Array.isArray(res)) return res as ExchangeTrade[];
  if (Array.isArray(res?.trades)) return res.trades as ExchangeTrade[];
  if (Array.isArray(res?.items)) return res.items as ExchangeTrade[];
  return [];
}

export function useExchangeTrades() {
  const [data, setData] = useState<ExchangeTradesVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async ({ symbol, limit }: { symbol?: string; limit?: number } = {}) => {
      acRef.current?.abort();
      acRef.current = new AbortController();

      setLoading(true);
      setError(null);
      try {
        const res: ExchangeTradesResponse = await exchangeApi.trades(
          { symbol, limit },
          acRef.current.signal,
        );

        const items = pickTradeItems(res);
        setData({
          count:
            typeof (res as any)?.count === "number"
              ? (res as any).count
              : items.length,
          items,
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

  useEffect(() => () => acRef.current?.abort(), []);

  return { data, loading, error, load };
}

/** -------------------------
 *  Place order
 *  ------------------------- */

export function useExchangeLimitBuy() {
  const [state, setState] = useState<AsyncState<LimitBuyResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: LimitBuyIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.limitBuy(body, acRef.current.signal);
      const data = unwrap<LimitBuyResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useExchangeAutoTrade() {
  const [state, setState] = useState<AsyncState<AutoTradeResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: AutoTradeIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState((p) => ({ ...p, loading: true, error: undefined }));
    try {
      const res = await exchangeApi.autoTrade(body, acRef.current.signal);
      const data = unwrap<AutoTradeResponse>(res);
      setState({ loading: false, data, error: undefined });
    } catch (e) {
      if (isAbortLike(e)) {
        setState((p) => ({ ...p, loading: false }));
        return;
      }
      setState((p) => ({ ...p, loading: false, error: toApiError(e).message }));
    }
  }, []);

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

export function useLiveRun() {
  const [state, setState] = useState<AsyncState<LiveRunResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: LiveRunIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const res = await exchangeApi.liveRun(body, acRef.current.signal);
      const data = unwrap<LiveRunResponse>(res);
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

  return { ...state, run };
}
