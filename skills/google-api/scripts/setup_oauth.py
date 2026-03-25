#!/usr/bin/env python3
"""Gmail OAuth setup - per-user token, localhost redirect flow"""
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import Flow

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(_SKILL_DIR, 'references', 'credentials.json')
TOKENS_DIR = os.path.expanduser('~/.openclaw/workspace/google_tokens')
REDIRECT_URI = 'http://localhost:8765'
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/presentations',
    'https://www.googleapis.com/auth/contacts',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://www.googleapis.com/auth/gmail.settings.sharing',
    'https://www.googleapis.com/auth/admin.directory.group.readonly',
    'https://www.googleapis.com/auth/admin.directory.group.member.readonly',
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
]

def token_path(user_id: str) -> str:
    os.makedirs(TOKENS_DIR, exist_ok=True)
    return os.path.join(TOKENS_DIR, f'{user_id}.json')

def setup(user_id: str):
    auth_code = None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            params = parse_qs(urlparse(self.path).query)
            if 'code' in params:
                auth_code = params['code'][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'<h1>Authorization successful! You can close this tab.</h1>')
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'<h1>Error: no code received</h1>')
        def log_message(self, *args): pass

    flow = Flow.from_client_secrets_file(CREDENTIALS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent')
    print(f'AUTHURL:{auth_url}')

    server = HTTPServer(('localhost', 8765), Handler)
    server.handle_request()

    if auth_code:
        flow.fetch_token(code=auth_code)
        creds = flow.credentials
        token_data = {
            'user_id': user_id,
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes),
        }
        with open(token_path(user_id), 'w') as f:
            json.dump(token_data, f, indent=2)
        print(f'TOKEN_SAVED:{token_path(user_id)}')
    else:
        print('ERROR: no code received')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: setup_oauth.py <user_id>')
        sys.exit(1)
    setup(sys.argv[1])
