import os
import re
import json
import ssl
import random
import time
import sys

import requests
from bs4 import BeautifulSoup

import whisper  # If you want to transcribe

# Google/YouTube imports
import http.client as httplib
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow

ssl._create_default_https_context = ssl._create_unverified_context

# ----------------------------
#  Web Scraping Configuration
# ----------------------------
URL = "https://cityofno.granicus.com/ViewPublisher.php?view_id=42"


def get_date_time(raw_text):
    """
    Extract date and time from the raw text using a regex.
    """
    match = re.search(
        r"(\w+,\s\w+\s\d{1,2},\s\d{4})\s*-\s*(\d{1,2}:\d{2}\s*[APMapm]{2})", raw_text
    )
    if match:
        return match.group(1), match.group(2)
    return raw_text, "Unknown Time"


def get_all_links():
    """
    Scrapes the city of New Orleans website and returns a list of meetings (dict).
    """
    response = requests.get(URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    meetings = []
    rows = soup.find_all("tr", class_="listingRow")

    for row in rows:
        meeting_data = {}
        columns = row.find_all("td", class_="listItem")

        if len(columns) >= 2:
            meeting_data["title"] = columns[0].get_text(strip=True)
            raw_date_time = columns[1].get_text(strip=True)
            meeting_data["date"], meeting_data["time"] = get_date_time(raw_date_time)

            # Look for links
            for a in row.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("//"):
                    href = "https:" + href
                if ".mp4" in href:
                    meeting_data["video"] = href
                elif "AgendaViewer.php" in href:
                    meeting_data["agenda"] = href
                elif "MinutesViewer.php" in href:
                    meeting_data["minutes"] = href

            # Only add if there's a video
            if "video" in meeting_data:
                meetings.append(meeting_data)

    return meetings


def download_file(url, file_type=""):
    """
    Download or extract the text from the requested URL.
    file_type is used for naming the saved file.
    """
    filename = f"{file_type}_{os.path.basename(url).split('?')[0]}"
    local_filepath = filename

    response = requests.get(url, stream=True)
    response.raise_for_status()

    # Check if it's HTML
    if "text/html" in response.headers.get("Content-Type", ""):
        soup = BeautifulSoup(response.text, "html.parser")
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()

        clean_text = "\n".join(
            line.strip() for line in soup.get_text().splitlines() if line.strip()
        )

        with open(local_filepath, "w", encoding="utf-8") as f:
            f.write(clean_text)

        print(f"{file_type.capitalize()} saved as text: {local_filepath}")
    else:
        # Otherwise, just save the raw data
        with open(local_filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"{file_type.capitalize()} downloaded: {local_filepath}")

    return local_filepath


def transcribe_video(file_path):
    """
    Transcribe the video using OpenAI Whisper.
    """
    model = whisper.load_model("small.en")
    result = model.transcribe(file_path)
    transcription_text = result["text"]

    transcription_filename = f"{os.path.splitext(file_path)[0]}_transcription.txt"
    with open(transcription_filename, "w", encoding="utf-8") as transcript_file:
        transcript_file.write(transcription_text)

    print(f"Transcription saved: {transcription_filename}")
    return transcription_filename


def process_links_by_index(index, do_transcribe=True):
    """
    Scrapes the meeting list, grabs the meeting at `index`, downloads files,
    optionally transcribes the video, and returns metadata dict.
    """
    meetings = get_all_links()

    if index >= len(meetings):
        print(f"No meeting found at index {index}")
        return None

    meeting = meetings[index]

    print(
        f"Downloading meeting: {meeting['title']} on {meeting['date']} at {meeting['time']}"
    )

    metadata = {
        "title": meeting["title"],
        "date": meeting["date"],
        "time": meeting["time"],
        "video": None,
        "agenda": None,
        "minutes": None,
        "transcript": None,
    }

    if "video" in meeting:
        video_file = download_file(meeting["video"], file_type="video")
        metadata["video"] = video_file
        if do_transcribe:
            transcript_file = transcribe_video(video_file)
            metadata["transcript"] = transcript_file
    else:
        print("No video found.")

    if "agenda" in meeting:
        metadata["agenda"] = download_file(meeting["agenda"], file_type="agenda")
    else:
        print("No agenda found.")

    if "minutes" in meeting:
        metadata["minutes"] = download_file(meeting["minutes"], file_type="minutes")
    else:
        print("No minutes found.")

    return metadata


def save_metadata(metadata):
    """
    Saves the metadata dictionary to a local JSON file.
    """
    filename = "video_metadata.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)
    print(f"Metadata saved as {filename}")


# --------------------------------------------
#      YouTube Upload Configuration
# --------------------------------------------

# Explicitly tell the underlying HTTP transport library not to retry,
# since we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    httplib.NotConnected,
    httplib.IncompleteRead,
    httplib.ImproperConnectionState,
    httplib.CannotSendRequest,
    httplib.CannotSendHeader,
    httplib.ResponseNotReady,
    httplib.BadStatusLine,
)

# Always retry when an apiclient.errors.HttpError with one of these
# status codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application.
CLIENT_SECRETS_FILE = "client_secret_1091585370962-sdu3p4mqmkkj49f0mun6qdu45p92np1n.apps.googleusercontent.com.json"

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel.
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

MISSING_CLIENT_SECRETS_MESSAGE = f"""
WARNING: Please configure OAuth 2.0

To make this sample run you will need to populate the client_secrets.json file
found at:

   {os.path.abspath(os.path.join(os.path.dirname(__file__), CLIENT_SECRETS_FILE))}

with information from the API Console
https://console.cloud.google.com/

For more information about the client_secrets.json file format, please visit:
https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
"""

VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")


def get_authenticated_service():
    """
    Authenticate with OAuth2 and return the YouTube API service resource.
    """
    flow = flow_from_clientsecrets(
        CLIENT_SECRETS_FILE,
        scope=YOUTUBE_UPLOAD_SCOPE,
        message=MISSING_CLIENT_SECRETS_MESSAGE,
    )

    storage = Storage("ytupload.py-oauth2.json" % sys.argv[0])
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        # run_flow will open a browser window asking for OAuth permissions.
        args_for_run_flow = argparser.parse_args([])
        credentials = run_flow(flow, storage, args_for_run_flow)

    return build(
        YOUTUBE_API_SERVICE_NAME,
        YOUTUBE_API_VERSION,
        http=credentials.authorize(httplib2.Http()),
    )


def resumable_upload(insert_request):
    """
    Perform the actual upload to YouTube, with a retry mechanism.
    """
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print("Uploading file...")
            status, response = insert_request.next_chunk()
            if response is not None:
                if "id" in response:
                    print("Video id '%s' was successfully uploaded." % response["id"])
                else:
                    print(
                        "The upload failed with an unexpected response: %s" % response
                    )
                    return None
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = "A retriable HTTP error %d occurred:\n%s" % (
                    e.resp.status,
                    e.content,
                )
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = "A retriable error occurred: %s" % e

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                print("No longer attempting to retry.")
                return None

            max_sleep = 2**retry
            sleep_seconds = random.random() * max_sleep
            print(f"Sleeping {sleep_seconds:.2f} seconds and then retrying...")
            time.sleep(sleep_seconds)
    return response


def upload_video_to_youtube(
    file_path,
    title="Default Title",
    description="Default Description",
    category_id="22",
    keywords="",
    privacy_status="public",
):
    """
    Upload a video file to YouTube with the given metadata.
    """
    youtube = get_authenticated_service()

    tags = keywords.split(",") if keywords else None

    body = dict(
        snippet=dict(
            title=title,
            description=description,
            tags=tags,
            categoryId=category_id,
        ),
        status=dict(privacyStatus=privacy_status),
    )

    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(file_path, chunksize=-1, resumable=True),
    )

    response = resumable_upload(insert_request)
    return response


# --------------------------------------------
#      The Single Callable Function
# --------------------------------------------


def scrape_and_upload_meeting(
    index,
    privacy_status="unlisted",
    do_transcribe=False,
    use_meeting_title=True,
    additional_keywords="Council,New Orleans",
):
    """
    1) Scrapes the city site for the meeting at `index`.
    2) Downloads and optionally transcribes the video.
    3) Uploads to YouTube with metadata derived from the meeting info.

    :param index: Which meeting index to process from the site.
    :param privacy_status: "public", "unlisted", or "private" (default "unlisted")
    :param do_transcribe: Whether to run Whisper transcription on the video (default False).
    :param use_meeting_title: If True, use the scraped meeting title for the YouTube title. Otherwise, use a placeholder.
    :param additional_keywords: Comma-separated keywords appended to the default set.

    :return: The final YouTube API response if successful, or None on failure.
    """
    # 1. Grab the metadata for the chosen meeting
    metadata = process_links_by_index(index, do_transcribe=do_transcribe)
    if not metadata or not metadata["video"]:
        print("No video metadata or video file. Aborting.")
        return None

    # 2. Save metadata as a JSON if you like
    save_metadata(metadata)

    # 3. Build a YouTube title & description from the metadata
    if use_meeting_title:
        yt_title = metadata["title"]
    else:
        yt_title = f"City Council Meeting {metadata['date']}"

    yt_description = (
        f"Meeting Date: {metadata['date']} at {metadata['time']}\n\n"
        "Automated upload from the City of New Orleans archives.\n"
    )
    if metadata["transcript"]:
        # Optionally, read the transcript and include it or parts of it
        transcript_text = ""
        with open(metadata["transcript"], "r", encoding="utf-8") as tfile:
            transcript_text = tfile.read()
        # Be mindful of the 5,000 character limit for YouTube descriptions if you add the transcript
        short_transcript = transcript_text[:4000] + "..."  # truncated for example
        yt_description += "\nTRANSCRIPT (partial):\n" + short_transcript

    # 4. Additional keywords
    combined_keywords = additional_keywords  # could add more logic here

    # 5. Upload to YouTube
    print("Starting upload to YouTube...")
    response = upload_video_to_youtube(
        file_path=metadata["video"],
        title=yt_title,
        description=yt_description,
        category_id="22",  # e.g. People & Blogs
        keywords=combined_keywords,
        privacy_status=privacy_status,
    )

    if response and "id" in response:
        print(f"Video uploaded successfully! YouTube ID: {response['id']}")
    else:
        print("Upload failed or was not completed.")

    return response


# -------------
#   Example
# -------------
if __name__ == "__main__":
    """
    Example usage: This will scrape the 9th index (which is the 10th item),
    download that video, transcribe it, and then upload it to YouTube.
    """
    # You can change these parameters as needed.
    YOUTUBE_PRIVACY = "unlisted"  # or "public", "private"
    MEETING_INDEX = 9
    DO_TRANSCRIBE = False

    response = scrape_and_upload_meeting(
        index=MEETING_INDEX,
        privacy_status=YOUTUBE_PRIVACY,
        do_transcribe=DO_TRANSCRIBE,
        use_meeting_title=True,
        additional_keywords="Council,New Orleans,Meeting",
    )
