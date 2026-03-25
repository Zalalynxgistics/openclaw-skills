#!/usr/bin/env python3
"""Google Workspace Directory API - query users, groups, members."""
import argparse, json, os, sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKENS_DIR = os.path.expanduser('~/.openclaw/workspace/google_tokens')

def get_service(user_id: str):
    tf = os.path.join(TOKENS_DIR, f'{user_id}_admin.json')
    if not os.path.exists(tf):
        print(json.dumps({'error': f'No admin token for {user_id}. Run OAuth setup first.'}))
        sys.exit(1)
    with open(tf) as f:
        t = json.load(f)
    creds = Credentials(token=t['token'], refresh_token=t['refresh_token'],
        token_uri=t['token_uri'], client_id=t['client_id'], client_secret=t['client_secret'])
    if creds.expired:
        creds.refresh(Request())
        t['token'] = creds.token
        with open(tf, 'w') as f2:
            json.dump(t, f2, indent=2)
    return build('admin', 'directory_v1', credentials=creds)

def list_users(svc, domain):
    users = []
    pt = None
    while True:
        r = svc.users().list(domain=domain, maxResults=500, pageToken=pt,
            fields='users(primaryEmail,name,orgUnitPath,suspended,isAdmin,phones,organizations),nextPageToken').execute()
        users.extend(r.get('users', []))
        pt = r.get('nextPageToken')
        if not pt: break
    return sorted(users, key=lambda u: u['primaryEmail'])

def list_groups(svc, domain):
    groups = []
    pt = None
    while True:
        r = svc.groups().list(domain=domain, maxResults=200, pageToken=pt).execute()
        groups.extend(r.get('groups', []))
        pt = r.get('nextPageToken')
        if not pt: break
    return sorted(groups, key=lambda g: g['email'])

def list_members(svc, group_key):
    members = []
    pt = None
    while True:
        try:
            r = svc.members().list(groupKey=group_key, maxResults=200, pageToken=pt).execute()
            members.extend(r.get('members', []))
            pt = r.get('nextPageToken')
            if not pt: break
        except Exception:
            break
    return sorted(members, key=lambda m: m.get('email', ''))

def user_groups(svc, email):
    groups = []
    pt = None
    while True:
        r = svc.groups().list(userKey=email, maxResults=200, pageToken=pt).execute()
        groups.extend(r.get('groups', []))
        pt = r.get('nextPageToken')
        if not pt: break
    return sorted(groups, key=lambda g: g['email'])

def full_dump(svc, domain):
    users = list_users(svc, domain)
    groups = list_groups(svc, domain)
    result = {'users': users, 'groups': []}
    for g in groups:
        members = list_members(svc, g['email'])
        result['groups'].append({
            'email': g['email'],
            'name': g.get('name', ''),
            'description': g.get('description', ''),
            'directMembersCount': g.get('directMembersCount', '0'),
            'members': [{'email': m.get('email',''), 'role': m.get('role','MEMBER')} for m in members]
        })
    return result

def search_users(svc, domain, query):
    """Search users by name or email (client-side filter)."""
    all_users = list_users(svc, domain)
    q = query.lower()
    return [u for u in all_users if q in u['primaryEmail'].lower()
            or q in u.get('name',{}).get('fullName','').lower()
            or q in u.get('name',{}).get('givenName','').lower()
            or q in u.get('name',{}).get('familyName','').lower()]

def search_groups(svc, domain, query):
    """Search groups by name or email (client-side filter)."""
    all_groups = list_groups(svc, domain)
    q = query.lower()
    return [g for g in all_groups if q in g['email'].lower() or q in g.get('name','').lower()]

def main():
    p = argparse.ArgumentParser(description='Google Workspace Directory')
    p.add_argument('--user-id', required=True, help='Telegram user ID for token lookup')
    p.add_argument('--domain', default='lynxinterfreight.com')
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('users')
    sub.add_parser('groups')
    m = sub.add_parser('members')
    m.add_argument('--group', required=True, help='Group email')
    ug = sub.add_parser('user-groups')
    ug.add_argument('--email', required=True, help='User email')
    sub.add_parser('dump')
    su = sub.add_parser('search-user')
    su.add_argument('--query', '-q', required=True, help='Search by name or email (supports Admin SDK query syntax)')
    sg = sub.add_parser('search-group')
    sg.add_argument('--query', '-q', required=True, help='Search groups by name or email')
    args = p.parse_args()

    svc = get_service(args.user_id)

    if args.action == 'users':
        print(json.dumps(list_users(svc, args.domain), indent=2, ensure_ascii=False))
    elif args.action == 'groups':
        print(json.dumps(list_groups(svc, args.domain), indent=2, ensure_ascii=False))
    elif args.action == 'members':
        print(json.dumps(list_members(svc, args.group), indent=2, ensure_ascii=False))
    elif args.action == 'user-groups':
        print(json.dumps(user_groups(svc, args.email), indent=2, ensure_ascii=False))
    elif args.action == 'dump':
        print(json.dumps(full_dump(svc, args.domain), indent=2, ensure_ascii=False))
    elif args.action == 'search-user':
        print(json.dumps(search_users(svc, args.domain, args.query), indent=2, ensure_ascii=False))
    elif args.action == 'search-group':
        print(json.dumps(search_groups(svc, args.domain, args.query), indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
