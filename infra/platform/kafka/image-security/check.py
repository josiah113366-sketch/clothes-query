"""Build and scan only this repository's Connect image; no registry login, push or Docker socket in scanner."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
SCANNER = "ghcr.io/aquasecurity/trivy@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa"
SCANNER_VERSION = "0.75.0"


def main():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "TF_", "KUBE", "TRIVY_"))}
    if env.get("DOCKER_HOST") or env.get("DOCKER_CONTEXT"):
        raise RuntimeError("Use the local Docker context without host/context overrides")

    def docker(*args, timeout=120, check=True):
        result = subprocess.run(["docker", *map(str, args)], capture_output=True, text=True,
                                encoding="utf-8", env=env, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(result.stderr[-2500:] or result.stdout[-2500:])
        return result

    context = json.loads(docker("context", "inspect").stdout)[0]
    if not context["Endpoints"]["docker"]["Host"].startswith(("unix://", "npipe://")):
        raise RuntimeError("Only a local Docker socket is supported")
    if docker("info", "--format", "{{.OSType}}").stdout.strip() != "linux":
        raise RuntimeError("Docker Linux engine is required")
    cache = REPO / ".cache" / "connect-security"
    cache.mkdir(parents=True, exist_ok=True)
    db_cache = cache / "trivy-cache"
    db_cache.mkdir(exist_ok=True)
    (cache / "empty.yaml").write_text("{}\n", encoding="utf-8")
    run_id = secrets.token_hex(5)
    image = "cq-connect-scan-" + run_id + ":local"
    scanner_name = "cq-trivy-" + run_id
    image_info = None
    with tempfile.TemporaryDirectory(prefix="export-", dir=cache) as temp:
        archive = Path(temp) / "image.tar"
        try:
            print("Building current pinned Connect image...", flush=True)
            docker("build", "--platform", "linux/amd64", "--tag", image, ROOT.parent / "connect-image", timeout=300)
            image_info = json.loads(docker("image", "inspect", image).stdout)[0]
            print("Exporting local image; scanner receives a read-only archive, no Docker socket...", flush=True)
            docker("image", "save", "--output", archive, image, timeout=180)
            print("Scanning OS and Java packages; initial vulnerability DB download may take several minutes...", flush=True)
            docker("run", "--rm", "--name", scanner_name, "--platform", "linux/amd64",
                   "--mount", f"type=bind,source={archive},target=/scan/image.tar,readonly",
                   "--mount", f"type=bind,source={db_cache},target=/root/.cache/trivy",
                   "--mount", f"type=bind,source={cache},target=/results",
                   SCANNER, "image", "--input", "/scan/image.tar", "--scanners", "vuln",
                   "--format", "json", "--output", "/results/report.json", "--config", "/results/empty.yaml",
                   "--ignorefile", "", "--disable-telemetry", "--skip-version-check", "--timeout", "10m",
                   timeout=660)
        finally:
            docker("container", "rm", "--force", scanner_name, check=False)
            docker("image", "rm", image, check=False)
    report = json.loads((cache / "report.json").read_text(encoding="utf-8"))
    if not report.get("Results") or not report.get("Metadata"):
        raise RuntimeError("No scan results/metadata; cannot classify scan as completed")
    raw = []
    unique = {}
    for result in report["Results"]:
        for vulnerability in result.get("Vulnerabilities") or []:
            row = {k: vulnerability.get(k, "") for k in ["VulnerabilityID", "PkgName", "PkgPath", "InstalledVersion", "FixedVersion", "Severity", "PrimaryURL"]}
            row["targetType"] = result.get("Type", "")
            path = row["PkgPath"].lstrip("/")
            row["component"] = ("Debezium plugin" if path.startswith("opt/kafka/plugins/postgres/") else
                                "Bundled Cruise Control" if path.startswith("opt/cruise-control/") else
                                "Base OS" if row["targetType"] == "redhat" else
                                "Kafka/Connect libraries" if path.startswith("opt/kafka/") else "Other bundled component")
            raw.append(row)
            unique.setdefault((row["VulnerabilityID"], row["PkgName"], row["InstalledVersion"]), row)
    rows = list(unique.values())
    counts = dict(Counter(v["Severity"] for v in rows))
    fixes = dict(Counter(v["Severity"] for v in rows if v["FixedVersion"]))
    database_metadata = {}
    for name, path in [("vulnerability", db_cache / "db" / "metadata.json"),
                       ("java", db_cache / "java-db" / "metadata.json")]:
        if path.exists():
            database_metadata[name] = json.loads(path.read_text())
    summary = {"scannedAtUTC": datetime.now(timezone.utc).isoformat(), "scanner": SCANNER,
               "scannerVersion": SCANNER_VERSION, "imageID": image_info["Id"],
               "dockerfileSHA256": hashlib.sha256((ROOT.parent / "connect-image" / "Dockerfile").read_bytes()).hexdigest(),
               "databaseMetadata": database_metadata, "rawFindingCount": len(raw),
               "uniquePackageFindingCount": len(rows), "severityCounts": counts,
               "withListedFixCounts": fixes,
               "componentSeverityCounts": {component: dict(Counter(r["Severity"] for r in rows if r["component"] == component))
                                           for component in sorted({r["component"] for r in rows})}, "findings": rows}
    (cache / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = ["# Connect image vulnerability scan", "", f"UTC: {summary['scannedAtUTC']}",
             f"Scanner: Trivy {SCANNER_VERSION} (digest pinned)", f"Image ID: `{image_info['Id']}`", "",
             f"Raw findings: {len(raw)}; unique CVE/package/version findings: {len(rows)}.", "",
             "| Severity | Findings | Listed fixed version |", "|---|---:|---:|"]
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        lines.append(f"| {severity} | {counts.get(severity, 0)} | {fixes.get(severity, 0)} |")
    lines += ["", "## First 15 critical/high package findings", "",
              "| CVE | Package | Installed | Listed fix | Severity |", "|---|---|---|---|---|"]
    important = sorted((r for r in rows if r["Severity"] in {"CRITICAL", "HIGH"}),
                       key=lambda r: (r["Severity"] != "CRITICAL", not bool(r["FixedVersion"]), r["VulnerabilityID"], r["PkgName"]))
    for row in important[:15]:
        fields = [row[k].replace("|", "\\|") for k in ["VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion", "Severity"]]
        lines.append("| " + " | ".join(fields) + " |")
    lines += ["", "A listed fix is advisory metadata, not proof of compatibility or exploitability.",
              "No findings are suppressed. This scan records results; it does not approve a release or change dependencies.",
              "Full local report and database timestamps are in report.json and summary.json."]
    (cache / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Scan complete. Unique package findings: " + json.dumps(counts, sort_keys=True), flush=True)
    print("Listed fixed versions: " + json.dumps(fixes, sort_keys=True), flush=True)
    print("Reports: .cache/connect-security/{report.json,summary.json,summary.md}", flush=True)


if __name__ == "__main__":
    main()
