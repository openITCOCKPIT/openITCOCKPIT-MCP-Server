# Configuration

Every setting the server reads, and which secret goes where.

Clients present `MCP_AUTH_TOKEN` to the server. What the server presents to
openITCOCKPIT depends on `OITC_AUTH_MODE`:

| Mode | The server acts as | Needs |
|---|---|---|
| `static` *(default)* | the one user of `OITC_APIKEY` | `OITC_APIKEY`, which must differ from `MCP_AUTH_TOKEN` |
| `delegated` *(preview)* | the user each request carries a token for | no API key; the http transport; an openITCOCKPIT with user tokens, see [compatibility](versioning.md) |

| Secret | Who presents it to whom |
|---|---|
| `MCP_AUTH_TOKEN` | **Clients → this server.** A random token you generate. |
| `OITC_APIKEY` | **This server → openITCOCKPIT**, static mode. The API key of a dedicated, least-privilege openITCOCKPIT user. |
| `X-OITC-User-Token` header | **Client → this server → openITCOCKPIT**, delegated mode. A short-lived token openITCOCKPIT issued for one user. |

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # generate MCP_AUTH_TOKEN
```

Copy `.env.example` to `.env` and fill it in. Precedence, highest first:
**CLI flags → environment variables → `.env` → defaults**. `.env` is gitignored
and must never be committed.

| Setting | Env var | Default |
|---|---|---|
| Client bearer token | `MCP_AUTH_TOKEN` | *(required for http)* |
| Whom the server acts as, `static` or `delegated` | `OITC_AUTH_MODE` | `static` |
| openITCOCKPIT API key | `OITC_APIKEY` | *(required in static mode, must be unset in delegated)* |
| openITCOCKPIT base URL | `OITC_BASEURL` | *(required)* |
| Verify the instance's TLS certificate | `OITC_VERIFY_TLS` | `true` |
| CA bundle for a self-signed instance | `OITC_CA_BUNDLE` | *(unset)* |
| Request timeout, seconds | `OITC_TIMEOUT_SECONDS` | `20` |
| Register the write tools | `OITC_ENABLE_WRITE_TOOLS` | `false` |
| Limit the instance to named toolsets, see [Toolsets](toolsets.md) | `OITC_TOOLSETS` | `all` |
| A toolsets file of your own | `OITC_TOOLSETS_FILE` | `./toolsets.toml`, else the one shipped |
| Cache scope-validation lookups | `OITC_SCOPE_CACHE_ENABLED` | `true` |
| Scope cache TTL, seconds | `OITC_SCOPE_CACHE_TTL_SECONDS` | `30` |
| Summarise the text half of a result | `OITC_COMPACT_CONTENT` | `false` |
| Transport, `http` or `stdio` | `OITC_TRANSPORT` | `http` |
| Bind address / port (http) | `OITC_HOST` / `OITC_PORT` | `0.0.0.0` / `8000` |
| Log level | `OITC_LOG_LEVEL` | `INFO` |
| Print the start-up banner | `OITC_SHOW_BANNER` | `true` |
