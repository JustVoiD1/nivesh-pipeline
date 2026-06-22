"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LayoutDashboard, ShieldAlert, Database, FileText, FolderOpen, TrendingUp } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const routes = [
    {
      label: "Dashboard",
      icon: LayoutDashboard,
      href: "/",
      active: pathname === "/",
    },
    {
      label: "Discovered Documents",
      icon: FolderOpen,
      href: "/documents",
      active: pathname === "/documents",
    },
    {
      label: "Quarantine Queue",
      icon: ShieldAlert,
      href: "/quarantine",
      active: pathname === "/quarantine",
    },
    {
      label: "Sources",
      icon: Database,
      href: "/sources",
      active: pathname === "/sources",
    },
    {
      label: "Published Holdings",
      icon: FileText,
      href: "/holdings",
      active: pathname === "/holdings",
    },
  ];

  return (
    <div className="flex w-64 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex h-16 items-center px-6 border-b border-zinc-200 dark:border-zinc-800">
        <Link href="/" className="flex items-center gap-2 font-semibold text-lg text-zinc-900 dark:text-zinc-50">
          <div className="h-8 w-8 rounded-xl bg-emerald-600 dark:bg-emerald-400 flex items-center justify-center text-xs text-white dark:text-black font-bold"><TrendingUp height={18} width={18} /></div>
          Nivesh Copilot
        </Link>
      </div>
      <div className="flex-1 space-y-1 p-4">
        {routes.map((route) => (
          <Link
            key={route.href}
            href={route.href}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
              route.active
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
                : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-50"
            )}
          >
            <route.icon className="h-4 w-4" />
            {route.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
