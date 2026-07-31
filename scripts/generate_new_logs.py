#!/usr/bin/env python3
import json, random, argparse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

SERVICES = ["notification-service", "search-service", "inventory-service", "billing-service"]

ERRORS = [
    "Elasticsearch index corrupted: shard {n} unrecoverable",
    "Rate limit exceeded: {n} requests/sec for client {uid}",
    "SSL certificate expired: handshake failed for {n} connections",
    "Disk space critical: {n}% used on volume",
    "Kafka consumer lag: {n}ms behind partition",
    "Webhook delivery failed: {n} retries exhausted for endpoint {uid}",
    "gRPC deadline exceeded: call timed out after {n}ms",
    "Circuit breaker tripped: {n} consecutive failures on {uid}",
]
WARNS = [
    "Queue depth growing: {n} messages pending",
    "Slow query detected: {n}ms execution time",
    "Token refresh approaching expiry: {n}s remaining"
]
INFOS = [
    "Notification sent: push delivered to {uid} in {n}ms",
    "Search query executed: {n} results in {uid}ms",
    "Inventory sync completed: {n} items updated"
]

def gen_log(base_time, offset):
    level = random.choices(["ERROR","WARN","INFO"], weights=[0.15,0.15,0.70])[0]
    templates = {"ERROR": ERRORS, "WARN": WARNS, "INFO": INFOS}[level]
    msg = random.choice(templates).format(n=random.randint(1,9999), uid=f"cli-{random.randint(1000,9999)}")
    return {"timestamp": (base_time + timedelta(seconds=offset)).isoformat(), "level": level, "service": random.choice(SERVICES), "message": msg, "metadata": {"request_id": f"req-{random.randint(100000,999999)}"}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--batch-size", type=int, default=100)
    args = p.parse_args()
    base = datetime.now(timezone.utc) - timedelta(hours=1)
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
    print(f"\nDone! {sent}/{args.count} new-pattern logs sent.")

if __name__ == "__main__":
    main()