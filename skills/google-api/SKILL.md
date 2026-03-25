---
name: google-api
description: Access and manage Google Workspace services (Gmail, Calendar, Drive, Docs, Sheets, Slides, Contacts, Tasks) via Google API. Use when reading/sending Gmail, managing calendar events, working with Drive files, Docs, Sheets, Slides, Contacts, or Tasks. Handles OAuth2 setup, token refresh, and API calls.
---

# Google Workspace Skill

## Credentials & Token Paths

- Credentials: `references/credentials.json` (bundled in skill — shared by all users)
- Tokens: `~/.openclaw/workspace/google_tokens/<user_id>.json` (one file per user)

## First-time OAuth Setup (per user)

If token for a user doesn't exist, run:

```bash
python3 scripts/setup_oauth.py <user_id>
```

`user_id` = Telegram user ID (e.g. `6871355627`). The script starts a local server on port 8765, prints an auth URL, and waits for the callback. Open the URL on the **local machine** (not mobile), authorize, and the token is saved automatically.

If port conflict: `fuser -k 8765/tcp && python3 scripts/setup_oauth.py <user_id>`

Check if user is already set up:
```bash
ls ~/.openclaw/workspace/google_tokens/
```

## Scopes Included

gmail.readonly, gmail.send, gmail.modify, calendar, drive, documents, spreadsheets, presentations, contacts, tasks

## Using the Token in Code

```python
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TOKENS_DIR = os.path.expanduser('~/.openclaw/workspace/google_tokens')

def get_creds(user_id: str):
    token_file = os.path.join(TOKENS_DIR, f'{user_id}.json')
    if not os.path.exists(token_file):
        raise FileNotFoundError(f'No token for user {user_id}. Run: python3 scripts/setup_oauth.py {user_id}')
    with open(token_file) as f:
        t = json.load(f)
    creds = Credentials(
        token=t['token'], refresh_token=t['refresh_token'],
        token_uri=t['token_uri'], client_id=t['client_id'],
        client_secret=t['client_secret']
    )
    if creds.expired:
        creds.refresh(Request())
        t['token'] = creds.token
        with open(token_file, 'w') as f:
            json.dump(t, f, indent=2)
    return creds
```

## Common API Services

```python
creds = get_creds()
gmail   = build('gmail', 'v1', credentials=creds)
cal     = build('calendar', 'v3', credentials=creds)
drive   = build('drive', 'v3', credentials=creds)
docs    = build('docs', 'v1', credentials=creds)
sheets  = build('sheets', 'v4', credentials=creds)
tasks   = build('tasks', 'v1', credentials=creds)
people  = build('people', 'v1', credentials=creds)
```

## Gmail Examples

```python
# List inbox
results = gmail.users().messages().list(userId='me', q='is:unread', maxResults=10).execute()

# Get message
msg = gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()

# Send email
import base64
from email.mime.text import MIMEText
message = MIMEText('body text')
message['to'] = 'recipient@example.com'
message['subject'] = 'Subject'
raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
```

## Calendar Examples

```python
# List upcoming events
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
events = cal.events().list(calendarId='primary', timeMin=now, maxResults=10, singleEvents=True, orderBy='startTime').execute()

# Create event
event = {
    'summary': 'Meeting',
    'start': {'dateTime': '2025-01-01T10:00:00+07:00'},
    'end':   {'dateTime': '2025-01-01T11:00:00+07:00'},
}
cal.events().insert(calendarId='primary', body=event).execute()
```

## Drive Examples

```python
# List files
files = drive.files().list(pageSize=10, fields='files(id,name,mimeType)').execute()

# Download file content
import io
from googleapiclient.http import MediaIoBaseDownload
request = drive.files().get_media(fileId=file_id)
fh = io.BytesIO()
downloader = MediaIoBaseDownload(fh, request)
done = False
while not done:
    _, done = downloader.next_chunk()
```

## Tasks Examples

```python
# List task lists
tasklists = tasks.tasklists().list().execute()

# List tasks
task_items = tasks.tasks().list(tasklist='@default').execute()

# Create task
tasks.tasks().insert(tasklist='@default', body={'title': 'New Task', 'notes': 'Details'}).execute()
```
