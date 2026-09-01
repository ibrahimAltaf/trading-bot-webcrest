import { NavLink, Outlet } from "react-router-dom";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

const tabs = [
  { to: "/exchange/monitor", label: "Monitor", desc: "Chart, orders, balances" },
  { to: "/exchange/orders", label: "Orders" },
  { to: "/exchange/trades", label: "Trades" },
  { to: "/exchange/buy", label: "Buy" },
  { to: "/exchange/auto-trade", label: "Auto-trade" },
  { to: "/exchange/adaptive", label: "Adaptive" },
];

export default function ExchangeLayout() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-bold text-slate-900">Exchange</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Live prices, orders, and trading — API integrated with TanStack Query
          </p>
        </div>
        <nav className="flex flex-wrap gap-1 px-4 pb-3">
          {tabs.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      <Outlet />
    </div>
  );
}
