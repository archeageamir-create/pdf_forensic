"""Archive source JARs and build POMs identified inside the shipped Java tools."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile

from collect_source_supplement import DEST, RECORDS, ROOT, digest, fetch

CENTRAL = "https://repo.maven.apache.org/maven2/"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def collect(gav: tuple[str, str, str]) -> dict:
    group, artifact, version = gav
    base = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}"
    files = []
    pom_only = (artifact == "listenablefuture" and version.startswith("9999.")) or artifact == "pdfbox-app"
    for suffix in ((".pom",) if pom_only else (".pom", "-sources.jar")):
        path = fetch(CENTRAL + base + suffix, DEST / "maven" / (base + suffix))
        if suffix.endswith("jar"):
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():
                    raise ValueError(f"Corrupt source archive: {base}")
        files.append({"file": path.relative_to(DEST).as_posix(), "url": CENTRAL + base + suffix, "sha256": digest(path)})
    pom = ET.parse(DEST / "maven" / (base + ".pom")).getroot()
    parents = []
    seen = set()
    while (parent := pom.find("m:parent", NS)) is not None:
        values = [parent.findtext("m:" + key, namespaces=NS) for key in ("groupId", "artifactId", "version")]
        if any(not value or "${" in value for value in values):
            raise ValueError(f"Unresolved parent of {gav}: {values}")
        pg, pa, pv = values
        rel = f"{pg.replace('.', '/')}/{pa}/{pv}/{pa}-{pv}.pom"
        if rel in seen:
            raise ValueError("Cyclic parent POM")
        seen.add(rel)
        path = fetch(CENTRAL + rel, DEST / "maven" / rel)
        parents.append({"file": path.relative_to(DEST).as_posix(), "url": CENTRAL + rel, "sha256": digest(path)})
        pom = ET.parse(path).getroot()
    result = {"gav": ":".join(gav), "files": files, "parents": parents}
    if artifact == "listenablefuture" and pom_only:
        result["note"] = "Empty conflict-avoidance artifact; actual classes are in Guava, whose sources are included."
    if artifact == "pdfbox-app":
        url = f"https://github.com/apache/pdfbox/archive/refs/tags/{version}.tar.gz"
        path = fetch(url, DEST / f"pdfbox-{version}-src.tar.gz")
        files.append({"file": path.name, "url": url, "sha256": digest(path)})
    return result


def main() -> None:
    components = {}
    # Saxon omits pom.properties from these shaded JARs. Versions verified by
    # net.sf.saxon.Version and by the embedded EPUBCheck / veraPDF parent POMs.
    for version, jar in (("11.4", "jhove/bin/jhove-ext-modules-1.34.0.jar"), ("12.8", "verapdf/bin/cli-1.30.2.jar")):
        components[("net.sf.saxon", "Saxon-HE", version)] = [{"jar": "app/resources/binaries/" + jar, "metadata": "net.sf.saxon.Version; embedded build POM"}]
    for tool in ("jhove", "verapdf", "pdfbox"):
        for jar in (ROOT / "app/resources/binaries" / tool).rglob("*.jar"):
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    if name.startswith("META-INF/maven/") and name.endswith("/pom.properties"):
                        props = dict(line.split("=", 1) for line in archive.read(name).decode("utf-8", "replace").splitlines() if "=" in line and not line.startswith("#"))
                        gav = tuple(props[k] for k in ("groupId", "artifactId", "version"))
                        components.setdefault(gav, []).append({"jar": jar.relative_to(ROOT).as_posix(), "metadata": name})
    records, errors = [], []
    # Shared parent POMs are common; fetch them serially to avoid writing the same
    # temporary path concurrently. These downloads are small and cached.
    for gav in sorted(components):
        try:
            record = collect(gav)
            record["identified_in"] = components[gav]
            records.append(record)
            print(record["gav"], flush=True)
        except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
            errors.append({"gav": ":".join(gav), "error": str(error)})
            print(errors[-1], flush=True)
    (RECORDS / "java-provenance.json").write_text(json.dumps({"components": records, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
