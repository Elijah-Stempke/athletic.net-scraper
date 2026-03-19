import sys
import time
import random
import re
import pandas as pd

# Output to folder
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
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
# GET ARGUMENTS OR PROMPT
# ---------------------------

if len(sys.argv) == 3:
    team_id = sys.argv[1]
    gender_choice = sys.argv[2].upper()
else:
    team_id = input("Enter Athletic.net Team ID: ")
    gender_choice = ""
    while gender_choice not in ["M", "F", "B"]:
        gender_choice = input("Select gender (M = Male, F = Female, B = Both): ").upper()

team_url = f"https://www.athletic.net/team/{team_id}/cross-country"
print(f"Opening team page for team ID {team_id}...")

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

driver.get(team_url)

WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, "h4"))
)

# ---------------------------
# GET TEAM NAME
# ---------------------------

try:
    team_name = driver.find_element(By.CSS_SELECTOR, "h2.mb-0 a").text.strip()
except:
    team_name = f"Team_{team_id}"

safe_team_name = re.sub(r'[\\/*?:"<>|]', "", team_name)

# ---------------------------
# PARSE TEAM PAGE
# ---------------------------

soup = BeautifulSoup(driver.page_source, "html.parser")
athletes = []

h4_tags = soup.find_all("h4")
for h4 in h4_tags:

    gender_text = h4.get_text(strip=True).lower()
    if gender_text == "boys":
        gender = "Male"
    elif gender_text == "girls":
        gender = "Female"
    else:
        continue

    if gender_choice == "M" and gender != "Male":
        continue
    if gender_choice == "F" and gender != "Female":
        continue

    next_sibling = h4.find_next_sibling()
    while next_sibling and next_sibling.name != "h4":
        for link in next_sibling.find_all("a", href=True):
            name_span = link.find("span", class_="text-truncate")
            if name_span:
                name = name_span.get_text(strip=True)
                href = link["href"]
                # Extract athlete ID from URL e.g. /athlete/23599186/cross-country
                match = re.search(r"/athlete/(\d+)/", href)
                if match:
                    athlete_id = match.group(1)
                    xc_url = f"https://www.athletic.net/athlete/{athlete_id}/cross-country"
                    track_url = f"https://www.athletic.net/athlete/{athlete_id}/track-and-field/"
                    athletes.append((name, athlete_id, xc_url, track_url, gender))
        next_sibling = next_sibling.find_next_sibling()

# Deduplicate by athlete_id
seen = set()
unique_athletes = []
for athlete in athletes:
    if athlete[1] not in seen:
        seen.add(athlete[1])
        unique_athletes.append(athlete)
athletes = unique_athletes

print(f"Found {len(athletes)} athletes")

# ---------------------------
# HELPER FUNCTIONS
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

        # Get only the direct text of h5, ignoring child spans (e.g. "- Relay Split")
        h5_text = h5.get_text(strip=True)

        # Skip relay splits
        if "relay" in h5_text.lower() or "split" in h5_text.lower():
            continue

        # Normalize event name for comparison
        if h5_text.strip().lower() != event_name.strip().lower():
            continue

        # Collect all times from this table
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
            # Return the original string of the fastest time
            fastest = min(times, key=lambda x: x[0])
            return fastest[1].rstrip("h")  # strip h suffix from saved value

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
            # Year is in first td, may include " Outdoor" etc.
            year_text = tds[0].get_text(strip=True)
            year_match = re.search(r"\d{4}", year_text)
            # Grade is in second td (text-success for XC, text-primary for track)
            grade_text = tds[1].get_text(strip=True)

            if year_match and grade_text.isdigit():
                year = int(year_match.group())
                if year > latest_year:
                    latest_year = year
                    latest_grade = grade_text

    return latest_grade


def make_hyperlink(url, name):
    """Build a spreadsheet-compatible HYPERLINK formula. Escapes apostrophes in names."""
    safe_name = name.replace("'", "''")
    return f'=HYPERLINK("{url}", "{safe_name}")'


def scrape_athlete(xc_url, track_url):
    """Scrape a single athlete's XC and track PRs with retries."""
    for attempt in range(3):
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
                grade = get_current_grade(xc_soup)
                xc_3mile = get_fastest_time(xc_soup, "3 Miles")
                xc_5k = get_fastest_time(xc_soup, "5000 Meters")
            else:
                print(f"  No XC results for athlete, skipping XC page")

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
                print(f"  No track results for athlete, skipping track page")

            return grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, "Success"

        except Exception as e:
            if attempt < 2:
                print(f"  Retrying {name} (attempt {attempt + 2} of 3)...")
                time.sleep(random.uniform(7.0, 9.0))
            else:
                print(f"\n*** {name} FAILED after 3 attempts ***\n")
                return "", "", "", "", "", "", "Failed"

# ---------------------------
# SCRAPE ALL ATHLETES
# ---------------------------

data = []

for name, athlete_id, xc_url, track_url, gender in athletes:
    print(f"Scraping: {name}")
    grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, status = scrape_athlete(xc_url, track_url)

    hyperlink = make_hyperlink(track_url, name)

    data.append({
        "Athlete Name": hyperlink,
        "Team": team_name,
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
    time.sleep(random.uniform(5.0, 7.0))
 
# ---------------------------
# SAVE CSV
# ---------------------------

df = pd.DataFrame(data, columns=[
    "Athlete Name", "Team", "Gender", "Grade",
    "3 Mile PR", "5000m PR", "800m PR", "1600m PR", "3200m PR",
    "Scrape Status"
])

output_file = OUTPUT_DIR / f"{safe_team_name}_{gender_choice}_prs.csv"
df.to_csv(output_file, index=False)

driver.quit()
print("\nFinished!")
print(f"Saved to {output_file}")
