import { useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./contexts/AuthContext";
import AppShell from "./components/layout/AppShell";
import ExchangeConnectionModal from "./components/ExchangeConnectionModal";
import Login from "./pages/Login";
import Register from "./pages/Register";
import DashboardPage from "./pages/Dashboard";
import Paper from "./pages/Paper";
import Exchange from "./pages/Exchange";
import AdaptiveEngine from "./pages/AdaptiveEngine";
import Logs from "./pages/Logs";
import SettingsPage from "./pages/Settings";
import ExecutionModeBadge from "./components/safety/ExecutionModeBadge";

import BacktestLayout from "./pages/Backtest/BacktestLayout";
import BacktestOverview from "./pages/Backtest/BacktestOverview";
import BacktestRecentRuns from "./pages/Backtest/BacktestRecentRuns";
import BacktestRun from "./pages/Backtest/BacktestRun";

import {
  LayoutDashboard,
  Activity,
  Settings as SettingsIcon,
  LayoutTemplate,
  List,
  Play,
  PlayCircle,
  CandlestickChart,
  ArrowLeftRight,
  ReceiptText,
  ArrowUpDown,
  ShoppingCart,
  Newspaper,
  LogsIcon,
  MonitorCheck,
} from "lucide-react";

import PaperRun from "./pages/paper/PaperRun";
import PaperPrice from "./pages/paper/PaperPrice";
import ExchangeOrders from "./pages/exchange/ExchangeOrders";
import ExchangesTrades from "./pages/exchange/ExchangesTrades";
import ExchangeMonitor from "./pages/exchange/ExchangeMonitor";
import BacktestCompare from "./pages/Backtest/BacktestCompare";
import BacktestValidate from "./pages/Backtest/BacktestValidate";
import PaperWallet from "./pages/paper/PaperWallet";
import PaperPositions from "./pages/paper/PaperPositions";
import PaperResetWallet from "./pages/paper/PaperResetWallet";
import ExchangeAutoTrade from "./pages/exchange/ExchangeAutoTrade";
import ExchangesLiveRun from "./pages/exchange/ExchangeRun";
import StatusSummary from "./pages/summary/StatusSummary";

type NavChild = { label: string; path: string; icon?: any };
type NavItem = {
  section?: string;
  label: string;
  icon: any;
  path?: string;
  active?: boolean;
  items?: NavChild[];
};

export default function App() {
  const { user, loading: authLoading, logout } = useAuth();
  const { pathname: activePath } = useLocation();
  const [exchangeModalOpen, setExchangeModalOpen] = useState(false);

  const navItems = useMemo<NavItem[]>(
    () => [
      {
        section: "TRADING",
        label: "Dashboard",
        icon: LayoutDashboard,
        path: "/",
      },
      {
        label: "Backtest",
        icon: Activity,
        path: "/backtest",
        items: [
          {
            label: "Overview",
            path: "/backtest/overview",
            icon: LayoutTemplate,
          },
          { label: "Recent runs", path: "/backtest/recent", icon: List },
          { label: "Run backtest", path: "/backtest/run", icon: Play },
          { label: "Validate", path: "/backtest/validate", icon: ShoppingCart },
          { label: "Compare", path: "/backtest/compare", icon: ShoppingCart },
        ],
      },
      {
        label: "Paper",
        icon: Newspaper,
        path: "/paper",
        items: [
          { label: "Run", path: "/paper/run", icon: PlayCircle },
          { label: "Price", path: "/paper/price", icon: CandlestickChart },
          { label: "Positions", path: "/paper/positions", icon: List },
          {
            label: "Reset Wallet",
            path: "/paper/reset-wallet",
            icon: ArrowUpDown,
          },
        ],
      },
      {
        label: "Exchange",
        icon: ArrowLeftRight,
        path: "/exchange/monitor",
        items: [
          { label: "Monitor", path: "/exchange/monitor", icon: Activity },
          { label: "Orders", path: "/exchange/orders", icon: ReceiptText },
          { label: "Trades", path: "/exchange/trades", icon: ArrowUpDown },
          { label: "Buy", path: "/exchange/buy", icon: ShoppingCart },
          { label: "Auto-trade", path: "/exchange/auto-trade", icon: Play },
        ],
      },
      {
        label: "Adaptive Engine",
        path: "/exchange/adaptive",
        icon: Activity,
      },
      {
        label: "Logs",
        icon: LogsIcon,
        path: "/logs",
      },
      {
        label: "Status Summary",
        icon: MonitorCheck,
        path: "/status-summary",
      },
      {
        section: "SYSTEM",
        label: "Settings",
        icon: SettingsIcon,
        path: "/settings",
      },
    ],
    [],
  );

  const navWithActive = useMemo<NavItem[]>(
    () =>
      navItems.map((it) => ({
        ...it,
        active: it.path
          ? it.path === "/"
            ? activePath === "/"
            : activePath.startsWith(it.path)
          : false,
      })),
    [navItems, activePath],
  );

  const title = useMemo(() => {
    const parent = navItems.find((n) =>
      n.path === "/"
        ? activePath === "/"
        : n.path
          ? activePath.startsWith(n.path)
          : false,
    );

    const child = parent?.items?.find((c) =>
      activePath === c.path ? true : activePath.startsWith(c.path + "/"),
    );

    return child?.label ?? parent?.label ?? "Dashboard";
  }, [navItems, activePath]);

  const subtitle = useMemo(() => {
    switch (true) {
      case activePath === "/":
        return "Overview of trading system";
      case activePath.startsWith("/backtest"):
        return "Run, validate, and compare strategy backtests";
      case activePath.startsWith("/paper"):
        return "Paper trading runner and price checks";
      case activePath.startsWith("/exchange"):
        return "Balances, orders, trades, and auto-trade";
      case activePath.startsWith("/logs"):
        return "System logs";
      case activePath.startsWith("/status-summary"):
        return "System health, scheduler, model, database, and exchange status";
      case activePath.startsWith("/settings"):
        return "Phase 2A safety, execution mode, keys, and reconciliation";
      default:
        return "AI Trading System";
    }
  }, [activePath]);

  if (authLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-slate-100">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-300 border-t-emerald-600" />
      </div>
    );
  }

  const rightActions = user ? (
    <div className="flex items-center gap-2">
      <ExecutionModeBadge />
      <button
        type="button"
        onClick={() => setExchangeModalOpen(true)}
        className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50"
      >
        Connect exchange
      </button>
      <span className="text-sm text-slate-500">{user.email}</span>
      <button
        type="button"
        onClick={logout}
        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
      >
        Logout
      </button>
    </div>
  ) : (
    <div className="flex items-center gap-2">
      <Link
        to="/login"
        className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50"
      >
        Sign in
      </Link>
      <Link
        to="/register"
        className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
      >
        Create account
      </Link>
    </div>
  );

  return (
    <>
      <AppShell
        title={title}
        subtitle={subtitle}
        navItems={navWithActive}
        rightActions={rightActions}
      >
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<DashboardPage />} />

          <Route path="/backtest" element={<BacktestLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<BacktestOverview />} />
            <Route path="recent" element={<BacktestRecentRuns />} />
            <Route path="run" element={<BacktestRun />} />
            <Route path="validate" element={<BacktestValidate />} />
            <Route path="compare" element={<BacktestCompare />} />
          </Route>

          <Route path="/paper" element={<Paper />}>
            <Route index element={<Navigate to="run" replace />} />
            <Route path="run" element={<PaperRun />} />
            <Route path="price" element={<PaperPrice />} />
            <Route path="wallet" element={<PaperWallet />} />
            <Route path="positions" element={<PaperPositions />} />
            <Route path="reset-wallet" element={<PaperResetWallet />} />
          </Route>

          <Route path="/exchange" element={<Exchange />}>
            <Route path="monitor" element={<ExchangeMonitor />} />
            <Route path="orders" element={<ExchangeOrders />} />
            <Route path="trades" element={<ExchangesTrades />} />
            <Route path="buy" element={<ExchangesLiveRun />} />
            <Route path="auto-trade" element={<ExchangeAutoTrade />} />
            <Route path="adaptive" element={<AdaptiveEngine />} />
          </Route>

          <Route path="/logs" element={<Logs />} />
          <Route path="/status-summary" element={<StatusSummary />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>

      {user && (
        <ExchangeConnectionModal
          open={exchangeModalOpen}
          onClose={() => setExchangeModalOpen(false)}
        />
      )}
    </>
  );
}
