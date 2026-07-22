# Public release checklist

## Repository hygiene

- [ ] `git status --ignored` shows that `.verification`, `.downloads`, build
  output, databases, logs and private-key formats are excluded.
- [ ] No real evidence, report export, local absolute path or user identifier is
  present in tracked files.
- [ ] Only the public `.cer` certificate is tracked; no `.pfx`, `.p12`, `.pem`
  or `.key` exists in the repository.
- [ ] `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `SOURCE_OFFER.md`,
  `SBOM.spdx.json` and `LICENSES/` are present.

## License compliance

- [ ] Run `python scripts/generate_compliance.py --check` in the clean build
  environment.
- [ ] Every bundled binary has an exact component/version entry and a license.
- [ ] Corresponding source archives listed in `third_party_sources/SOURCES.json`
  are mirrored as a release asset or remain available under the written offer.
- [ ] LGPL replacement/rebuild instructions have been tested.
- [ ] Apache NOTICE files and third-party copyright notices are not removed.

## Release

- [ ] Unit tests pass.
- [ ] The installed application and each helper executable are Authenticode
  signed before the installer is assembled.
- [ ] The installer is signed and timestamped.
- [ ] Release SHA-256 values are published separately from the binaries.
- [ ] The compliance archive and exact application source archive accompany the
  binary release.

This checklist is an engineering control, not a substitute for legal advice in
the jurisdictions where the software is distributed.
