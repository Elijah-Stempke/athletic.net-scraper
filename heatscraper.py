import time
import random
import re
import pandas as pd
from pathlib import Path
from collections import defaultdict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------
# PARSE HEATS.TXT
# ---------------------------
# Format:
#   Line 1: meet ID
#   Remaining lines: [number] [Lastname], [Firstname] [grade] [school]

heats_path = Path(__file__).parent / "heats.txt"
with open(heats_path, "r") as f:
    lines = [line.strip() for line in f if line.strip()]

meet_id = lines[0]
print(f"Meet ID: {meet_id}")

# Parse each athlete line into structured data
# Pattern: number  Lastname, Firstname  grade  school
athlete_pattern = re.compile(r"^\d+\s+(.+?),\s+(\S+)\s+(\d+)\s+(.+)$")

# Group athletes by school: {school_name: [(full_name, grade), ...]}
athletes_by_school = defaultdict(list)

for line in lines[1:]:
    match = athlete_pattern.match(line)
    if match:
        last_name = match.group(1).strip()
        first_name = match.group(2).strip()
        grade = match.group(3).strip()
        school = match.group(4).strip()
        full_name = f"{first_name} {last_name}"  # flip to Firstname Lastname
        athletes_by_school[school].append((full_name, grade))
    else:
        print(f"  Could not parse line: {line}")

print(f"Found {sum(len(v) for v in athletes_by_school.values())} athletes across {len(athletes_by_school)} schools")

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

driver.execute_cdp_cmd("Network.enable", {})
driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
    "*.png", "*.jpg", "*.gif", "*.svg", "*.woff", "*.woff2",
    "*.ttf", "*.css", "*.ico", "googletagmanager.com/*",
    "google-analytics.com/*", "doubleclick.net/*"
]})

# ---------------------------
# LOAD MEET TEAMS PAGE
# ---------------------------

teams_url = f"https://www.athletic.net/TrackAndField/meet/{meet_id}/teams"
print(f"Loading meet teams page: {teams_url}")
driver.get(teams_url)

try:
    WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "nav.nav"))
    )
    time.sleep(3)  # extra wait for Angular rendering
except:
    print("Team list did not load.")
    driver.quit()
    exit()

soup = BeautifulSoup(driver.page_source, "html.parser")
team_links = soup.select("nav.nav a.nav-link[href*='/team/']")

# Build a dict of {team_name: team_id} from the meet page
meet_teams = {}
for link in team_links:
    href = link["href"]
    id_match = re.search(r"/team/(\d+)/", href)
    if id_match:
        team_name_on_page = link.get_text(strip=True)
        meet_teams[team_name_on_page] = id_match.group(1)

print(f"Found {len(meet_teams)} teams on meet page")

# ---------------------------
# MATCH SCHOOLS FROM HEATS.TXT TO MEET TEAMS
# Using starts-with logic to handle truncated school names
# ---------------------------

# school_to_team_id: {school_from_heats: (matched_team_name, team_id)}
school_to_team = {}

for school in athletes_by_school:
    matched = None
    for team_name_on_page, team_id in meet_teams.items():
        if team_name_on_page.lower().startswith(school.lower()):
            matched = (team_name_on_page, team_id)
            break
    if matched:
        print(f"  Matched '{school}' → '{matched[0]}' (ID: {matched[1]})")
        school_to_team[school] = matched
    else:
        print(f"  *** Could not match school: '{school}' — athletes will be marked Failed")

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
    Skips relay tables. Returns the fastest time string or "".
    """
    tables = soup.find_all("table", class_="histEvent")
    for table in tables:
        h5 = table.find("h5", class_="bold")
        if not h5:
            continue
        h5_text = h5.get_text(strip=True)
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
    """Get athlete's most recent grade across all event tables."""
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


def make_hyperlink(url, name):
    """Build a spreadsheet-compatible HYPERLINK formula."""
    safe_name = name.replace("'", "''")
    return f'=HYPERLINK("{url}", "{safe_name}")'


def get_team_roster(team_id):
    """
    Load a team's XC roster page and return a dict of
    {athlete_name_lowercase: (athlete_id, gender)}
    """
    team_url = f"https://www.athletic.net/team/{team_id}/cross-country"
    driver.get(team_url)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h4"))
        )
        WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, "span.text-truncate"))
)
    except:
        print(f"  Could not load roster for team {team_id}")
        return {}

    soup = BeautifulSoup(driver.page_source, "html.parser")
    roster = {}

    h4_tags = soup.find_all("h4")
    for h4 in h4_tags:
        gender_text = h4.get_text(strip=True).lower()
        if gender_text == "boys":
            gender = "Male"
        elif gender_text == "girls":
            gender = "Female"
        else:
            continue

        next_sibling = h4.find_next_sibling()
        while next_sibling and next_sibling.name != "h4":
            for link in next_sibling.find_all("a", href=True):
                name_span = link.find("span", class_="text-truncate")
                if name_span:
                    roster_name = name_span.get_text(strip=True)
                    href = link["href"]
                    id_match = re.search(r"/athlete/(\d+)/", href)
                    if id_match:
                        athlete_id = id_match.group(1)
                        roster[roster_name.lower()] = (athlete_id, gender)
            next_sibling = next_sibling.find_next_sibling()

    return roster


def scrape_athlete_prs(name, athlete_id):
    """Scrape XC and track PRs for a single athlete with retries."""
    xc_url = f"https://www.athletic.net/athlete/{athlete_id}/cross-country"
    track_url = f"https://www.athletic.net/athlete/{athlete_id}/track-and-field/"

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
                print(f"  No XC results for {name}, skipping XC page")

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
                print(f"  No track results for {name}, skipping track page")

            return grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, "Success"

        except Exception as e:
            if attempt < 2:
                print(f"  Retrying {name} (attempt {attempt + 2} of 3)...")
                time.sleep(random.uniform(7.0, 9.0))
            else:
                print(f"\n*** {name} FAILED after 3 attempts ***\n")
                return "", "", "", "", "", "", "Failed"


# ---------------------------
# MAIN SCRAPING LOOP
# Process one team at a time, scraping all listed athletes per team
# ---------------------------

data = []

for school, athletes_in_school in athletes_by_school.items():

    # Check if we matched this school to a team
    if school not in school_to_team:
        print(f"\nSkipping {school} — no team match found")
        for name, grade_from_heats in athletes_in_school:
            track_url = ""
            data.append({
                "Athlete Name": name,
                "Team": school,
                "Gender": "",
                "Grade": grade_from_heats,
                "3 Mile PR": "",
                "5000m PR": "",
                "800m PR": "",
                "1600m PR": "",
                "3200m PR": "",
                "Scrape Status": "Failed - School Not Found"
            })
        continue

    team_name, team_id = school_to_team[school]
    print(f"\nLoading roster for {team_name}...")

    roster = get_team_roster(team_id)
    print(f"  Found {len(roster)} athletes on roster")

    time.sleep(random.uniform(2.0, 3.0))

    for name, grade_from_heats in athletes_in_school:
        print(f"  Scraping: {name}")
        athlete_id = None
        gender = ""

        # Look up athlete in roster by name (case-insensitive)
        roster_entry = roster.get(name.lower())
        if roster_entry:
            athlete_id, gender = roster_entry
        else:
            print(f"  *** {name} not found on {team_name} roster — marking as Failed")
            data.append({
                "Athlete Name": name,
                "Team": team_name,
                "Gender": "",
                "Grade": grade_from_heats,
                "3 Mile PR": "",
                "5000m PR": "",
                "800m PR": "",
                "1600m PR": "",
                "3200m PR": "",
                "Scrape Status": "Failed - Not Found on Roster"
            })
            continue

        track_url = f"https://www.athletic.net/athlete/{athlete_id}/track-and-field/"
        grade, xc_3mile, xc_5k, pr800, pr1600, pr3200, status = scrape_athlete_prs(name, athlete_id)
        hyperlink = make_hyperlink(track_url, name)

        data.append({
            "Athlete Name": hyperlink,
            "Team": team_name,
            "Gender": gender,
            "Grade": grade if grade else grade_from_heats,
            "3 Mile PR": xc_3mile,
            "5000m PR": xc_5k,
            "800m PR": pr800,
            "1600m PR": pr1600,
            "3200m PR": pr3200,
            "Scrape Status": status
        })

        time.sleep(random.uniform(3.0, 4.0))

# ---------------------------
# SAVE OUTPUT CSV
# ---------------------------

df = pd.DataFrame(data, columns=[
    "Athlete Name", "Team", "Gender", "Grade",
    "3 Mile PR", "5000m PR", "800m PR", "1600m PR", "3200m PR",
    "Scrape Status"
])

n = 1
while (OUTPUT_DIR / f"heat{n}.csv").exists():
    n += 1
output_file = OUTPUT_DIR / f"heat{n}.csv"
df.to_csv(output_file, index=False)

driver.quit()
print(f"\nFinished! Saved to {output_file}")