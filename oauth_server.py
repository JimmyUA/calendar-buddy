# oauth_server.py
import logging
from flask import Flask, request, redirect, render_template_string

# Initialize config first to setup Firestore client
import config
import google_services as gs # Needs Firestore functions

# Configure logging for the Flask server
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Basic HTML templates for success/failure pages
SUCCESS_TEMPLATE = """
<!doctype html>
<html><head><title>Authentication Successful</title>
<style>body { font-family: sans-serif; padding: 20px; } .success { color: green; } </style></head>
<body><h1 class="success">Authentication Successful!</h1>
<p>You have successfully connected your Google Calendar.</p>
<p>You can now close this window and return to Telegram.</p>
</body></html>
"""

FAILURE_TEMPLATE = """
<!doctype html>
<html><head><title>Authentication Failed</title>
<style>body { font-family: sans-serif; padding: 20px; } .error { color: red; } </style></head>
<body><h1 class="error">Authentication Failed</h1>
<p>Something went wrong during the authentication process:</p>
<p><strong>{{ error_message }}</strong></p>
<p>Please try connecting again from the Telegram bot. If the problem persists, contact the bot administrator.</p>
</body></html>
"""

@app.route('/oauth2callback')
def oauth2callback():
    """Handles the redirect from Google OAuth using Firestore."""

    # Check if Firestore client is available (initialized in config)
    if config.FIRESTORE_DB is None:
        logger.error("OAuth callback received but Firestore is not available.")
        return render_template_string(FAILURE_TEMPLATE, error_message="Internal server error: Database connection failed."), 500

    state = request.args.get('state')
    code = request.args.get('code')
    error = request.args.get('error')
    scope = request.args.get('scope') # Get scopes granted by user

    logger.info(f"Received OAuth callback: state={state}, code={'[present]' if code else '[absent]'}, error={error}, scope={scope}")

    if error:
        logger.error(f"OAuth Error received: {error}")
        # Provide more specific error messages if possible
        error_msg = f"Google returned an error: {error}"
        if error == 'access_denied':
            error_msg = "You denied the permission request. Please try again and grant access if you want to connect your calendar."
        return render_template_string(FAILURE_TEMPLATE, error_message=error_msg), 400

    if not state or not code:
        logger.error("Missing state or code in OAuth callback.")
        return render_template_string(FAILURE_TEMPLATE, error_message="Missing state or authorization code from Google."), 400

    # Verify the state parameter using Firestore
    user_id = gs.verify_oauth_state(state)
    if not user_id:
        # Error logged within verify_oauth_state
        return render_template_string(FAILURE_TEMPLATE, error_message="Invalid or expired request token (state mismatch or DB error). Please try initiating the connection again from Telegram."), 400

    # Exchange code for credentials
    flow = gs.get_google_auth_flow()
    if not flow:
         logger.error("Failed to get OAuth flow object during callback.")
         return render_template_string(FAILURE_TEMPLATE, error_message="Internal server error: Could not create OAuth flow."), 500

    try:
        logger.info(f"Exchanging authorization code for tokens for user {user_id}...")
        # ---> Add Logging Here <---
        logger.debug(f"Using code: {code[:10]}...") # Log first few chars of code
        logger.debug(f"Flow Client ID: {flow.client_config.get('client_id', 'MISSING')}")
        logger.debug(f"Flow Redirect URI: {flow.redirect_uri}") # Check the URI the flow object has
        # Be CAREFUL logging secrets, even in debug. Avoid logging flow.client_config['client_secret']
        # ---> End Logging <---
        # Specify the redirect_uri again when fetching token
        flow.fetch_token(code=code)
        credentials = flow.credentials # Contains access and refresh tokens

        # Log granted scopes vs required scopes
        granted_scopes = set(credentials.scopes)
        required_scopes = set(config.GOOGLE_CALENDAR_SCOPES)
        if not required_scopes.issubset(granted_scopes):
             logger.warning(f"User {user_id} did not grant all required scopes. Granted: {granted_scopes}, Required: {required_scopes}")
             # Decide how to handle - fail or proceed with limited functionality?
             # For this bot, calendar read/write are essential, so fail.
             return render_template_string(FAILURE_TEMPLATE, error_message=f"Required permissions were not granted. Please ensure you approve access to Google Calendar (Read and Write)."), 400

        logger.info(f"Successfully obtained credentials for user {user_id}. Scopes: {granted_scopes}")

        # Store the credentials securely using Firestore function
        success = gs.store_user_credentials(user_id, credentials)
        if not success:
            # Handle potential Firestore write failure
            logger.error(f"Failed to store credentials in Firestore for user {user_id} during callback.")
            return render_template_string(FAILURE_TEMPLATE, error_message="Authentication succeeded but failed to save connection details. Please try again or contact support."), 500


        # Redirect user to a success page
        logger.info(f"OAuth flow completed successfully for user {user_id}.")
        return render_template_string(SUCCESS_TEMPLATE)

    except Exception as e:
        # Catch errors during token fetch or storage
        logger.error(f"Error exchanging code or storing credentials for user {user_id}: {e}", exc_info=True)
        # Provide a generic error message for security
        return render_template_string(FAILURE_TEMPLATE, error_message=f"An unexpected error occurred during authentication."), 500

if __name__ == '__main__':
    # Firestore client is initialized when config is imported.
    # Check if initialization failed (although config import might raise error earlier)
    if config.FIRESTORE_DB is None:
        logger.critical("Cannot start OAuth server: Firestore client failed initialization in config.")
    else:
        logger.info(f"Starting OAuth callback server on {config.WEB_SERVER_HOST}:{config.WEB_SERVER_PORT}")
        # Use waitress or gunicorn for production instead of Flask's dev server
        app.run(host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT, debug=False)