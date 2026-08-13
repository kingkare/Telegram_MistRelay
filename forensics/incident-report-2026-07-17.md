# MistRelay Incident Report - 2026-07-17

## Assessment

MistRelay's old container was compromised. Two independent exposed surfaces were used:

1. A static asset path traversal returned arbitrary readable files from inside the container, including application configuration, SQLite data and a reusable Telegram session.
2. aria2 JSON-RPC listened publicly with the seven-character default secret. The container also ran as root with `privileged`, host networking and the Docker socket mounted. The attacker used aria2-controlled `dir`/`out` values to read and write files inside the container; the application then automatically uploaded completed tasks to Telegram.

The confirmed malicious task window was `2026-07-16 17:23:21-17:41:14 UTC` (`2026-07-17 01:23:21-01:41:14 +0800`). The application initiated 106 Telegram uploads, messages `5811-5916`, totaling 43,338 bytes, into channel `-1001998444696`.

No current host persistence attributable to this incident was found. Host SSH records contain no accepted login during the incident window, Docker/containerd records contain no attributable create/start/exec action, and the checked host preload, SSH key and cron paths are clean. This is an evidence statement, not proof that the old privileged container could never have affected the host.

## Source Attribution

### Primary source candidate: `125.230.75.157`

- 600 recorded HTTP requests, including 503 failed logins.
- Enumerated APIs from `00:11 +0800`, tested traversal at `01:22:08-01:22:12`, immediately preceded the first malicious aria2 task at `01:23:21`, then requested attacker-specific names such as `jiuyue_host_proof*.txt` at `01:26:43-01:26:46`.
- APNIC/TWNIC registration maps `125.230.0.0/16` to Chunghwa Telecom HiNet residential ADSL/FTTB in Taiwan: <https://rdap.apnic.net/ip/125.230.75.157>.
- Evidence strength is high for association with the activity, but only medium for submission of the JSON-RPC tasks because aria2 retained no RPC client IP log.

### Follow-on read/exfiltration source: `104.28.238.119`

- Made 19,725 requests, successfully traversed to sensitive files and later fetched Telegram stream links for messages `5811-5916` using correct capability hashes.
- ARIN registration maps the containing network to Cloudflare: <https://rdap.arin.net/registry/ip/104.28.238.119>.
- This can be a proxy/intermediary exit. It cannot be equated to the same person as `125.230.75.157` without Cloudflare records.

### Weak source candidate: `223.166.221.136`

- API/SSH probing and one `/api/ws` request occurred 12 seconds before the first aria2 task, but only temporal proximity links it.
- APNIC registration maps it to China Unicom Shanghai: <https://rdap.apnic.net/ip/223.166.221.136>.

Local evidence cannot identify a natural person. Subscriber mapping requires provider-side source-port/subscriber logs at the exact UTC timestamps. The Git author name, SSH key comment, Telegram entity cache and webhook UUIDs are forgeable identifiers and are not proof of identity.

## Confirmed Activity

- The attacker staged or read `authorized_keys`, `ld.so.preload`, `.libsyscheck.so`, cron files, aria2 hooks and replacements named like system commands.
- `/proc/1/root/...` in these tasks addressed the container PID 1 root filesystem, not the host root filesystem.
- The container's `/usr/sbin/service`, `/usr/bin/tzselect`, `/usr/bin/ldd`, `/usr/bin/c_rehash` and `/app/start.sh` were deleted/overwritten and the old container must not be reused.
- No successful Web administrator login was recorded on July 17. The initial compromise path does not require a successful Web login.
- The public static traversal separately returned HTTP 200 for sensitive container paths, including configuration, database, Telegram session, process environment and container `/etc/shadow`.

## Indicators

| Indicator | Value |
| --- | --- |
| Primary source candidate | `125.230.75.157` |
| Follow-on read source | `104.28.238.119` |
| Weak source candidate | `223.166.221.136` |
| ELF sample SHA-256 | `9d03ad78906857fd6db7641e35b28266b69a5ec71ef456ee525aef3cce410423` |
| `ld.so.preload` SHA-256 | `bd5faaef028c58c9fca42b40285389c1fdd8a9d6a58e2282d7b4b81a698013f0` |
| Attacker public key SHA-256 | `1c1cae72a7c3400990b0abb3ee843e50340482cad51ad12401385f21ca2ef3ff` |
| SSH public key fingerprint | `SHA256:b87TdrVwyViX4HxdK+jjXJbsJCxTV+nT8zFP82s553M` |
| SSH key comment | `sophomores@DESKTOP-8I52PMD` |
| Webhook UUID | `8dccae9d-5aef-4b0b-a0d2-514cb0822b82` |
| Webhook UUID | `8bb93932-6d30-44f0-8f34-5187fa08f148` |
| Telegram storage channel | `-1001998444696`, messages `5811-5916` |

The ELF constructor creates `/tmp/.xok`, writes environment data to `/tmp/.sys-check`, and attempts a webhook request with hostname and UID. No saved marker or network telemetry proves that the webhook call succeeded.

## Git and Credential Exposure

- Local unsigned commit `24f988a4a97a2271a9fe40b89e73c9e49384788a` contains a real Telethon session backup. Blob: `50a8c7d7ef3d381ef5a10c272603e0db5b8eb25b`; file SHA-256: `033de58b16d3253691bbea4c30e583fb81827cee2eab6645a3abe26932e8123a`.
- The local tracking ref for `origin/main` does not contain that commit. This does not prove the commit was never copied to another remote.
- The Git author field is unsigned and forgeable. It cannot attribute the intrusion.
- Telegram Bot tokens/API credentials/session keys, Web administrator credentials, aria2 RPC secret and rclone OAuth grants must all be treated as compromised and revoked at their providers.

## Remediation Applied

- Restricted all file APIs to `/data/downloads` and blocked traversal and symlink components.
- Restricted static assets to the built asset root.
- Removed public/query-string administrator JWT authentication; WebSockets now use an authenticated subprotocol and thumbnails use short-lived path-scoped tickets.
- Redacted secrets from `/api/config`, made credentials/destinations offline-only and removed `FORWARD_ID` silent mirroring.
- Deleted the legacy `FORWARD_ID`, rclone, OneDrive and Google Drive destination rows from the stopped runtime database, retired the exposed `db/config.yml`, and disabled automatic YAML fallback. Legacy YAML import now requires an explicit owner-only, one-off offline command and verifies SQLite before erasing the source.
- Preserved the two live rclone configuration files as owner-only evidence with a SHA-256 sidecar, then removed them from the working deployment. Provider-side OAuth grant revocation remains required.
- Secure-deleted and vacuumed the stopped runtime database after removing all five credential rows (`API_ID`, `API_HASH`, primary/additional Bot tokens and `RPC_SECRET`). The original database remains in the revalidated evidence set. No preserved Telegram, RPC or rclone plaintext secret remains in the working deployment.
- Added login throttling, short-lived access tokens, refresh-token rotation/revocation, stronger versioned password hashing and transactional incident credential rotation with recoverable legacy-file cleanup.
- Added incident-evidence fingerprint rejection to credential rotation, the database activation gate and the container startup gate. The fingerprints cover the one exposed API ID, one API hash, four Bot tokens and one RPC secret without embedding plaintext secrets.
- Added a read-only activation preflight that verifies exact Telegram identity scope and HTTPS origin, SQLite integrity/schema/configuration, administrator/session state, data-volume permissions, stopped-container privileges/mounts/network/resources, and image-to-worktree critical-file hashes.
- Raised public stream capability hashes from 24 to 128 bits and reject invalid capabilities before Telegram API calls.
- Made Telegram ingestion allowlists fail closed and numeric-ID-only.
- Rebuilt the container as UID/GID 10001 with a read-only root filesystem, all capabilities dropped, `no-new-privileges`, no Docker socket, loopback-only Web publishing and loopback-only high-entropy aria2 RPC.
- Added process supervision, readiness checks, bounded queues, resource limits, log rotation and fixed base-image digests.
- Enabled SQLite foreign-key enforcement and repaired 10 pre-incident legacy orphan links by applying their declared `ON DELETE SET NULL` behavior; no legacy media rows were deleted. The database now passes both integrity and foreign-key checks.
- Disabled raw aiohttp access logging and supplied URI/query/Referer-free Nginx logging so thumbnail tickets and stream capabilities are not persisted in request logs.
- Removed the session backup and local agent permissions from the current Git index and added ignore/build-exclusion rules. The unpushed local history still requires sanitization before any push.
- Prepared provider-specific preservation drafts for HiNet, Cloudflare, Telegram and webhook.site under `forensics/preservation/`; no request was sent automatically.
- Rebuilt and recreated the stopped deployment as image `sha256:e78771fab699cb96c33a902b6d4a366c925fcfd814a0bbf0bb25edb7d0400f9c`. The final isolated image test suite passed 71 tests; npm and Python dependency audits found no known vulnerabilities. No OS image scanner was available on the host.

The replacement container remains intentionally in `created` state with no listener on host ports 8080 or 6800. Its startup gate exits before launching aria2 or the Web service because the new credentials are intentionally absent. The staged preflight passes evidence-fingerprint removal, filesystem, SQLite integrity/foreign-key and all container checks; it correctly fails the credential, security-schema, administrator-baseline and public-activation requirements until provider-side revocation and offline credential rotation are completed.

## Evidence

- Preserved evidence root: `/root/openclaw-backups/mistrelay-incident-20260717T120632Z`
- Integrity manifest: `/root/openclaw-backups/mistrelay-incident-20260717T120632Z/SHA256SUMS` (revalidated successfully)
- Pre-FK-repair database copy: `/root/openclaw-backups/mistrelay-incident-20260717T120632Z/remediation/downloads.pre-fk-repair-20260718T1218Z.db` (separate SHA-256 sidecar revalidated successfully)
- Preserved rclone configurations and hash sidecar: `/root/openclaw-backups/mistrelay-incident-20260717T120632Z/revoked-live-files/`
- Provider preservation packet: [README.md](/root/MistRelay-dev/forensics/preservation/README.md:1)
- First malicious task: [mistrelay.log.1](/root/openclaw-backups/mistrelay-incident-20260717T120632Z/db/logs/mistrelay.log.1:59911)
- Last upload completion: [mistrelay.log.1](/root/openclaw-backups/mistrelay-incident-20260717T120632Z/db/logs/mistrelay.log.1:61842)
- Primary source correlation: [mistrelay.log.1](/root/openclaw-backups/mistrelay-incident-20260717T120632Z/db/logs/mistrelay.log.1:59902)
- Container/host final assessment: [host-audit-final-assessment.txt](/root/openclaw-backups/mistrelay-incident-20260717T120632Z/remediation/verification/host-audit-final-assessment.txt:1)

Database `message_date` values from the affected application were local `Asia/Shanghai` times incorrectly suffixed with `Z`. Docker log timestamps are the authoritative UTC timeline.

## Required External Actions

1. Ask Chunghwa Telecom/HiNet to preserve subscriber/NAT mapping for `125.230.75.157` across the exact UTC attack window. Supply source and destination ports from any upstream firewall records if available.
2. Complete the placeholders and send the drafts in `forensics/preservation/`: webhook.site first because anonymous data may expire quickly, then HiNet and Telegram; give the Cloudflare draft only to an actual investigating officer or counsel. Provider records are required for account or natural-person attribution.
3. Revoke and reissue all Telegram and rclone credentials before starting the rebuilt service. The recovery input also requires an explicit HTTPS public origin, or safely disables outbound stream links when left empty.
4. Do not push the current local branch until the session-bearing local commit has been removed from history.
5. Install the supplied Nginx template only after DNS and TLS are ready, then verify real client IP handling, Origin rejection, WebSocket subprotocol authentication, byte ranges, upload limits and `/api/health` through the public HTTPS endpoint before enabling restart automation.
