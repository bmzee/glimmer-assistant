import json

from assistant.tools.msgraph import GraphClient, make_msgraph_tools
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
