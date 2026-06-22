"use client";

import { useEffect, useState } from "react";
import { fetchDiscoveredDocuments, DiscoveredDocument } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, ExternalLink, ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DiscoveredDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const pageSize = 25;

  const loadData = () => {
    setLoading(true);
    fetchDiscoveredDocuments(pageSize, (page - 1) * pageSize)
      .then((data) => {
        setDocuments(data);
        setHasMore(data.length === pageSize);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load documents");
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, [page]);

  const formatBytes = (bytes: number | null) => {
    if (bytes === null || bytes === undefined) return "—";
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const getStatusBadgeVariant = (status: string) => {
    switch (status.toUpperCase()) {
      case "PUBLISHED":
      case "EXTRACTED":
        return "success";
      case "QUARANTINED":
        return "warning";
      case "FAILED":
      case "REJECTED":
        return "destructive";
      default:
        return "secondary";
    }
  };

  return (
    <div className="p-8 space-y-8 flex-1">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Discovered Documents</h1>
          <p className="text-zinc-500 dark:text-zinc-400">
            Audit trail of all files scraped, analyzed, and ingested by the pipeline.
          </p>
        </div>
        <Button onClick={loadData} variant="outline">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      <Card className="border-zinc-200 overflow-auto h-[75%] dark:border-zinc-800 bg-white dark:bg-zinc-950">
        <CardHeader>
          <CardTitle>Discovery Ledger</CardTitle>
          <CardDescription>
            Files found on target AMC statutory disclosure pages.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="text-red-500 text-sm">{error}</p>
          ) : loading && documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-400">
              <RefreshCw className="h-8 w-8 animate-spin mb-4" />
              <p>Loading documents...</p>
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              No discovered documents found.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-md border border-zinc-200 dark:border-zinc-800">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>AMC Name</TableHead>
                      <TableHead>File Name</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Novelty</TableHead>
                      <TableHead>Discovered At</TableHead>
                      <TableHead className="text-right">Link</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.map((doc) => (
                      <TableRow key={doc.id}>
                        <TableCell className="font-semibold">{doc.amc_name}</TableCell>
                        <TableCell className="max-w-[250px] truncate font-medium">
                          {doc.filename || "No filename"}
                        </TableCell>
                        <TableCell>{formatBytes(doc.file_size_bytes)}</TableCell>
                        <TableCell>
                          <code className="text-xs uppercase">{doc.file_type || "—"}</code>
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusBadgeVariant(doc.status)}>
                            {doc.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {doc.is_novel ? (
                            <Badge variant="outline" className="text-emerald-500 border-emerald-500/30 bg-emerald-500/5">
                              Novel
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-zinc-400">
                              Seen / Dupe
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-zinc-500 text-xs">
                          {new Date(doc.discovered_at).toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8"
                            onClick={() => window.open(doc.url, "_blank")}
                          >
                            <ExternalLink className="h-4 w-4 text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination controls */}
              <div className="flex items-center justify-between border-t border-zinc-200 dark:border-zinc-800 pt-4">
                <div className="text-xs text-zinc-400">
                  Page {page}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    <ChevronLeft className="h-4 w-4 mr-1" /> Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => p + 1)}
                    disabled={!hasMore}
                  >
                    Next <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
