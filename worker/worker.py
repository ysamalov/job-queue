"""Worker process that claims and executes jobs."""
from __future__ import annotations

import os
import random
import time
import uuid

import requests

API_URL = os.getenv("API_URL", "http://api:8000")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "secret-worker-token")
WORKER_ID = os.getenv("WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))

HEADERS = {
    "Authorization": f"Bearer {WORKER_TOKEN}",
    "X-Worker-Id": WORKER_ID,
}


def run() -> None:
    print(f"Worker {WORKER_ID} starting, polling {API_URL}")
    while True:
        try:
            resp = requests.post(f"{API_URL}/jobs/claim", headers=HEADERS, timeout=10)
            if resp.status_code == 200 and resp.json() is not None:
                job = resp.json()
                job_id = job["id"]
                print(f"[{WORKER_ID}] Claimed job {job_id}: {job['prompt'][:60]}")

                # Simulate generation
                delay = random.uniform(2, 5)
                time.sleep(delay)
                result_text = f"Generated result for prompt: '{job['prompt'][:100]}' (took {delay:.1f}s)"

                resp2 = requests.post(
                    f"{API_URL}/jobs/{job_id}/complete",
                    json={"result": result_text},
                    headers=HEADERS,
                    timeout=10,
                )
                if resp2.status_code == 200:
                    print(f"[{WORKER_ID}] Completed job {job_id}")
                else:
                    print(f"[{WORKER_ID}] Failed to complete job {job_id}: {resp2.text}")
            else:
                time.sleep(POLL_INTERVAL)
        except requests.RequestException as exc:
            print(f"[{WORKER_ID}] Connection error: {exc}")
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print(f"[{WORKER_ID}] Shutting down")
            break


if __name__ == "__main__":
    run()
