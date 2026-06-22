"use client";

import { useEffect, useState } from "react";
import { fetchSources, triggerPipelineRun, stopPipelineRun, SourceConfig } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Database, RefreshCw, Play, ExternalLink } from "lucide-react";

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});
  const [stopping, setStopping] = useState<Record<string, boolean>>({});

  const loadData = (showLoading = true) => {
    if (showLoading) setLoading(true);
    fetchSources()
      .then((data) => {
        setSources(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load sources");
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
    // Poll sources running status every 3 seconds
    const interval = setInterval(() => {
      loadData(false);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleTrigger = async (sourceKey: string) => {
    setTriggering(prev => ({ ...prev, [sourceKey]: true }));
    // Optimistically update UI to show as running immediately
    setSources(prev => prev.map(s => s.source_key === sourceKey ? { ...s, is_running: true } : s));
    try {
      await triggerPipelineRun(sourceKey);
      loadData(false);
    } catch (err: any) {
      alert(err.message || "Failed to trigger pipeline");
      loadData(false);
    } finally {
      setTriggering(prev => ({ ...prev, [sourceKey]: false }));
    }
  };

  const handleStop = async (sourceKey: string) => {
    setStopping(prev => ({ ...prev, [sourceKey]: true }));
    // Optimistically update UI to show as stopped immediately
    setSources(prev => prev.map(s => s.source_key === sourceKey ? { ...s, is_running: false } : s));
    try {
      await stopPipelineRun(sourceKey);
      loadData(false);
    } catch (err: any) {
      alert(err.message || "Failed to stop pipeline");
      loadData(false);
    } finally {
      setStopping(prev => ({ ...prev, [sourceKey]: false }));
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 h-full p-8 text-zinc-400">
        <RefreshCw className="h-8 w-8 animate-spin mb-4" />
        <p>Loading sources list...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-500">
        <h2 className="text-xl font-bold">Error loading sources</h2>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="relative p-8 space-y-8 flex-1 h-full">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">AMC Ingestion Sources</h1>
        <p className="text-zinc-500 dark:text-zinc-400">
          Manage and trigger extraction pipelines for heterogeneous asset managers.
        </p>
      </div>

      <Card className="h-[75%] overflow-auto">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Configured Targets</CardTitle>
          </div>
          <Button size="sm" variant="outline" onClick={() => loadData(true)}>
            <RefreshCw className="h-4 w-4 mr-2" /> Refresh
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>AMC Name</TableHead>
                <TableHead>Source Key</TableHead>
                <TableHead>Base URL</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>File Types</TableHead>
                <TableHead className="text-right">Scrape Run</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((src) => (
                <TableRow key={src.id}>
                  <TableCell className="font-semibold">{src.amc_name}</TableCell>
                  <TableCell>
                    <code className="text-xs px-1.5 py-0.5 bg-zinc-100 rounded text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300">
                      {src.source_key}
                    </code>
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-zinc-500">
                    <a href={src.base_url} target="_blank" rel="noreferrer" className="hover:underline inline-flex items-center gap-1">
                      {src.base_url} <ExternalLink className="h-3 w-3" />
                    </a>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{src.discovery_strategy}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {src.file_types.map(ft => (
                        <Badge key={ft} variant="outline" className="text-xs uppercase">{ft}</Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      {src.is_running ? (
                        <>
                          <span className="inline-flex items-center text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-400 px-4 py-2 rounded-md">
                            <RefreshCw className="h-3.5 w-3.5 animate-spin mr-1.5" /> Running
                          </span>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleStop(src.source_key)}
                            disabled={stopping[src.source_key]}
                            className=""
                          >
                            {stopping[src.source_key] ? "Stopping..." : "Stop"}
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          className="bg-emerald-600 dark:bg-emerald-400 hover:bg-emerald-500 dark:hover:bg-emerald-300"
                          onClick={() => {
                            setSources(prev => prev.map(s => s.id === src.id ? { ...s, is_running: true } : s))
                            handleTrigger(src.source_key)
                          }}
                          disabled={triggering[src.source_key]}
                        >
                          {triggering[src.source_key] ? (
                            <RefreshCw className="h-3.5 w-3.5 animate-spin mr-1.5" />
                          ) : (
                            <Play className="h-3.5 w-3.5 mr-1.5" />
                          )}
                          {triggering[src.source_key] ? "Starting..." : "Run Scrape"}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}

            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
