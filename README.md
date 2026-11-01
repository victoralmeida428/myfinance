# myfinance

## Multi-account bot

The Telegram bot can serve several people from the same bot token. Each account
has its own Telegram user ID, Pluggy credentials, any number of Pluggy items and
its own SQLite database.

1. Copy the example and fill in the real account data:

   ```sh
   cp accounts.example.toml accounts.toml
   chmod 600 accounts.toml
   ```

2. Keep credentials in `.env`. Accounts without explicit `*_env` fields read
   `ACCOUNT_<ID>_PLUGGY_CLIENT_ID` and `ACCOUNT_<ID>_PLUGGY_CLIENT_SECRET`.

3. `accounts.toml` and `.env` are git-ignored and never go into the Docker
   image. The bot mounts `accounts.toml` read-only from the host.

4. Start the bot with `make run` locally or `make up` / `make deploy` in Docker.
   The bot refuses to start when `accounts.toml` is missing; `make up` and
   `make deploy` also check for the file before starting.
