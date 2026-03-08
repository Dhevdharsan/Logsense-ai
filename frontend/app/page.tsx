"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from "recharts";

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try { setSummary(await api.getDashboardSummary()); }
      catch (err) { setError(err instanceof Error ? err.message : "Failed to load"); }
      finally { setLoading(false); }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-500">Loading dashboard...</div>;
  if (error) return (
    <div className="flex items-center justify-center h-64">
      <div className="bg-red-950 border border-red-900 rounded-xl p-6 text-center max-w-md">
        <div className="text-red-400 font-semibold mb-2">Failed to load dashboard</div>
        <div className="text-gray-400 text-sm">{error}</div>
        <div className="text-gray-500 text-xs mt-2">Is the backend running? Check localhost:8000/health</div>
      </div>
    </div>
  );
  if (!summary) return null;

  const chartData = summary.logs_over_time.map((d) => ({ time: d.hour.slice(11, 16), logs: d.count, anomalies: d.anomalies }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-gray-400 text-sm mt-1">{summary.last_analysis_at ? `Last analysis: ${new Date(summary.last_analysis_at).toLocaleString()}` : "No analysis run yet"}</p>
        </div>
        <button onClick={() => api.runAnalysis().then(r => alert(`Started: ${r.job_id}`)).catch(() => alert("Analysis not ready yet (Week 2)"))} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          ▶ Run Analysis
        </button>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {[
          { title: "Total Logs", value: summary.total_logs.toLocaleString(), sub: "All time", color: "blue" },
          { title: "Anomalies", value: summary.anomaly_count.toLocaleString(), sub: `${summary.anomaly_rate_pct}% of logs`, color: "red" },
          { title: "Clusters", value: summary.cluster_count.toString(), sub: "Error groups", color: "purple" },
          { title: "Services", value: summary.top_services.length.toString(), sub: "With errors", color: "green" },
        ].map(({ title, value, sub, color }) => (
          <div key={title} className={`rounded-xl border p-4 bg-${color}-950 border-${color}-900`}>
            <div className="text-xs font-medium text-gray-400 mb-1">{title}</div>
            <div className={`text-3xl font-bold text-${color}-400`}>{value}</div>
            <div className="text-xs text-gray-500 mt-1">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 bg-gray-900 rounded-xl border border-gray-800 p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Log Volume — Last 24h</h2>
          {chartData.length === 0
            ? <div className="h-52 flex items-center justify-center text-gray-600 text-sm">Ingest logs to see chart</div>
            : <ResponsiveContainer width="100%" height={210}>
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" stroke="#4b5563" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#4b5563" tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", borderRadius: "8px" }} />
                  <Area type="monotone" dataKey="logs" stroke="#3b82f6" fill="#1d4ed820" strokeWidth={2} name="Total" />
                  <Area type="monotone" dataKey="anomalies" stroke="#ef4444" fill="#dc262620" strokeWidth={2} name="Anomalies" />
                </AreaChart>
              </ResponsiveContainer>
          }
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Top Services by Errors</h2>
          {summary.top_services.length === 0
            ? <div className="h-52 flex items-center justify-center text-gray-600 text-sm">No error logs yet</div>
            : <ResponsiveContainer width="100%" height={210}>
                <BarChart data={summary.top_services} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis type="number" stroke="#4b5563" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="service" stroke="#4b5563" tick={{ fontSize: 10 }} width={90} />
                  <Tooltip contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", borderRadius: "8px" }} />
                  <Bar dataKey="error_count" fill="#3b82f6" radius={[0, 4, 4, 0]} name="Errors" />
                </BarChart>
              </ResponsiveContainer>
          }
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { href: "/logs", title: "Browse Logs →", desc: "Search and filter all ingested logs" },
          { href: "/anomalies", title: "View Anomalies →", desc: `${summary.anomaly_count} anomalous logs detected` },
          { href: "/clusters", title: "Explore Clusters →", desc: `${summary.cluster_count} error clusters with AI summaries` },
        ].map(({ href, title, desc }) => (
          <a key={href} href={href} className="block bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-blue-800 transition-colors group">
            <div className="font-semibold text-white group-hover:text-blue-400 transition-colors">{title}</div>
            <div className="text-sm text-gray-400 mt-1">{desc}</div>
          </a>
        ))}
      </div>
    </div>
  );
}
