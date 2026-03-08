import type { LogListResponse, IngestResponse, DashboardSummary, Cluster } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => apiFetch<{ status: string }>("/health"),
  getDashboardSummary: () => apiFetch<DashboardSummary>("/api/v1/dashboard/summary"),
  getLogs: (params?: { page?: number; page_size?: number; level?: string; service?: string; anomalies_only?: boolean }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.page_size) q.set("page_size", String(params.page_size));
    if (params?.level) q.set("level", params.level);
    if (params?.service) q.set("service", params.service);
    if (params?.anomalies_only) q.set("anomalies_only", "true");
    return apiFetch<LogListResponse>(`/api/v1/logs?${q}`);
  },
  ingestLogs: (logs: unknown[]) => apiFetch<IngestResponse>("/api/v1/logs/ingest", { method: "POST", body: JSON.stringify({ logs }) }),
  getClusters: () => apiFetch<{ items: Cluster[]; total: number }>("/api/v1/clusters"),
  runAnalysis: () => apiFetch<{ job_id: string }>("/api/v1/analyze/run", { method: "POST" }),
};
