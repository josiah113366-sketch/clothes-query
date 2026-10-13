"""Download a pinned portable Helm binary to .cache; print its absolute path."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "3.19.0"
ARCHIVES = {
    "linux-amd64": ("tar.gz", "a7f81ce08007091b86d8bd696eb4d86b8d0f2e1b9f6c714be62f82f96a594496", "helm"),
    "windows-amd64": ("zip", "6488630c2e5d5945ed990fa02fd9e99f9c6792cdbcd79eb264b6cfb90179d2d1", "helm.exe"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=ARCHIVES)
    args = parser.parse_args()
    target = args.platform or {"Windows": "windows-amd64", "Linux": "linux-amd64"}.get(platform.system())
    if target not in ARCHIVES or (not args.platform and platform.machine().lower() not in {"amd64", "x86_64"}):
        raise RuntimeError("Only Linux/Windows amd64 are supported")
    extension, checksum, executable = ARCHIVES[target]
    cache = ROOT / ".cache" / "helm" / target
    cache.mkdir(parents=True, exist_ok=True)
    name = f"helm-v{VERSION}-{target}.{extension}"
    archive = cache / name
    if not archive.exists():
        content = urllib.request.urlopen("https://get.helm.sh/" + name, timeout=60).read()
        if hashlib.sha256(content).hexdigest() != checksum:
            raise RuntimeError("Helm archive checksum mismatch")
        archive.write_bytes(content)
    content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != checksum:
        raise RuntimeError("Cached Helm archive checksum mismatch")
    member = target + "/" + executable
    if extension == "zip":
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            binary = package.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as package:
            binary = package.extractfile(member).read()
    destination = cache / executable
    destination.write_bytes(binary)
    destination.chmod(0o755)
    print(destination)


if __name__ == "__main__":
    main()
