# openITCOCKPIT MCP Server

<!--
The Docker Hub repository overview. Docker Hub has no way to read this from the
repo, so it has to be pasted into the "Repository overview" field by hand -
keep it short enough that doing so stays cheap, and leave the detail on GitHub.
-->

An [MCP](https://modelcontextprotocol.io) server that exposes an
[openITCOCKPIT](https://www.openitcockpit.io/) monitoring instance to an LLM
client: host and service status, log entries, downtimes, acknowledgements,
check history, software inventory and pending updates — plus optional,
off-by-default tools that change the monitoring configuration.

39 tools, 24 read-only and 15 write. **Requires openITCOCKPIT 5.6 or newer**;
one image serves every supported release.

## Tags

| Tag | |
|---|---|
| `0.1.0` | Immutable. **Pin this.** |
| `latest` | The newest release, whatever it is |

Still `0.x`: the tool set is settling, so a minor bump may break a client.

## Run

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="a-token-you-generate" \
  -e OITC_APIKEY="the-openITCOCKPIT-api-key" \
  -e OITC_BASEURL="https://openitcockpit.example.org" \
  openitcockpit/mcp-server:0.1.0
```

Point your client at `http://localhost:8000/mcp`, using `MCP_AUTH_TOKEN` as the
bearer token. No secret is baked into the image.

## Before you expose it

The two secrets have different jobs and the server refuses to start if they are
equal: `MCP_AUTH_TOKEN` is what clients present to this server, `OITC_APIKEY` is
what this server presents to openITCOCKPIT. Every client that passes the bearer
check acts as the one openITCOCKPIT user that key belongs to, so create it for a
dedicated, least-privilege user.

Write tools are not even registered unless `OITC_ENABLE_WRITE_TOOLS=true`. The
HTTP transport serves plain HTTP — terminate TLS at a reverse proxy or keep the
server on a trusted network. TLS verification *towards* openITCOCKPIT is on by
default; for a self-signed instance set `OITC_CA_BUNDLE` rather than turning it
off.

## Documentation

Full configuration, the tool reference, client setup, `stdio` transport and the
changelog:

**https://github.com/openITCOCKPIT/openITCOCKPIT-MCP-Server**
