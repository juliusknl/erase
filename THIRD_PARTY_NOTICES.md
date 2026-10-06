# Third-party components

erase uses third-party software under its respective licenses. Its own license
does not replace those terms. The exact Python dependency versions and hashes are
in `requirements.lock`; development dependencies are recorded in `uv.lock`.

The macOS preview preserves the bundled runtime and installed distributions'
license files, including nested notices. In the app bundle:

- Python's license is in `Contents/Resources/python/lib/python3.13/LICENSE.txt`
  (the version directory follows the build interpreter).
- Python package licenses and metadata are in that directory's `site-packages`,
  usually under each `*.dist-info/licenses/` directory or its `METADATA` file.
- Native and vendored components, including libsodium, Playwright's driver and
  Python's bundled libraries, retain the notices included in their distributions.
- App source and this notice are in `Contents/Resources/app`.

Builds copy an unmodified uv-managed standalone Python runtime before installing
the hash-locked dependencies. The platform runtime's own provenance and all
redistribution obligations must be checked for each publicly shipped build; this
inventory is not a completed legal/compliance certification.

Broker catalog entries reference official public sources and contain factual
metadata and limited supporting excerpts. Broker names and marks belong to their
owners; catalog inclusion does not imply affiliation or endorsement. No user's
private correspondence or personal experiment database belongs in the release.

The ChatGPT sign-in logo is the official OpenAI asset from
https://developers.openai.com/assets/siwc/sign-in-buttons/chatgpt-logo-white.svg.
OpenAI and ChatGPT names and marks belong to OpenAI. The asset is used for the
official sign-in button and remains subject to OpenAI's branding guidelines;
erase's MIT license does not grant rights to third-party marks.
