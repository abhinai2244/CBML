# Generate Telegram Pyrogram Session

> Creates a Pyrogram session string for Telegram user authentication.

## Quick Info

- **Purpose**: Generate Telegram user session (not bot)
- **Output**: Session sent to your Telegram Saved Messages
- **Required**: Telegram API credentials from my.telegram.org

---

## Which User Are You?

- **Newbie**: Start with "Step-by-Step for Beginners" below
- **Pro**: Jump to "CLI Reference" for advanced options

---

## Getting Started

### Prerequisites

1. **Telegram Account** - You need an active Telegram account
2. **API Credentials** from https://my.telegram.org/apps:
   - API ID
   - API Hash
3. **Python dependencies**:
   ```bash
   pip install pyrogram tgcrypto
   ```

---

## For Newbies (Step-by-Step)

### Step 1: Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Login with your phone number
3. Click **Create application**
4. Copy your:
   - **App api_id** (number)
   - **App api_hash** (32-character string)

### Step 2: Run the Script

```bash
cd gen_scripts/gen_pyro_session
python script.py
```

### Step 3: Enter Your Credentials

When prompted, enter:
- **API KEY**: `12345678:AbCdEfGhIjKlMnOpQrStUvWxY`
- **API HASH**: Your 32-character hash
- **Phone**: Your number with country code (e.g., +91XXXXXXXXXX)

### Step 4: Verify Authentication

1. Check Telegram for a login code
2. Enter the code when prompted
3. Wait for session generation

### What Happens

1. Pyrogram client connects to Telegram
2. Session string is generated
3. Session is sent to your **Saved Messages** in Telegram
4. You copy the session string for bot configuration

### After Completion

- ✅ Copy session string from Telegram Saved Messages
- ✅ Paste in your bot's configuration
- ✅ Session works immediately

---

## For Pro Users

### CLI Reference

This script uses interactive prompts. No CLI flags available.

| Behavior | Description |
|----------|-------------|
| Validation | API key must contain colon, API hash must be 32 chars |
| Phone format | Must include country code (+1, +91, etc.) |
| Session storage | In-memory only, not saved to disk |
| Device info | Custom app version and device model |

### Workflow Examples

```bash
# Standard interactive run
cd gen_scripts/gen_pyro_session
python script.py

# After getting session, use in bot config:
pyrogram_session = "your_session_string_here"
```

### Session Format

The generated session is a Pyrogram v2 session string:
```
AQABB...
```

This string contains encrypted credentials for your Telegram account.

### Security Notes

- ⚠️ **Never share your session string**
- ⚠️ Anyone with this string can access your Telegram account
- ⚠️ Store securely, never commit to version control

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid API key format` | Wrong format | Use format: `12345678:AbCdEfGh...` |
| `API HASH must be 32 characters` | Wrong length | Copy exact 32 chars from my.telegram.org |
| `Invalid phone format` | Missing country code | Include + and country code |
| `Pyrogram not installed` | Missing dependencies | `pip install pyrogram tgcrypto` |

### Common Issues

**"Authentication failed"**
- Verify API ID and HASH are correct
- Check you can receive Telegram messages
- Ensure phone number includes country code

**"Session not sent to Saved Messages"**
- Check your Telegram for new messages
- The script sends to your own account ("me")

---

## Next Steps

| Goal | Next Action |
|------|--------------|
| Configure bot | Paste session in bot config |
| Add more accounts | Run script again with different phone |
| Test bot | Start the bot and send /start |

---

## Related Scripts

- **driveid** - Configure drives the bot can search
- **gen_sa_accounts** - Set up Google Drive access