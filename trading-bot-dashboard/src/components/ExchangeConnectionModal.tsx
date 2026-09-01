import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { authApi } from "../apis/auth/auth.api";
import { toApiError } from "../lib/http";

const EXCHANGES = [
  { id: "binance", label: "Binance" },
  { id: "binanceus", label: "Binance US" },
  { id: "bybit", label: "Bybit" },
  { id: "okx", label: "OKX" },
  { id: "kucoin", label: "KuCoin" },
  { id: "gateio", label: "Gate.io" },
  { id: "kraken", label: "Kraken" },
] as const;

type Props = { open: boolean; onClose: () => void };

export default function ExchangeConnectionModal({ open, onClose }: Props) {
  const { token } = useAuth();
  const [exchangeId, setExchangeId] = useState("binance");
  const [testnet, setTestnet] = useState(true);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!open || !token) return;
    setMessage(null);
    setLoading(true);
    authApi
      .getExchangeConfig(token)
      .then((r) => {
        setExchangeId(r.exchange_id || "binance");
        setTestnet(r.testnet ?? true);
        setApiKey("");
        setApiSecret("");
      })
      .catch(() => setMessage({ type: "err", text: "Could not load config" }))
      .finally(() => setLoading(false));
  }, [open, token]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setMessage(null);
    setSaving(true);
    try {
      await authApi.putExchangeConfig(token, {
        exchange_id: exchangeId,
        testnet,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        ...(apiSecret.trim() ? { api_secret: apiSecret.trim() } : {}),
      });
      setMessage({ type: "ok", text: "Exchange connection saved." });
      setApiKey("");
      setApiSecret("");
      setTimeout(() => { setMessage(null); onClose(); }, 1500);
    } catch (err: any) {
      setMessage({ type: "err", text: toApiError(err).message || "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-900">Connect exchange</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <form onSubmit={handleSave} className="p-5 space-y-4">
          {loading && (
            <div className="text-sm text-slate-500">Loading…</div>
          )}
          {!loading && (
            <>
              {message && (
                <div
                  className={`rounded-lg px-3 py-2 text-sm ${
                    message.type === "ok"
                      ? "bg-emerald-50 text-emerald-800"
                      : "bg-rose-50 text-rose-800"
                  }`}
                >
                  {message.text}
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-slate-700">Exchange</label>
                <select
                  value={exchangeId}
                  onChange={(e) => setExchangeId(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  {EXCHANGES.map((ex) => (
                    <option key={ex.id} value={ex.id}>
                      {ex.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="testnet"
                  checked={testnet}
                  onChange={(e) => setTestnet(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                />
                <label htmlFor="testnet" className="text-sm font-medium text-slate-700">
                  Use testnet / sandbox (no real funds)
                </label>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Leave blank to keep existing"
                  autoComplete="off"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">API Secret</label>
                <input
                  type="password"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  placeholder="Leave blank to keep existing"
                  autoComplete="off"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 rounded-lg bg-emerald-600 px-4 py-2.5 font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-lg border border-slate-300 px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  );
}
