# Webhook.site Urgent Preservation Request

To: `support@webhook.site` or the official support portal.

Official retention/contact source: <https://webhook.site/terms>. The published
policy says anonymous URL data may expire after 7 days, so this request is urgent.

Subject: `URGENT RECORD PRESERVATION - MALWARE WEBHOOK UUIDS - MistRelay-2026-07-17`

```text
Dear Webhook.site Support / Webhook ApS,

I am [REQUESTER] for [VICTIM/ORGANIZATION], operator of compromised server
23.94.9.54. Contact: [VERIFIABLE EMAIL/PHONE]. Case reference: [CASE/PENDING].

Please immediately preserve existing records for these Webhook.site UUIDs:

- 8dccae9d-5aef-4b0b-a0d2-514cb0822b82
- 8bb93932-6d30-44f0-8f34-5187fa08f148

Malicious ELF SHA-256:
9d03ad78906857fd6db7641e35b28266b69a5ec71ef456ee525aef3cce410423

The code contains these UUIDs and attempts a request containing host/UID data.
Local telemetry does not prove that the outbound request succeeded. The core
incident interval is 2026-07-16 17:23:21.460Z to 17:41:14.680Z; please preserve
the complete UUID lifecycle from 2026-07-15 00:00:00Z through receipt of this
notice, including deleted/expired data and available backups.

Please preserve for at least 180 days or the longest period available:

1. UUID creation/change/delete/expiry, ownership mode and account association.
2. Creator and console/API login source IP/port, User-Agent, session/device and
   authentication audit records.
3. Every inbound request: timestamp, source IP/port, method, URL, headers, query,
   body and available TLS metadata.
4. Token response templates, forwarding/redirection destinations and delivery logs.
5. Console view, API retrieval, export and per-request deletion audit records.
6. Deleted-object backups/snapshots and whether both UUIDs share an account,
   session, IP, API key or device.
7. If no request arrived, confirmation of a zero result and whether each UUID
   existed at any time.

This is a preservation request only; disclosure may follow through appropriate
legal process. Please confirm a preservation reference, scope, timezone and any
data already expired or unavailable.

The UUIDs can be copied or forged and do not by themselves identify their creator
as the attacker.

Sincerely,
[REQUESTER]
```
