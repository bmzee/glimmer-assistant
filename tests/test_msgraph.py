import json
import os
import stat
from unittest.mock import MagicMock

from assistant.tools.msgraph import GraphAuth, GraphClient, make_msgraph_tools
from assistant.tools.registry import RiskTier


class FakeAuth:
    def get_token(self):
        return "SECRET-TOKEN-VALUE"


class FakeHTTP:
    """Records requests; returns canned JSON."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.response


def by_name(tools):
    return {t.name: t for t in tools}


def test_client_adds_bearer_token():
    http = FakeHTTP({"value": []})
    client = GraphClient(FakeAuth(), http=http)
    client.get("/me/messages")
    assert http.calls[0]["headers"]["Authorization"] == "Bearer SECRET-TOKEN-VALUE"
    assert http.calls[0]["url"].startswith("https://graph.microsoft.com/v1.0")


def test_list_mail_is_untrusted_and_summarizes():
    response = {
        "value": [
            {
                "subject": "Q3 numbers",
                "from": {"emailAddress": {"address": "sarah@example.com"}},
                "receivedDateTime": "2026-08-22T09:00:00Z",
                "id": "AAA",
            }
        ]
    }
    tools = by_name(make_msgraph_tools(GraphClient(FakeAuth(), http=FakeHTTP(response))))
    tool = tools["m365_list_mail"]
    assert tool.untrusted is True
    out = tool.func({"count": 5})
    assert "sarah@example.com" in out
    assert "Q3 numbers" in out


def test_token_never_appears_in_tool_output():
    response = {"value": [{"subject": "s", "from": {"emailAddress": {"address": "a@b.c"}}, "id": "1"}]}
    tools = by_name(make_msgraph_tools(GraphClient(FakeAuth(), http=FakeHTTP(response))))
    out = tools["m365_list_mail"].func({"count": 1})
    assert "SECRET-TOKEN-VALUE" not in out  # credentials must never leak to the model


def test_send_mail_is_confirm_outbound_and_posts():
    http = FakeHTTP({})
    tools = by_name(make_msgraph_tools(GraphClient(FakeAuth(), http=http)))
    tool = tools["m365_send_mail"]
    assert tool.risk_tier == RiskTier.CONFIRM
    assert tool.outbound is True
    tool.func({"to": "a@b.com", "subject": "hi", "body": "there"})
    call = http.calls[0]
    assert call["method"] == "POST"
    assert "/me/sendMail" in call["url"]
    payload = json.loads(call["body"])
    assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "a@b.com"


def test_graph_errors_become_error_strings():
    class BoomHTTP:
        def __call__(self, method, url, headers, body=None):
            raise RuntimeError("401 Unauthorized")

    tools = by_name(make_msgraph_tools(GraphClient(FakeAuth(), http=BoomHTTP())))
    assert tools["m365_list_mail"].func({"count": 1}).startswith("ERROR:")


def test_get_token_uses_silent_when_account_cached():
    """Test that cached tokens are reused without re-auth."""
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = [{"home_account_id": "x"}]
    fake_app.acquire_token_silent.return_value = {"access_token": "TOK"}

    auth = GraphAuth("client-id", app=fake_app)
    token = auth.get_token()

    assert token == "TOK"
    fake_app.initiate_device_flow.assert_not_called()


def test_device_flow_prints_and_never_submits_credentials(capsys):
    """Test device-code flow prints URL/code for user to complete sign-in."""
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "message": "Go to https://example.com and enter ABC123"
    }
    fake_app.acquire_token_by_device_flow.return_value = {"access_token": "TOK2"}

    auth = GraphAuth("client-id", app=fake_app)
    token = auth.get_token()

    assert token == "TOK2"
    # Verify device code was printed to user
    captured = capsys.readouterr()
    assert "ABC123" in captured.out
    assert "Go to https://example.com" in captured.out
    # Verify only device-flow methods were used (no password submission)
    fake_app.acquire_token_silent.assert_not_called()


def test_auth_failure_raises_clear_error():
    """Test that auth failures raise RuntimeError with description."""
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "message": "Sign in"
    }
    fake_app.acquire_token_by_device_flow.return_value = {
        "error_description": "The user denied the request"
    }

    auth = GraphAuth("client-id", app=fake_app)
    try:
        auth.get_token()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "auth failed" in str(e)


def test_stale_cache_file_perms_remediated_on_load(tmp_path):
    """A pre-fix 0644 cache file must be tightened to 0600 the next time it loads."""
    import msal

    cache_path = tmp_path / "m365-token.json"
    cache_path.write_text(msal.SerializableTokenCache().serialize())
    os.chmod(cache_path, 0o644)

    auth = GraphAuth("client-id", cache_path=cache_path)
    auth._application()  # loads the existing (insecure) cache file

    mode = stat.S_IMODE(os.stat(cache_path).st_mode)
    assert mode == 0o600


def test_read_mail_url_encodes_message_id():
    """Test that message_id is URL-encoded to prevent injection."""
    http = FakeHTTP({"subject": "test", "from": {"emailAddress": {"address": "a@b.c"}}, "body": {"content": ""}})
    tools = by_name(make_msgraph_tools(GraphClient(FakeAuth(), http=http)))

    # Message ID with special characters that need encoding
    tools["m365_read_mail"].func({"message_id": "msg/123?foo=bar"})

    # Verify the URL has the encoded form
    call = http.calls[0]
    # The message_id should be percent-encoded: msg%2F123%3Ffoo%3Dbar
    assert "msg%2F123%3Ffoo%3Dbar" in call["url"]
    assert "msg/123?foo=bar" not in call["url"]
