# Telegram Verification & Key Distribution Bot

A Telegram bot that verifies users through channel subscription and distributes keys with a cooldown system.

## Features

- **Channel Verification**: Users must join specified channels before claiming keys
- **Key Distribution**: Automated key assignment with customizable duration
- **Cooldown System**: Prevents users from claiming keys too frequently (default 48 hours)
- **Admin Panel**: Manage keys, channels, and settings
- **Web Server**: HTTP server to keep the bot alive on hosting platforms

## Setup

### Prerequisites

- Python 3.11+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Your Telegram User ID (can get from [@userinfobot](https://t.me/userinfobot))

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env`:
   ```
   BOT_TOKEN=your_bot_token_here
   ADMIN_ID=your_telegram_user_id
   PORT=5000
   ```

3. Run the bot:
   ```bash
   python verify_key_bot.py
   ```

## Admin Commands

Use `/admin` in Telegram to access the admin panel:

- **Add Keys**: Add new keys for distribution
- **View Stats**: Check unused/used keys and user count
- **Add Channel**: Add a required channel for verification
- **Remove Channel**: Remove a channel from requirements
- **List Channels**: View all configured channels
- **Set Cooldown**: Change the hours between key claims

### Adding Keys

Keys are added in this format (one per line):
```
key_text | duration_days | optional_name | optional_link
```

Example:
```
ABC123XYZ | 30 | Premium Key | https://example.com
DEF456UVW | 7
```

## User Flow

1. User starts the bot with `/start`
2. User joins all required channels
3. User clicks "✅ Verify" to confirm subscription
4. User clicks "▶️ Start" to claim a key
5. Bot assigns the next available key with expiration date

## Database

The bot uses SQLite with the following tables:
- `channels` - Required channels for verification
- `users` - User records and verification status
- `keys` - Available and used keys
- `sales` - Key assignment history
- `settings` - Bot configuration

## Web Server

The bot includes an HTTP server on port 5000 that responds to health checks, useful for platforms like Render or Replit that require an active web service.

## License

This project is provided as-is for educational and personal use.
