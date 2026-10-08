# Configure Drive List

> Configure which Google Drives and folders the bot can search.

## Quick Info

- **Purpose**: Set up drive/folder list for file searching
- **Output**: `list_drives.txt` in gen_scripts root
- **Required**: Drive IDs from Google Drive URL

---

## Which User Are You?

- **Newbie**: Start with "Step-by-Step for Beginners" below
- **Pro**: Jump to "CLI Reference" for advanced options

---

## Getting Started

### Prerequisites

1. **Google Drive access** - At least one drive you want to configure
2. **Drive IDs** - Available from drive URLs
3. **No Python dependencies needed** - Pure standard library

---

## For Newbies (Step-by-Step)

### Step 1: Find Your Drive ID

**For Main Drive (My Drive):**
- Use `root` as the ID

**For Team Drive:**
1. Open the Team Drive in browser
2. Look at the URL:
   ```
   https://drive.google.com/drive/folders/0ABC123456789XYZabcdefghijklmnop
   ```
3. The ID is everything after `folders/`: `0ABC123456789XYZabcdefghijklmnop`

**For Shared Folder:**
1. Right-click folder → Share
2. Copy the link
3. Extract ID from: `https://drive.google.com/drive/folders/ABCD123456789...`

### Step 2: Find Index URL (Optional)

If you have a Google Index for this drive:
- Copy the full index URL (e.g., `https://index.example.com/drive`)
- Leave empty if not needed

### Step 3: Run the Script

```bash
cd gen_scripts/driveid
python script.py
```

### Step 4: Enter Drive Details

When prompted:
```
How many drives/folders you want to add? 2

--- Drive 1 ---
Name (anything): My_TeamDrive
Drive ID (use 'root' for main drive): 0ABC123456789XYZabcdefghijklmnop
Index URL (optional, press Enter to skip): 

--- Drive 2 ---
Name (anything): Movies_Folder
Drive ID (use 'root' for main drive): root
Index URL (optional, press Enter to skip):
```

### After Completion

- ✅ `list_drives.txt` created in gen_scripts root
- ✅ Bot can now search these drives
- ✅ Add more drives anytime by re-running

---

## For Pro Users

### File Format

The `list_drives.txt` file uses space-separated format:

```
NAME DRIVE_ID INDEX_URL
```

Example:
```
My_TeamDrive 0ABC123xyz root
Movies 1XYZ789abc https://index.example.com/movies
```

### CLI Reference

This script uses interactive prompts.

| Option | Description |
|--------|-------------|
| Name | Any identifier (spaces converted to underscores) |
| Drive ID | `root` for main drive, or Team Drive ID |
| Index URL | Optional - for indexed drives |

### Workflow Examples

```bash
# Configure drives
cd gen_scripts/driveid
python script.py

# Manual edit (alternative)
echo "MyDrive root" >> ../list_drives.txt
echo "TeamDrive 0ABC123xyz" >> ../list_drives.txt
```

### Multiple Drives

You can configure multiple drives. Each line represents one drive:

```
Drive1 root
Drive2 0ABC123xyz
Folder1 root
```

The bot will search all configured drives.

### Index URLs

If you have a Google Index (search interface) for a drive:
- Enter the full URL
- Bot will use index instead of API for that drive

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| Name/ID empty | Missing input | Re-enter, cannot be blank |
| File write error | Permission issue | Check write permissions |
| Drive not accessible | Permissions | Ensure you have access to drive |

### Common Issues

**"Drive ID not found"**
- Verify you can access the drive in browser
- Check URL for correct ID format

**"Empty configuration"**
- Re-run script and add at least one drive

---

## Next Steps

| Goal | Next Action |
|------|--------------|
| Generate token | Run `gen_token_pickle` script |
| Add service accounts | Run `gen_sa_accounts` script |
| Test bot | Start bot and search a file |

---

## Related Scripts

- **gen_token_pickle** - Authenticate with Google Drive
- **gen_sa_accounts** - Create service accounts for Team Drives
- **add_to_team_drive** - Add service accounts to Team Drive