import subprocess
import time
import json
import pandas as pd
from pathlib import Path

SCRAPER_SCRIPT = "athletescraper.py"
TEMP_DIR = Path(__file__).parent / "temp_batches"
OUTPUT_DIR = Path(__file__).parent / "output"
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------
# PROMPTS
# ---------------------------

MAX_CONCURRENT = int(input("Enter Maximum Concurrent Scrapers: "))

# ---------------------------
# LOAD ATHLETE IDs
# ---------------------------

with open("athletes.txt") as f:
    athlete_ids = [line.strip() for line in f if line.strip()]

print(f"Loaded {len(athlete_ids)} athletes from athletes.txt")

# ---------------------------
# SPLIT INTO BATCHES
# One batch per worker — divide athletes as evenly as possible
# e.g. 100 athletes with 3 workers = batches of 34, 33, 33
# ---------------------------

batches = [[] for _ in range(MAX_CONCURRENT)]
for i, athlete_id in enumerate(athlete_ids):
    batches[i % MAX_CONCURRENT].append(athlete_id)

# Remove any empty batches (in case MAX_CONCURRENT > number of athletes)
batches = [b for b in batches if b]

print(f"Split into {len(batches)} batches")

# Write each batch to a temp JSON file so the worker can read it
batch_files = []
for i, batch in enumerate(batches):
    batch_path = TEMP_DIR / f"batch_{i + 1}.json"
    with open(batch_path, "w") as f:
        json.dump(batch, f)
    batch_files.append(batch_path)

# ---------------------------
# SPAWN WORKER PROCESSES
# ---------------------------

running_processes = []

for i, batch_file in enumerate(batch_files):
    batch_number = i + 1
    print(f"Starting scraper for batch {batch_number} ({len(batches[i])} athletes)")

    process = subprocess.Popen(
        ["python", SCRAPER_SCRIPT, str(batch_file), str(batch_number)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    running_processes.append(process)

# ---------------------------
# WAIT AND COLLECT OUTPUT FILES
# ---------------------------

output_files = []

for p in running_processes:
    stdout, _ = p.communicate()
    for line in stdout.splitlines():
        print(line)
        if line.startswith("OUTPUTFILE:"):
            output_files.append(line.replace("OUTPUTFILE:", "").strip())

# ---------------------------
# MERGE INTO SINGLE OUTPUT FILE
# ---------------------------

if output_files:
    # Find next available athletes N .csv filename
    n = 1
    while (OUTPUT_DIR / f"athletes{n}.csv").exists():
        n += 1
    merged_path = OUTPUT_DIR / f"athletes{n}.csv"

    # Read and concatenate all batch CSVs
    dfs = [pd.read_csv(f) for f in output_files if Path(f).exists()]
    merged_df = pd.concat(dfs, ignore_index=True)
    merged_df.to_csv(merged_path, index=False)

    print(f"\nMerged file saved to {merged_path}")

# ---------------------------
# CLEAN UP TEMP BATCH FILES
# ---------------------------

for batch_file in batch_files:
    try:
        Path(batch_file).unlink()
    except:
        pass

# Remove temp folder if empty
try:
    TEMP_DIR.rmdir()
except:
    pass

print("All athletes finished!")
