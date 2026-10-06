"""Local, conservative response drafts; never execute instructions from email."""

import re

from erasure.replies import new_reply_text, requests_information


def prepare_reply(body: str, profile: dict) -> dict:
    text = re.split(
        r"this message contains information|\nHello .+ Privacy Team,",
        new_reply_text(body),
        flags=re.I,
    )[0]
    text = re.sub(r"\s+", " ", text).lower()
    if requests_information(text) and re.search(r"mobile ad(?:vertising)? (?:id|identifier)|\b(?:maids?|aaids?|idfa)\b", text):
        return {
            "body": "Hello,\n\nPlease process my deletion and opt-out request for this device identifier:\nMobile Advertising ID: [ADD mobile advertising ID]\n\nPlease confirm the scope and outcome. Do not use the identifier for other purposes.\n\nThank you,\n"
            + profile.get("full_name", ""),
            "missing": ["Mobile Advertising ID"],
            "disclosed": [],
        }
    confirmation = re.search(
        r'\b(?:reply|respond)\b.{0,60}\bconfirm(?:ing)?\b.{0,100}\b(?:proceed|deletion|removal)\b|'
        r'please confirm (?:that )?you (?:would like|want) to proceed with (?:the|your) request', text)
    if confirmation and not requests_information(text):
        return {
            'body': 'Hello,\n\nI confirm that I want you to proceed with my personal-data deletion request. Please confirm the outcome.\n\nThank you,\n' + profile.get('full_name', ''),
            'missing': [], 'disclosed': [],
        }
    if "interne sperrdatei" in text:
        return {
            "body": "Guten Tag,\n\nbitte nehmen Sie meinen bereits im bisherigen Schriftwechsel angegebenen Namen und meine Anschrift wie angeboten in Ihre interne Sperrdatei auf, um eine erneute Nutzung für Direktmarketing zu verhindern. Bitte bestätigen Sie die Aufnahme.\n\nVielen Dank\n"
            + profile.get("full_name", ""),
            "missing": [],
            "disclosed": [],
        }
    no_match = bool(
        re.search(
            r"no (?:matching )?(?:records?|data)|unable to (?:locate|find)|does not contain any details|not been able to identify",
            text,
        )
    )
    if not no_match and not requests_information(text) and not re.search(
        r"(?:please|kindly) (?:respond|reply|provide|send|ask you to provide)|following information|bitten wir sie|could you kindly provide",
        text,
    ):
        return {}
    lines = [
        "Hello,",
        "",
        "Thank you for your response. Please continue processing my personal-data deletion and opt-out request.",
        "",
    ]
    missing, disclosed = [], []
    if re.search(r"if you (?:are unable|cannot)|if the form", text):
        lines += [
            "I would like to use the email fallback you described.",
            "[ADD why you could not complete the form]",
            "",
        ]
        missing.append("Why you could not complete the form")

    def field(label, value):
        if value:
            lines.append(f"{label}: {value}")
            disclosed.append(label)
        else:
            lines.append(f"{label}: [ADD {label.lower()} or explain if not applicable]")
            missing.append(label)

    if re.search(r"full name|legal name|vollständigen? namen", text):
        field("Full name", profile.get("full_name"))
    if "country" in text:
        field("Country of residence", profile.get("country"))
    if "state/province" in text or "state or province" in text:
        field("State/province", profile.get("state"))
    if "city" in text:
        field("City of residence", profile.get("city"))
    # Policy descriptions and signatures are not requests to disclose fields.
    requested_sentences = [sentence for sentence in re.split(r'(?<=[.!?])\s+', text)
                           if re.search(r'please|kindly|could you|we (?:need|require|must know)|'
                                        r'following information|bitten wir sie|benötigen wir|pourriez-vous', sentence)]
    field_text = ' '.join(requested_sentences) or text
    if re.search(r"(?:work|business|professional|corporate(?: \(work\))?) email", field_text):
        field("Work email to check", profile.get("work_email"))
    elif re.search(r"email address|e-mail address|e-mail-adresse", text):
        field("Email addresses to check", ", ".join(profile.get("other_emails") or []))
    elif no_match:
        field("Additional email addresses to check", ", ".join(profile.get("other_emails") or []))
    if re.search(r"employer|company name|name of your company", field_text):
        field("Current or most recent employer", profile.get("employer"))
    if re.search(r"linkedin (?:url|profile)|public linkedin", text):
        field("LinkedIn profile URL", profile.get("linkedin_url"))
    if "rocketreach url" in text:
        field("RocketReach profile URL", profile.get("rocketreach_url"))
    if re.search(r"provide your postal address|benötigen wir.{0,70}(?:postadresse|postanschrift)", field_text):
        # Never insert a stored home address without per-request disclosure review.
        field("Postal address (only if you choose to share it)", None)
    if re.search(r"phone number|telephone number|telefonnummer", text):
        field("Phone number to check", profile.get("phone"))
    if not disclosed and not missing:
        lines.append("[ADD the information or clarification requested in the broker’s reply]")
        missing.append("Requested information or clarification")
    lines += [
        "",
        "Please use these details only to locate my existing records and process this request. Please confirm the outcome.",
        "",
        "Thank you,",
        profile.get("full_name", ""),
    ]
    return {"body": "\n".join(lines), "missing": missing, "disclosed": disclosed}
