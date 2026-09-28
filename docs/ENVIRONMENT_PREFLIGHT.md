# 0.0.0-P3 environment preflight

Checked on 2026-09-28 against the supplied LXC and Discord application. This is an environment check, not an end-to-end bot test.

| Item | Observed result | Limit |
|---|---|---|
| LXC | Debian 13, x86_64, Python 3.13.5, systemd running | Service deployment is not yet configured |
| Capacity | 32 GB free on the root filesystem; 7.8 GiB available memory at check time | Shared workload may change available resources |
| Clock | NTP synchronized | Request boundary tests are later |
| Codex | CLI 0.158.0 present, root account reports ChatGPT sign-in | Dedicated bot account auth, model selection and invocation are not yet verified |
| Developer tools | Git 2.47.3 and isolated Python environment installed | Lock file install and smoke verified in 0.0.0-P2 |
| Discord | Bot REST authentication succeeded; app is in one Guild | Gateway and Message Content intent behavior still require a live check |
| Test channel | A pre-existing text channel intended for bot tests is readable through History API | Sending messages, administrator interaction and callback permissions are not yet verified |
| Other channels | Some channels correctly deny History access | The bot must never treat those channels as permitted summary sources |

An unprivileged `yoyackbot-dev` account owns its development data directory (mode `0700`). The token and development Guild/channel identifiers are in a server-only file owned by that account (mode `0600`). The application configuration check succeeds under the development account without displaying the token. The public repository has examples only.

The Discord application currently exposes a limited Message Content flag while unverified. The [Discord privileged intent guidance](https://support-dev.discord.com/hc/en-us/articles/6207308062871-What-are-Privileged-Intents) explains why actual Gateway behavior must be checked. A successful REST call does not establish that a message listener receives normal message bodies. That check belongs to 0.1.0-P1.

The Codex CLI is installed, but the configured model and safe invocation under the bot account remain gates for 0.5.0-P1/P3. No model output, Discord post, service deployment, or database integration is claimed here.
