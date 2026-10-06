# Security policy

Personal Erasure handles identity data, mailbox authorization, and private correspondence. Please do not report vulnerabilities in a public issue or include real personal data, access tokens, database files, request emails, screenshots, or broker responses in a report.

## Reporting a vulnerability

Use the repository's private vulnerability-reporting feature under **Security → Report a vulnerability**. The eventual public repository must enable GitHub private vulnerability reporting before its first release.

Include:

- the affected version or commit;
- the security impact;
- minimal reproduction steps using synthetic data;
- whether the issue can expose identity data, OAuth tokens, signatures, or correspondence.

Do not test against a real broker, send messages, access another person's installation, or retain any personal data encountered accidentally.

There is currently no bug-bounty program. Maintainers will acknowledge a report when practical, investigate it privately, and publish a fix and advisory before disclosing exploit details.

## Supported versions

Until a stable release exists, only the latest tagged alpha is supported. The `main` branch may contain unreleased changes and should not be used as an unattended production service.

## Security boundaries

This is a single-user, localhost application. It is not designed for public internet exposure, shared computers, multiple users, or hosted multi-tenant deployment. See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) and [docs/PRIVACY.md](docs/PRIVACY.md).
