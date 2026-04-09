"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Cluster } from "@/lib/types";

const CONF_COLORS: Record<string, string> = {
  high:   "bg-green-900 text-green-300",
  medium: "bg-yellow-900 text-yellow-300",
  low:    "bg-red-900 text-red-300",
};

export default function ClustersPage() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [loading, setLoading]   = useState(true);
  const [summarizing, setSummarizing] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api.getClusters().then(r => setClusters(r.items)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const summarizeAll = async () => {
    setSummarizing(-1);
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/llm/summarize-all`, { method: "POST" });
      load();
    } finally {
      setSummarizing(null);
    }
  };

  const summarizeOne = async (id: number) => {
    setSummarizing(id);
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/llm/summarize/${id}`, { method: "POST" });
      load();
    } finally {
      setSummarizing(null);
    }
  };

  const withSummary = clusters.filter(c => c.llm_summary).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Cluster Explorer</h1>
          <p className="text-gray-400 text-sm mt-1">
            {loading ? "..." : `${clusters.length} error clusters · ${withSummary} with AI summaries`}
          </p>
        </div>
        <button
          onClick={summarizeAll}
          disabled={summarizing !== null}
          className="bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          {summarizing === -1 ? "Generating..." : "✦ Summarize All"}
        </button>
      </div>

      {loading ? (
        <div className="text-center text-gray-600 py-20">Loading clusters...</div>
      ) : clusters.length === 0 ? (
        <div className="text-center text-gray-600 py-20">
          No clusters yet — run analysis first from the Dashboard
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {clusters.map(cluster => (
            <div key={cluster.id}
              className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-gray-700 transition-colors">

              {/* Header */}
              <div className="px-5 py-4 flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-xs font-mono text-gray-500">#{cluster.id}</span>
                    <h3 className="font-semibold text-white truncate">{cluster.label ?? "Unnamed cluster"}</h3>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400">{cluster.size} logs</span>
                    {cluster.llm_confidence && (
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${CONF_COLORS[cluster.llm_confidence] ?? "bg-gray-800 text-gray-400"}`}>
                        {cluster.llm_confidence} confidence
                      </span>
                    )}
                    {cluster.summary_cached_at && (
                      <span className="text-xs text-gray-600">
                        cached {new Date(cluster.summary_cached_at).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  {!cluster.llm_summary && (
                    <button onClick={() => summarizeOne(cluster.id)}
                      disabled={summarizing !== null}
                      className="text-xs bg-purple-900 hover:bg-purple-800 disabled:opacity-40 text-purple-300 px-3 py-1.5 rounded-lg transition-colors">
                      {summarizing === cluster.id ? "..." : "✦ Summarize"}
                    </button>
                  )}
                  <button onClick={() => setExpanded(expanded === cluster.id ? null : cluster.id)}
                    className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-lg transition-colors">
                    {expanded === cluster.id ? "Collapse ↑" : "Details ↓"}
                  </button>
                </div>
              </div>

              {/* AI Summary */}
              {cluster.llm_summary && (
                <div className="mx-5 mb-4 bg-purple-950/40 border border-purple-900/50 rounded-lg p-3">
                  <div className="text-xs text-purple-400 font-semibold mb-1">✦ AI Root Cause Analysis</div>
                  <p className="text-sm text-gray-200 leading-relaxed">{cluster.llm_summary}</p>
                </div>
              )}

              {/* Expanded details */}
              {expanded === cluster.id && (
                <div className="px-5 pb-4 border-t border-gray-800 pt-4">
                  <div className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">Sample Messages</div>
                  <div className="space-y-1.5">
                    {(cluster.sample_messages ?? []).map((msg, i) => (
                      <div key={i} className="text-xs font-mono text-gray-400 bg-gray-800 rounded px-3 py-1.5">
                        {msg}
                      </div>
                    ))}
                  </div>
                  {!cluster.llm_summary && (
                    <p className="text-xs text-gray-600 mt-3">No AI summary yet — click "Summarize" above</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
