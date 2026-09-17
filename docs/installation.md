# Installation

Docker, from source, and the MCP Registry.

### Docker

```bash
docker run -d -p 8000:8000 --env-file .env openitcockpit/mcp-server:0.4.0
```

**Which tag?** The tag is this server's own version. `0.4.0` never changes, so a
redeploy gives you exactly what you tested - pin that. `latest` is the only
other tag and it moves under you. The tag says nothing about your openITCOCKPIT
version; one image serves 5.6 and newer. See [Versioning](versioning.md).

Or with individual variables, for CI or a secret manager:

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="..." \
  -e OITC_APIKEY="..." \
  -e OITC_BASEURL="https://openitcockpit.example.org" \
  openitcockpit/mcp-server:0.4.0
```

No secret is baked into the image; configuration is read from the environment
at start-up.

**Or with Compose.** [`docker-compose.example.yml`](docker-compose.example.yml)
is a complete deployment of the published image - restart policy, health check,
and every setting inline in two blocks, required and optional. Copy it, fill in
the three required values, and:

```bash
docker compose -f docker-compose.example.yml up -d
```

The `docker-compose.yml` next to it is a different thing: it builds from this
repository and reads `.env`, which is what the [Quickstart](../README.md#quickstart) uses.

### From source

```bash
pip install .
cp .env.example .env
oitc-mcp
```

`oitc-mcp --help` lists the flags that override the configuration
(`--transport`, `--host`, `--port`, `--log-level`).

### MCP Registry

`server.json` in the repo root is this server's entry for the
[MCP Registry](https://registry.modelcontextprotocol.io), published with
`mcp-publisher publish`. The registry name is
`io.github.openITCOCKPIT/mcp-server`, and the Dockerfile carries the same
string as an `io.modelcontextprotocol.server.name` label - the registry reads
it off the published image as its only ownership proof for an OCI package, and
compares it case-sensitively.

Three values have to agree at release time: `MCP_VERSION`, the `version` in
`server.json`, and the image tag in its package `identifier`.
`tests/test_server_json.py` fails when they do not.
