# Telegram Victim Bot/Session Preservation Request

Initial victim notification channels published by Telegram:
`abuse@telegram.org`, `security@telegram.org`.

Official references: <https://telegram.org/faq>,
<https://telegram.org/privacy>, <https://core.telegram.org/bug-bounty>.

Subject: `URGENT PRESERVATION - COMPROMISED BOT/SESSION - MistRelay-2026-07-17`

```text
Dear Telegram Abuse and Security Teams,

I am [REQUESTER] and can prove control of the affected bot and storage channel.
Contact: [VERIFIABLE EMAIL/PHONE]. Case reference: [CASE NUMBER OR PENDING].

This is a request to preserve existing records pending applicable legal process.
It is not a request to disclose another user's personal data by ordinary email.

Affected objects:
- Bot ID: 5625760372
- Bot username: jiuyuetanzhen_bot
- Telegram application API ID: 2420373
- Storage channel ID: -1001998444696 (peer 1998444696)
- Messages: 5811 through 5916, 106 consecutive uploads, 43,338 bytes total
- Upload interval: 2026-07-16 17:23:21.460Z to 17:41:14.680Z
- Victim server's expected source address: 23.94.9.54
- Preserved session file SHA-256:
  9cc12605a9b0b7762f3f5e8baad30a2d8275eacd564831e660671d4477d45f3a
- Session exposure first confirmed at 2026-07-16 21:09:04.261Z

Please preserve from 2026-07-16 16:00:00Z through the actual credential/session
revocation time, for at least 180 days or the longest period available:

1. Complete objects/media and edit/delete history for messages 5811-5916.
2. Channel administrator/permission changes, bot add/remove and admin logs.
3. Bot API and MTProto authorization/session creation, reuse and revocation logs.
4. Source IP/port, DC, API ID, client/app/device and time for each authorization.
5. Any use after 21:09:04Z from a source other than 23.94.9.54.
6. BotFather token issue/reset/revoke events and related control audit records.
7. Upload/API method and server-connection metadata for messages 5811-5916.
8. Historical records for deleted or invalidated sessions.

Please confirm a preservation reference, scope, timezone and unavailable data,
and identify the channel through which an authority should serve legal process.

The bot, channel and victim server are victim-controlled objects. The messages
were automatically uploaded after the server was manipulated and are not actor
identity evidence by themselves. No API hash, Bot token or raw session is
attached to this notice.

Sincerely,
[REQUESTER]
```
