import { http } from "../../lib/http";

export type LogLevel = "INFO" | "ERROR" | "WARN" | "DEBUG" | string;

export type LogItem = {
  id: number;
  ts: string; // ISO string
  level: LogLevel;
  category: string;
  message: string;
  symbol?: string | null;
  timeframe?: string | null;
};

export type LogsListResponse = {
  ok: boolean;
  items: LogItem[];
};

export const logsApi = {
  list: async (params?: { limit?: number }, signal?: AbortSignal) => {
    const r = await http.get<LogsListResponse>("/logs", { params, signal });
    return r.data;
  },
};
