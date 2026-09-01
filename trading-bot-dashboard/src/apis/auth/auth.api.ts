import { http } from "../../lib/http";

const AUTH = "/auth";

export type User = { id: number; email: string; name: string | null };

export type AuthResponse = {
  ok: boolean;
  user: User;
  token: string;
};

export type MeResponse = { ok: boolean; user: User };

export type ExchangeConfigResponse = {
  ok: boolean;
  exchange_id: string;
  testnet: boolean;
  api_key_set: boolean;
  api_secret_set: boolean;
};

export type ExchangeConfigIn = {
  exchange_id?: string;
  testnet?: boolean;
  api_key?: string;
  api_secret?: string;
};

export const authApi = {
  register: (body: { email: string; password: string; name?: string }) =>
    http.post<AuthResponse>(`${AUTH}/register`, body).then((r) => r.data),

  login: (body: { email: string; password: string }) =>
    http.post<AuthResponse>(`${AUTH}/login`, body).then((r) => r.data),

  me: (token: string) =>
    http
      .get<MeResponse>(`${AUTH}/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((r) => r.data),

  getExchangeConfig: (token: string) =>
    http
      .get<ExchangeConfigResponse>(`${AUTH}/exchange-config`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((r) => r.data),

  putExchangeConfig: (token: string, body: ExchangeConfigIn) =>
    http
      .put<ExchangeConfigResponse>(`${AUTH}/exchange-config`, body, {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((r) => r.data),
};

export const AUTH_TOKEN_KEY = "auth_token";
