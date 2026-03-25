---
name: google-directory
description: Query Google Workspace directory for users, groups, and group members via Admin SDK Directory API. Use when looking up employee info, group mail members, finding which groups a user belongs to, or listing all groups/users in the organization. Requires an admin-scoped OAuth token.
---

# Google Directory Skill

## Token

Admin token: `~/.openclaw/workspace/google_tokens/<user_id>_admin.json`

This token has read-only scopes:
- `admin.directory.user.readonly`
- `admin.directory.group.readonly`
- `admin.directory.group.member.readonly`

## Usage

Run the script with an action:

```bash
python3 scripts/directory.py --user-id <telegram_user_id> <action> [options]
```

### Actions

**List all users:**
```bash
python3 scripts/directory.py --user-id 6871355627 users
```

**List all groups:**
```bash
python3 scripts/directory.py --user-id 6871355627 groups
```

**List members of a group:**
```bash
python3 scripts/directory.py --user-id 6871355627 members --group cs.th@lynxinterfreight.com
```

**Find groups a user belongs to:**
```bash
python3 scripts/directory.py --user-id 6871355627 user-groups --email sujika@lynxinterfreight.com
```

**Search users by name or email:**
```bash
python3 scripts/directory.py --user-id 6871355627 search-user -q "chanin"
```

**Search groups by name or email:**
```bash
python3 scripts/directory.py --user-id 6871355627 search-group -q "warehouse"
```

**Full dump (all groups + members + users):**
```bash
python3 scripts/directory.py --user-id 6871355627 dump
```

All output is JSON to stdout.

## Domain

Default domain: `lynxinterfreight.com` (override with `--domain`).

## Setup

Requires Admin SDK API enabled in Google Cloud Console and an OAuth token with admin directory scopes. See `references/setup.md` for first-time setup instructions.
