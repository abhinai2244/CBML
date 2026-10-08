# Add Service Accounts to Team Drive

> Adds Google service accounts to a Team Drive with organizer access.

## Quick Info

- **Purpose**: Grant service accounts access to Team Drive
- **Input**: Service account credentials from `gen_sa_accounts`
- **Required**: Manager access on the Team Drive

---

## Which User Are You?

- **Newbie**: Start with "Step-by-Step for Beginners" below
- **Pro**: Jump to "CLI Reference" for advanced options

---

## Getting Started

### Prerequisites

1. **Service accounts** created with `gen_sa_accounts` script
2. **Team Drive ID** - Get from drive URL
3. **Manager access** - Your Google account must be a Manager on the Team Drive
4. **Credentials** in `config/credentials.json`

### Understanding Permissions

| Role | Access Level |
|------|--------------|
| Reader | Can view files |
| Commenter | Can view + comment |
| Writer | Can upload/modify |
| Organizer | Full access + can add members |

For bot file searching, **Organizer** is required.

---

## For Newbies (Step-by-Step)

### Step 1: Create Service Accounts

If you haven't already:
```bash
cd gen_scripts/gen_sa_accounts
python script.py --quick-setup 5
```

This creates accounts in `accounts/` folder.

### Step 2: Find Team Drive ID

1. Open your Team Drive in browser
2. Look at the URL:
   ```
   https://drive.google.com/drive/folders/0ABC123456789XYZabcdefghijklmnop
   ```
3. Copy the ID (everything after `folders/`): `0ABC123456789XYZabcdefghijklmnop`

### Step 3: Run the Script

```bash
cd gen_scripts/add_to_team_drive
python script.py --drive-id "0ABC123456789XYZabcdefghijklmnop"
```

### Step 4: Confirm

When prompted:
- Press `y` to confirm (or use `--yes` flag to skip)

### What Happens

1. Script finds all `.json` files in accounts folder
2. Adds each service account as organizer to the Team Drive
3. Shows progress for each account

### After Completion

✅ All service accounts now have organizer access
✅ Bot can search files in this Team Drive

---

## For Pro Users

### CLI Reference

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--path`, `-p` | string | No | `accounts` | Path to service accounts folder |
| `--credentials`, `-c` | string | No | `../../config/credentials.json` | Credentials file path |
| `--drive-id`, `-d` | string | Yes | - | Team Drive ID |
| `--yes`, `-y` | flag | No | false | Skip confirmation prompt |

### Workflow Examples

```bash
# Basic usage
python script.py --drive-id "0ABC123xyz"

# With custom accounts path
python script.py -p ./my_accounts -d "0ABC123xyz"

# Skip confirmation
python script.py -d "0ABC123xyz" --yes
```

### Finding Drive ID

| Drive Type | How to Get ID |
|------------|---------------|
| Team Drive | URL after `/folders/` |
| Shared Folder | URL after `/folders/` |
| My Drive | Use `root` (not applicable for this script) |

### Authentication Flow

The script:
1. Uses credentials from `config/credentials.json`
2. Creates/refreshes token in `config/tokens/token_sa.pickle`
3. Uses console OAuth if needed

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `No service account files` | Run gen_sa_accounts first | Create service accounts |
| `No credentials found` | Missing credentials.json | Run gen_token_pickle |
| `Manager access required` | Insufficient permissions | Ensure your account is Manager |
| `Batch execution failed` | API rate limit | Wait and retry |

### Common Issues

**"Authentication failed"**
- Run gen_token_pickle first
- Ensure credentials.json is valid

**"Manager access required"**
- Your Google account needs Manager role on the Team Drive
- Ask the Team Drive owner to upgrade your role

**"Service account already exists"**
- Normal - script continues with others
- Some accounts may already be added

---

## Next Steps

| Goal | Action |
|------|--------|
| Test access | Start bot and search a file |
| Add more drives | Run script with different Drive ID |
| Use in bot | Copy accounts folder to bot's accounts/ |

---

## Related Scripts

- **gen_sa_accounts** - Create service accounts
- **gen_token_pickle** - Authenticate with Google
- **driveid** - Configure drives to search