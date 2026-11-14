"""
tests/test_n8n_workflow.py  –  D-085
Every call the triage workflow makes to the KnowOps API (all routes but /health and /auth/login need a token)
must either be the login itself or send `Authorization: Bearer`, and the nodes must form one connected chain.
"""

import json
from pathlib import Path

WORKFLOW = json.loads((Path(__file__).resolve().parent.parent / "n8n" / "incident_triage_workflow.json").read_text(encoding="utf-8"))


def _api_nodes():
    return [n for n in WORKFLOW["nodes"] if "localhost:8000" in n["parameters"].get("url", "")]


def test_every_api_call_is_the_login_or_sends_a_bearer_token():
    assert len(_api_nodes()) == 3
    for node in _api_nodes():
        if node["parameters"]["url"].endswith("/auth/login"):
            continue
        headers = node["parameters"]["headerParameters"]["parameters"]
        assert any(h["name"] == "Authorization" and h["value"].startswith("=Bearer ") for h in headers), node["name"]


def test_login_reads_credentials_from_n8n_env_not_the_file():
    login = next(n for n in _api_nodes() if n["parameters"]["url"].endswith("/auth/login"))
    values = [p["value"] for p in login["parameters"]["bodyParameters"]["parameters"]]
    assert values == ["={{ $env.KNOWOPS_USERNAME }}", "={{ $env.KNOWOPS_PASSWORD }}"]


def test_nodes_form_one_chain_from_the_webhook_to_slack():
    conn = WORKFLOW["connections"]
    name, order = "Incoming Alert Webhook", ["Incoming Alert Webhook"]
    while name in conn:
        name = conn[name]["main"][0][0]["node"]
        order.append(name)
    assert order == ["Incoming Alert Webhook", "Log In to KnowOps", "Create Incident Ticket",
                     "Autonomous Agent Triage", "Notify On-Call Channel"]
    assert set(order) == {n["name"] for n in WORKFLOW["nodes"]}
