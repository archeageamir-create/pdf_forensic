"""Generate license bundle, third-party notices and an SPDX 2.3 SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "compliance" / "components.json"
LICENSE_ROOT = PROJECT_ROOT / "app" / "resources" / "licenses"
RESOURCE_ROOT = PROJECT_ROOT / "app" / "resources"
NOTICE_PATH = RESOURCE_ROOT / "THIRD_PARTY_NOTICES.md"
SBOM_PATH = RESOURCE_ROOT / "SBOM.spdx.json"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", value).strip("-.") or "component"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_url(dist: metadata.Distribution) -> str:
    for item in dist.metadata.get_all("Project-URL") or []:
        if "," in item:
            label, url = item.split(",", 1)
            if label.strip().lower() in {"homepage", "source", "repository", "documentation"}:
                return url.strip()
    return (dist.metadata.get("Home-page") or "NOASSERTION").strip()


def _license_expression(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    raw = (dist.metadata.get("License") or "NOASSERTION").strip()
    known = {
        "MIT License": "MIT",
        "BSD License": "BSD-3-Clause",
        "Apache Software License": "Apache-2.0",
    }
    return known.get(raw, raw if len(raw) < 120 else "NOASSERTION")


def _copy_distribution_licenses(dist: metadata.Distribution, destination: Path) -> int:
    copied = 0
    seen: set[str] = set()
    for relative in dist.files or []:
        name = relative.name.lower()
        lowered_parts = [part.lower() for part in relative.parts]
        dist_info_license_dir = any(
            part == "licenses" and any(
                parent.endswith(".dist-info") for parent in lowered_parts[:index]
            )
            for index, part in enumerate(lowered_parts)
        )
        if not (
            dist_info_license_dir
            or name.startswith(("license", "copying", "notice", "authors"))
        ):
            continue
        source = Path(dist.locate_file(relative))
        if not source.is_file():
            continue
        try:
            marker = next(
                index for index, part in enumerate(relative.parts)
                if part.lower() == "licenses"
            )
            clean_relative = Path(*relative.parts[marker + 1 :])
        except StopIteration:
            clean_relative = Path(relative.name)
        if not clean_relative.parts:
            clean_relative = Path(relative.name)
        target = destination / clean_relative
        key = str(target).casefold()
        if key in seen:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        seen.add(key)
        copied += 1
    return copied


def _extract_jar_notices(jar_path: Path, destination: Path) -> int:
    if not jar_path.is_file():
        return 0
    if destination.is_dir():
        shutil.rmtree(destination)
    copied = 0
    with zipfile.ZipFile(jar_path) as archive:
        for member in archive.namelist():
            name = Path(member).name.lower()
            if Path(member).suffix.lower() == ".class":
                continue
            if not (
                re.search(r"(?:^|[._-])(?:license|notice|copying)(?:[._-]|$)", name)
                or name == "dependencies"
            ):
                continue
            if member.endswith("/"):
                continue
            flattened = member.replace("/", "__").replace("\\", "__")
            target = destination / flattened
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            copied += 1
    return copied


def _maven_license(group: str) -> str:
    if group.startswith("org.apache.pdfbox"):
        return "Apache-2.0"
    if group.startswith("org.openpreservation.jhove"):
        return "LGPL-2.1-or-later"
    if group.startswith(("org.verapdf", "org.verapdf.apps")):
        return "MPL-2.0 OR GPL-3.0-or-later"
    if group.startswith("com.fasterxml.jackson"):
        return "Apache-2.0"
    if group.startswith(("jakarta.json", "org.eclipse.parsson")):
        return "EPL-2.0 OR (GPL-2.0-only WITH Classpath-exception-2.0)"
    if group == "com.sun.istack":
        return "BSD-3-Clause"
    return "NOASSERTION"


def _discover_maven_packages() -> list[dict[str, Any]]:
    discovered: dict[tuple[str, str, str], tuple[dict[str, str], Path]] = {}
    for jar_path in (PROJECT_ROOT / "app" / "resources" / "binaries").rglob("*.jar"):
        try:
            with zipfile.ZipFile(jar_path) as archive:
                for member in archive.namelist():
                    if not member.endswith("pom.properties"):
                        continue
                    values: dict[str, str] = {}
                    text = archive.read(member).decode("utf-8", "replace")
                    for line in text.splitlines():
                        if "=" in line and not line.lstrip().startswith("#"):
                            key, value = line.split("=", 1)
                            values[key.strip()] = value.strip()
                    group = values.get("groupId")
                    artifact = values.get("artifactId")
                    version = values.get("version")
                    if group and artifact and version:
                        discovered[(group, artifact, version)] = (values, jar_path)
        except zipfile.BadZipFile:
            continue
    packages: list[dict[str, Any]] = []
    for (group, artifact, version), (_, jar_path) in sorted(discovered.items()):
        package = _package(
            name=f"{group}:{artifact}", version=version,
            license_id=_maven_license(group), supplier="NOASSERTION",
            homepage=f"https://central.sonatype.com/artifact/{group}/{artifact}/{version}",
            source=f"https://central.sonatype.com/artifact/{group}/{artifact}/{version}",
        )
        relative = jar_path.relative_to(PROJECT_ROOT).as_posix()
        package["comment"] += f" Embedded Maven artifact discovered in {relative}."
        packages.append(package)
    return packages


def _package(
    *, name: str, version: str, license_id: str, supplier: str,
    homepage: str, source: str, artifact: Path | None = None,
    scope: str = "runtime",
) -> dict[str, Any]:
    spdx_id = f"SPDXRef-Package-{_safe_id(name)}-{_safe_id(version)}"
    result: dict[str, Any] = {
        "SPDXID": spdx_id,
        "name": name,
        "versionInfo": version,
        "supplier": supplier,
        "downloadLocation": source if source else "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "copyrightText": "NOASSERTION",
        "homepage": homepage if homepage else "NOASSERTION",
        "primaryPackagePurpose": "LIBRARY" if scope == "runtime" else "APPLICATION",
        "comment": f"Distribution scope: {scope}.",
    }
    if artifact and artifact.is_file():
        result["checksums"] = [{"algorithm": "SHA256", "checksumValue": _sha256(artifact)}]
        try:
            display_path = artifact.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            display_path = f"build source for {artifact.name}"
        result["comment"] += f" Bundled artifact: {display_path}."
    return result


def _load_components() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _resolve_artifact(relative: str) -> Path:
    expected = PROJECT_ROOT / relative
    if expected.is_file():
        return expected
    fallbacks = {
        "app/resources/binaries/ExifTool.exe": (
            Path.home() / "AppData/Local/Programs/ExifTool/ExifTool.exe"
        ),
        "app/resources/binaries/qpdf/qpdf.exe": Path(
            "C:/Program Files/qpdf 12.3.2/bin/qpdf.exe"
        ),
    }
    return fallbacks.get(relative, expected)


def _copy_fixed_licenses() -> list[str]:
    errors: list[str] = []
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        target = LICENSE_ROOT / "python-runtime" / "LICENSE.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, target)
    else:
        errors.append(f"CPython license not found: {python_license}")

    exif_root = Path.home() / "AppData" / "Local" / "Programs" / "ExifTool" / "exiftool_files"
    for filename in ("LICENSE", "README", "Licenses_Strawberry_Perl.zip"):
        source = exif_root / filename
        if source.is_file():
            target = LICENSE_ROOT / "exiftool" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            errors.append(f"ExifTool notice not found: {source}")

    qpdf_license = Path("C:/Program Files/qpdf 12.3.2/share/doc/qpdf/manual-html/license.html")
    if qpdf_license.is_file():
        target = LICENSE_ROOT / "qpdf" / "license.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(qpdf_license, target)
    else:
        errors.append(f"qpdf license not found: {qpdf_license}")

    jars = {
        "pdfbox": PROJECT_ROOT / "app/resources/binaries/pdfbox/pdfbox-app-3.0.8.jar",
        "verapdf": PROJECT_ROOT / "app/resources/binaries/verapdf/bin/cli-1.30.2.jar",
        "jhove": PROJECT_ROOT / "app/resources/binaries/jhove/bin/jhove-apps-1.34.0.jar",
    }
    for name, path in jars.items():
        if _extract_jar_notices(path, LICENSE_ROOT / name / "embedded") == 0:
            errors.append(f"Embedded JAR notices not found: {path}")
    return errors


def generate() -> tuple[int, list[str]]:
    config = _load_components()
    LICENSE_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(LICENSE_ROOT / "python", ignore_errors=True)
    errors = _copy_fixed_licenses()
    packages: list[dict[str, Any]] = []

    app = config["application"]
    app_package = _package(
        name=app["name"], version=app["version"], license_id=app["license"],
        supplier=app["supplier"], homepage=app["homepage"],
        source=app["homepage"], scope="application",
    )
    app_package["primaryPackagePurpose"] = "APPLICATION"
    packages.append(app_package)

    runtime = config["python_runtime"]
    packages.append(_package(
        name=runtime["name"], version=runtime["version"], license_id=runtime["license"],
        supplier=runtime["supplier"], homepage=runtime["homepage"], source=runtime["source"],
    ))

    python_names = [(name, "runtime") for name in config["python_distributions"]]
    python_names += [(name, "build") for name in config["build_distributions"]]
    for distribution_name, scope in python_names:
        try:
            dist = metadata.distribution(distribution_name)
        except metadata.PackageNotFoundError:
            errors.append(f"Python distribution not installed: {distribution_name}")
            continue
        license_dir = LICENSE_ROOT / "python" / f"{distribution_name}-{dist.version}"
        copied = _copy_distribution_licenses(dist, license_dir)
        if copied == 0:
            errors.append(f"No license file found for Python distribution: {distribution_name}")
        packages.append(_package(
            name=distribution_name, version=dist.version,
            license_id=_license_expression(dist), supplier="NOASSERTION",
            homepage=_project_url(dist), source=_project_url(dist), scope=scope,
        ))

    for component in config["external_components"]:
        artifact = _resolve_artifact(component["artifact"]) if component.get("artifact") else None
        if artifact and not artifact.is_file():
            errors.append(f"Bundled artifact missing: {component['artifact']}")
        packages.append(_package(
            name=component["name"], version=component["version"],
            license_id=component["license"], supplier=component["supplier"],
            homepage=component["homepage"], source=component["source"],
            artifact=artifact,
        ))

    packages.extend(_discover_maven_packages())

    relationships = []
    for package in packages[1:]:
        relation = "BUILD_TOOL_OF" if "Distribution scope: build" in package["comment"] else "DEPENDS_ON"
        if relation == "BUILD_TOOL_OF":
            relationships.append({
                "spdxElementId": package["SPDXID"],
                "relationshipType": relation,
                "relatedSpdxElement": app_package["SPDXID"],
            })
        else:
            relationships.append({
                "spdxElementId": app_package["SPDXID"],
                "relationshipType": relation,
                "relatedSpdxElement": package["SPDXID"],
            })

    namespace_seed = json.dumps(config, sort_keys=True).encode("utf-8")
    namespace_uuid = uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(namespace_seed).hexdigest())
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Document-Forensic-Inspector-{app['version']}",
        "documentNamespace": f"https://github.com/archeageamir-create/document-forensic-inspector/spdx/{app['version']}/{namespace_uuid}",
        "creationInfo": {
            "created": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: scripts/generate_compliance.py", "Person: Amirkhan Smagulov"],
            "licenseListVersion": "3.27",
        },
        "documentDescribes": [app_package["SPDXID"]],
        "packages": packages,
        "relationships": relationships,
        "hasExtractedLicensingInfos": [
            {
                "licenseId": "LicenseRef-Public-Domain",
                "extractedText": "The bundled PDFiD and pdf-parser source headers state that the programs are public domain.",
                "seeAlsos": ["https://github.com/DidierStevens/DidierStevensSuite"],
            },
            {
                "licenseId": "LicenseRef-Microsoft-Visual-Cpp-Runtime",
                "extractedText": "Microsoft Visual C++ runtime files are redistributed under the applicable Microsoft Visual Studio redist terms.",
                "seeAlsos": ["https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist"],
            },
        ],
    }
    SBOM_PATH.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    runtime_packages = [package for package in packages[1:] if "scope: build" not in package["comment"]]
    build_packages = [package for package in packages[1:] if "scope: build" in package["comment"]]
    notice = [
        "# Third-party notices",
        "",
        "Document Forensic Inspector shell, integration, reporting and Windows packaging are",
        "Copyright 2026 Amirkhan Smagulov and licensed under Apache-2.0. The components",
        "below remain independent works of their respective authors. No authorship or",
        "ownership of those projects is claimed.",
        "",
        "Metadata conflicts and tool output are technical observations, not automatic",
        "findings of falsification. The software and reports are provided without warranty.",
        "",
        "## Runtime and bundled components",
        "",
        "| Component | Version | Declared license | Source/homepage |",
        "|---|---:|---|---|",
    ]
    for package in runtime_packages:
        url = package["downloadLocation"] if package["downloadLocation"] != "NOASSERTION" else package["homepage"]
        notice.append(f"| {package['name']} | {package['versionInfo']} | `{package['licenseDeclared']}` | {url} |")
    notice.extend(["", "## Build-only components", "", "| Component | Version | License |", "|---|---:|---|"])
    for package in build_packages:
        notice.append(f"| {package['name']} | {package['versionInfo']} | `{package['licenseDeclared']}` |")
    notice.extend([
        "",
        "The complete SPDX 2.3 inventory is in `SBOM.spdx.json`. License texts are in",
        "the `licenses` directory. The bundled Temurin runtime additionally keeps its full",
        "module-by-module notices in `app/resources/binaries/java/legal`.",
        "",
        "Corresponding-source locations and the written offer are in `SOURCE_OFFER.md` and",
        "`compliance/THIRD_PARTY_SOURCES.json`. See `docs/LGPL_COMPLIANCE.md` for Qt/PySide",
        "replacement and relinking instructions.",
    ])
    NOTICE_PATH.write_text("\n".join(notice) + "\n", encoding="utf-8")

    shutil.copy2(NOTICE_PATH, PROJECT_ROOT / "THIRD_PARTY_NOTICES.md")
    shutil.copy2(SBOM_PATH, PROJECT_ROOT / "SBOM.spdx.json")
    compliance_resource = RESOURCE_ROOT / "compliance"
    compliance_resource.mkdir(parents=True, exist_ok=True)
    for source in (
        PROJECT_ROOT / "LICENSE",
        PROJECT_ROOT / "NOTICE",
        PROJECT_ROOT / "SOURCE_OFFER.md",
        PROJECT_ROOT / "docs/LGPL_COMPLIANCE.md",
        PROJECT_ROOT / "compliance/components.json",
        PROJECT_ROOT / "compliance/THIRD_PARTY_SOURCES.json",
    ):
        shutil.copy2(source, compliance_resource / source.name)
    return len(packages), errors


def check() -> list[str]:
    errors: list[str] = []
    required = [
        PROJECT_ROOT / "LICENSE", PROJECT_ROOT / "NOTICE", PROJECT_ROOT / "SOURCE_OFFER.md",
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.md", PROJECT_ROOT / "SBOM.spdx.json",
        PROJECT_ROOT / "compliance/THIRD_PARTY_SOURCES.json",
        PROJECT_ROOT / "docs/LGPL_COMPLIANCE.md",
    ]
    errors.extend(f"Required compliance file missing: {path}" for path in required if not path.is_file())
    if SBOM_PATH.is_file():
        sbom = json.loads(SBOM_PATH.read_text(encoding="utf-8"))
        if sbom.get("spdxVersion") != "SPDX-2.3":
            errors.append("SBOM is not SPDX 2.3")
        if len(sbom.get("packages", [])) < 70:
            errors.append("SBOM package inventory is unexpectedly short")
    for directory in ("python", "python-runtime", "qt", "qpdf", "exiftool", "poppler", "jhove", "verapdf", "pdfbox"):
        path = LICENSE_ROOT / directory
        if not path.is_dir() or not any(item.is_file() for item in path.rglob("*")):
            errors.append(f"License directory missing or empty: {path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate generated compliance files")
    args = parser.parse_args()
    generated_errors: list[str] = []
    if not args.check:
        count, generated_errors = generate()
        print(f"Generated compliance inventory for {count} packages.")
    errors = generated_errors + check()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Compliance checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
