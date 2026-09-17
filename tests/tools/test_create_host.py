"""Creating a host, with and without the openITCOCKPIT agent in pull mode."""

from __future__ import annotations

import json
import re

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"


class Instance:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def __call__(self, request):
        path = request.url.split("?")[0].removeprefix(BASE_URL)
        if request.method == "POST":
            self.posts.append((path, json.loads(request.body)))
            return 200, {}, json.dumps({"id": 42})
        if path.startswith("/containers/byString"):
            return 200, {}, json.dumps({"containers": [{"key": 1, "value": "/root"}]})
        if "loadElementsByContainerId" in path or "loadContainers" in path:
            return (
                200,
                {},
                json.dumps(
                    {
                        "hosttemplates": [
                            {"key": 1, "value": "default host"},
                            {"key": 3, "value": "openITCOCKPIT Agent - Pull"},
                        ],
                        "servicetemplates": [],
                        "timeperiods": [],
                        "checkperiods": [],
                        "contacts": [],
                        "contactgroups": [],
                        "hostgroups": [],
                        "servicegroups": [],
                        "satellites": [],
                        "sharingContainers": [],
                        "exporters": [],
                        "slas": [],
                        "existingServices": [],
                        "isSlaHost": False,
                        "containers": [{"key": 1, "value": "/root"}],
                    }
                ),
            )
        return 200, {}, json.dumps({})


@pytest.fixture
def instance(settings):
    fake = Instance()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for method in (responses.GET, responses.POST):
            mock.add_callback(method, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
        mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("create_host", arguments)).structured_content


async def test_a_host_without_an_agent_port_is_one_request(instance):
    mcp, fake = instance
    result = await call(mcp, name="web01", address="10.0.0.1")

    assert [path for path, _ in fake.posts] == ["/hosts/add.json"]
    assert result["hosttemplate_name"] == "default host"
    assert "agentconfigId" not in result


async def test_an_agent_port_also_sets_up_the_connection_and_picks_the_agent_template(instance):
    mcp, fake = instance
    result = await call(mcp, name="web02", address="10.0.0.2", agent_pull_port=3333, agent_pull_user="probe", agent_pull_password="s3cret")

    assert [path for path, _ in fake.posts] == ["/hosts/add.json", "/agentconnector/config.json"]
    assert result["hosttemplate_name"] == "openITCOCKPIT Agent - Pull"
    assert result["agentconfigId"] == 42
    config = fake.posts[1][1]["config"]
    assert config["int"]["bind_port"] == 3333
    assert config["bool"]["enable_push_mode"] is False
    assert config["bool"]["use_http_basic_auth"] is True
    assert config["string"]["username"] == "probe"


async def test_a_template_the_caller_names_is_kept_even_with_an_agent_port(instance):
    mcp, _ = instance
    result = await call(mcp, name="web03", address="10.0.0.3", hosttemplate_name="default host", agent_pull_port=3333)

    assert result["hosttemplate_name"] == "default host"
