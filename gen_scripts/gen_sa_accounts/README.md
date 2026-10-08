# Generate Google Service Accounts

> Creates Google Cloud projects, service accounts, and downloads credential files for Team Drive access.

## Quick Info

- **Purpose**: Generate service account credentials for Google Drive API
- **Output**: JSON credential files in specified folder
- **Required**: `config/credentials.json` with proper API enabled

---

## Which User Are You?

- **Newbie**: Start with "Step-by-Step for Beginners" below
- **Pro**: Jump to "CLI Reference" for advanced workflows

---

## Getting Started

### Prerequisites

1. **Google Cloud credentials** in `config/credentials.json`
2. **APIs enabled** in Google Cloud Console:
   - Cloud Resource Manager API
   - IAM API
   - Service Usage API
   - Google Drive API
3. **Python dependencies**:
   ```bash
   pip install -r config/requirements-cli.txt
   ```

### Understanding Service Accounts

Service accounts are robot accounts that can:
- Access Google Drive/Team Drives programmatically
- Be added to Team Drives with specific permissions
- Work 24/7 without human authentication

Each service account counts as one "user" toward drive limits.

---

## For Newbies (Step-by-Step)

### Step 1: Ensure Prerequisites

1. Verify `config/credentials.json` exists
2. Ensure all required APIs are enabled in Google Cloud
3. Install dependencies

### Step 2: Run Quick Setup (Recommended)

```bash
cd gen_scripts/gen_sa_accounts
python script.py --quick-setup 5
```

This will:
- Create 5 new Google Cloud projects
- Enable IAM and Drive APIs on each
- Create 100 service accounts per project (500 total)
- Download all credential JSON files

### Step 3: Wait for Completion

⚠️ This process takes 5-15 minutes due to Google API rate limits.

You will see progress output like:
```
Creating projects: 5
Creating accounts in project-123...
Downloading keys from project-123...
```

### Step 4: Verify Output

After completion:
```
accounts/
├── 0.json
├── 1.json
├── ...
└── 499.json
```

Each file is a service account credential.

### Step 5: Add to Team Drive

Run the `add_to_team_drive` script:
```bash
cd ../add_to_team_drive
python script.py --drive-id "YOUR_TEAM_DRIVE_ID"
```

---

## For Pro Users

### CLI Reference

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--path`, `-p` | string | No | `accounts` | Output directory for credentials |
| `--credentials` | string | No | `../../config/credentials.json` | Credentials file path |
| `--token` | string | No | `../../config/tokens/token_sa.pickle` | SA token file |
| `--quick-setup` | int | No | - | Create N projects with full setup |
| `--new-only` | flag | No | false | Only use newly created projects (with --quick-setup) |
| `--list-projects` | flag | No | - | List all viewable projects |
| `--list-sas` | string | No | - | List SAs in specific project |
| `--create-projects` | int | No | - | Create N new projects |
| `--max-projects` | int | No | 12 | Maximum projects allowed |
| `--enable-services` | string | No | - | Enable services (`*`=all, `~`=new) |
| `--create-sas` | string | No | - | Create SAs (`*`=all, `~`=new) |
| `--download-keys` | string | No | - | Download keys (`*`=all, `~`=new) |
| `--delete-sas` | string | No | - | Delete SAs in project |
| `--services` | list | No | `iam drive` | Services to enable |

### Special Values

| Value | Meaning |
|-------|---------|
| `*` | All projects |
| `~` | Only newly created projects (with --quick-setup) |

### Workflow Examples

```bash
# Quick setup - create 5 projects with everything
python script.py --quick-setup 5

# List all projects
python script.py --list-projects

# List SAs in a specific project
python script.py --list-sas my-project-id

# Enable services on all projects
python script.py --enable-services "*"

# Download keys from specific project
python script.py --download-keys my-project-id

# Custom path and max projects
python script.py --quick-setup 3 --path ./my_accounts --max-projects 12
```

### Project Limits

- Default: 12 projects maximum per account
- Each project: 100 service accounts
- Each SA: Can be added to multiple Team Drives

### Performance Notes

- Creating projects: ~30 seconds each
- Enabling services: ~10 seconds each
- Creating 100 SAs: ~2-5 minutes
- Downloading 100 keys: ~5-10 minutes

Total time for 5 projects: ~15-30 minutes

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `No credentials found` | Missing credentials.json | Run gen_token_pickle first |
| `Cannot create N projects` | Exceeds 12 project limit | Delete existing projects or use --max-projects |
| `Error creating projects` | API rate limit | Wait and retry |
| `Error enabling services` | Project not ready | Wait and retry |
| `Error creating SA keys` | Rate limit | Script handles automatically with retry |

### Common Issues

**"Max projects allowed: 12"**
- Google limits projects per account
- Use `--max-projects` to adjust if you have fewer available
- Delete unused projects at https://console.cloud.google.com

**"Rate limit errors"**
- Normal behavior, script handles automatically
- Wait times are built-in for Google API limits

**"Batch errors"**
- Usually transient, script retries automatically
- If persists, check API quotas in Google Cloud Console

---

## Next Steps

| Goal | Action |
|------|--------|
| Add accounts to Team Drive | Run add_to_team_drive script |
| Use in bot | Copy accounts folder to bot's accounts/ |
| Test | Search a file in the configured Team Drive |

---

## Related Scripts

- **gen_token_pickle** - Initial OAuth authentication
- **add_to_team_drive** - Add accounts to Team Drive
- **driveid** - Configure drives to search