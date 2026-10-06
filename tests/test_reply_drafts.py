import pytest

from erasure.reply_drafts import prepare_reply


def test_requested_details_only_and_conditional_fallback():
    draft = prepare_reply(
        "If you are unable to complete the Privacy Request Center, kindly respond to this email with the following information: Full Name; Country and State/Province of residence; City of residence; Email address you wish to access; Phone number you wish to access.",
        {
            "full_name": "Test Person",
            "other_emails": ["real@example.test"],
            "phone": "+1234567",
            "postal_address": "PRIVATE STREET",
            "birth_date": "PRIVATE DOB",
        },
    )
    assert "Test Person" in draft["body"] and "real@example.test" in draft["body"]
    assert "+1234567" in draft["body"]
    assert "PRIVATE" not in draft["body"]
    assert "[ADD why you could not complete the form]" in draft["body"]
    assert "City of residence" in draft["missing"]


@pytest.mark.parametrize(
    "body",
    [
        "Your ticket has been resolved. If not, simply reply to this email.",
        "We received your request. This message contains information which is confidential. Please reply to the sender if received in error.",
        "Your data has been deleted.",
    ],
)
def test_no_unnecessary_reply_to_closures_or_acknowledgements(body):
    assert prepare_reply(body, {}) == {}


def test_incomplete_draft_cannot_be_sent(db, vault):
    from erasure.config import Settings
    from erasure.store import Store
    from erasure.workflow import Workflow

    with pytest.raises(ValueError, match="placeholders"):
        Workflow(db, Store(db, vault), Settings()).send_reply(
            1, "privacy@example.test", "[ADD city]"
        )


def test_device_identifier_request_does_not_disclose_unrelated_profile_fields():
    draft = prepare_reply(
        "We must know the Mobile Ad ID (MAID) of your device. Please provide it.",
        {
            "full_name": "Test Person",
            "postal_address": "PRIVATE",
            "other_emails": ["PRIVATE@example.test"],
        },
    )
    assert "[ADD mobile advertising ID]" in draft["body"]
    assert "PRIVATE" not in draft["body"]


def test_plural_device_identifiers_and_aaid_prepare_specific_step():
    draft = prepare_reply('Please provide the mobile advertising identifiers (AAIDs) of your devices.', {
        'other_emails': ['PRIVATE@example.test'], 'postal_address': 'PRIVATE',
    })
    assert draft['missing'] == ['Mobile Advertising ID']
    assert 'PRIVATE' not in draft['body']


@pytest.mark.parametrize('body', [
    'Please reply to confirm that you want us to proceed with your deletion request.',
    'Please confirm you would like to proceed with the request. You may also use our form.',
])
def test_reply_to_confirm_does_not_ask_user_to_invent_information(body):
    draft = prepare_reply(body, {'full_name': 'Test Person'})
    assert draft['missing'] == []
    assert 'confirm' in draft['body'].lower()
    assert '[ADD' not in draft['body']


def test_no_match_suggests_existing_aliases_and_ignores_quoted_request():
    draft = prepare_reply(
        "Our system does not contain any details associated with this email address.\nOn Wed someone wrote:\nPlease provide your phone number.",
        {"other_emails": ["work@example.test"], "phone": "PRIVATE"},
    )
    assert "work@example.test" in draft["body"]
    assert "PRIVATE" not in draft["body"]


def test_requested_professional_fields_are_prepared_without_unrelated_data():
    draft = prepare_reply("Please provide your work email address and employer.", {
        "work_email": "work@example.test", "employer": "Synthetic Company",
        "other_emails": ["PRIVATE@example.test"], "postal_address": "PRIVATE STREET",
    })
    assert "work@example.test" in draft["body"]
    assert "Synthetic Company" in draft["body"]
    assert "PRIVATE" not in draft["body"]
    assert draft["missing"] == []


def test_corporate_email_request_ignores_incidental_employer_description():
    draft = prepare_reply('Our database includes company names and professional emails. '
                          'We require your corporate (work) email address to locate your records.', {
        'work_email': 'work@example.test', 'employer': 'PRIVATE COMPANY',
        'other_emails': ['PRIVATE@example.test'],
    })
    assert draft['disclosed'] == ['Work email to check']
    assert 'PRIVATE' not in draft['body']


def test_german_postal_matching_requires_a_personal_disclosure_choice():
    draft = prepare_reply('Für die erforderliche Recherche benötigen wir daher Ihre komplette Postadresse (PLZ und Ort).', {
        'postal_address': 'PRIVATE STREET', 'other_emails': ['PRIVATE@example.test'],
    })
    assert draft['missing'] == ['Postal address (only if you choose to share it)']
    assert 'PRIVATE' not in draft['body']
