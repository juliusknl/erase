# Threat model

## Security goals

erase aims to:

- keep identity data, signatures, OAuth tokens, and correspondence out of source control and casual filesystem inspection;
- prevent unauthenticated browser access to the localhost dashboard;
- prevent cross-site request forgery for state-changing dashboard actions;
- send personal information only to a recently validated broker-controlled destination;
- require a person when a workflow becomes ambiguous or legally sensitive;
- preserve a useful local audit trail without operating a central data service.

## In scope

The primary threats are accidental publication of personal data or secrets, malicious web pages attempting local requests, copied database or backup files, forged or unrelated broker replies, changed broker destinations, dependency compromise, and unintended duplicate or excessive submissions.

## Out of scope for the current alpha

- a compromised or malicious operating-system administrator;
- malware running as the logged-in user on an unlocked machine;
- public internet exposure of the dashboard;
- shared-computer or multi-user isolation;
- hostile multi-tenant hosting;
- compromise of Google, a broker, or the user's mailbox provider;
- guaranteeing that a broker truthfully deletes every copy of a record.

## Trust boundaries

1. **Browser to localhost application:** protected by a password session, login throttling, CSRF tokens, localhost Host validation and restrictive browser headers. The service binds to `127.0.0.1` by default and must not be exposed publicly.
2. **Application to local storage:** selected sensitive payloads are encrypted with a Keychain-held master key. SQLite metadata and the running process remain visible to a sufficiently privileged local attacker.
3. **Application to Gmail:** OAuth tokens authorize powerful mailbox operations. The dedicated mailbox and minimal message correlation reduce, but do not eliminate, this exposure.
4. **Application to brokers:** broker contact data and forms are untrusted and change over time. HTTPS allowlisting, recent validation, disclosure minimization, batch limits, and approval gates constrain submissions.
5. **Application to dependencies:** Python packages, the base container, browser binaries, and GitHub Actions form a software-supply-chain boundary. Locked dependencies, CI, update review, and pinned Actions reduce risk.

## Important residual risks

- Encryption at rest cannot help while the application is running and has decrypted data in memory.
- A valid-looking email reply can be spoofed unless sender and authentication evidence are verified before automatic state changes.
- A broker may request additional information or identity documents. The application must not upload these unattended.
- Browser automation can put data into the wrong field after a site redesign. Unknown forms must fail closed.
- Losing the Keychain master key makes encrypted backups unusable.

## Pre-release security work

- retain regression coverage for authenticated sender evidence, login throttling,
  security headers and CSRF/Host rejection (implemented);
- add a tested local deletion and bounded retention workflow;
- add master-key rotation or a documented recovery strategy;
- inspect the allowlisted release payload for credentials and personal data;
  publish from that clean tree, never the unrelated parent repository/history;
- perform a clean-machine backup/restore drill;
- obtain an independent security review before recommending unattended use broadly.
