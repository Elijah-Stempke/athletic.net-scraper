import re
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# ---------------------------
# INPUT MEET ID
# ---------------------------
meet_id = input("Enter Athletic.net Meet ID: ")
teams_url = f"https://www.athletic.net/TrackAndField/meet/{meet_id}/teams"

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

# ---------------------------
# LOAD TEAMS PAGE
# ---------------------------
driver.get(teams_url)

# Wait for the container nav elements to appear
try:
    WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "nav.nav"))
    )
    # Extra wait for Angular to finish rendering
    time.sleep(3)
except:
    print("Team list did not load.")
    driver.quit()
    exit()

# ---------------------------
# PARSE TEAM IDS
# ---------------------------
soup = BeautifulSoup(driver.page_source, "html.parser")
team_links = soup.select("nav.nav a.nav-link[href*='/team/']")

team_ids = []

for link in team_links:
    href = link["href"]
    match = re.search(r"/team/(\d+)/", href)
    if match:
        team_ids.append(match.group(1))

# Remove duplicates and sort numerically
team_ids = sorted(list(set(team_ids)), key=int)

# ---------------------------
# SAVE TO TXT
# ---------------------------
output_file = f"meet_{meet_id}_teams.txt"
with open(output_file, "w") as f:
    for tid in team_ids:
        f.write(f"{tid}\n")

print(f"Found {len(team_ids)} teams. Saved to {output_file}")

driver.quit()