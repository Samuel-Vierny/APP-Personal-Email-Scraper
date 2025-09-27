import os
import json
import base64
import logging
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

# --- Configuration ---
# SCOPE has been returned to read-only, as sending mail is no longer needed.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CONFIG_FILE = 'config.json'
LOG_FILE = 'scraper.log'
TOKEN_DIR = 'tokens/' 

# --- Setup Detailed Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SCRAPER - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() 
    ]
)

def get_message_body(msg):
    """Parses a Gmail message to find the text/plain body."""
    if msg['payload'].get('body', {}).get('data'):
        return base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
    elif msg['payload'].get('parts'):
        for part in msg['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
    return "Could not find readable content."

def main():
    """
    A robust script that connects to Gmail, logs its actions, handles errors,
    and saves email content to a timestamped file on the desktop.
    """
    logging.info("--- Script execution started ---")
    
    try:
        # --- 1. Load and Validate Configuration ---
        logging.info(f"Loading configuration from {CONFIG_FILE}")
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        target_email = config.get('target_email', '').strip()
        query = config.get('search_query', '')
        output_filename = config.get('output_filename', 'scraped_emails.txt')

        if not all([target_email, query, output_filename]):
            logging.error("Config validation failed. 'target_email', 'search_query', and 'output_filename' must all be present in config.json.")
            return

        logging.info(f"Configuration loaded for user: {target_email}")

        # --- 2. Authenticate User (using the tokens/ directory) ---
        if not os.path.exists(TOKEN_DIR):
            os.makedirs(TOKEN_DIR)
        
        token_file = os.path.join(TOKEN_DIR, f"{target_email}.json")
        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logging.info("Credentials expired. Refreshing token...")
                try:
                    creds.refresh(Request())
                except RefreshError as e:
                    logging.warning(f"Refresh token is invalid or revoked. Deleting it and re-authenticating. Error: {e}")
                    os.remove(token_file)
                    creds = None # Force re-authentication by setting creds to None
            
            # This block will now run if there's no token OR if the refresh failed.
            if not creds: 
                logging.info(f"No valid token found for {target_email}. Starting new authorization flow.")
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(token_file, "w") as token:
                token.write(creds.to_json())
            logging.info(f"Authorization successful. Token saved to {token_file}")

        service = build("gmail", "v1", credentials=creds)

        # --- 3. Search and Scrape Emails ---
        logging.info(f"Searching Gmail with query: '{query}'")
        result = service.users().messages().list(userId='me', q=query).execute()
        messages = result.get('messages', [])

        if not messages:
            logging.warning("No messages found matching the query.")
        else:
            logging.info(f"Found {len(messages)} email(s). Fetching content...")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name, file_ext = os.path.splitext(output_filename)
            timestamped_filename = f"{file_name}_{timestamp}{file_ext}"

            desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
            full_output_path = os.path.join(desktop_path, timestamped_filename)

            with open(full_output_path, 'w', encoding='utf-8') as f:
                f.write(f"Scrape Report\nTime: {datetime.now()}\nUser: {target_email}\nQuery: {query}\n\n")
                for i, msg_info in enumerate(messages):
                    msg = service.users().messages().get(userId='me', id=msg_info['id']).execute()
                    headers = msg.get("payload", {}).get("headers", [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                    from_sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'No Sender')
                    date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'No Date')
                    body = get_message_body(msg)
                    f.write(f"--- Email {i+1}/{len(messages)} ---\nSubject: {subject}\nFrom: {from_sender}\nDate: {date}\n\n{body}\n\n---------------------------------\n\n")
            
            logging.info(f"Successfully saved scrape results to: {full_output_path}")

    except FileNotFoundError:
        logging.error(f"CRITICAL ERROR: The '{CONFIG_FILE}' or 'credentials.json' file was not found.")
    except HttpError as error:
        logging.error(f"An API error occurred: {error}")
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        logging.info("--- Script execution finished ---\n")

if __name__ == "__main__":
    main()