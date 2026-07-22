# Security policy

Do not attach real evidence files, exported reports, case databases, passwords,
private signing keys or personal data to public issues.

Security reports should initially contain only a minimal reproducible example
created from synthetic data. If a report requires a real document, agree on a
private transfer channel with the maintainer before sending it.

The application processes untrusted documents locally. External analyzers are
executed against a working copy, never against the original file. This design
reduces evidence-integrity risk but does not make every bundled parser a
sandbox. Analyze hostile documents on an isolated workstation where the case
requires it.
