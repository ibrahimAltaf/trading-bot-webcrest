import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError } from "../../lib/http";
import {
  statusApi,
  type StartupCheckResponse,
  type StatusSummaryResponse,
} from "./summary.api";

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

export function useStatusSummary() {
  const [state, setState] = useState<AsyncState<StatusSummaryResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });

    try {
      const res = await statusApi.summary(acRef.current.signal);
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

  useEffect(() => {
    return () => acRef.current?.abort();
  }, []);

  return { ...state, run };
}

export function useStartupCheck() {
  const [state, setState] = useState<AsyncState<StartupCheckResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });

    try {
      const res = await statusApi.startupCheck(acRef.current.signal);
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

  useEffect(() => {
    return () => acRef.current?.abort();
  }, []);

  return { ...state, run };
}
