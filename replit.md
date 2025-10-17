# Telegram Key Distribution Bot

## Project Overview
This is a Telegram bot that verifies users through channel subscriptions and distributes keys with a built-in cooldown system. The bot includes a web server wrapper to keep it alive on hosting platforms.

## Architecture
- **Language**: Python 3.11
- **Framework**: aiogram 2.25.1 (Telegram bot framework)
- **Database**: SQLite (aiosqlite)
- **Web Server**: aiohttp
- **Dependencies**: python-dotenv for environment management

## Project Structure
```
.
├── verify_key_bot.py    # Main bot application
├── requirements.txt     # Python dependencies
├── .env                 # Environment configuration (not in git)
├── .env.example        # Example environment file
├── Procfile            # Process configuration
└── bot_data.db         # SQLite database (created on first run)
```

## Core Features
1. **User Verification**: Users must join configured Telegram channels before claiming keys
2. **Key Management**: Admin can add/manage keys with duration and metadata
3. **Cooldown System**: Configurable cooldown period between key claims (default 48 hours)
4. **Admin Panel**: Full admin interface via Telegram commands
5. **Web Server**: HTTP endpoint on port 5000 for health checks

## Configuration
The bot requires these environment variables:
- `BOT_TOKEN`: Telegram Bot API token
- `ADMIN_ID`: Telegram user ID of the administrator
- `PORT`: Web server port (default: 5000)

Current configuration is stored in `.env` file.

## Database Schema
- `channels`: Required channels for verification
- `users`: User records with verification status
- `keys`: Available and assigned keys
- `sales`: Key assignment history
- `settings`: Bot configuration settings

## Recent Changes
- **2025-10-17**: Initial Replit setup & Feature Enhancements
  - Installed Python 3.11 and all dependencies
  - Completed the bot implementation (was partially incomplete)
  - Added missing callback handlers and admin functionality
  - Configured workflow to run bot server on port 5000
  - Created .gitignore for Python project
  - Added README and documentation
  
- **2025-10-17**: Enhanced Features Update
  - ✅ Improved channel verification with bot admin check
  - ✅ Enhanced all messages with emojis and better formatting
  - ✅ Added custom key message feature in admin panel
  - ✅ Implemented MarkdownV2 with proper escaping for safety
  - ✅ Added support for variables in custom messages: {key}, {days}, {user}
  - ✅ Admin username support (@tgshaitaan) added alongside ID

## Running the Bot
The bot is configured to run automatically via the "Bot Server" workflow. It:
1. Initializes the SQLite database on first run
2. Starts the Telegram bot polling
3. Launches HTTP server on port 5000

## Admin Usage
1. Start bot with `/admin` command in Telegram
2. Use inline keyboard to:
   - 🔑 Add keys (format: `key | duration_days | name | link`)
   - 📊 View statistics
   - 📢 Add/Remove channels
   - 📋 List configured channels
   - ⏰ Configure cooldown period
   - 💬 Customize key message template

### Custom Key Message
Admin can customize the message sent when users receive keys:
- Use `{key}` for the key text
- Use `{days}` for duration in days
- Use `{user}` for user's first name
- Supports Markdown formatting (**, *, `, etc.)

## User Flow
1. `/start` - Begin interaction
2. Join required channels
3. Click "✅ Verify" 
4. Click "▶️ Start" to claim key
5. Receive key with expiration date
