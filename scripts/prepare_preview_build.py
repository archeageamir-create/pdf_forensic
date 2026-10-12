"""Inventory the local preview's build environment without rewriting release SBOMs.

The standalone preview bundles Python libraries, scripts and every CLI engine.
This is a build inventory, not an Authenticode/public-release audit.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__
from scripts.prepare_runtime_dependencies import verify_bundle
from scripts.generate_compliance import (
    _copy_distribution_licenses,
    _license_expression,
    _package,
    _project_url,
)


def prepare(*, release: bool = False) -> Path:
    runtime = verify_bundle()
    target = ROOT / "build" / ("release-resources" if release else "preview-resources")
    if target.exists():
        if not target.resolve().is_relative_to((ROOT / "build").resolve()):
            raise ValueError("Build resources escape the build directory")
        target.rename(target.with_name(target.name + "-previous-" + uuid.uuid4().hex))
    target.mkdir(parents=True, exist_ok=True)
    project_url = "https://github.com/archeageamir-create/pdf_forensic"
    packages = [
        _package(
            name="Document Forensic Inspector" if release else "Document Forensic Inspector Universal Preview",
            version=__version__ if release else __version__ + "+universal",
            license_id="Apache-2.0",
            supplier="Organization: ANSE LLP",
            homepage=project_url,
            source=project_url,
            scope="application",
        )
    ]
    packages.append(
        _package(
            name="CPython",
            version=platform.python_version(),
            license_id="PSF-2.0",
            supplier="Organization: Python Software Foundation",
            homepage="https://www.python.org",
            source=f"https://www.python.org/ftp/python/{platform.python_version()}/Python-{platform.python_version()}.tgz",
        )
    )
    inventory = []
    notices = [
        "# Document Forensic Inspector — build inventory",
        "",
        "This standalone build bundles Python, Qt, ExifTool (including Perl), qpdf, pdfcpu, Poppler, ffprobe, Java, JHOVE, veraPDF, PDFBox and the repository PDF scripts. No separate runtime installation is needed. Exact engine files and hashes are in binaries/RUNTIME_MANIFEST.json; upstream download hashes are in compliance/runtime-dependencies.lock.json.",
        "",
        "The inventory records the actual build environment; build-only packages are labelled separately. Third-party rights and license notices are retained. This distribution is unsigned.",
        "",
    ]
    for component in runtime["components"]:
        packages.append(_package(
            name=component["name"], version=component["version"],
            license_id=component["license"], supplier="NOASSERTION",
            homepage=component["url"], source=component["url"],
            scope="bundled external engine",
        ))
        notices.append(f"- Bundled {component['name']} {component['version']}: {component['license']}. Upstream: {component['url']}.")
    provenance = json.loads((ROOT / "compliance/source-records/poppler-provenance.json").read_text(encoding="utf-8"))
    for component in provenance["components"]:
        if component["component"] == "poppler":
            continue
        packages.append(_package(name="Poppler dependency: " + component["component"], version=component["version"], license_id=component["license"], supplier="NOASSERTION", homepage=component["package_url"], source=component["sources"][0]["url"], scope="bundled native library"))
        notices.append(f"- Poppler dependency {component['component']} {component['version']}: {component['license']}. Exact source and patches: compliance/source-records/conda.")
    notices.extend([
        "- Microsoft Visual C++ runtime DLLs: Microsoft Software License Terms; supplied with the pinned qpdf/Java/CPython packages. These runtime files are not covered by the application's Apache license.",
        "- Saxon-HE 11.4 and 12.8: MPL-2.0; source JARs and build POMs included in the dependency-source supplement.",
        "- Pillow 12.3.0 includes an LGPL-2.1-or-later FriBiDi loading shim. Its source and the sources for rebuilding the text-shaping module are included. The optional GPL libimagequant feature is disabled in this build.",
        "- Additional QtBase, QtSvg and QtImageFormats attribution/license files: licenses/repository-notices/qt-third-party.",
    ])
    for distribution in sorted(
        metadata.distributions(), key=lambda d: d.metadata["Name"].lower()
    ):
        name = distribution.metadata["Name"]
        if name == "document-forensics-lab":
            continue
        license_id = _license_expression(distribution)
        copied = _copy_distribution_licenses(
            distribution, target / "licenses" / "python" / name
        )
        package = _package(
            name=name,
            version=distribution.version,
            license_id=license_id,
            supplier="NOASSERTION",
            homepage=_project_url(distribution),
            source="NOASSERTION",
            scope="build environment",
        )
        packages.append(package)
        inventory.append(
            {
                "name": name,
                "version": distribution.version,
                "license": license_id,
                "license_files": copied,
            }
        )
        notices.append(
            f"- {name} {distribution.version}: {license_id}. License files: {copied}."
        )
    from PySide6.QtCore import qVersion

    qt_version = qVersion()
    packages.append(
        _package(
            name="Qt libraries used by PySide6",
            version=qt_version,
            license_id="LGPL-3.0-only OR GPL-3.0-only OR LicenseRef-Qt-Commercial",
            supplier="Organization: The Qt Company",
            homepage="https://www.qt.io",
            source=f"https://download.qt.io/archive/qt/{'.'.join(qt_version.split('.')[:2])}/{qt_version}/submodules/",
        )
    )
    # Include the original script notices and LGPL replacement instructions.
    shutil.copytree(
        ROOT / "app/resources/licenses",
        target / "licenses" / "repository-notices",
        dirs_exist_ok=True,
    )
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, target / "licenses" / "CPython-LICENSE.txt")
    for filename in ("pdfid.py", "pdf-parser.py"):
        script = ROOT / "app/resources/tools" / filename
        packages.append(
            _package(
                name=filename,
                version="repository copy",
                license_id="LicenseRef-Public-Domain",
                supplier="Person: Didier Stevens",
                homepage="https://blog.didierstevens.com/",
                source="https://github.com/DidierStevens/DidierStevensSuite",
                artifact=script,
                scope="tool script",
            )
        )
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "DFI build environment",
        "documentNamespace": "https://spdx.org/spdxdocs/dfi-preview-"
        + str(uuid.uuid4()),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: prepare_preview_build.py"],
        },
        "documentDescribes": [packages[0]["SPDXID"]],
        "packages": packages,
        "relationships": [],
        "hasExtractedLicensingInfos": [
            {
                "licenseId": "LicenseRef-Public-Domain",
                "extractedText": "Tool scripts retain the public-domain dedication in their source headers.",
            },
            {
                "licenseId": "LicenseRef-Qt-Commercial",
                "extractedText": "Alternative commercial Qt license; this build does not assert a commercial Qt entitlement.",
            },
        ],
    }
    source_files = [
        path
        for path in (ROOT / "app").rglob("*")
        if path.is_file() and path.suffix == ".py"
    ]
    manifest = {
        "created_utc": created,
        "base_version": __version__,
        "build": "release" if release else "universal-preview",
        "standalone": True,
        "runtime_manifest_sha256": hashlib.sha256((ROOT / "app/resources/binaries/RUNTIME_MANIFEST.json").read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "qt": qt_version,
        "python_build_environment": inventory,
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(source_files)
        },
    }
    (target / "BUILD_INVENTORY.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "SBOM.spdx.json").write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "THIRD_PARTY_NOTICES.md").write_text("\n".join(notices), encoding="utf-8")
    print(target)
    return target


if __name__ == "__main__":
    prepare()
