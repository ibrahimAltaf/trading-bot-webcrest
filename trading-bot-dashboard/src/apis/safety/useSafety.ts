import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import type { ExecutionMode } from "../../lib/executionMode";
import {
  safetyApi,
  type LiveReadinessResponse,
  type ExecutionModeSnapshot,
} from "./safety.api";

export const safetyKeys = {
  all: ["safety"] as const,
  status: () => [...safetyKeys.all, "status"] as const,
  killSwitch: () => [...safetyKeys.all, "killSwitch"] as const,
  limits: () => [...safetyKeys.all, "limits"] as const,
  reconcile: () => [...safetyKeys.all, "reconcile"] as const,
  exchangeReconcile: (mode?: string, symbols?: string) =>
    [...safetyKeys.all, "exchangeReconcile", mode, symbols] as const,
  executionMode: () => [...safetyKeys.all, "executionMode"] as const,
  liveReadiness: () => [...safetyKeys.all, "liveReadiness"] as const,
  shadowAudit: (symbol?: string) =>
    [...safetyKeys.all, "shadowAudit", symbol] as const,
  operationalReadiness: () =>
    [...safetyKeys.all, "operationalReadiness"] as const,
  phase2c: () => [...safetyKeys.all, "phase2c"] as const,
};

function invalidateSafety(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: safetyKeys.all });
}

export function useSafetyStatusQuery(
  options?: UseQueryOptions<unknown, Error, Awaited<ReturnType<typeof safetyApi.status>>>,
) {
  return useQuery({
    queryKey: safetyKeys.status(),
    queryFn: () => safetyApi.status(),
    refetchInterval: 15_000,
    ...options,
  });
}

export function useKillSwitchQuery(
  options?: UseQueryOptions<unknown, Error, Awaited<ReturnType<typeof safetyApi.killSwitch>>>,
) {
  return useQuery({
    queryKey: safetyKeys.killSwitch(),
    queryFn: () => safetyApi.killSwitch(),
    refetchInterval: 10_000,
    ...options,
  });
}

export function useExecutionModeQuery(
  options?: UseQueryOptions<
    unknown,
    Error,
    { ok: boolean } & ExecutionModeSnapshot
  >,
) {
  return useQuery({
    queryKey: safetyKeys.executionMode(),
    queryFn: () => safetyApi.executionMode(),
    refetchInterval: 10_000,
    ...options,
  });
}

export function useLiveReadinessQuery(
  options?: UseQueryOptions<unknown, Error, LiveReadinessResponse>,
) {
  return useQuery({
    queryKey: safetyKeys.liveReadiness(),
    queryFn: () => safetyApi.liveReadiness(),
    refetchInterval: 20_000,
    ...options,
  });
}

export function useShadowAuditQuery(symbol?: string) {
  return useQuery({
    queryKey: safetyKeys.shadowAudit(symbol),
    queryFn: () => safetyApi.shadowAudit({ symbol, limit: 100 }),
    refetchInterval: 30_000,
  });
}

export function useOperationalReadinessQuery() {
  return useQuery({
    queryKey: safetyKeys.operationalReadiness(),
    queryFn: () => safetyApi.operationalReadiness(),
    staleTime: 60_000,
  });
}

export function useSafetyLimitsQuery(
  options?: UseQueryOptions<unknown, Error, Awaited<ReturnType<typeof safetyApi.limits>>>,
) {
  return useQuery({
    queryKey: safetyKeys.limits(),
    queryFn: () => safetyApi.limits(),
    staleTime: 60_000,
    ...options,
  });
}

export function useSafetyReconcileQuery(
  options?: UseQueryOptions<unknown, Error, Record<string, unknown>>,
) {
  return useQuery({
    queryKey: safetyKeys.reconcile(),
    queryFn: () => safetyApi.reconcile(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useExchangeReconcileQuery(
  mode: ExecutionMode = "shadow",
  symbols?: string,
  options?: UseQueryOptions<unknown, Error, Record<string, unknown>>,
) {
  return useQuery({
    queryKey: safetyKeys.exchangeReconcile(mode, symbols),
    queryFn: () => safetyApi.exchangeReconcile({ mode, symbols }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useSetExecutionModeMutation(
  options?: UseMutationOptions<
    Awaited<ReturnType<typeof safetyApi.setExecutionMode>>,
    Error,
    { mode: ExecutionMode; reason?: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => safetyApi.setExecutionMode(body),
    onSuccess: () => {
      invalidateSafety(qc);
      qc.invalidateQueries({ queryKey: ["exchange"] });
    },
    ...options,
  });
}

export function useClearExecutionModeMutation(
  options?: UseMutationOptions<
    Awaited<ReturnType<typeof safetyApi.clearExecutionModeOverride>>,
    Error,
    void
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => safetyApi.clearExecutionModeOverride(),
    onSuccess: () => invalidateSafety(qc),
    ...options,
  });
}

export function useEngageKillSwitchMutation(
  options?: UseMutationOptions<
    Awaited<ReturnType<typeof safetyApi.engageKillSwitch>>,
    Error,
    { reason: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => safetyApi.engageKillSwitch(body),
    onSuccess: () => invalidateSafety(qc),
    ...options,
  });
}

export function useReleaseKillSwitchMutation(
  options?: UseMutationOptions<
    Awaited<ReturnType<typeof safetyApi.releaseKillSwitch>>,
    Error,
    { reason: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => safetyApi.releaseKillSwitch(body),
    onSuccess: () => invalidateSafety(qc),
    ...options,
  });
}

export function usePhase2cStatusQuery() {
  return useQuery({
    queryKey: safetyKeys.phase2c(),
    queryFn: () => safetyApi.phase2cStatus(),
    refetchInterval: 15_000,
  });
}

export function useActivatePhase2cMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { reason: string; by?: string }) =>
      safetyApi.activatePhase2c(body),
    onSuccess: () => invalidateSafety(qc),
  });
}

export function useDeactivatePhase2cMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { reason: string; by?: string }) =>
      safetyApi.deactivatePhase2c(body),
    onSuccess: () => invalidateSafety(qc),
  });
}
