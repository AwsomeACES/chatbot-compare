# Security

AI Agent Studio is a local, single-user application. It binds loopback
(`127.0.0.1`) and is not hardened for shared or internet-facing hosting. See
[docs/shared-hosting-readiness.md](docs/shared-hosting-readiness.md) for what a
multi-user deployment would require.

## Supported versions

| Version                    | Supported                       |
| -------------------------- | ------------------------------- |
| `master` (current)         | Yes — fixes land here           |
| Earlier release candidates | No — update to current `master` |

There has been no tagged public release yet, so there are no maintained release
branches. Python 3.12 is the supported interpreter.

## Reporting a vulnerability

> **Private reporting is not yet enabled on this repository.** As of
> 2026-11-09, GitHub's private vulnerability reporting is switched off and no
> security contact address has been published. Nothing here should be read as a
> promise of a monitored channel or a response time.

**Please do not open a public issue for a suspected vulnerability.** A public
issue discloses the problem before there is a fix.

Until a private channel exists, the honest options are:

1. **Preferred — ask the maintainer to enable private reporting.** The
   repository owner can switch it on under _Settings → Code security → Private
   vulnerability reporting_. The _Security_ tab then offers "Report a
   vulnerability" and the report stays private. This is the maintainer action
   this document is waiting on.
2. **Otherwise, make private contact first.** Open a public issue containing
   **no technical detail** — for example "requesting a private channel to report
   a security issue" — and ask how to send the details privately.

### Maintainer setup still required

- [ ] Enable GitHub private vulnerability reporting.
- [ ] Publish a monitored security contact, or state that private reporting is the only route.
- [ ] Replace the notice above once a real channel exists.

Because this is a local tool with no server component and no multi-tenant data,
most findings will concern the safety boundaries below rather than remote
compromise.

## Threat boundary

What Studio defends against:

- **Uploaded application code is never executed, imported, built or installed.**
  White-box scanning reads source inside a restricted, networkless Docker
  sandbox. An isolated application runner remains Planned, not shipped.
- **Archive extraction is bounded** against path traversal, symlink escape,
  expansion bombs and oversized members.
- **Cross-site request forgery.** Every non-GET API request requires a Studio
  request header, the origin is checked against the server's own base URL, and
  the host header is restricted to loopback names.
- **Credential disclosure.** Keys are entered in password fields, kept out of
  Git, scrubbed from saved Runs, redacted from exports, and the source packager
  refuses to publish an archive containing a known local credential value.
- **Untrusted model and bot output** is escaped when rendered and treated as
  data, never as markup or code.
- **Server-side request forgery.** Target and Judge URLs must resolve to public
  or loopback addresses; private-network and cloud metadata endpoints are
  refused.

What Studio does **not** defend against, by design:

- An attacker who already controls your machine or your user account.
- A malicious chatbot you deliberately point Studio at, beyond bounding the
  response size and treating its text as data.
- Anything about the **security of the bot under test**. A passing Finding is
  evidence about one check, never a statement that an application is secure.
- Shared or networked deployment. Binding a non-loopback address is outside the
  supported configuration.
- Scanner completeness. A scanner that produced no evidence is reported as
  **Not tested**, and an unresolved dependency version is never reported as a
  confirmed installed vulnerable version.

## Credentials and safe project exports

Keep real credentials only in your local `.env` or an approved secret store.
Never send a complete working-directory ZIP: Git ignore rules do not apply to
Explorer's "Compress to ZIP" operation. Virtual environments and runtime
reports may also contain private configuration or conversations.

Create the shareable source archive from the repository root:

```powershell
& .\.venv\Scripts\python.exe .\scripts\package_release.py --root . --output "..\ai-agent-studio-source.zip"
```

```sh
.venv/bin/python scripts/package_release.py --root . --output ../ai-agent-studio-source.zip
```

The exporter uses an explicit source allowlist and excludes local environments,
runtime data, dependency folders, secrets, nested archives and symlinks. It checks
the completed ZIP before publishing it and refuses to overwrite an existing
archive. `.env.example` is included only with blank credential settings.
Known local credential values found in source files cause the export to fail;
errors identify the file, never print the credential. This check is an extra
guard, not proof that all possible secrets in arbitrary source are detectable.

## If a key is exposed

1. Revoke the exposed key in the issuing provider's account. Removing a ZIP or
   changing a local value does not revoke it.
2. Create a replacement and save it only in the local `.env`. Do not paste keys
   into chat, a ticket, a commit, screenshots, or an example file.
3. Restart Studio after saving the replacement: its environment is read at startup.
4. Remove the unsafe archive from every location to which it was distributed.
   Removing your sent email does not remove a recipient's copy. Ask recipients
   to remove their copies through your normal incident-response process.
5. Verify revocation in the provider account. A failed request due to quota,
   permissions, or network errors does not prove a key was revoked. Perform a
   live key check only with explicit authorization, using the provider's official
   endpoint and without logging credentials.

Google's key-management guidance: https://ai.google.dev/gemini-api/docs/api-key

`.gitignore` prevents ordinary accidental staging of local secrets and archives;
it cannot remove a previously tracked secret. `.gitattributes` excludes sensitive
paths from Git exports. A release archive must still be inspected before sharing.

## Audit integrity, honestly described

Governance keeps an append-only audit chain with hashes checked against a stored
anchor. That detects particular edits to retained records. It is **not** a
signature, not external immutable storage, and not tamper-proof against someone
who controls both the machine and the anchor.
