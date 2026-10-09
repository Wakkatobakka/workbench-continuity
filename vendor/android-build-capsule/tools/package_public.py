#!/usr/bin/env python3
"""Package only the verified public allowlist. Does not sweep a working folder."""
import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import importlib.util
spec = importlib.util.spec_from_file_location("wakka_capsule", ROOT / "abc.py")
capsule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capsule)


def main():
    parser = argparse.ArgumentParser(description="Make a verified public core ZIP")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        parser.error("Output already exists; choose a new file.")
    files = capsule.public_files()
    for name in files:
        p = Path(name)
        if p.parts[0] in (".private", "runtime", "Private_Capsules") or p.suffix.lower() in (
            ".jks", ".keystore", ".p12", ".pfx", ".pk8", ".pem", ".key", ".jar", ".so", ".exe", ".dll"):
            raise capsule.CapsuleError("Forbidden public payload: " + name)
        if p.suffix.lower() == ".apk" and name != "examples/CapsuleDemo/prebuilt/CapsuleDemo_v0.1.0.apk":
            raise capsule.CapsuleError("Unexpected APK in public allowlist: " + name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in files:
            z.write(ROOT / name, "WAKKA_Android_Build_Capsule_Public_v0.1.0/" + name)
    print("PUBLIC CORE ZIP: " + str(output))
    print("FILES: " + str(len(files)) + "; SIZE: " + str(output.stat().st_size) + " bytes")


if __name__ == "__main__":
    main()
