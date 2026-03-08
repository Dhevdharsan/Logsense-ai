#!/usr/bin/env python3
import json, random, argparse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

SERVICES = ["payment-service", "auth-service", "api-gateway", "user-service"]
ERRORS = [
    "Database connection pool exhausted: timeout after {n}s",
    "DB connection refused: host=postgres port=5432",
    "Database query timeout: exceeded {n}ms limit",
    "JWT token validation failed: signature mismatch for user {uid}",
    "Authentication failed: invalid credentials for user {uid}",
    "Payment gateway timeout: stripe returned 504 after {n}ms",
    "Charge failed: card declined for amount ${amount}",
    "Segmentation fault in worker process {pid}: core dumped",
    "Out of memory: kill process {pid}",
]
WARNS = ["High memory usage: {n}%", "Response time degraded: p99={n}ms", "Cache miss rate: {n}%"]
INFOS = ["Request processed: GET /api/v1/users/{uid} in {n}ms", "User {uid} logged in", "Health check passed"]

def gen_log(base_time, offset):
    level = random.choices(["ERROR","WARN","INFO"], weights=[0.2,0.15,0.65])[0]
    templates = {"ERROR": ERRORS, "WARN": WARNS, "INFO": INFOS}[level]
    msg = random.choice(templates).format(n=random.randint(1,9999), uid=f"usr-{random.randint(1000,9999)}", pid=random.randint(100,9999), amount=round(random.uniform(5,500),2))
    return {"timestamp": (base_time + timedelta(seconds=offset)).isoformat(), "level": level, "service": random.choice(SERVICES), "message": msg, "metadata": {"request_id": f"req-{random.randint(100000,999999)}"}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--batch-size", type=int, default=100)
    args = p.parse_args()
    base = datetime.now(timezone.utc) - timedelta(hours=24)
    logs = [gen_log(base, i*2) for i in range(args.count)]
    sent = 0
    for i in range(0, len(logs), args.batch_size):
        batch = logs[i:i+args.batch_size]
        req = urllib.request.Request(f"{args.url}/api/v1/logs/ingest", data=json.dumps({"logs": batch}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                r = json.loads(resp.read())
                sent += r["ingested_count"]
                print(f"  Sent {r['ingested_count']} logs | job={r['job_id']}")
        except urllib.error.URLError as e:
            print(f"  ERROR: {e}")
            break
    print(f"\nDone! {sent}/{args.count} logs sent. Open http://localhost:3000")

if __name__ == "__main__":
    main()
