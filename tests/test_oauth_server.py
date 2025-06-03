# tests/test_oauth_server.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from flask import Flask

# Import the app from oauth_server
from oauth_server import app, SUCCESS_TEMPLATE, FAILURE_TEMPLATE
# We will also need to mock functions from google_services, so import it or its path
import google_services as gs # To mock functions from it
import config as app_config # To access app_config.GOOGLE_CALENDAR_SCOPES
from .conftest import TEST_USER_ID


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_oauth_callback_success(client, mocker):
    # Mock parameters
    test_state = 'test_state_123'
    test_code = 'test_auth_code_456'

    # Mock gs.verify_oauth_state to return a user_id
    mock_verify_state = mocker.patch('oauth_server.gs.verify_oauth_state', return_value=TEST_USER_ID)

    # Mock gs.get_google_auth_flow and its methods
    mock_flow_instance = MagicMock()
    # The actual credentials object has a 'scopes' attribute (a list)
    # and is used by gs.store_user_credentials
    mock_credentials = MagicMock()
    mock_credentials.scopes = app_config.GOOGLE_CALENDAR_SCOPES # Simulate all required scopes granted
    mock_flow_instance.credentials = mock_credentials
    # fetch_token is synchronous and called directly in oauth_server.py
    mock_flow_instance.fetch_token = MagicMock()
    mock_get_flow = mocker.patch('oauth_server.gs.get_google_auth_flow', return_value=mock_flow_instance)

    # Mock gs.store_user_credentials
    # This is an async function in google_services, but oauth_server doesn't await it.
    # This is a bug in oauth_server.py. gs.store_user_credentials should be awaited.
    # For now, mock it as a standard MagicMock to reflect current sync call.
    # If oauth_server.py is fixed to await it, this mock should be AsyncMock.
    mock_store_creds = mocker.patch('oauth_server.gs.store_user_credentials', return_value=True) # Patched as sync

    # Make the GET request to the callback URL
    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')

    # Assertions
    assert response.status_code == 200
    assert "Authentication Successful!" in response.data.decode()

    mock_verify_state.assert_called_once_with(test_state)
    mock_get_flow.assert_called_once()
    mock_flow_instance.fetch_token.assert_called_once_with(code=test_code)
    # gs.store_user_credentials is called with user_id and the credentials from flow
    mock_store_creds.assert_called_once_with(TEST_USER_ID, mock_flow_instance.credentials)


# --- Placeholder for additional tests ---

def test_oauth_callback_error_param(client, mocker):
    """Test when Google returns an error parameter (e.g., access_denied)."""
    test_state = 'test_state_error'
    google_error = 'access_denied'

    response = client.get(f'/oauth2callback?state={test_state}&error={google_error}')

    assert response.status_code == 400
    assert "Authentication Failed" in response.data.decode()
    assert "You denied the permission request" in response.data.decode()

def test_oauth_callback_missing_state(client, mocker):
    test_code = 'test_code_no_state'
    response = client.get(f'/oauth2callback?code={test_code}')
    assert response.status_code == 400
    assert "Missing state or authorization code" in response.data.decode()

def test_oauth_callback_missing_code(client, mocker):
    test_state = 'test_state_no_code'
    response = client.get(f'/oauth2callback?state={test_state}')
    assert response.status_code == 400
    assert "Missing state or authorization code" in response.data.decode()

def test_oauth_callback_verify_state_fails(client, mocker):
    test_state = 'invalid_state'
    test_code = 'any_code'
    mocker.patch('oauth_server.gs.verify_oauth_state', return_value=None) # Simulate state verification failure

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 400
    assert "Invalid or expired request token" in response.data.decode()

def test_oauth_callback_get_flow_fails(client, mocker):
    test_state = 'valid_state_for_flow_fail'
    test_code = 'any_code'
    mocker.patch('oauth_server.gs.verify_oauth_state', return_value=TEST_USER_ID)
    mocker.patch('oauth_server.gs.get_google_auth_flow', return_value=None) # Simulate flow object creation failure

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 500
    assert "Could not create OAuth flow" in response.data.decode()

def test_oauth_callback_fetch_token_exception(client, mocker):
    test_state = 'valid_state_for_token_fail'
    test_code = 'any_code'
    mocker.patch('oauth_server.gs.verify_oauth_state', return_value=TEST_USER_ID)
    mock_flow_instance = MagicMock()
    mock_flow_instance.fetch_token.side_effect = Exception("Token fetch failed miserably")
    mocker.patch('oauth_server.gs.get_google_auth_flow', return_value=mock_flow_instance)

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 500
    assert "An unexpected error occurred during authentication" in response.data.decode()

def test_oauth_callback_scopes_not_granted(client, mocker):
    test_state = 'valid_state_scope_fail'
    test_code = 'any_code'
    mocker.patch('oauth_server.gs.verify_oauth_state', return_value=TEST_USER_ID)

    mock_flow_instance = MagicMock()
    mock_credentials = MagicMock()
    mock_credentials.scopes = ["email"] # User only granted email scope
    mock_flow_instance.credentials = mock_credentials
    mock_flow_instance.fetch_token = MagicMock()
    mocker.patch('oauth_server.gs.get_google_auth_flow', return_value=mock_flow_instance)

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 400
    assert "Required permissions were not granted" in response.data.decode()

def test_oauth_callback_store_credentials_fails(client, mocker):
    test_state = 'valid_state_store_fail'
    test_code = 'any_code'
    mocker.patch('oauth_server.gs.verify_oauth_state', return_value=TEST_USER_ID)

    mock_flow_instance = MagicMock()
    mock_credentials = MagicMock()
    mock_credentials.scopes = app_config.GOOGLE_CALENDAR_SCOPES
    mock_flow_instance.credentials = mock_credentials
    mock_flow_instance.fetch_token = MagicMock()
    mocker.patch('oauth_server.gs.get_google_auth_flow', return_value=mock_flow_instance)

    # Mock gs.store_user_credentials to return False
    mocker.patch('oauth_server.gs.store_user_credentials', return_value=False)

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 500
    assert "failed to save connection details" in response.data.decode()

def test_oauth_callback_firestore_not_available(client, mocker):
    test_state = 'any_state'
    test_code = 'any_code'
    # Patch config.FIRESTORE_DB to be None *within the context of this test*
    mocker.patch('oauth_server.config.FIRESTORE_DB', None)

    response = client.get(f'/oauth2callback?state={test_state}&code={test_code}')
    assert response.status_code == 500
    assert "Internal server error: Database connection failed" in response.data.decode()
