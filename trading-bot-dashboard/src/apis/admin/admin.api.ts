import { http } from "../../lib/http";

export type BinanceKeysSnapshot = {
  ok?: boolean;
  overlay_present?: boolean;
  overlay_api_key_masked?: string | null;
  overlay_api_secret_set?: boolean;
  overlay_testnet?: boolean | null;
  overlay_updated_by?: string | null;
  env_api_key_set?: boolean;
  env_api_secret_set?: boolean;
  env_testnet?: boolean;
  effective_api_key_masked?: string | null;
  effective_api_secret_set?: boolean;
  effective_testnet?: boolean;
  source?: string;
  ready_for_signed_requests?: boolean;
  encryption_available?: boolean;
  _principal?: string;
};

export type BinanceKeysVerifyResult = {
  ok: boolean;
  stage?: string;
  error?: unknown;
  base_url?: string;
  testnet?: boolean;
  can_trade?: boolean;
  account_type?: string;
  balances_nonzero?: Array<{
    asset: string;
    free: string;
    locked: string;
  }>;
};

function adminHeaders(): Record<string, string> {
  const token = String(import.meta.env.VITE_ADMIN_TOKEN ?? "").trim();
  return token ? { "X-Admin-Token": token } : {};
}

export const adminApi = {
  getBinanceKeys: async (signal?: AbortSignal) => {
    const r = await http.get<BinanceKeysSnapshot>("/admin/binance-keys", {
      signal,
      headers: adminHeaders(),
    });
    return r.data;
  },

  putBinanceKeys: async (body: {
    api_key?: string;
    api_secret?: string;
    testnet?: boolean;
  }) => {
    const r = await http.put<BinanceKeysSnapshot>("/admin/binance-keys", body, {
      headers: adminHeaders(),
    });
    return r.data;
  },

  verifyBinanceKeys: async (body?: {
    api_key?: string;
    api_secret?: string;
    testnet?: boolean;
  }) => {
    const r = await http.post<BinanceKeysVerifyResult>(
      "/admin/binance-keys/verify",
      body ?? {},
      { headers: adminHeaders() },
    );
    return r.data;
  },

  clearBinanceKeysOverride: async () => {
    const r = await http.delete<BinanceKeysSnapshot & { cleared?: boolean }>(
      "/admin/binance-keys/override",
      { headers: adminHeaders() },
    );
    return r.data;
  },
};
