# Source delivery status for 0.5.0

The public application source archive contains the shell, build scripts,
dependency download lock, tests, documentation and legal notices. The application
is Apache-2.0; third-party components retain their own terms.

Eight upstream source archives have been collected for PySide6/shiboken6, Qt,
Poppler, poppler-data, JHOVE, veraPDF applications, OpenJDK and FFmpeg core.
Their archive names and upstream locations are in THIRD_PARTY_SOURCES.json.
The dependency-source delivery includes SHA-256 values for the actual downloads.
All eight archives were read as TAR archives without extraction errors.

This collection is not a certification that every upstream binary can be
reproduced from it. In particular, the complete corresponding sources and build
instructions for every static dependency in the third-party ffprobe build have
not yet been verified. The FFmpeg core archive alone does not resolve that gap.
Transitive dependencies in upstream binary distributions also require matching
against their retained notices and build information before public distribution.

Release readiness therefore remains conditional on completing that source
coverage review. A successful packaging audit checks presence of legal files
and accidental private-data leakage; it does not certify legal compliance.
The written source offer and original upstream notices remain in the package.
