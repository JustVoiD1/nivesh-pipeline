"use client";

import { useEffect, useState } from "react";
import { fetchQuarantine, reviewQuarantined, QuarantinedItem } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ShieldAlert, RefreshCw, Eye, CheckCircle2, XCircle, Edit, ChevronLeft, ChevronRight } from "lucide-react";

export default function QuarantinePage() {
  const [items, setItems] = useState<QuarantinedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<QuarantinedItem | null>(null);
  const [notes, setNotes] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const pageSize = 15;

  // Corrections form state
  const [correctedAmc, setCorrectedAmc] = useState("");
  const [correctedScheme, setCorrectedScheme] = useState("");
  const [correctedMonth, setCorrectedMonth] = useState<number | "">("");
  const [correctedYear, setCorrectedYear] = useState<number | "">("");

  const loadData = () => {
    setLoading(true);
    fetchQuarantine(pageSize, (page - 1) * pageSize)
      .then((data) => {
        setItems(data);
        setHasMore(data.length === pageSize);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load quarantine queue");
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, [page]);

  const handleReview = async (decision: "ACCEPTED" | "REJECTED" | "RECLASSIFIED") => {
    if (!selectedItem) return;
    try {
      const corrections = decision === "RECLASSIFIED" ? {
        corrected_amc_name: correctedAmc || undefined,
        corrected_scheme_name: correctedScheme || undefined,
        corrected_period_month: correctedMonth ? Number(correctedMonth) : undefined,
        corrected_period_year: correctedYear ? Number(correctedYear) : undefined,
      } : undefined;

      await reviewQuarantined(selectedItem.classification_id, decision, notes, corrections);
      setSelectedItem(null);
      setNotes("");
      setCorrectedAmc("");
      setCorrectedScheme("");
      setCorrectedMonth("");
      setCorrectedYear("");
      loadData();
    } catch (err: any) {
      alert(err.message || "Review submission failed");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 h-full p-8 text-zinc-400">
        <RefreshCw className="h-8 w-8 animate-spin mb-4" />
        <p>Loading quarantine queue...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-500">
        <h2 className="text-xl font-bold">Error loading quarantine</h2>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="h-full p-8 space-y-8 flex-1 relative">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Manual Review Queue</h1>
        <p className="text-zinc-500 dark:text-zinc-400">
          Documents flagged by classifier due to low confidence or schema drift.
        </p>
      </div>

      <div className="h-full grid gap-8 lg:grid-cols-3">
        {/* Queue Table */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="overflow-auto h-[75%]">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Quarantined Items</CardTitle>
                <CardDescription>Select an item to view classification signals.</CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={loadData}>
                <RefreshCw className="h-4 w-4 mr-2" /> Refresh
              </Button>
            </CardHeader>
            <CardContent>
              {items.length === 0 ? (
                <div className="text-center py-12 text-zinc-500 flex flex-col items-center">
                  <ShieldAlert className="h-10 w-10 text-zinc-400 mb-3" />
                  <p>Queue is empty! All ingestion records matched expected parameters.</p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Filename</TableHead>
                        <TableHead>Suggested Identity</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Reason</TableHead>
                        <TableHead className="text-right">Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((item) => (
                        <TableRow
                          key={item.classification_id}
                          className={selectedItem?.classification_id === item.classification_id ? "bg-zinc-100 dark:bg-zinc-800" : ""}
                        >
                          <TableCell className="font-medium max-w-[200px] truncate">
                            {item.filename || "Unknown file"}
                          </TableCell>
                          <TableCell>
                            <div className="text-xs">
                              <span className="font-semibold text-zinc-700 dark:text-zinc-300">{item.amc_name || "Unknown AMC"}</span>
                              <br />
                              <span className="text-zinc-500">{item.scheme_name || "Unknown Scheme"}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant={item.confidence_score > 0.6 ? "warning" : "destructive"}>
                              {(item.confidence_score * 100).toFixed(0)}%
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <span className="text-xs text-red-500 font-semibold">{item.quarantine_reason}</span>
                          </TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" variant="ghost" onClick={() => {
                              setSelectedItem(item);
                              setCorrectedAmc(item.amc_name || "");
                              setCorrectedScheme(item.scheme_name || "");
                              setCorrectedMonth(item.period_label ? 1 : ""); // placeholder
                              setCorrectedYear(item.period_label ? 2026 : "");
                            }}>
                              <Eye className="h-4 w-4 mr-2" /> Inspect
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  {/* Pagination Controls */}
                  <div className="flex items-center justify-between border-t border-zinc-200 dark:border-zinc-800 pt-4 mt-4">
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
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Review Sidepanel */}
        <div className="h-full lg:col-span-1">
          {selectedItem ? (
            <Card className="border-zinc-300 dark:border-zinc-700 shadow-lg overflow-auto h-[75%]">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 text-amber-500" /> Inspect Document
                </CardTitle>
                <CardDescription className="break-all">{selectedItem.filename}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Quarantine Diagnostics</h4>
                  <p className="text-sm mt-1 text-red-600 dark:text-red-400 font-medium">
                    {selectedItem.quarantine_details || "Flagged due to low classifier confidence."}
                  </p>
                </div>

                <div className="border-t pt-3">
                  <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">Correction & Reclassification Form</h4>
                  <div className="space-y-2 text-xs">
                    <div>
                      <label className="block text-zinc-400 mb-1">AMC Name</label>
                      <input
                        className="w-full rounded border px-2 py-1.5 bg-transparent dark:border-zinc-800"
                        value={correctedAmc}
                        onChange={(e) => setCorrectedAmc(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-zinc-400 mb-1">Scheme Name</label>
                      <input
                        className="w-full rounded border px-2 py-1.5 bg-transparent dark:border-zinc-800"
                        value={correctedScheme}
                        onChange={(e) => setCorrectedScheme(e.target.value)}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-zinc-400 mb-1">Month (1-12)</label>
                        <input
                          type="number"
                          className="w-full rounded border px-2 py-1.5 bg-transparent dark:border-zinc-800"
                          value={correctedMonth}
                          onChange={(e) => setCorrectedMonth(e.target.value ? Number(e.target.value) : "")}
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Year (e.g. 2026)</label>
                        <input
                          type="number"
                          className="w-full rounded border px-2 py-1.5 bg-transparent dark:border-zinc-800"
                          value={correctedYear}
                          onChange={(e) => setCorrectedYear(e.target.value ? Number(e.target.value) : "")}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div className="border-t pt-3">
                  <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Review Notes</label>
                  <textarea
                    className="w-full text-xs rounded border p-2 bg-transparent dark:border-zinc-800 h-16"
                    placeholder="Provide reason for decision..."
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />
                </div>

                <div className="grid grid-cols-3 gap-2 border-t pt-4">
                  <Button size="sm" variant="default" onClick={() => handleReview("ACCEPTED")}>
                    <CheckCircle2 className="h-3 w-3 mr-1" /> Approve
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => handleReview("REJECTED")}>
                    <XCircle className="h-3 w-3 mr-1" /> Reject
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => handleReview("RECLASSIFIED")}>
                    <Edit className="h-3 w-3 mr-1" /> Update
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="h-full flex items-center justify-center p-6 border rounded-xl border-dashed text-zinc-500 text-sm">
              No item selected
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
