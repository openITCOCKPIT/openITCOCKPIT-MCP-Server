# Connecting a client

How a client reaches this server over HTTP or stdio, with working examples.

### HTTP (server runs as a service)

Clients send `Authorization: Bearer <MCP_AUTH_TOKEN>`. The comparison is
constant-time; a missing, malformed or wrong token gets HTTP `401`.

```json
{
  "url": "http://your-mcp-server:8000/mcp",
  "headers": { "Authorization": "Bearer your-mcp-auth-token" }
}
```

### stdio (client spawns the server)

No HTTP layer, so no `MCP_AUTH_TOKEN` is needed. Two ways to spawn it.

**From the image**, which needs nothing installed but Docker. This is what the
[MCP Registry](installation.md) entry describes, and the form to hand to someone
who just wants to connect a desktop client:

```json
{
  "command": "docker",
  "args": [
    "run", "-i", "--rm",
    "-e", "OITC_TRANSPORT=stdio",
    "-e", "OITC_APIKEY",
    "-e", "OITC_BASEURL",
    "openitcockpit/mcp-server:0.5.0"
  ],
  "env": {
    "OITC_APIKEY": "your-openitcockpit-api-key",
    "OITC_BASEURL": "https://openitcockpit.example.org"
  }
}
```

The `-e NAME` flags carry no value: Docker takes it from the environment the
client provides, so neither secret ends up in the process list.

**From an install**, once `pip install .` has put `oitc-mcp` on the path:

```json
{
  "command": "oitc-mcp",
  "args": ["--transport", "stdio"],
  "env": {
    "OITC_APIKEY": "your-openitcockpit-api-key",
    "OITC_BASEURL": "https://openitcockpit.example.org"
  }
}
```

> [!NOTE]
> Either way the server runs on the client's machine and holds the
> openITCOCKPIT API key there. The http transport keeps that key on one host
> you operate and gives clients a bearer token instead - prefer it when more
> than one person connects.
