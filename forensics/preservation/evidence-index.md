# Common Evidence Index

Incident reference: `MistRelay-2026-07-17`

Victim server: `23.94.9.54`

Confirmed malicious task interval: `2026-07-16 17:23:21.460Z` through
`2026-07-16 17:41:14.680Z`.

Preserved evidence root:
`/root/openclaw-backups/mistrelay-incident-20260717T120632Z`

The original `SHA256SUMS` manifest has been revalidated. Its own SHA-256 is:

```text
37a3d4d35cdaa1a453e52f949221f04664aed44c4bbb2e31af89e6d26b5a1875
```

Recommended minimum attachments:

- [Incident report](/root/MistRelay-dev/forensics/incident-report-2026-07-17.md:1), hashed again immediately before submission.
- Provider-specific log extracts containing UTC timestamp, observed source,
  destination and event result. Redact authorization values and capability URLs.
- IOC hashes and the Telegram channel/message range from the incident report.
- A short chain-of-custody statement identifying who collected each attachment,
  collection time, source system and SHA-256.

Do not send raw secrets or the raw session. The preserved `db/bot.session` file
hash is `9cc12605a9b0b7762f3f5e8baad30a2d8275eacd564831e660671d4477d45f3a`;
the hash is sufficient to identify it in the initial preservation notice.

Required wording boundary: observed IP addresses, account objects, UUIDs and key
comments are investigative leads, not proof of a natural person's identity.
