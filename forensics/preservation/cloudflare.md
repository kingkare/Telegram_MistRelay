# Cloudflare Preservation Request For Investigating Authority

Official policy and channel:
<https://www.cloudflare.com/trust-hub/law-enforcement/>

Do not send this draft to Cloudflare's law-enforcement address unless the sender
is an actual verified official. Cloudflare states that it requires legal process
for subscriber data and that transactional data may be retained only briefly.

Subject: `URGENT RECORD PRESERVATION - 104.28.238.119 - MistRelay-2026-07-17`

```text
Dear Cloudflare Legal Response Team,

I am [OFFICER NAME/RANK/AGENCY/UNIT], badge [BADGE], case [CASE NUMBER].
Official contact: [AGENCY EMAIL/PHONE].

This request asks Cloudflare to preserve existing records pending applicable
legal process. It does not request voluntary disclosure at this stage.

Observed Cloudflare address: 104.28.238.119
Victim destination: 23.94.9.54:8080
Observed requests: 19,725
Observed interval: 2026-07-16 13:51:55Z to 2026-07-17 11:59:48Z
Requested preservation window: 2026-07-16 13:30:00Z to 2026-07-17 12:30:00Z

Correlation points:
- First post-task request: 2026-07-16 17:42:38.978Z
- Configuration read: 2026-07-16 21:08:45.943Z
- Telegram session reads: 21:09:04.261Z, 21:09:07.104Z, 21:10:25.233Z
- Stream read for channel message 5811: 22:00:02.716Z
- Stream read for channel message 5916: 23:42:43.814Z
- Further related reads: 2026-07-17 00:38:13.177Z, 00:39:43.920Z,
  and 03:02:45.521Z

The victim access log lacks client source ports. Please preserve data capable of
mapping this shared egress address using Cloudflare's own destination/port and
session records, including:

1. The product role of this address at each timestamp (WARP, MASQUE, Zero Trust,
   proxy egress or another service).
2. Ingress-to-egress NAT/tunnel mapping, client source IP/port, egress source
   port, destination five-tuple and session start/end.
3. Tunnel/session, device registration/public key, client version and protocol.
4. Associated account/organization/device, login and audit records.
5. Available request method, target URL, User-Agent, TLS and connection metadata.
6. Account deletion, device removal, key rotation and log-export audit records.
7. If this address cannot be mapped, its exact product role and the data classes
   that were or were not retained.

Please preserve for at least 180 days or the longest period available, and
confirm the preservation reference, scope, timezone and unavailable data.

104.28.238.119 is a Cloudflare intermediary/shared egress lead. We do not treat
it as a natural-person identity or assert it is the same actor as any other IP.

Sincerely,
[VERIFIED OFFICIAL]
```
