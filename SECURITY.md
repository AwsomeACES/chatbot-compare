# Credentials and safe project exports

Keep real credentials only in your local `.env` or an approved secret store.
Never send a complete working-directory ZIP: Git ignore rules do not apply to
Explorer's "Compress to ZIP" operation. Virtual environments and runtime
reports may also contain private configuration or conversations.

Create the shareable source archive with:

```powershell
Set-Location "D:\AI-Agent-Testing-Studio"
& .\.venv\Scripts\python.exe .\scripts\package_release.py --root . --output "..\AI-Agent-Testing-Studio-safe.zip"
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
