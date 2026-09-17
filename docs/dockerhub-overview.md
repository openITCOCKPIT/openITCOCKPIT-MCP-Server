# openITCOCKPIT MCP Server

<!--
The Docker Hub repository overview. Docker Hub has no way to read this from the
repo, so it has to be pasted into the "Repository overview" field by hand. Keep
it short and free of anything that dates: no tool counts, no version numbers.
The detail belongs on GitHub, which is one link away.
-->

An [MCP](https://modelcontextprotocol.io) server that puts an
[openITCOCKPIT](https://www.openitcockpit.io/) monitoring instance in front of
an LLM client: what is broken and why, what someone already handles, what
changed - and, off by default, the tools that act on it.

> **Use at your own risk.** This server lets a language model read and, with
> write tools enabled, change your monitoring configuration. Review what it
> proposes before you approve it, and start with read-only access. Provided
> "as is", without warranty or liability of any kind (MIT License).

Requires openITCOCKPIT 5.6 or newer. One image serves every supported release.

## Run

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="a-token-you-generate" \
  -e OITC_APIKEY="the-openITCOCKPIT-api-key" \
  -e OITC_BASEURL="https://openitcockpit.example.org" \
  openitcockpit/mcp-server:latest
```

Point your client at `http://localhost:8000/mcp`, using `MCP_AUTH_TOKEN` as the
bearer token. No secret is baked into the image.

Pin the exact version tag you tested rather than `latest`. What a version number
promises, and when a client has to be adjusted, is on GitHub under Versioning.

## Before you expose it

The two secrets have different jobs and the server refuses to start if they are
equal: `MCP_AUTH_TOKEN` is what clients present to this server, `OITC_APIKEY` is
what this server presents to openITCOCKPIT. Every client that passes the bearer
check acts as the one openITCOCKPIT user that key belongs to, so create it for a
dedicated, least-privilege user.

Write tools are not registered at all unless `OITC_ENABLE_WRITE_TOOLS=true`. The
HTTP transport serves plain HTTP, so terminate TLS at a reverse proxy or keep the
server on a trusted network. TLS verification towards openITCOCKPIT is on by
default; for a self-signed instance set `OITC_CA_BUNDLE` rather than turning it
off.

## Everything else

Configuration, the tool reference, client setup, `stdio` transport, toolsets and
the changelog:

**https://github.com/openITCOCKPIT/openITCOCKPIT-MCP-Server**
