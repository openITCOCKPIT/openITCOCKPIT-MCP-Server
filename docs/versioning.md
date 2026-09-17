# Versioning and compatibility

How versions are numbered and which openITCOCKPIT releases work.

The image tag is this server's version, from `MCP_VERSION`. Two tags per
release, and no others:

| Image tag | Mutable? | Use for |
|---|---|---|
| `0.4.0` | no | **Pin this.** Exactly this build. |
| `latest` | yes | The newest release, whatever it is |

Semver: patch for fixes, minor for added tools, major for anything that breaks
a client. **But this is still `0.x`** - the tool set is settling, so a minor
bump may break one too. Pin the exact version and read the
[CHANGELOG](../CHANGELOG.md) before you move.

### Compatibility

**openITCOCKPIT 5.6 or newer** - one image serves every supported release.

Every tool was exercised against live instances on the 5.6 line, and the
openITCOCKPIT API is backwards compatible, so newer instances are expected to
work. One caveat: `list_installed_software` and `find_pending_updates` need
the openITCOCKPIT agent's package
endpoints and fail with an API error where that feature is absent.

**Delegated mode** is a preview. It needs an openITCOCKPIT that issues user tokens, which
ships with an upcoming openITCOCKPIT release: it accepts
`Authorization: Bearer <token>` and creates its signing key with
`oitc api_tokens --generate-key`. Against an openITCOCKPIT without them every
call in delegated mode is rejected; static mode is unaffected.
