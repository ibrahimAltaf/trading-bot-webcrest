"use client";

import React from "react";
import { Menu } from "lucide-react";

export default function Topbar({
  title,
  subtitle,
  rightActions,
  onMenuClick,
}: {
  title: string;
  subtitle?: string;
  rightActions?: React.ReactNode;
  onMenuClick?: () => void;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onMenuClick}
          className="mt-1 inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 md:hidden"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div className="leading-6">
          <div className="text-[28px] font-semibold text-slate-900">
            {title}
          </div>
          {subtitle ? (
            <div className="mt-1 text-[12px] text-slate-500">{subtitle}</div>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {rightActions ? (
          rightActions
        ) : (
          <>
            <button
              type="button"
              className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-base font-semibold text-slate-800 shadow-sm hover:bg-slate-50"
            >
              <span className="text-slate-500">Time period:</span>
              <span>This month</span>
            </button>
          </>
        )}
      </div>
    </header>
  );
}
