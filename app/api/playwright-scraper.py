import os
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CITY_COUNCIL_URL = "https://cityofno.granicus.com/ViewPublisher.php?view_id=42"


def get_first_mp4_link():
    """Use Playwright to scrape the city council page and return the first .mp4 link found."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(CITY_COUNCIL_URL)

        # Wait a bit for JavaScript-based content to load
        page.wait_for_timeout(5000)  # 5 seconds

        # Get rendered HTML
        html_content = page.content()
        browser.close()

    soup = BeautifulSoup(html_content, "html.parser")
    rows = soup.find_all("tr", class_="listingRow")

    for row in rows:
        for a_tag in row.find_all("a", href=True):
            href = a_tag["href"].strip()
            if ".mp4" in href:
                if href.startswith("//"):
                    href = "https:" + href
                return href
    return None


def download_file(url, filename=None):
    """Download a file from `url` using requests."""
    if not filename:
        filename = os.path.basename(url).split("?")[0]

    headers = {
        "User-Agent": "Mozilla/5.0 (Playwright-based scraper)",
        "Referer": "https://cityofno.granicus.com/",
    }

    print(f"Downloading from: {url}")
    with requests.get(url, stream=True, headers=headers) as r:
        r.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    print(f"Saved as: {filename}")
    return filename


def handler(request):
    """
    Vercel will call `handler(request)`.

    Return a dictionary with `statusCode` and `body` (and optional `headers`).
    """
    try:
        # 1. Scrape to get the first MP4 link.
        mp4_link = get_first_mp4_link()
        if not mp4_link:
            return {"statusCode": 404, "body": "No MP4 link found on the page."}

        # 2. (Optional) Download the file.
        #    Careful: Storage is ephemeral in serverless environment.
        downloaded_filename = download_file(mp4_link, filename="first_video.mp4")

        # 3. Return some sort of message.
        return {
            "statusCode": 200,
            "body": f"Successfully downloaded {mp4_link} to {downloaded_filename}",
        }

    except Exception as e:
        return {"statusCode": 500, "body": f"Error: {str(e)}"}
