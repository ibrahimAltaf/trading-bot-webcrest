import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import {
  adminApi,
  type BinanceKeysSnapshot,
  type BinanceKeysVerifyResult,
} from "./admin.api";

export const adminKeys = {
  all: ["admin"] as const,
  binanceKeys: () => [...adminKeys.all, "binanceKeys"] as const,
};

export function useBinanceKeysQuery(
  options?: UseQueryOptions<unknown, Error, BinanceKeysSnapshot>,
) {
  return useQuery({
    queryKey: adminKeys.binanceKeys(),
    queryFn: () => adminApi.getBinanceKeys(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function usePutBinanceKeysMutation(
  options?: UseMutationOptions<
    BinanceKeysSnapshot,
    Error,
    { api_key?: string; api_secret?: string; testnet?: boolean }
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => adminApi.putBinanceKeys(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.binanceKeys() });
      qc.invalidateQueries({ queryKey: ["safety"] });
    },
    ...options,
  });
}

export function useVerifyBinanceKeysMutation(
  options?: UseMutationOptions<
    BinanceKeysVerifyResult,
    Error,
    { api_key?: string; api_secret?: string; testnet?: boolean } | void
  >,
) {
  return useMutation({
    mutationFn: (body) => adminApi.verifyBinanceKeys(body ?? {}),
    ...options,
  });
}

export function useClearBinanceKeysMutation(
  options?: UseMutationOptions<BinanceKeysSnapshot, Error, void>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => adminApi.clearBinanceKeysOverride(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.binanceKeys() });
      qc.invalidateQueries({ queryKey: ["safety"] });
    },
    ...options,
  });
}
