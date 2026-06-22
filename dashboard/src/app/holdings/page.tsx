"use client";

import { useEffect, useState } from "react";
import { fetchPublished, PublishedHolding } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Search, ChevronLeft, ChevronRight } from "lucide-react";

export default function HoldingsPage() {
  const [holdings, setHoldings] = useState<PublishedHolding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [schemeQuery, setSchemeQuery] = useState("");
  const [amcQuery, setAmcQuery] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const pageSize = 50;

  const loadData = () => {
    setLoading(true);
    fetchPublished(amcQuery || undefined, schemeQuery || undefined, pageSize, (page - 1) * pageSize)
      .then((data) => {
        setHoldings(data);
        setHasMore(data.length === pageSize);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load holdings");
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, [page]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (page === 1) {
      loadData();
    } else {
      setPage(1);
    }
  };

  if (loading && holdings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 h-full p-8 text-zinc-400">
        <RefreshCw className="h-8 w-8 animate-spin mb-4" />
        <p>Loading published holdings...</p>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 flex-1">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Published Holdings</h1>
          <p className="text-zinc-500 dark:text-zinc-400">
            Browse successfully extracted mutual fund holdings data from the warehouse.
          </p>
        </div>
        <Button onClick={loadData} variant="outline">
          <RefreshCw className="h-4 w-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Filter bar */}
      <form onSubmit={handleSearch} className="flex flex-wrap gap-4 items-end bg-zinc-50 border-zinc-200 dark:bg-zinc-900/20 p-4 rounded-xl border dark:border-zinc-800">
        <div className="flex flex-col space-y-1.5 flex-1 min-w-[200px]">
          <input
            className="w-full text-sm rounded border px-3 py-2 bg-white text-zinc-900 border-zinc-200 dark:bg-zinc-950 dark:text-zinc-50 dark:border-zinc-800"
            placeholder="Search scheme (e.g. Hybrid)..."
            value={schemeQuery}
            onChange={(e) => setSchemeQuery(e.target.value)}
          />
        </div>
        <div className="flex flex-col space-y-1.5 min-w-[200px]">
          <select
            className="rounded border px-3 py-2 bg-white text-zinc-900 border-zinc-200 dark:bg-zinc-950 dark:text-zinc-50 dark:border-zinc-800 text-sm"
            value={amcQuery}
            onChange={(e) => setAmcQuery(e.target.value)}
          >
            <option value="">All AMCs</option>
            <option value="SBI Mutual Fund">SBI Mutual Fund</option>
            <option value="HDFC Mutual Fund">HDFC Mutual Fund</option>
            <option value="ICICI Prudential Mutual Fund">ICICI Prudential Mutual Fund</option>
            <option value="Nippon India Mutual Fund">Nippon India Mutual Fund</option>
            <option value="UTI Mutual Fund">UTI Mutual Fund</option>
          </select>
        </div>
        <Button type="submit">
          <Search className="h-4 w-4 mr-2" /> Search
        </Button>
      </form>

      {/* Holdings list */}
      <Card>
        <CardHeader>
          <CardTitle>Warehouse Records</CardTitle>
          <CardDescription>
            Showing up to 100 holdings records. Total clean data rows available: {holdings.length}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="text-red-500 text-sm">{error}</p>
          ) : holdings.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              No holdings found matching filter query.
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Scheme</TableHead>
                    <TableHead>ISIN</TableHead>
                    <TableHead>Instrument Name</TableHead>
                    <TableHead>Industry / Rating</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Market Value</TableHead>
                    <TableHead className="text-right">% of NAV</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {holdings.map((h) => (
                    <TableRow key={h.id}>
                      <TableCell>
                        <div className="text-xs">
                          <span className="font-semibold">{h.scheme_name}</span>
                          <br />
                          <span className="text-zinc-500 text-[10px]">{h.amc_name} • {h.period_month}/{h.period_year}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <code className="text-xs px-1.5 py-0.5 bg-zinc-150 rounded text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300">
                          {h.isin || "—"}
                        </code>
                      </TableCell>
                      <TableCell className="max-w-[250px] truncate text-xs font-medium">
                        {h.instrument_name || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-zinc-400">
                        {h.industry || h.rating || "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {h.quantity ? h.quantity.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs font-semibold">
                        {h.market_value ? `₹${h.market_value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs text-emerald-500 font-bold">
                        {h.pct_to_net_assets ? `${h.pct_to_net_assets}%` : "—"}
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
  );
}
