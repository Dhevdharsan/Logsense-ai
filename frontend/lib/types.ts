export interface LogEntry {
  id: number;
  timestamp: string;
  level: "ERROR" | "WARN" | "INFO" | "DEBUG";
  service: string;
  message: string;
  is_anomaly: boolean;
  anomaly_score: number | null;
  cluster_id: number | null;
  created_at: string;
}
export interface LogListResponse { items: LogEntry[]; total: number; page: number; page_size: number; has_next: boolean; }
export interface IngestResponse { status: string; ingested_count: number; job_id: string; message: string; }
export interface Cluster { id: number; label: string | null; size: number; sample_messages: string[] | null; llm_summary: string | null; llm_confidence: string | null; summary_cached_at: string | null; created_at: string; }
export interface DashboardSummary { total_logs: number; anomaly_count: number; anomaly_rate_pct: number; cluster_count: number; top_services: { service: string; error_count: number }[]; logs_over_time: { hour: string; count: number; anomalies: number }[]; last_analysis_at: string | null; }
