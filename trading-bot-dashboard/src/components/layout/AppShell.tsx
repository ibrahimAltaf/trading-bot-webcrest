"use client";

import React, { useMemo, useState } from "react";
import { useNavigate, type To } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import type { LucideIcon } from "lucide-react";

export type ShellNavChild = {
  label: string;
  path?: string;
  onClick?: () => void;
  active?: boolean;
};

export type ShellNavItem = {
  section?: string;
  label: string;
  icon: LucideIcon | any;
  path?: string;
  onClick?: () => void;
  active?: boolean;
  items?: ShellNavChild[];
};

export default function AppShell({
  title,
  subtitle,
  navItems,
  rightActions,
  children,
}: {
  title: string;
  subtitle: string;
  navItems: Array<{
    section?: string;
    label: string;
    icon: any;
    path?: string;
    active?: boolean;
    items?: Array<{
      label: string;
      path: string;
      icon?: any;
      active?: boolean;
    }>;
  }>;
  rightActions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const navigate = useNavigate();

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const items = useMemo<ShellNavItem[]>(() => {
    return navItems.map((it) => {
      const path = it.path;
      return {
        ...it,
        onClick: path ? () => navigate(path as To) : undefined,
      };
    });
  }, [navItems, navigate]);

  return (
    <div className="flex gap-4 p-4 bg-slate-50 h-dvh overflow-hidden">
      {/* Desktop sidebar fixed */}
      <div className="hidden md:block">
        <Sidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          mobileOpen={false}
          onMobileClose={() => {}}
          items={items}
        />
      </div>

      {/* Mobile sidebar */}
      {mobileOpen ? (
        <div className="md:hidden">
          <Sidebar
            collapsed={false}
            onToggle={() => setMobileOpen(false)}
            mobileOpen={mobileOpen}
            onMobileClose={() => setMobileOpen(false)}
            items={items}
          />
        </div>
      ) : null}

      {/* Main */}
      <main className="flex-1 min-w-0 h-dvh overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-6 py-4">
          <Topbar
            title={title}
            subtitle={subtitle}
            rightActions={rightActions}
            onMenuClick={() => setMobileOpen(true)}
          />
        </div>
        <div className="h-[calc(100dvh-73px)] overflow-y-auto overscroll-contain p-6 pb-15">
          {children}
        </div>
      </main>
    </div>
  );
}
