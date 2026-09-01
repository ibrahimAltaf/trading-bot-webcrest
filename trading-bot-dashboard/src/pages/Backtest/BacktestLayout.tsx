import { NavLink, Outlet } from "react-router-dom";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export default function BacktestLayout() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">Backtest</div>
            <div className="mt-1 text-xs text-slate-500">
              Overview, recent runs, and run backtest
            </div>
          </div>

          <div className="flex items-center gap-2">
            <NavLink
              to="/backtest/overview"
              className={({ isActive }) =>
                cn(
                  "h-9 rounded-lg border px-3 text-sm font-semibold flex justify-center text-center align-middle items-center",
                  isActive
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-800",
                )
              }
            >
              Overview
            </NavLink>

            <NavLink
              to="/backtest/recent"
              className={({ isActive }) =>
                cn(
                  "h-9 rounded-lg border px-3 text-sm font-semibold flex justify-center text-center align-middle items-center",
                  isActive
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-800",
                )
              }
            >
              Recent runs
            </NavLink>

            <NavLink
              to="/backtest/run"
              className={({ isActive }) =>
                cn(
                  "h-9 rounded-lg border px-3 text-sm font-semibold flex justify-center text-center align-middle items-center",
                  isActive
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-800",
                )
              }
            >
              Run backtest
            </NavLink>
          </div>
        </div>
      </div>

      <Outlet />
    </div>
  );
}
