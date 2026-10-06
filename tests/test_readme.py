"""Keep the source landing page useful and its release images intact."""

import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from erasure.catalog_readiness import readiness
from erasure.config import Settings

ROOT = Path(__file__).parents[1]


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {'href', 'src'} and value:
                self.urls.append(value)


def test_readme_local_links_and_images_exist():
    readme = (ROOT / 'README.md').read_text()
    references = References()
    references.feed(readme)
    references.urls.extend(re.findall(r'\]\(([^)]+)\)', readme))
    local = []
    for url in references.urls:
        parsed = urlsplit(url)
        if parsed.scheme or not parsed.path:
            continue
        target = (ROOT / unquote(parsed.path)).resolve()
        assert target.is_relative_to(ROOT.resolve()), url
        assert target.is_file(), url
        local.append(parsed.path)
    assert {'docs/assets/erase-banner.svg', 'docs/assets/erase-dashboard.png'} <= set(local)
    assert 'fictional demo data' in readme
    assert readme.index('fictional demo data') < readme.index('](docs/assets/erase-dashboard.png)')


def test_readme_route_counts_match_the_declared_alpha():
    readme = (ROOT / 'README.md').read_text()
    scope = readiness(Settings(_env_file=None, catalog_dir=ROOT / 'catalog'))
    assert f"{scope['email_workflows']} reviewed automatic email workflows" in readme
    assert f"{scope['guided_forms']} guided manual routes" in readme


def test_readme_media_are_valid_self_contained_assets():
    banner = ElementTree.parse(ROOT / 'docs/assets/erase-banner.svg')  # noqa: S314 - trusted authored SVG
    assert banner.getroot().tag == '{http://www.w3.org/2000/svg}svg'
    assert not any(node.tag.endswith(('script', 'foreignObject')) for node in banner.iter())
    assert all(not value.startswith(('https:', 'http:'))
               for node in banner.iter() for value in node.attrib.values())
    screenshot = (ROOT / 'docs/assets/erase-dashboard.png').read_bytes()
    assert screenshot.startswith(b'\x89PNG\r\n\x1a\n')
    width, height = struct.unpack('>II', screenshot[16:24])
    assert width >= 1000 and height >= 600
    assert len(screenshot) < 2_000_000
