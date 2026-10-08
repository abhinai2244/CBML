# Generate Google Drive Token

> Authenticates with Google Drive API and generates a token file for use with other scripts.

## Quick Info

- **Purpose**: Create OAuth 2.0 token for Google Drive API access
- **Output**: `tokens/token.pickle`
- **Required**: `config/credentials.json`

---

## Which User Are You?

- **Newbie**: Start with "Step-by-Step for Beginners" below
- **Pro**: Jump to "CLI Reference" for advanced options

---

## Getting Started

### Prerequisites

1. **Google Cloud Project** with Google Drive API enabled
2. **OAuth 2.0 Credentials** (Desktop app type) downloaded as `credentials.json`
3. **Python dependencies** installed:
   ```bash
   pip install -r config/requirements-cli.txt
   ```

### File Structure

```
gen_scripts/
├── config/
│   └── credentials.json    # Your OAuth credentials
└── tokens/
    └── token.pickle       # Generated token (auto-created)
```

---

## For Newbies (Step-by-Step)

### Step 1: Get Google Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Go to **APIs & Services** → **Enabled APIs & services**
4. Enable **Google Drive API**
5. Go to **OAuth consent screen** → Create (External)
6. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
7. Choose **Desktop app** → Download JSON

### Step 2: Place Credentials

Move the downloaded JSON file to:
```
gen_scripts/config/credentials.json
```

### Step 3: Run the Script

```bash
cd gen_scripts/gen_token_pickle
python script.py
```

### What to Expect

1. Script checks for existing valid token
2. If expired, attempts automatic refresh
3. If no token, opens browser for OAuth authentication
4. Token saved to `tokens/token.pickle`

### After Completion

- ✅ Token is ready for use
- ✅ You can now run other Google Drive scripts
- ✅ Token auto-refreshes when expired

---

## For Pro Users

### CLI Reference

This script uses automatic token management. No CLI flags needed for basic use.

| Behavior | Description |
|----------|-------------|
| Auto-detect token | Checks `tokens/token.pickle` first |
| Auto-refresh | Refreshes expired tokens automatically |
| Browser auth | Opens default browser for OAuth (if available) |
| Console fallback | Falls back to console input if browser fails |

### Token File Location

| File | Default Path | Description |
|------|--------------|-------------|
| Token | `../tokens/token.pickle` | OAuth 2.0 refresh token |

### Environment Variables

No environment variables required. All paths are relative to script location.

### Workflow Examples

```bash
# Standard run (token auto-generated)
cd gen_scripts/gen_token_pickle
python script.py

# Alternative: Run from gen_scripts root
python -m gen_token_pickle.script
```

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `credentials.json not found` | File missing | See "Get Google Credentials" above |
| `OAuth failed` | Invalid credentials | Check API enabled, redownload credentials |
| `Token refresh failed` | Expired refresh token | Delete `token.pickle` and re-run |
| `Browser not opening` | No GUI available | Console auth will be used automatically |

### Common Issues

**"Missing credentials.json"**
- Download from Google Cloud Console → Credentials
- Ensure Google Drive API is enabled
- File must be named exactly `credentials.json`

**"Token expired"**
- Script automatically refreshes
- If refresh fails, delete `tokens/token.pickle` and re-run

---

## Next Steps

| Goal | Script |
|------|--------|
| Add drives to search list | `../driveid/` |
| Create service accounts | `../gen_sa_accounts/` |
| Full bot setup | See main project README |

---

## Related Scripts

- **gen_sa_accounts** - Create service accounts for Team Drive access
- **add_to_team_drive** - Add service accounts to Team Drive
- **driveid** - Configure which drives the bot can search