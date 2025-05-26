# Calendar-Buddy

This project is a Telegram bot that uses a Large Language Model (LLM) agent to help you manage your Google Calendar. You can interact with the bot using natural language to create, delete, and view calendar events.

## Features

- **Natural Language Understanding:** Interact with your calendar by typing commands in plain English (e.g., "Schedule a meeting for tomorrow at 2pm," "What's on my agenda for Friday?").
- **Google Calendar Integration:** Securely connects to your Google Calendar to manage events.
- **Event Management:**
    - Create new calendar events.
    - Delete existing calendar events.
    - Update existing events (e.g., reschedule, change title/description, update location).
    - View your agenda for specific days, weeks, or periods.
- **Timezone Support:** Allows users to set their local timezone for accurate event scheduling and display.
- **Conversation History:** Remembers the context of your conversation for a more natural interaction flow.
- **User-Friendly Commands:** Provides simple slash commands for common actions like:
    - `/connect_calendar`: Link your Google Calendar.
    - `/disconnect_calendar`: Remove Google Calendar integration.
    - `/my_status`: Check the current connection status.
    - `/set_timezone`: Configure your local timezone.
    - `/help`: Get assistance and a list of commands.

## Setup and Installation

Follow these steps to set up and run the Telegram Calendar Assistant Bot:

### 1. Prerequisites

- **Python:** Version 3.9 or higher recommended.
- **Google Cloud Project:** You'll need a Google Cloud Platform (GCP) project with the Google Calendar API enabled.
- **Telegram Bot Token:** A token for your Telegram bot, obtainable from BotFather.
- **Git:** For cloning the repository.

### 2. Clone the Repository

```bash
git clone <repository_url> # Replace <repository_url> with the actual URL
cd <repository_directory_name>
```

### 3. Create a Virtual Environment

It's highly recommended to use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

### 4. Install Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

The bot uses environment variables for configuration. Create a `.env` file in the root of the project or set these variables in your environment:

```env
TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"

# Google OAuth Configuration
GOOGLE_CLIENT_SECRETS_FILE="path/to/your/client_secret.json"
# OR directly paste the content of the client_secret.json file:
# GOOGLE_CLIENT_SECRETS_CONTENT='{"web":{"client_id":"...", "project_id":"...", ...}}'

OAUTH_REDIRECT_URI="http://localhost:5000/oauth2callback" # Or your deployed callback URL

# Google API Key (for LLM services like Gemini)
GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"

# Health Check Server Port (Optional, defaults to 8080 if not set by Cloud Run)
# PORT="8080"
```

**Obtaining Google Credentials:**

- **`GOOGLE_CLIENT_SECRETS_FILE` / `GOOGLE_CLIENT_SECRETS_CONTENT`:**
    1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
    2. Select your GCP project.
    3. Navigate to "APIs & Services" > "Credentials".
    4. Click "+ CREATE CREDENTIALS" and choose "OAuth client ID".
    5. Select "Web application" as the application type.
    6. Under "Authorized redirect URIs", add the `OAUTH_REDIRECT_URI` you will use (e.g., `http://localhost:5000/oauth2callback` for local development).
    7. Click "Create". Download the JSON file. You can either provide the path to this file in `GOOGLE_CLIENT_SECRETS_FILE` or paste its content directly into `GOOGLE_CLIENT_SECRETS_CONTENT`.
- **`GOOGLE_API_KEY`:**
    1. In the Google Cloud Console, navigate to "APIs & Services" > "Credentials".
    2. Click "+ CREATE CREDENTIALS" and choose "API key".
    3. Secure this API key appropriately. You might need to enable the "Generative Language API" or similar for your project if you are using Gemini.
- **`TELEGRAM_BOT_TOKEN`:**
    1. Open Telegram and search for "BotFather".
    2. Start a chat with BotFather and use the `/newbot` command.
    3. Follow the instructions to create your bot and receive the token.

### 6. Initialize Firestore

This bot uses Firestore for storing user tokens and preferences.
1. Ensure you have a Google Cloud Project (as mentioned in Prerequisites).
2. In the Google Cloud Console, navigate to "Firestore Database" (or "Databases" and select Firestore).
3. Create a Firestore database in Native mode or Datastore mode. Choose a location.
4. **Enable the Firestore API** in the "APIs & Services" > "Library" section of your GCP project if it's not already enabled.
5. **Authentication:** For local development, ensure you are authenticated with Google Cloud. The easiest way is often to use the Google Cloud CLI:
   ```bash
   gcloud auth application-default login
   ```
   This command will store credentials that the Firestore client library can automatically pick up. For deployed environments (like Cloud Run), service accounts with appropriate Firestore permissions are recommended.

## Running the Bot

The application consists of two main components that need to be run separately:

1.  **OAuth Server:** This server handles the Google OAuth2 flow, allowing users to authorize the bot to access their calendars.
2.  **Telegram Bot:** This is the main bot application that interacts with users on Telegram.

**Steps to Run:**

1.  **Start the OAuth Server:**
    Open a terminal, navigate to the project directory, and run:
    ```bash
    python oauth_server.py
    ```
    By default, this server runs on `http://localhost:5000`. Ensure your `OAUTH_REDIRECT_URI` environment variable matches this address (specifically the `/oauth2callback` endpoint).

2.  **Start the Telegram Bot:**
    Open another terminal, navigate to the project directory, and run:
    ```bash
    python bot.py
    ```
    The bot will start polling for updates from Telegram.

**Important:**
*   The `oauth_server.py` must be running and accessible at the `OAUTH_REDIRECT_URI` when users attempt to connect their Google Calendar via the `/connect_calendar` command.
*   For production deployments, you would typically run these as separate services, ensuring the OAuth server's redirect URI is correctly configured and publicly accessible. The bot also includes a basic health check endpoint (`/`) that can be used by services like Cloud Run.

## Usage

Once the bot is running and you've started a chat with it on Telegram:

1.  **Start Interaction:**
    - You can usually just start typing natural language commands.
    - Alternatively, send `/start` to get a welcome message.

2.  **Connect Your Google Calendar:**
    - Send the `/connect_calendar` command.
    - The bot will provide a link to authorize Google Calendar access. Click the link and follow the Google authentication flow.
    - Upon successful authorization, you'll be redirected to the `OAUTH_REDIRECT_URI` (which confirms the connection to the `oauth_server.py`), and the bot will notify you.

3.  **Set Your Timezone:**
    - Send the `/set_timezone` command (e.g., `/set_timezone America/New_York`).
    - The bot will ask you to provide your timezone in IANA format (e.g., `America/New_York`, `Europe/London`). This is important for accurately scheduling and displaying event times.
    - You can find a list of IANA timezones [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

4.  **Interact with Your Calendar:**
    - **Natural Language:**
        - "What's on my calendar for tomorrow?"
        - "Show me my events for next Monday."
        - "Schedule a meeting with John for Wednesday at 3 PM about the project."
        - "Create an event: Dentist appointment next Tuesday at 10 AM."
        - "Delete the budget review meeting on Friday."
        - "Cancel my 1-on-1 with Sarah."
        - "Reschedule my 10am meeting to 11am tomorrow."
        - "Change the title of my 'Project Review' event to 'Final Project Review'."
    - The bot will use its LLM agent to understand your request and may ask for confirmation before creating, updating, or deleting events.

5.  **Available Slash Commands:**
    - `/start`: Displays the welcome message.
    - `/help`: Shows the help message with command list and usage examples.
    - `/connect_calendar`: Initiates the Google Calendar connection process.
    - `/disconnect_calendar`: Revokes the bot's access to your Google Calendar and deletes your stored credentials.
    - `/my_status`: Checks if your Google Calendar is currently connected and if the credentials are valid.
    - `/set_timezone`: Allows you to set or update your local timezone.
    - `/summary [time period]`: Explicitly asks for a summary of events for a given period (e.g., `/summary today`, `/summary next week`).

## Project Structure

Here's a brief overview of the key files and directories:

```
.
├── .dockerignore           # Specifies intentionally untracked files for Docker
├── Dockerfile.bot          # Dockerfile for the main bot application
├── Dockerfile.oauth        # Dockerfile for the OAuth server
├── bot.py                  # Main entry point for the Telegram bot application
├── config.py               # Handles configuration, environment variables, and initializes services like Firestore
├── google_services.py      # Contains functions for interacting with Google APIs (Calendar, OAuth)
├── handler/                # Message formatting utilities
│   ├── __init__.py
│   └── message_formatter.py
├── handlers.py             # Defines handlers for Telegram commands, messages, and callbacks
├── llm/                    # Logic related to the Large Language Model (LLM) agent
│   ├── __init__.py
│   ├── agent.py            # Initializes and configures the LangChain agent
│   ├── agent_tools.py      # Defines tools the agent can use (e.g., calendar actions)
│   ├── llm_service.py      # Wrapper for LLM API calls (e.g., chat completion, parsing)
│   └── tools/              # Specific tool implementations for the agent
│       ├── __init__.py
│       ├── calendar_base.py
│       ├── create_calendar.py
│       ├── delete_calendar.py
│       ├── formatting.py
│       ├── get_current_time_tool.py
│       ├── read_calendar.py
│       └── search_calendar.py
├── main.py                 # (Seems to be a sample/placeholder file)
├── oauth_server.py         # Flask server to handle the Google OAuth2 callback
├── requirements-dev.txt    # Python dependencies for development
├── requirements.txt        # Python dependencies for the project
├── tests/                  # Unit and integration tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agent_tools.py
│   ├── test_handlers.py
│   └── test_utils.py
├── time_util.py            # Utility functions for time and date formatting
└── utils.py                # General utility functions
```

## Contributing

Contributions are welcome! If you'd like to improve the bot or add new features:

1.  **Fork the repository.**
2.  **Create a new branch** for your feature or bug fix (e.g., `feature/new-command` or `fix/calendar-bug`).
3.  **Make your changes.**
4.  **Add tests** for your changes, if applicable.
5.  **Ensure your code lints** and follows the project's coding style (if defined).
6.  **Submit a pull request** with a clear description of your changes.

## License

This project is currently unlicensed. You can add a license file (e.g., `LICENSE.md`) and update this section if you choose to license it. Common choices include the [MIT License](https://opensource.org/licenses/MIT) or the [Apache License 2.0](https://opensource.org/licenses/Apache-2.0).
