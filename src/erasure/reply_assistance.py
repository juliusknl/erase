"""Optional reply assistance settings. Keys stay encrypted and never enter UI context."""

from erasure import chatgpt_auth
from erasure.jev import JevClassifier, JevError

SETTING = 'reply_assistance'
ERRORS = {
    'chatgpt_state': 'This sign-in expired or could not be verified. Start again.',
    'chatgpt_identity': 'ChatGPT sign-in could not be verified. Reconnect the selected account.',
    'chatgpt_cancelled': 'ChatGPT connection was cancelled.',
    'chatgpt_reconnect': 'Reconnect ChatGPT to renew access.',
    'chatgpt_permission': 'Allow ChatGPT plan usage when connecting. An eligible plan is required.',
    'chatgpt_loopback': 'Open erase at http://127.0.0.1 on its configured port to connect ChatGPT.',
    'chatgpt_model_unavailable': 'OpenAI did not allow GPT-6 Luna for this account. Try a different account or use Jev.',
    'chatgpt_invalid_response': 'ChatGPT returned an unusable or interrupted response. Try again shortly.',
    'chatgpt_unavailable': 'ChatGPT could not be reached. Try again shortly.',
    'chatgpt_limit': 'ChatGPT usage is unavailable or its allowance is exhausted. Check your ChatGPT usage settings.',
    'chatgpt_check_failed': 'The sample reply check did not pass. Your working connection was not replaced.',
    'chatgpt_ineligible': 'OpenAI does not allow ChatGPT plan usage for this account or workspace. Use another eligible account or Jev.',
    'chatgpt_unsupported_request': 'OpenAI rejected an unsupported setting in the reply check. This needs an app fix, not another sign-in.',
    'chatgpt_integration_error': 'OpenAI rejected the integration’s permission or route. This needs an app fix, not repeated sign-ins.',
    'chatgpt_busy': 'Another ChatGPT connection update is in progress. Try again shortly.',
    'chatgpt_settings_changed': 'Reply assistance changed during sign-in. Start again to use ChatGPT.',
    'missing_key': 'Paste your TypeSafe API key to connect.',
    'invalid_key': 'That key doesn’t look right. Copy it again from TypeSafe.',
    'http_401': 'TypeSafe didn’t accept this key. Copy a new key and try again.',
    'http_403': 'This key doesn’t have access to Jev. Check your TypeSafe account.',
    'http_402': 'Add credit in TypeSafe, then try again.',
    'http_429': 'TypeSafe is busy or your usage limit was reached. Try again shortly.',
    'provider_unavailable': 'TypeSafe couldn’t be reached. Try again shortly.',
    'invalid_response': 'TypeSafe didn’t return a usable response. Try again shortly.',
}


def selection(settings, store=None):
    if settings.demo_mode:
        provider = store.get_setting('demo_reply_assistance_provider', 'jev') if store else 'jev'
        return {'provider': provider, 'enabled': False}
    selected = chatgpt_auth.read(store, chatgpt_auth.PROVIDER) if store else None
    if selected:
        return selected
    return {'provider': 'jev', 'enabled': configuration(settings, store)[0]}


def configuration(settings, store=None):
    if settings.demo_mode:
        return False, ''
    saved = store.get_setting(SETTING) if store else None
    if isinstance(saved, dict):
        key = saved.get('api_key', '')
        return bool(saved.get('enabled') and key), key
    return settings.jev_enabled and bool(settings.typesafe_api_key.get_secret_value()), settings.typesafe_api_key.get_secret_value()


def public_status(settings, store):
    on, key = configuration(settings, store)
    selected = selection(settings, store)
    accounts = [] if settings.demo_mode else [
        {'id': identifier, 'label': record.get('label', 'Account'), 'email': record.get('email', ''),
         'connected': bool(record.get('refresh_token'))}
        for identifier, record in chatgpt_auth.read(store, chatgpt_auth.SETTING, {}).items()]
    details = {'provider': selected['provider'], 'account': selected.get('account', ''), 'accounts': accounts,
               'can_retry_chatgpt': False if settings.demo_mode else chatgpt_auth.can_retry(store)}
    if settings.demo_mode:
        on = bool(store.get_setting('demo_reply_assistance', False))
        return {**details, 'enabled': on, 'has_key': False, 'label': 'Demo connected' if on else 'Off', 'error': ''}
    on = selected['enabled']
    health = store.get_setting(selected['provider'] + '_health', {})
    error = (ERRORS.get(health.get('error'), 'Reply assistance is temporarily unavailable.')
             if on and health.get('error') else '')
    return {**details, 'enabled': on, 'has_key': bool(key), 'label': 'Needs attention' if error else ('On' if on else 'Off'), 'error': error}


def check_connection(api_key):
    """Only a fixed synthetic reply is used; no user mail or profile is sent."""
    if not api_key:
        raise JevError('missing_key')
    if len(api_key) > 512 or not all(33 <= ord(char) <= 126 for char in api_key):
        raise JevError('invalid_key')
    classifier = JevClassifier(api_key)
    try:
        classifier.classify('Test removal request', 'We received your request and will process it within 30 days.')
    finally:
        classifier.close()


def connect(settings, store, api_key):
    if settings.demo_mode:
        store.set_setting('demo_reply_assistance', True, encrypted=True)
        store.set_setting('demo_reply_assistance_provider', 'jev', encrypted=True)
        return
    _, previous_key = configuration(settings, store)
    key = api_key.strip() or previous_key
    check_connection(key)
    store.set_setting(SETTING, {'enabled': True, 'api_key': key}, encrypted=True)
    store.set_setting(chatgpt_auth.PROVIDER, {'provider': 'jev', 'enabled': True}, encrypted=True)
    health = store.get_setting('jev_health', {})
    store.set_setting('jev_health', {**health, 'error': '', 'retry_after': ''}, encrypted=True)


def turn_off(settings, store, *, forget=False):
    if settings.demo_mode:
        store.set_setting('demo_reply_assistance', False, encrypted=True)
        return
    selected = selection(settings, store)
    if selected['provider'] == 'chatgpt':
        if forget:
            return chatgpt_auth.disconnect(store, selected.get('account', ''))
        store.set_setting(chatgpt_auth.PROVIDER, {**selected, 'enabled': False}, encrypted=True)
        return
    _, key = configuration(settings, store)
    # An explicit empty override prevents an environment key from silently taking over.
    store.set_setting(SETTING, {'enabled': False, 'api_key': '' if forget else key}, encrypted=True)
    store.set_setting(chatgpt_auth.PROVIDER, {'provider': 'jev', 'enabled': False}, encrypted=True)
