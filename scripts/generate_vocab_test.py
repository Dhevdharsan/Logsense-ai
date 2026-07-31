#!/usr/bin/env python3
import json, random, argparse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

SERVICES = ["test-service"]

# Same count, same structure, different vocabulary
BLAND = "Request failed: user {uid} request error at {n}ms"
JARGON = "Mutex deadlock detected: thread {n} starved on semaphore {uid}"

def gen_log(base_time, offset, template):
    msg = template.format(n=random.randint(1,9999), uid=f"usr-{random.randint(1000,9999)}")
    return {"timestamp": (base_time + timedelta(seconds=offset)).isoformat(), "level": "ERROR", "service": random.choice(SERVICES), "message": msg, "metadata": {"request_id": f"req-{random.randint(100000,999999)}"}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count-each", type=int, default=20)
    p.add_argument("--url", default="http://localhost:8000")
    args = p.parse_args()
    base = datetime.now(timezone.utc)

    logs = []
    for i in range(args.count_each):
        logs.append(gen_log(base, i*2, BLAND))
    for i in range(args.count_each):
        logs.append(gen_log(base, (args.count_each+i)*2, JARGON))

    req = urllib.request.Request(f"{args.url}/api/v1/logs/ingest", data=json.dumps({"logs": logs}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            r = json.loads(resp.read())
            print(f"Sent {r['ingested_count']} logs | job={r['job_id']}")
    except urllib.error.URLError as e:
        print(f"ERROR: {e}")

    print(f"\nDone! {args.count_each} bland + {args.count_each} jargon logs sent.")

if __name__ == "__main__":
    main()