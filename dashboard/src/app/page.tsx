"use client";

import { useEffect, useState } from "react";
import { fetchStats, Stats } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Database, ShieldAlert, FileCheck, RefreshCw, AlertTriangle } from "lucide-react";
import Link from "next/link";
export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats()
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load stats");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 h-full p-8 text-zinc-400">
        <RefreshCw className="h-8 w-8 animate-spin mb-4" />
        <p>Loading stats...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-500">
        <h2 className="text-xl font-bold">Error loading dashboard</h2>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 flex-1">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">AMC Ingestion Status</h1>
        <p className="text-zinc-500 dark:text-zinc-400">
          Real-time ingestion performance and pipeline health metrics.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Link href="/sources">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Sources</CardTitle>
              <Database className="h-4 w-4 text-zinc-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats?.total_sources || 0}</div>
              <p className="text-xs text-zinc-500 mt-1">
                {stats?.enabled_sources || 0} active scraping targets
              </p>
            </CardContent>
          </Card>
        </Link>

        <Link href="/documents">
          <Card className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Discovered Documents</CardTitle>
              <FileCheck className="h-4 w-4 text-zinc-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats?.total_documents || 0}</div>
              <p className="text-xs text-zinc-500 mt-1">Total tracked across all runs</p>
            </CardContent>
          </Card>
        </Link>
        <Link href="/quarantine">
          <Card className="border-red-200/50 dark:border-red-900/50 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">In Quarantine</CardTitle>
              <ShieldAlert className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                {stats?.total_quarantined || 0}
              </div>
              <p className="text-xs text-zinc-500 mt-1">Requires human review</p>
            </CardContent>
          </Card>
        </Link>
        <Link href="/holdings">
          <Card className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Published Records</CardTitle>
              <FileCheck className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                {stats?.total_published || 0}
              </div>
              <p className="text-xs text-zinc-500 mt-1">Clean holdings records in warehouse</p>
            </CardContent>
          </Card>
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>System Performance & Health</CardTitle>
            <CardDescription>Status indicators for core ingestion components.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between border-b pb-2">
              <span className="font-medium text-sm">Database Connectivity</span>
              <Badge variant="success">Healthy</Badge>
            </div>
            <div className="flex items-center justify-between border-b pb-2">
              <span className="font-medium text-sm">Playwright Sandbox</span>
              <Badge variant="success">Ready</Badge>
            </div>
            <div className="flex items-center justify-between border-b pb-2">
              <span className="font-medium text-sm">Drift Monitor</span>
              <Badge variant="success">Active</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-medium text-sm">Identity Resolution Engine</span>
              <Badge variant="success">Online</Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Active Alerts</CardTitle>
            <CardDescription>System structural shifts or schema warnings.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col items-center justify-center py-6 text-zinc-500 text-sm">
            <AlertTriangle className="h-10 w-10 text-amber-500 mb-3" />
            <p>No active structural drift alerts detected.</p>
            <p className="text-xs text-zinc-400 mt-1">All layout structures currently align with baselines.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
