"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Moon,
  LogOut,
  X,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import type { ShellNavItem } from "./AppShell";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
  items,
}: {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  items: ShellNavItem[];
}) {
  const initialOpen = useMemo(() => {
    const open: Record<string, boolean> = {};
    for (const it of items) {
      if (it.items?.length) open[it.label] = Boolean(it.active);
    }
    return open;
  }, [items]);

  const [open, setOpen] = useState<Record<string, boolean>>(initialOpen);

  useEffect(() => {
    setOpen((prev) => {
      const next = { ...prev };

      for (const it of items) {
        if (!it.items?.length) continue;

        const anyChildActive =
          (it.items as any[])?.some((c) => c?.active) || it.active;

        if (anyChildActive && next[it.label] === undefined) {
          next[it.label] = true;
        }
      }

      return next;
    });
  }, [items]);

  // ✅ Mobile overlay wrapper
  const isMobileDrawer = mobileOpen;

  return (
    <>
      {/* Mobile backdrop */}
      {isMobileDrawer ? (
        <button
          type="button"
          onClick={onMobileClose}
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          aria-label="Close sidebar backdrop"
        />
      ) : null}

      <aside
        className={cn(
          "flex h-dvh flex-col overflow-hidden min-h-0 rounded-2xl border border-slate-200 bg-white shadow-sm",
          // desktop sizing
          !isMobileDrawer && (collapsed ? "w-[84px]" : "w-[300px]"),
          // mobile drawer positioning + safe height
          isMobileDrawer
            ? "fixed left-4 top-4 bottom-4 z-50 w-[300px] md:hidden"
            : "",
        )}
      >
        {/* Header */}
        <div
          className={cn(
            "flex items-center justify-between gap-3 py-4",
            collapsed ? "px-3" : "px-5",
          )}
        >
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-emerald-50 text-emerald-700">
              <span className="text-sm font-bold">T</span>
            </div>

            {!collapsed ? (
              <div className="leading-tight">
                <div className="text-sm font-semibold text-slate-900">
                  Trading Bot
                </div>
                <div className="text-xs text-slate-500">Admin Panel</div>
              </div>
            ) : null}
          </div>

          {/* ✅ Desktop collapse toggle OR Mobile close button */}
          {isMobileDrawer ? (
            <button
              type="button"
              onClick={onMobileClose}
              className="grid h-10 w-10 place-items-center rounded-2xl border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              aria-label="Close sidebar"
            >
              <X className="h-5 w-5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onToggle}
              className="grid h-10 w-10 place-items-center rounded-2xl border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              aria-label="Toggle sidebar"
            >
              {collapsed ? (
                <ChevronRight className="h-5 w-5" />
              ) : (
                <ChevronLeft className="h-5 w-5" />
              )}
            </button>
          )}
        </div>

        <div
          className={cn(
            "flex-1 min-h-0 overflow-y-auto pb-3",
            collapsed ? "px-2" : "px-3",
          )}
        >
          {items.map((item, idx) => {
            const isSection = Boolean(item.section);
            const Icon = item.icon;
            const hasChildren =
              Array.isArray(item.items) && item.items.length > 0;
            const isOpen = open[item.label] === true;

            return (
              <React.Fragment key={`${item.label}-${idx}`}>
                {isSection && !collapsed ? (
                  <div className="px-2 pb-2 pt-3 text-[11px] font-semibold tracking-wide text-slate-400">
                    {item.section}
                  </div>
                ) : null}

                {/* Parent row */}
                {hasChildren ? (
                  <button
                    type="button"
                    onClick={() => {
                      setOpen((p) => ({ ...p, [item.label]: !p[item.label] }));
                    }}
                    className={cn(
                      "group flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left transition",
                      item.active
                        ? "bg-emerald-50 text-emerald-800"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                    )}
                    title={collapsed ? item.label : undefined}
                    aria-expanded={isOpen}
                  >
                    <span
                      className={cn(
                        "grid h-10 w-10 place-items-center rounded-2xl",
                        item.active
                          ? "bg-white text-emerald-700 shadow-sm"
                          : "bg-slate-50 text-slate-600 group-hover:bg-white",
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </span>

                    {!collapsed ? (
                      <>
                        <span className="text-sm font-medium">
                          {item.label}
                        </span>

                        <span className="ml-auto grid h-8 w-8 place-items-center rounded-xl text-slate-500">
                          {isOpen ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                        </span>
                      </>
                    ) : null}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      item.onClick?.();
                      onMobileClose?.();
                    }}
                    className={cn(
                      "group flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left transition",
                      item.active
                        ? "bg-emerald-50 text-emerald-800"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    <span
                      className={cn(
                        "grid h-10 w-10 place-items-center rounded-2xl",
                        item.active
                          ? "bg-white text-emerald-700 shadow-sm"
                          : "bg-slate-50 text-slate-600 group-hover:bg-white",
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </span>

                    {!collapsed ? (
                      <span className="text-sm font-medium">{item.label}</span>
                    ) : null}
                  </button>
                )}

                {/* Children list */}
                {!collapsed && hasChildren && isOpen ? (
                  <div className="ml-[52px] mt-1 space-y-1">
                    {item.items!.map((child, cIdx) => {
                      const childActive = Boolean((child as any).active);
                      const childPath = (child as any).path as
                        | string
                        | undefined;

                      return (
                        <NavLink
                          key={`${child.label}-${cIdx}`}
                          to={childPath ?? "#"}
                          onClick={() => onMobileClose?.()}
                          className={cn(
                            "flex w-full items-center rounded-xl px-3 py-2 text-left text-sm font-medium transition",
                            childActive
                              ? "bg-slate-100 text-slate-900"
                              : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                          )}
                          end
                        >
                          {child.label}
                        </NavLink>
                      );
                    })}
                  </div>
                ) : null}
              </React.Fragment>
            );
          })}
        </div>

        {/* Footer */}
        <div
          className={cn(
            "mt-auto border-t border-slate-200 p-4 pb-8",
            collapsed && "px-3",
          )}
        >
          <div
            className={cn(
              "flex items-center gap-3",
              collapsed && "justify-center",
            )}
          >
            <div className="h-10 w-10 rounded-full bg-slate-200" />
            {!collapsed ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-900">
                  Trading Bot
                </div>
                <div className="text-xs text-slate-500">Admin Manager</div>
              </div>
            ) : null}
          </div>

          <div
            className={cn(
              "mt-4",
              collapsed
                ? "flex flex-col gap-2"
                : "flex items-center justify-between gap-2",
            )}
          >
            <button
              type="button"
              className={cn(
                "flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50",
                collapsed ? "w-full justify-center px-0" : "",
              )}
              title={collapsed ? "Dark mode" : undefined}
            >
              <Moon className="h-4 w-4" />
              {!collapsed ? <span>Dark mode</span> : null}
            </button>

            <button
              type="button"
              className={cn(
                "flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50",
                collapsed ? "w-full justify-center px-0" : "",
              )}
              title={collapsed ? "Log out" : undefined}
            >
              <LogOut className="h-4 w-4" />
              {!collapsed ? <span>Log out</span> : null}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
