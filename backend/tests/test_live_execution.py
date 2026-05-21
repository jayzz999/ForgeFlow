import pytest
from unittest.mock import patch, MagicMock
from backend.main import _execute_live_connector_step

@pytest.fixture
def mock_urlopen():
    with patch("backend.main.urlopen") as mock:
        yield mock

@pytest.fixture
def mock_db():
    with patch("backend.main._platform_db") as mock:
        yield mock

def test_slack_ok_false_is_treated_as_failure(mock_urlopen, mock_db):
    # Setup mock response for ok: false
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok": false, "error": "invalid_auth"}'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    spec = {"id": "spec-123"}
    step = {
        "id": "step-1",
        "connector_id": "slack.post_message",
        "approval_required": False
    }
    inputs = {"channel": "#test", "text": "hello"}

    with patch("backend.main._secret_for_service", return_value="fake-token"):
        status, output, error = _execute_live_connector_step(spec, step, inputs)

    assert status == "failed"
    assert output["status_code"] == 200
    assert output["response"]["ok"] is False
    assert error == "invalid_auth"

def test_slack_ok_true_is_treated_as_success(mock_urlopen, mock_db):
    # Setup mock response for ok: true
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok": true, "channel": "C123"}'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    spec = {"id": "spec-123"}
    step = {
        "id": "step-1",
        "connector_id": "slack.post_message",
        "approval_required": False
    }
    inputs = {"channel": "#test", "text": "hello"}

    with patch("backend.main._secret_for_service", return_value="fake-token"):
        status, output, error = _execute_live_connector_step(spec, step, inputs)

    assert status == "succeeded"
    assert output["status_code"] == 200
    assert output["response"]["ok"] is True
    assert error is None
