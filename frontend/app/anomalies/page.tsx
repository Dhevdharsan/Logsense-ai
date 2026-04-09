"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LogEntry } from "@/lib/types";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

export default function AnomaliesPage() {
  const [logs, setLogs]       = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getLogs({ anomalies_only: true, page_size: 500 })
      .then(r => setLogs(r.items))
      .finally(() => setLoading(false));
  }, []);

  // Score distribution buckets for chart
  const buckets = [
    { range: "0.0–0.1", count: 0 },
    { range: "0.1–0.2", count: 0 },
    { range: "0.2–0.3", count: 0 },
    { range: "0.3–0.4", count: 0 },
    { range: "0.4–0.5", count: 0 },
    { range: "0.5+",    count: 0 },
  ];
  logs.forEach(l => {
    const s = l.anomaly_score ?? 0;
    if (s < 0.1) buckets[0].count++;
    else if (s < 0.2) buckets[1].count++;
    else if (s < 0.3) buckets[2].count++;
    else if (s < 0.4) buckets[3].count++;
    else if (s < 0.5) buckets[4].count++;
    else buckets[5].count++;
  });

  // Score → red intensity
  const scoreColor = (s: number) => {
    if (s > 0.4) return "text-red-300";
    if (s > 0.25) return "text-orange-300";
    return "text-yellow-300";
  };

  const byService = logs.reduce<Record<string, number>>((acc, l) => {
    acc[l.service] = (acc[l.service] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Anomalies</h1>
        <p className="text-gray-400 text-sm mt-1">
          {loading ? "..." : `${logs.length} anomalous logs detected by Isolation Forest (4.8% of total)`}
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4">
        {Object.entries(byService).map(([svc, count]) => (
          <div key={svc} className="bg-red-950 border border-red-900 rounded-xl p-4">
            <div className="text-xs text-gray-400 mb-1">{svc}</div>
            <div className="text-2xl font-bold text-red-400">{count}</div>
            <div className="text-xs text-gray-500">anomalies</div>
          </div>
        ))}
      </div>

      {/* Score distribution chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Anomaly Score Distribution</h2>
        <p className="text-xs text-gray-500 mb-3">Higher score = more anomalous. Isolation Forest scores range from ~0 to 0.6+</p>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={buckets}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="range" stroke="#4b5563" tick={{ fontSize: 11 }} />
            <YAxis stroke="#4b5563" tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", borderRadius: "8px" }} />
            <Bar dataKey="count" name="Anomalies" radius={[4, 4, 0, 0]}>
              {buckets.map((_, i) => (
                <Cell key={i} fill={i < 2 ? "#fbbf24" : i < 4 ? "#f97316" : "#ef4444"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Anomaly list */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="text-sm font-semibold text-gray-300">Flagged Logs — sorted by anomaly score</h2>
        </div>
        {loading ? (
          <div className="py-12 text-center text-gray-600">Loading anomalies...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-xs uppercase border-b border-gray-800">
                <th className="text-left px-4 py-3 w-20">Score</th>
                <th className="text-left px-4 py-3 w-32">Service</th>
                <th className="text-left px-4 py-3 w-20">Level</th>
                <th className="text-left px-4 py-3">Message</th>
              </tr>
            </thead>
            <tbody>
              {[...logs].sort((a, b) => (b.anomaly_score ?? 0) - (a.anomaly_score ?? 0)).map(log => (
                <tr key={log.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-2.5">
                    <span className={`font-mono font-bold text-xs ${scoreColor(log.anomaly_score ?? 0)}`}>
                      {(log.anomaly_score ?? 0).toFixed(3)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">{log.service}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                      log.level === "ERROR" ? "bg-red-900 text-red-300" : "bg-yellow-900 text-yellow-300"}`}>
                      {log.level}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-300 text-xs font-mono truncate max-w-sm">{log.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
