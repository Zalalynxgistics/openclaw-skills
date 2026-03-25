# Setup Guide - Google Directory Skill

## Prerequisites

1. Google Workspace account with Admin role (at minimum: Users Read + Groups Read + Group Members Read)
2. Admin SDK API enabled in Google Cloud Console
3. OAuth Client ID (from google-api skill's credentials.json)

## Steps

### 1. Create Custom Admin Role (Google Admin Console)

1. Go to admin.google.com → Account → Admin roles
2. Create new role (e.g. "API Directory Reader")
3. Select privileges: Groups > Read, Group Members > Read, Users > Read
4. Assign role to the account that will authorize

### 2. Enable Admin SDK API

Go to: https://console.cloud.google.com/apis/api/admin.googleapis.com?project=<PROJECT_ID>
Click Enable.

### 3. OAuth Authorization

Generate auth URL and exchange code:

```bash
cd ~/openclaw_skills/google-api
python3 -u -c "
import json, os, secrets, hashlib, base64
from urllib.parse import urlencode

with open('references/credentials.json') as f:
    ci = json.load(f).get('installed') or json.load(f).get('web')

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group.readonly',
    'https://www.googleapis.com/auth/admin.directory.group.member.readonly',
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
]

code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b'=').decode()

# Save verifier for later exchange
json.dump({'code_verifier': code_verifier, 'client_id': ci['client_id'],
    'client_secret': ci['client_secret'], 'token_uri': ci['token_uri']},
    open('/tmp/oauth_verifier.json','w'))

params = {'response_type':'code','client_id':ci['client_id'],
    'redirect_uri':'http://localhost:8765','scope':' '.join(SCOPES),
    'code_challenge':code_challenge,'code_challenge_method':'S256',
    'access_type':'offline','prompt':'consent'}
print(ci['auth_uri']+'?'+urlencode(params))
"
```

User opens URL, authorizes, copies redirected URL with code. Then exchange:

```bash
python3 -c "
import json, os, requests
v = json.load(open('/tmp/oauth_verifier.json'))
CODE = '<paste code here>'
resp = requests.post(v['token_uri'], data={
    'code':CODE,'client_id':v['client_id'],'client_secret':v['client_secret'],
    'redirect_uri':'http://localhost:8765','grant_type':'authorization_code',
    'code_verifier':v['code_verifier']})
data = resp.json()
tf = os.path.expanduser('~/.openclaw/workspace/google_tokens/<USER_ID>_admin.json')
json.dump({'user_id':'<USER_ID>','token':data['access_token'],
    'refresh_token':data.get('refresh_token'),'token_uri':v['token_uri'],
    'client_id':v['client_id'],'client_secret':v['client_secret'],
    'scopes':data.get('scope','').split()}, open(tf,'w'), indent=2)
print('Saved:', tf)
"
```
