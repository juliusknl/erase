import pytest

from erasure.replies import ReplyKind, assess_sender, classify_reply, extract_case_token


@pytest.mark.parametrize('quote', [
    '-----Ursprüngliche Nachricht-----\nPlease provide your phone number.',
    "-----Message d'origine-----\nPlease provide your phone number.",
    'W poniedziałek Privacy napisał(a):\nPlease provide your phone number.',
    'Hello Example Privacy Team,\nPlease confirm deletion of my personal data.',
])
def test_receipt_ignores_multilingual_and_repeated_original_requests(quote):
    assert classify_reply('Re: deletion', 'We received your request.\n' + quote).kind == ReplyKind.CONFIRMATION


@pytest.mark.parametrize('body, expected', [
    ('Please provide the mobile advertising identifiers (AAIDs) of your devices.', ReplyKind.INFORMATION_REQUESTED),
    ('Please provide your phone number so we can locate your record.', ReplyKind.INFORMATION_REQUESTED),
    ('Please reply to confirm that you want us to proceed with your deletion request.', ReplyKind.ACTION_REQUIRED),
    ('We have removed your information from our database.', ReplyKind.COMPLETED),
    ('We did not find any profiles matching the data points provided.', ReplyKind.NOT_FOUND),
    ('Our system does not contain any details associated with this email address.', ReplyKind.NOT_FOUND),
    ('Your ticket has been resolved. We submitted your request for processing. Your data will be removed.\nHello Example Privacy Team,\nPlease confirm deletion.', ReplyKind.CONFIRMATION),
])
def test_audited_reply_patterns_without_ai(body, expected):
    assert classify_reply('Your privacy request', body).kind == expected


@pytest.mark.parametrize('body', [
    'We have not removed your information.',
    'We have removed your request from our queue.',
    'Your request for deletion has been removed from the queue.',
    'We have removed your email from our marketing mailing list.',
])
def test_request_cancellation_and_suppression_are_not_deletion(body):
    assert classify_reply('Re: deletion completed', body).kind != ReplyKind.COMPLETED


def test_access_only_appendix_does_not_create_identity_task_for_deletion():
    from erasure.replies import removal_reply_text
    body = ("We received your deletion request.\n\n"
            "If you've sent a right to know request, please read and do the following:\n\n"
            "Please provide a government-issued ID before we can act on your request to know.")
    assert 'government' not in removal_reply_text(body)
    assert classify_reply('Privacy', body).kind != ReplyKind.IDENTITY_REQUESTED


def test_optional_extra_identifiers_do_not_make_a_receipt_homework():
    body = ('We received your request. If your request included deletion, it has been processed. '
            'If you believe there are other emails or addresses that could match, please reply with that information.\n\n'
            "If you've sent a right to know request, please read and do the following:\n\n"
            'Please provide a government-issued ID.')
    assert classify_reply('Privacy', body).kind == ReplyKind.CONFIRMATION


def test_designated_form_instruction_wins_over_generic_acknowledgement():
    body = ('We will review your request. If your email concerns consumer rights, '
            'please submit your request via one of our designated methods: Web Intake Form Access: https://example.test/form')
    assert classify_reply('Privacy', body).kind == ReplyKind.FORM_REQUIRED


def test_matching_mailbox_step_is_not_a_confirmation_link():
    from erasure.replies import matching_mailbox_required
    assert matching_mailbox_required('Please send us a new email/ticket from the email address listed confirming your name.')
    assert matching_mailbox_required('You need to send us your request via either email, mentioned on our website or via any your business email.')
    assert not matching_mailbox_required('Please verify your email using the link below.')


@pytest.mark.parametrize('body', [
    'Thank you for submitting your request. Your request will be processed and completed within the next 30 days.',
    'We are processing your request.',
    'We’re all set. Your ticket (#123) has been resolved. If not, simply reply to this email to let us know.',
])
def test_routine_updates_do_not_need_classification(body):
    assert classify_reply('Your request', body).kind in {ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL}


def test_acknowledgement_does_not_hide_an_explicit_portal_step():
    assert classify_reply('Received', 'We received your request. Please log into our portal to continue.').kind == ReplyKind.ACTION_REQUIRED


@pytest.mark.parametrize('body', [
    'If you are looking to make a data subject privacy request, please visit https://broker.test/remove.',
    'If your email concerns a consumer rights request, please submit your request via our designated method.',
    'We acknowledge receipt of your request. So please do click the link above so we may address your request.',
])
def test_conditional_privacy_instructions_are_not_optional_support_footers(body):
    from erasure.replies import actionable_reply
    assert actionable_reply(body)


@pytest.mark.parametrize('body', [
    'Your ticket has been resolved. If you have any further questions, please reply to this message.',
    'We have added your information to the removal queue, which will be completed within 24-72 hours.',
])
def test_optional_support_footer_and_removal_queue_do_not_create_tasks(body):
    from erasure.replies import actionable_reply
    assert not actionable_reply(body)


@pytest.mark.parametrize("body", [
    "We are processing your request.\nOn Monday you wrote:\nYour data has been deleted.",
    "We are processing your request.\n> Your data has been deleted.",
    "We are processing your request.\nFrom: privacy@example.test\nDeletion complete.",
    "Bitte warten.\nAm Montag schrieb Privacy:\nDeletion complete.",
    "Please confirm whether your data has been deleted.",
    "If your data has been deleted, it cannot be recovered.",
    "We will let you know when your data has been deleted.",
    "Your data has been deleted? Please confirm.",
    "We are still investigating your request.",
    "If we hold no personal data, we will tell you.",
])
def test_quotes_subjects_questions_and_promises_are_not_outcome_evidence(body):
    reply = classify_reply("Re: Deletion complete", body)
    assert reply.kind not in {ReplyKind.COMPLETED, ReplyKind.NOT_FOUND}


def test_current_outcome_takes_precedence_over_quoted_form_request():
    reply = classify_reply("Your request", "Your personal data has been deleted.\n"
                           "On Monday we wrote:\nPlease use our Privacy Request Center.")
    assert reply.kind == ReplyKind.COMPLETED


def test_form_instruction_and_german_acknowledgement_are_distinct():
    assert (
        classify_reply(
            "Datenschutz", "Hiermit bestätigen wir Ihnen den Eingang Ihrer\nDatenschutzanfrage."
        ).kind
        == ReplyKind.CONFIRMATION
    )
    assert (
        classify_reply(
            "Privacy", "Please use our Privacy Request Center. We do not respond to requests here."
        ).kind
        == ReplyKind.FORM_REQUIRED
    )
    assert (
        classify_reply(
            "Datenschutz", "Hiermit bestätigen wir Ihnen den Eingang Ihrer Datenschutzanfrage."
        ).kind
        == ReplyKind.CONFIRMATION
    )
    assert (
        classify_reply("Privacy", "Visit our privacy policy for more information.").kind
        == ReplyKind.AMBIGUOUS
    )


def test_form_links_must_be_same_domain_and_actionable():
    from erasure.models import Broker
    from erasure.replies import request_form_url

    broker = Broker(domain="sample.test", required_fields="{}")
    assert request_form_url(broker, "https://sample.test/privacy-policy") == ""
    assert request_form_url(broker, "https://sample.test.attacker.test/remove") == ""
    assert (
        request_form_url(broker, "https://sample.test/remove-profile")
        == "https://sample.test/remove-profile"
    )


def test_reply_classification() -> None:
    reply = classify_reply("Request ER-00000A", "Your personal information has been deleted.")
    assert reply.kind == ReplyKind.COMPLETED
    assert reply.confidence >= 90


@pytest.mark.parametrize("body", [
    "Please confirm your email using the link below.",
    "We received your request. Please verify your email address.",
    "Confirm your deletion request using the button below.",
    "Click the link below to verify your email address.",
    "Bitte bestätigen Sie Ihre E-Mail-Adresse.",
])
def test_email_verification_is_not_a_receipt(body):
    assert classify_reply("Your request", body).kind == ReplyKind.EMAIL_VERIFICATION


def test_inherited_subject_and_quoted_verification_do_not_create_a_new_task():
    assert classify_reply("Please confirm your email", "We received your request.\n"
                          "On Monday we wrote:\nPlease confirm your email.").kind == ReplyKind.CONFIRMATION


def test_identity_request_and_token() -> None:
    reply = classify_reply("Re: request", "Please provide a government-issued ID to proceed")
    assert reply.kind == ReplyKind.IDENTITY_REQUESTED
    assert extract_case_token("Re: ER-ABC123", "") == "ER-ABC123"
    assert extract_case_token("No ref", "none") is None


def test_sender_requires_authentication_and_broker_alignment() -> None:
    trusted = assess_sender(
        "Privacy Team <privacy@mail.broker.test>",
        "mx.google.com; dkim=pass header.i=@mail.broker.test; dmarc=pass header.from=broker.test",
        broker_domain="broker.test",
        broker_contact="privacy@broker.test",
    )
    assert trusted.trusted

    unauthenticated = assess_sender(
        "privacy@broker.test",
        "mx.google.com; spf=fail; dkim=none; dmarc=fail",
        broker_domain="broker.test",
        broker_contact="privacy@broker.test",
    )
    assert unauthenticated.trusted is False

    wrong_domain = assess_sender(
        "privacy@lookalike.test",
        "mx.google.com; dmarc=pass header.from=lookalike.test",
        broker_domain="broker.test",
        broker_contact="privacy@broker.test",
    )
    assert wrong_domain.trusted is False

    forged_authentication_header = assess_sender(
        "privacy@broker.test",
        "attacker.example; dmarc=pass header.from=broker.test",
        broker_domain="broker.test",
        broker_contact="privacy@broker.test",
    )
    assert forged_authentication_header.trusted is False


def test_folded_gmail_authentication_preserves_verdicts():
    def check(headers):
        return assess_sender(
            "privacy@broker.test",
            headers,
            broker_domain="broker.test",
            broker_contact="privacy@broker.test",
        )

    assert check(
        "mx.google.com;\r\n       dkim=pass header.i=@broker.test;\r\n       dmarc=pass header.from=broker.test"
    ).trusted
    assert not check(
        "mx.google.com; dmarc=fail\r\nattacker.test; dmarc=pass header.from=broker.test"
    ).trusted
