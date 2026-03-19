import sys
import time
import random
import re
import json
import pandas as pd
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
LOG_DIR = Path(__file__).parent / "log"
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
        
# ---------------------------
# GET ARGUMENTS
# athlete_pr_scraper.py is always called by the controller
# argv[1] = path to a temp JSON file containing a list of athlete IDs for this batch
# argv[2] = batch number (used to name the partial output file)
# ---------------------------

batch_file = sys.argv[1]
batch_number = sys.argv[2]

log_file = LOG_DIR / f"athletes_batch_{batch_number}.log"

def log(message):
    print(message)  # still prints to stdout for the controller to capture
    with open(log_file, "a") as f:
        f.write(message + "\n")

with open(batch_file, "r") as f:
    athlete_ids = json.load(f)

print(f"Batch {batch_number}: {len(athlete_ids)} athletes to scrape")

# ---------------------------
# HEADLESS CHROME SETUP
# ---------------------------

chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--log-level=3")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=chrome_options
)

# Block unnecessary resources to speed up page loads
driver.execute_cdp_cmd("Network.enable", {})
driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
    "*.png", "*.jpg", "*.gif", "*.svg", "*.woff", "*.woff2",
    "*.ttf", "*.css", "*.ico", "googletagmanager.com/*",
    "google-analytics.com/*", "doubleclick.net/*"
]})

# ---------------------------
# HELPER FUNCTIONS
# (identical to athletic_pr_scraper.py)
# ---------------------------

def time_to_seconds(time_str):
    """Convert M:SS.xx string to float seconds for comparison. Strips hand-timing 'h' suffix."""
    cleaned = time_str.strip().rstrip("h")
    parts = cleaned.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return None


def get_fastest_time(soup, event_name):
    """
    Find the table for a specific event and return the fastest time across all seasons.
    Skips relay tables. Event name must match exactly (case-insensitive, stripped).
    Returns the original time string of the fastest time, or "" if not found.
    """
    tables = soup.find_all("table", class_="histEvent")
    for table in tables:
        h5 = table.find("h5", class_="bold")
        if not h5:
            continue

        h5_text = h5.get_text(strip=True)

        # Skip relay splits
        if "relay" in h5_text.lower() or "split" in h5_text.lower():
            continue

        if h5_text.strip().lower() != event_name.strip().lower():
            continue

        times = []
        rows = table.find_all("tr", class_="ng-star-inserted")
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 3:
                continue
            span = tds[2].find("span", class_="ng-star-inserted")
            if span:
                raw_time = span.get_text(strip=True)
                seconds = time_to_seconds(raw_time)
                if seconds is not None:
                    times.append((seconds, raw_time))

        if times:
            fastest = min(times, key=lambda x: x[0])
            return fastest[1].rstrip("h")

    return ""


def get_current_grade(soup):
    """
    Get the athlete's most recent grade by finding the highest year entry
    across all event tables and returning its associated grade.
    """
    latest_year = 0
    latest_grade = ""

    tables = soup.find_all("table", class_="histEvent")
    for table in tables:
        rows = table.find_all("tr", class_="ng-star-inserted")
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 2: 
                continue
            year_text = tds[0].get_text(strip=True)
            year_match = re.search(r"\d{4}", year_text)
            grade_text = tds[1].get_text(strip=True)

            if year_match and grade_text.isdigit():
                year = int(year_match.group())
                if year > latest_year:
                    latest_year = year
                    latest_grade = grade_text

    return latest_grade


def get_athlete_name(soup):
    """Extract athlete name from their profile page."""
    try:
        name_tag = soup.find("h1")
        if name_tag:
            return name_tag.get_text(strip=True)
    except:
        pass
    return "Unknown"


def get_athlete_team(soup):
    """Extract current team name from athlete profile page."""
    try:
        team_tag = soup.find("a", href=re.compile(r"/team/"))
        if team_tag:
            return team_tag.get_text(strip=True)
    except:
        pass
    return ""


def get_athlete_gender(soup):
    """Extract gender from athlete profile page by checking which section they appear in."""
    try:
        # Athletic.net shows gender in the athlete header
        gender_tag = soup.find("span", string=re.compile(r"Boys|Girls|Male|Female", re.I))
        if gender_tag:
            text = gender_tag.get_text(strip=True).lower()
            if "boy" in text or "male" in text:
                return "Male"
            elif "girl" in text or "female" in text:
                return "Female"
    except:
        pass
    return ""


def make_hyperlink(url, name):
    """Build a spreadsheet-compatible HYPERLINK formula. Escapes apostrophes in names."""
    safe_name = name.replace("'", "''")
    return f'=HYPERLINK("{url}", "{safe_name}")'


def scrape_athlete(athlete_id):
    """Scrape a single athlete's XC and track PRs with retries."""
    xc_url = f"https://www.athletic.net/athlete/{athlete_id}/cross-country"
    track_url = f"https://www.athletic.net/athlete/{athlete_id}/track-and-field/"
    attempt = 0
    name = f"Athlete_{athlete_id}"  # fallback in case XC page never loads

    while True:
        try:
            # --- XC Page ---
            grade = ""
            xc_3mile = xc_5k = ""
            driver.get(xc_url)
            WebDriverWait(driver, 20).until(lambda d:
                d.find_elements(By.CSS_SELECTOR, "tr.ng-star-inserted") or
                d.find_elements(By.CSS_SELECTOR, "small.ng-star-inserted")
            )
            if driver.find_elements(By.CSS_SELECTOR, "tr.ng-star-inserted"):
                xc_soup = BeautifulSoup(driver.page_source, "html.parser")

                name = get_athlete_name(xc_soup)
                team = get_athlete_team(xc_soup)
                gender = get_athlete_gender(xc_soup)

                grade = get_current_grade(xc_soup)
                xc_3mile = get_fastest_time(xc_soup, "3 Miles")
                xc_5k = get_fastest_time(xc_soup, "5000 Meters")
            else:
                log(f"  No XC results for {athlete_id}, skipping XC page")
                team = ""
                gender = ""

            # Pause between XC and track page to avoid rate limiting
            time.sleep(random.uniform(1.5, 3.0))

            # --- Track Page ---
            pr800 = pr1600 = pr3200 = ""
            driver.get(track_url)
            WebDriverWait(driver, 20).until(lambda d:
                d.find_elements(By.CSS_SELECTOR, "tr.ng-star-inserted") or
                d.find_elements(By.CSS_SELECTOR, "small.ng-star-inserted")
            )
            if driver.find_elements(By.CSS_SELECTOR, "tr.ng-star-inserted"):
                track_soup = BeautifulSoup(driver.page_source, "html.parser")

                track_grade = get_current_grade(track_soup)
                if track_grade and (not grade or int(track_grade) > int(grade)):
                    grade = track_grade

                pr800 = get_fastest_time(track_soup, "800 Meters")
                pr1600 = get_fastest_time(track_soup, "1600 Meters")
                pr3200 = get_fastest_time(track_soup, "3200 Meters")
            else:
                log(f"  No track results for {athlete_id}, skipping track page")

            return name, team, gender, grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, "Success"

        except Exception as e:
            name = get_athlete_name(xc_soup)
            attempt += 1
            if attempt == 1:
                log(f"  Retrying {name} (attempt 2)...")
                time.sleep(random.uniform(5.0, 7.0))
            elif attempt == 2:
                log(f"  Retrying {name} (attempt 3)")
                time.sleep(random.uniform(5.0, 7.0))
            else:
                log(f"\n*** Retrying {name} (attempt {attempt + 1}) - waiting longer...")
                time.sleep(random.uniform(7.0, 9.0))

# ---------------------------
# SCRAPE ALL ATHLETES IN BATCH
# ---------------------------

data = []

for athlete_id in athlete_ids:
    log(f"Scraping athlete ID: {athlete_id}")
    name, team, gender, grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, status = scrape_athlete(athlete_id)

    track_url = f"https://www.athletic.net/athlete/{athlete_id}/track-and-field/"
    hyperlink = make_hyperlink(track_url, name)

    data.append({
        "Athlete Name": hyperlink,
        "Team": team,
        "Gender": gender,
        "Grade": grade,
        "3 Mile PR": xc_3mile,
        "5000m PR": xc_5k,
        "800m PR": pr800,
        "1600m PR": pr1600,
        "3200m PR": pr3200,
        "Scrape Status": status
    })

    # Pause between athletes to avoid rate limiting
    time.sleep(random.uniform(3.0, 5.0))

# ---------------------------
# SAVE PARTIAL CSV FOR THIS BATCH
# ---------------------------

df = pd.DataFrame(data, columns=[
    "Athlete Name", "Team", "Gender", "Grade",
    "3 Mile PR", "5000m PR", "800m PR", "1600m PR", "3200m PR",
    "Scrape Status"
])

partial_file = OUTPUT_DIR / f"athletes_batch_{batch_number}.csv"
df.to_csv(partial_file, index=False)

driver.quit()
log(f"\nBatch {batch_number} finished!")
log(f"OUTPUTFILE:{partial_file}")
