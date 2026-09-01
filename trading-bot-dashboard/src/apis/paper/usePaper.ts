// src/apis/paper/usePaper.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError } from "../../lib/http";
import {
  paperApi,
  type PaperPositionsResponse,
  type PaperResetWalletIn,
  type PaperResetWalletResponse,
  type PaperWalletResponse,
  type PaperPriceResponse,
  type PaperRunIn,
  type PaperRunResponse,
  type PaperCloseIn,
  type PaperCloseResponse,
} from "./paper.api";

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

export function usePaperPrice() {
  const [state, setState] = useState<AsyncState<PaperPriceResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (symbol = "BTCUSDT") => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });

    try {
      const data = await paperApi.price(symbol, acRef.current.signal);
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

export function usePaperRun() {
  const [state, setState] = useState<AsyncState<PaperRunResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: PaperRunIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const data = await paperApi.run(body, acRef.current.signal);
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

/** ✅ NEW: positions */
export function usePaperPositions() {
  const [state, setState] = useState<AsyncState<PaperPositionsResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (params?: { symbol?: string | null; is_open?: boolean | null }) => {
      acRef.current?.abort();
      acRef.current = new AbortController();

      setState({ loading: true });
      try {
        const data = await paperApi.positions(params, acRef.current.signal);
        setState({ loading: false, data });
      } catch (e) {
        if (isAbortLike(e)) {
          setState((p) => ({ ...p, loading: false }));
          return;
        }
        setState({ loading: false, error: toApiError(e).message });
      }
    },
    [],
  );

  useEffect(() => () => acRef.current?.abort(), []);

  return { ...state, run };
}

/** ✅ NEW: wallet */
export function usePaperWallet() {
  const [state, setState] = useState<AsyncState<PaperWalletResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const data = await paperApi.wallet(acRef.current.signal);
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

/** ✅ NEW: reset wallet */
export function usePaperResetWallet() {
  const [state, setState] = useState<AsyncState<PaperResetWalletResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: PaperResetWalletIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const data = await paperApi.resetWallet(body, acRef.current.signal);
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

/** ✅ NEW: close position */
export function usePaperClose() {
  const [state, setState] = useState<AsyncState<PaperCloseResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (body: PaperCloseIn) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const data = await paperApi.close(body, acRef.current.signal);
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
