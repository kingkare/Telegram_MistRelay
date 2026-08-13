# MistRelay Provider Preservation Packet

This directory contains provider-specific preservation requests for incident
`MistRelay-2026-07-17`. These are drafts only. No request has been sent.

## Send Order

1. Send `webhook-site.md` immediately. Webhook.site states that anonymous data
   may expire after 7 days and that access logs may be retained for up to 50
   days: <https://webhook.site/terms>.
2. Send `hinet.md` to the abuse contacts published in the official APNIC RDAP
   record for the observed address: <https://rdap.apnic.net/ip/125.230.75.157>.
3. Send `telegram.md` as a victim security/abuse notification. Telegram lists
   `abuse@telegram.org` for abuse and `security@telegram.org` for security
   reports: <https://telegram.org/faq>, <https://core.telegram.org/bug-bounty>.
4. Give `cloudflare.md` to the investigating officer or counsel. Cloudflare
   requires valid legal process for subscriber data and reserves its law
   enforcement address for verified officials: <https://www.cloudflare.com/trust-hub/law-enforcement/>.

Do not impersonate law enforcement. Each request asks only for preservation at
this stage, not voluntary disclosure of subscriber data. Replace every bracketed
placeholder, use a verifiable sender address, and request a preservation/case
reference plus the provider's log timezone.

Do not attach the raw SQLite database, Telegram session, API hash, Bot token,
RPC secret, capability hashes, or credential files. Use the minimum extracts
listed in `evidence-index.md`, preferably through a provider evidence portal.

All times in these drafts are UTC. Application `message_date` values were
historically written as Shanghai local time with an incorrect `Z`; Docker log
timestamps and the converted access-log timeline are authoritative.
