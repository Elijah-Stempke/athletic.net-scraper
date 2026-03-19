import sys
import time
import random
import re
import pandas as pd

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

driver.get(team_url)

# Wait for team roster to load
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
                url = "https://www.athletic.net" + link["href"]
                athletes.append((name, url, gender))
        next_sibling = next_sibling.find_next_sibling()

athletes = list(dict.fromkeys(athletes))
print(f"Found {len(athletes)} athletes")

# ---------------------------
# HELPER FUNCTIONS
# ---------------------------

def find_pr(text, event):
    pattern = rf"{event}.*?(\d+:\d+\.\d+)"
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return ""

def find_current_grade(soup):
    rows = soup.find_all("tr", class_="ng-star-inserted")
    grades = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) >= 2:
            grade_text = tds[1].get_text(strip=True)
            if grade_text.isdigit():
                grades.append(int(grade_text))
    if grades:
        return str(max(grades))
    return ""

def scrape_athlete(url):
    """Scrape a single athlete with retries and waits"""
    for attempt in range(3):
        try:
            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tr.ng-star-inserted"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            text = soup.get_text()

            grade = find_current_grade(soup)
            xc5k = find_pr(text, "5000")
            xc3mile = find_pr(text, "3 Mile")

            # Find track link if exists
            track_link = None
            for a in soup.find_all("a", href=True):
                if "/track" in a["href"]:
                    track_link = "https://www.athletic.net" + a["href"]
                    break

            pr800 = pr1600 = pr3200 = ""
            if track_link:
                driver.get(track_link)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "tr.ng-star-inserted"))
                )
                track_soup = BeautifulSoup(driver.page_source, "html.parser")
                track_text = track_soup.get_text()
                pr800 = find_pr(track_text, "800")
                pr1600 = find_pr(track_text, "1600")
                pr3200 = find_pr(track_text, "3200")

            return grade, xc3mile, xc5k, pr800, pr1600, pr3200

        except Exception as e:
            if attempt < 2:
                time.sleep(2)  # small wait before retry
            else:
                print(f"Skipped {url} due to {e}")
                return "", "", "", "", "", ""

# ---------------------------
# SCRAPE ALL ATHLETES
# ---------------------------

data = []

for name, url, gender in athletes:
    print("Scraping:", name)
    grade, xc3mile, xc5k, pr800, pr1600, pr3200 = scrape_athlete(url)
    data.append({
        "Athlete Name": name,
        "Team": team_name,
        "Gender": gender,
        "Grade": grade,
        "3 Mile PR": xc3mile,
        "5000m PR": xc5k,
        "800m PR": pr800,
        "1600m PR": pr1600,
        "3200m PR": pr3200
    })

# ---------------------------
# SAVE CSV
# ---------------------------

df = pd.DataFrame(data)
output_file = f"{safe_team_name}_{gender_choice}_prs.csv"
df.to_csv(output_file, index=False)

driver.quit()
print("\nFinished!")
print(f"Saved to {output_file}")