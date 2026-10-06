"""Browser-local presentation preferences; never part of sending consent."""

THEMES = {
    'porcelain': {'name': 'Porcelain', 'scheme': 'light'},
    'conservatory': {'name': 'Conservatory', 'scheme': 'dark'},
    'atelier': {'name': 'Atelier', 'scheme': 'light'},
    'midnight': {'name': 'Midnight', 'scheme': 'dark'},
}
DEFAULT = 'porcelain'


def cookie_name(demo=False):
    return 'erasure_demo_appearance' if demo else 'erasure_appearance'


def current(request, demo=False):
    value = request.cookies.get(cookie_name(demo))
    return value if value in THEMES else DEFAULT


def remember(response, value, settings):
    if value not in THEMES:
        raise ValueError('Unknown appearance')
    response.set_cookie(cookie_name(settings.demo_mode), value, max_age=365 * 24 * 60 * 60,
                        httponly=True, secure=settings.base_url.startswith('https://'),
                        samesite='lax', path='/')
    return response
