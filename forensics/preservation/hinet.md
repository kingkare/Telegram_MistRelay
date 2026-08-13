# HiNet / Chunghwa Telecom Preservation Request

To: `abuse@hinet.net`, `network-adm@hinet.net`

Official contact source: <https://rdap.apnic.net/ip/125.230.75.157>

Subject: `URGENT RECORD PRESERVATION - 125.230.75.157 - 2026-07-16 UTC - MistRelay-2026-07-17`

```text
Dear HiNet / Chunghwa Telecom Incident Response,

I am [REQUESTER NAME/TITLE] for [VICTIM/ORGANIZATION], the operator of victim
server 23.94.9.54. Contact: [VERIFIABLE EMAIL/PHONE]. Police/case reference:
[CASE NUMBER OR "NOT YET ASSIGNED"].

This is an urgent request to preserve existing records only. It does not ask
you to disclose subscriber information without applicable legal process.

Our server logs record activity strongly associated with 125.230.75.157:

- Observed activity: 2026-07-16 16:11:17Z to 17:26:46Z
- Requested preservation window: 2026-07-16 15:45:00Z to 18:00:00Z
- Traversal probes: 2026-07-16 17:22:08Z to 17:22:12Z
- First malicious aria2 task: 2026-07-16 17:23:21.460Z
- Attacker-specific proof-name requests: 17:26:43Z to 17:26:46Z
- Destination: 23.94.9.54:8080
- Please also check flows to 23.94.9.54:6800. Local aria2 logs did not retain
  the RPC client address, so we do not claim this IP is proven to have submitted
  those RPC calls.

Please preserve for at least 180 days, or the longest period available:

1. DHCP, PPPoE, RADIUS start/stop/interim and dynamic IP assignment records.
2. If CGNAT was used, complete pre/post-NAT five-tuples, ports and mapping times.
3. Access account, line/CPE/ONT/BRAS and session identifiers for the interval.
4. NetFlow, firewall or edge records to destination ports 8080 and 6800.
5. Account creation/change/login records and legally obtainable subscriber data.
6. Log clock source, precision, timezone and retention policy.

Please confirm a preservation reference, the exact time range and data classes
preserved, unavailable data classes, and the legal channel for a later request.

The address may represent shared access, a proxy, a compromised device or a
different household user. We do not identify the subscriber as the attacker.

Sincerely,
[REQUESTER]
```
