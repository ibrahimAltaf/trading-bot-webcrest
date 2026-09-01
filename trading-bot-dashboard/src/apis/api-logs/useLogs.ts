import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError } from "../../lib/http";
import { logsApi, type LogsListResponse } from "./logs.api";

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

export function useLogsList() {
  const [state, setState] = useState<AsyncState<LogsListResponse>>({
    loading: false,
  });

  const acRef = useRef<AbortController | null>(null);

  const run = useCallback(async (limit = 50) => {
    acRef.current?.abort();
    acRef.current = new AbortController();

    setState({ loading: true });
    try {
      const res = await logsApi.list({ limit }, acRef.current.signal);
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

  return { ...state, run };
}
