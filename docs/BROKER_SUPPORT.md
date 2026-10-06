# Broker support levels

Catalog size is not product coverage. erase uses the following terms so that users can tell discovery data apart from tested automation.

| Level | Meaning | What the software may do |
| --- | --- | --- |
| Catalogued | A public registry or another authoritative source identifies the entity as a possible data broker. | Show it as a candidate only. |
| Contact discovered | An apparent privacy address or removal page has been found but not fully checked. | Display the contact for research; do not submit automatically. |
| Validated email | A maintainer checked the recipient, request template, required fields, and jurisdiction recently. | Prepare or send an email after the user's campaign approval. |
| Validated browser | A maintainer checked the official form and its required fields recently. | Open or populate only the validated steps; stop at approval gates. |
| Acknowledged | The broker acknowledged a real request, without proving deletion. | Track the response and schedule any required follow-up. |
| Removal confirmed | A broker stated that the request was completed or a user verified removal. | Mark the case complete and schedule a recheck. |
| Rechecked | A later check found no renewed listing or the broker reconfirmed the removal. | Record dated evidence and schedule the next cadence. |

## Validation requirements

A validated workflow must record a `last_validated_at` date, use an official broker-controlled destination, disclose only required profile fields, identify the supported geography, and fail closed when the destination or expected flow changes.

Validation expires because broker ownership, forms, addresses, and requirements change. An expired workflow returns to review rather than continuing unattended.

## Metrics

Public progress reports should publish each level independently. Never describe the number of imported registry rows, domains, or candidate cases as “supported brokers.” Likewise, a sent or acknowledged request is not a confirmed removal.
