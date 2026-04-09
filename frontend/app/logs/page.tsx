"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LogEntry, LogListResponse } from "@/lib/types";

const LEVELS = ["", "ERROR", "WARN", "INFO", "DEBUG"];
const SERVICES = ["", "auth-service", "payment-service", "api-gateway", "user-service"];

const LEVEL_COLORS: Record<string, string> = {
  ERROR: "bg-red-900 text-red-300",
  WARN:  "bg-yellow-900 text-yellow-300",
  INFO:  "bg-blue-900 text-blue-300",
  DEBUG: "bg-gray-800 text-gray-400",
};

export default function LogsPage() {
  const [data, setData]         = useState<LogListResponse | null>(null);
  const [loading, setLoading]   = useState(true);
  const [page, setPage]         = useState(1);
  const [level, setLevel]       = useState("");
  const [service, setService]   = useState("");
  const [anomalyOnly, setAnomaly] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.getLogs({ page, page_size: 50, level: level || undefined, service: service || undefined, anomalies_only: anomalyOnly })
      .then(setData).finally(() => setLoading(false));
  }, [page, level, service, anomalyOnly]);

  const reset = () => { setPage(1); setLevel(""); setService(""); setAnomaly(false); };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Log Browser</h1>
          <p className="text-gray-400 text-sm mt-1">{data?.total.toLocaleString() ?? "..."} logs matching filters</p>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-wrap gap-3 items-center">
        <select value={level} onChange={e => { setLevel(e.target.value); setPage(1); }}
          className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2">
          {LEVELS.map(l => <option key={l} value={l}>{l || "All Levels"}</option>)}
        </select>
        <select value={service} onChange={e => { setService(e.target.value); setPage(1); }}
          className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2">
          {SERVICES.map(s => <option key={s} value={s}>{s || "All Services"}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input type="checkbox" checked={anomalyOnly} onChange={e => { setAnomaly(e.target.checked); setPage(1); }}
            className="accent-red-500" />
          Anomalies only
        </label>
        <button onClick={reset} className="ml-auto text-xs text-gray-500 hover:text-gray-300 transition-colors">
          Reset filters
        </button>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
              <th className="text-left px-4 py-3 w-36">Time</th>
              <th className="text-left px-4 py-3 w-20">Level</th>
              <th className="text-left px-4 py-3 w-32">Service</th>
              <th className="text-left px-4 py-3">Message</th>
              <th className="text-left px-4 py-3 w-20">Score</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-600">Loading...</td></tr>
            ) : data?.items.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-600">No logs match filters</td></tr>
            ) : data?.items.map((log) => (
              <tr key={log.id}
                className={`border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors ${log.is_anomaly ? "bg-red-950/20" : ""}`}>
                <td className="px-4 py-2.5 text-gray-500 text-xs font-mono whitespace-nowrap">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${LEVEL_COLORS[log.level] ?? "bg-gray-800 text-gray-400"}`}>
                    {log.level}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-gray-400 text-xs">{log.service}</td>
                <td className="px-4 py-2.5 text-gray-300 text-xs font-mono truncate max-w-xs">
                  {log.is_anomaly && <span className="text-red-400 mr-2">⚠</span>}
                  {log.message}
                </td>
                <td className="px-4 py-2.5 text-xs font-mono">
                  {log.anomaly_score != null ? (
                    <span className={log.is_anomaly ? "text-red-400" : "text-gray-600"}>
                      {log.anomaly_score.toFixed(3)}
                    </span>
                  ) : <span className="text-gray-700">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>Page {page} of {Math.ceil(data.total / 50)}</span>
          <div className="flex gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1.5 bg-gray-800 rounded-lg disabled:opacity-30 hover:bg-gray-700 transition-colors">
              ← Prev
            </button>
            <button onClick={() => setPage(p => p + 1)} disabled={!data.has_next}
              className="px-3 py-1.5 bg-gray-800 rounded-lg disabled:opacity-30 hover:bg-gray-700 transition-colors">
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
