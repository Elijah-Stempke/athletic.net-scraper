import subprocess
import time

MAX_CONCURRENT = int(input("Enter Maximum Concurrent Teams: "))
SCRAPER_SCRIPT = "teamscraper.py"

# Ask gender once
gender_choice = ""
while gender_choice not in ["M", "F", "B"]:
    gender_choice = input("Select gender (M = Male, F = Female, B = Both): ").upper()

# Load teams
with open("teams.txt") as f:
    team_ids = [line.strip() for line in f if line.strip()]

running_processes = []

for team_id in team_ids:

    # Wait if max concurrent reached
    while len(running_processes) >= MAX_CONCURRENT:
        running_processes = [p for p in running_processes if p.poll() is None]
        time.sleep(0.2)

    print(f"Starting scraper for team {team_id}")

    process = subprocess.Popen(
        ["python", SCRAPER_SCRIPT, team_id, gender_choice]
    )

    running_processes.append(process)

# Wait for remaining scrapers
for p in running_processes:
    p.wait()

print("All teams finished!")