# Shared-hosting readiness

This Studio is a **local, single-user tool**. It binds to loopback, trusts whoever can reach that port, and stores every Run, upload, credential and audit record in one database owned by one person. That design is deliberate and is not a defect.

This document is the honest gap list for making it safe for more than one person. Nothing here is implemented. Adding a login screen to the current application would hide the gaps rather than close them, so this is written as the work required, not as a migration plan to start today.

Shared use is **conditional**: it needs a decision from the owner about who the users are, where it runs and which identity system it must use. Until that decision exists, the loopback default and the current behaviour stay as they are.

## Contents

- [What the current design assumes](#what-the-current-design-assumes)
- [Required before shared use](#required-before-shared-use)
- [What a login screen alone does not fix](#what-a-login-screen-alone-does-not-fix)
- [Questions the owner must answer first](#questions-the-owner-must-answer-first)
- [Suggested order of work](#suggested-order-of-work)

## What the current design assumes

| Assumption                     | Where it shows                                                                                | Consequence for shared use                                           |
| ------------------------------ | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| One trusted operator           | No authentication anywhere; `X-Studio-Request` is a cross-site-request guard, not an identity | Anyone who reaches the port has full control                         |
| Loopback only                  | `start.sh` and `run.ps1` bind `127.0.0.1`; the container binds `0.0.0.0` for port mapping     | Exposing the port is exposing the whole Studio                       |
| One data owner                 | One SQLite database; records are keyed by UUID with no owner column                           | Every user would see and could delete every other user's Runs        |
| One set of credentials         | Provider keys in `.env` and Studio settings, shared by every Run                              | One user's test spends another user's quota and bills their key      |
| Uploads are the operator's own | Source ZIPs are extracted to a shared runtime directory under the server's identity           | One user could read another user's uploaded source                   |
| Downloads are unguarded        | Report and evidence downloads are reachable by anyone who knows the Run ID                    | A leaked or guessed ID discloses an entire assessment                |
| One in-memory scheduler        | `scheduling.Runtime` holds per-provider limits in this process                                | Concurrent users share one rate limit with no fairness or accounting |
| Deletion is absolute           | Retention and deletion act on the whole record                                                | One user could delete another user's evidence and audit history      |

## Required before shared use

Each item is a prerequisite, not a nice-to-have.

### 1. Authentication

An identity for every request, verified server-side, with session expiry and revocation. It must integrate with whatever the deployment already uses (SSO, OIDC, an internal directory) rather than inventing a password store. Local accounts need password hashing with a current algorithm, rate-limited sign-in and a recovery path that cannot be used to take over an account.

### 2. Server-side authorization

Authentication says who is asking; authorization decides what they may do. Every route that reads or writes a Run, assessment, calibration set, credential, upload or audit record needs an ownership or role check **on the server**. Hiding a button is not authorization. This is the largest change, because the current routes assume the caller owns everything.

### 3. Per-user data isolation

An owner column on every record kind, enforced in the query layer rather than remembered at each call site, plus a decision about what sharing means: read-only sharing, team ownership, or none. Listings, history pickers, exports, retention sweeps and deletion all have to respect it. Existing single-owner records need a migration that assigns them to the current owner without losing their audit anchors.

### 4. Credential separation

Per-user provider credentials, stored encrypted at rest with a key that is not in the repository or the database, never returned to the browser, and never written into a report, log or audit entry. Metering and cost attribution must follow the credential owner, otherwise one user's spending appears on another's account. The current shared `.env` key must stop being the fallback for everyone.

### 5. Cross-site request and session protection

Real CSRF tokens bound to the session for every state-changing request, `Secure`, `HttpOnly` and `SameSite` cookies, HTTPS termination with HSTS, and a Content-Security-Policy. The current `X-Studio-Request` header check is a same-origin heuristic suited to a loopback tool; it is not a CSRF defence for a hosted application.

### 6. Secure downloads

Reports, evidence JSON, teammate Markdown and PDFs must be authorized per request rather than guarded by an unguessable identifier. Short-lived, single-use, owner-bound links; no directory listing; and a content-disposition and type that cannot be used to serve a user's upload back as active content.

### 7. Upload isolation

Per-user upload directories with quotas, extraction limits that already exist kept intact, and no path where one user's archive can be read by another. Scanner containers must receive only the requesting user's source, mounted read-only, with the existing no-network sandbox unchanged. The rule that an uploaded application is never executed or imported on the host does not change.

### 8. Operational controls

Multi-worker operation needs shared admission control and rate limiting, because the current scheduler's per-provider limits live in one process; running two workers today would double the real request rate. Beyond that: backups with a tested restore, an append-only audit store separate from the application database, per-user quotas and budget caps, a log pipeline that does not capture transcripts or credentials, dependency and image patching, and a documented incident path. The audit hash chain detects edits against its stored anchor; in a shared deployment it needs an external anchor, because an administrator can reach both the database and its backups.

## What a login screen alone does not fix

Adding a sign-in page without items 2 to 8 would leave every one of these true:

- Any signed-in user could read, export and delete every other user's Runs, because no route checks ownership.
- Provider keys would still be shared, so costs and quota exhaustion would be unattributable.
- Uploaded source would still sit in a shared directory.
- Download links would still be bearer tokens in disguise.
- Two workers would still double the provider request rate.
- The audit chain would still be verifiable only against a database an administrator controls.

A Studio in that state would be less safe than the current loopback tool, because it would look multi-user while behaving single-user. The product must not describe itself as secure, certified or production-ready on the strength of a login form.

## Questions the owner must answer first

1. Is a shared deployment actually wanted, or is remote access for one person enough? A single-user remote setup is a different and much smaller problem: an SSH tunnel, a VPN, or a reverse proxy with the owner's own authentication in front of an unchanged loopback Studio.
2. Who are the users, and do they share work or keep it private? Team ownership and private ownership need different data models.
3. Which identity system must it use, and is an existing SSO or directory available?
4. Where does it run (a managed container platform, a virtual machine, an internal network only), and who administers it?
5. Whose provider credentials and budget pay for Runs, and must spending be attributable per user?
6. What must the retention and deletion rules be when one user's evidence is another user's audit record?
7. Is there an existing security review or compliance requirement the deployment must satisfy?

## Suggested order of work

If the answers justify shared hosting, the safe order is roughly:

1. Decide the ownership model, then add the owner column and the query-layer enforcement — before any login screen, so there is something for authorization to check.
2. Add authentication and session protection.
3. Add authorization checks route by route, with a test per route that a non-owner is refused.
4. Separate credentials and cost attribution.
5. Isolate uploads and secure downloads.
6. Add shared admission control, then and only then allow more than one worker.
7. Add the operational controls, external audit anchoring and backups.
8. Commission an independent security review. This document is a gap list written by the implementer; it is not a security assessment.

Until then: keep the loopback default, keep the single-owner assumptions explicit in the interface, and do not claim shared-use readiness. Local improvements continue independently of this decision.
