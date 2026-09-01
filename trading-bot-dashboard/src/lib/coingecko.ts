export type CoinRow = {
  id: string;
  symbol: string;
  name: string;
  image: string;
  current_price: number;
  market_cap: number;
  price_change_percentage_24h: number;
};

type CacheEntry<T> = { ts: number; data: T };

const memCache = new Map<string, CacheEntry<any>>();

function readCache<T>(key: string, ttlMs: number): T | null {
  const now = Date.now();

  // 1) memory
  const mem = memCache.get(key);
  if (mem && now - mem.ts < ttlMs) return mem.data as T;

  // 2) localStorage
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry<T>;
    if (!parsed?.ts || now - parsed.ts >= ttlMs) return null;

    // refresh memory
    memCache.set(key, parsed);
    return parsed.data;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, data: T): void {
  const entry: CacheEntry<T> = { ts: Date.now(), data };
  memCache.set(key, entry);
  try {
    localStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // ignore quota / private mode
  }
}

export async function fetchCoinMarkets(args: {
  vsCurrency?: string; // e.g. "usd"
  perPage?: number; // <= 250
  page?: number;
  ttlMs?: number; // cache TTL
  signal?: AbortSignal;
}): Promise<CoinRow[]> {
  const vs = (args.vsCurrency ?? "usd").toLowerCase();
  const perPage = args.perPage ?? 50;
  const page = args.page ?? 1;
  const ttlMs = args.ttlMs ?? 60_000;

  const cacheKey = `cg:markets:${vs}:${perPage}:${page}`;
  const cached = readCache<CoinRow[]>(cacheKey, ttlMs);
  if (cached) return cached;

  const url = new URL("https://api.coingecko.com/api/v3/coins/markets");
  url.searchParams.set("vs_currency", vs);
  url.searchParams.set("order", "market_cap_desc");
  url.searchParams.set("per_page", String(perPage));
  url.searchParams.set("page", String(page));
  url.searchParams.set("sparkline", "false");
  url.searchParams.set("price_change_percentage", "24h");

  const res = await fetch(url.toString(), {
    signal: args.signal,
    headers: {
      Accept: "application/json",
    },
  });

  if (!res.ok) {
    // surface rate-limit nicely
    const text = await res.text().catch(() => "");
    throw new Error(`CoinGecko error ${res.status}: ${text || res.statusText}`);
  }

  const json = (await res.json()) as any[];

  const rows: CoinRow[] = (json ?? []).map((c) => ({
    id: c.id,
    symbol: c.symbol,
    name: c.name,
    image: c.image,
    current_price: Number(c.current_price) || 0,
    market_cap: Number(c.market_cap) || 0,
    price_change_percentage_24h:
      Number(
        c.price_change_percentage_24h_in_currency ??
          c.price_change_percentage_24h,
      ) || 0,
  }));

  writeCache(cacheKey, rows);
  return rows;
}
