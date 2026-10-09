#!/usr/bin/env python3
"""WAKKA Android Build Capsule public core. MIT; Python standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent
API = 35
BUILD_TOOLS = "35.0.0"
TERMS_URL = "https://developer.android.com/studio/terms"


class CapsuleError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def inside(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise CapsuleError("Path escapes its project or runtime: " + str(name))
    return path


def run(command, env=None, cwd=None, timeout=180):
    # Windows ZIP writers and some workspace transfers omit executable bits.
    # SDK executables are Path arguments; host Java commands remain strings.
    executable = command[0]
    if isinstance(executable, Path) and executable.is_file() and platform.system() == "Linux":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Passwords are supplied by environment, never by command line.
        raise CapsuleError("Command failed: " + Path(str(command[0])).name + "\n"
                           + result.stdout[-6000:] + result.stderr[-6000:])
    return (result.stdout + result.stderr).strip()


def java_command():
    configured = os.environ.get("ABC_JAVA_HOME") or os.environ.get("JAVA_HOME")
    java = Path(configured) / "bin" / "java" if configured else None
    if java and java.is_file():
        return str(java)
    java = shutil.which("java")
    if not java:
        raise CapsuleError("Java is missing. This runtime needs a host JDK 17 or newer. "
                           "The Capsule does not install or change system Java.")
    return java


def java_tool(name):
    java = java_command()
    sibling = Path(java).resolve().parent / name
    found = str(sibling) if sibling.is_file() else shutil.which(name)
    if found:
        return [found]
    # Some chat hosts retain JDK modules but omit the javac/jar launchers.
    modules = {"javac": "jdk.compiler/com.sun.tools.javac.Main",
               "jar": "jdk.jartool/sun.tools.jar.Main"}
    if name in modules:
        return [java, "-m", modules[name]]
    raise CapsuleError(name + " is missing from this Java installation.")


def sdk_path(value=None):
    value = value or os.environ.get("ABC_SDK_ROOT")
    path = Path(value).resolve() if value else ROOT / "runtime" / "sdk"
    if not path.is_dir():
        raise CapsuleError("SDK runtime is missing. Upload your private Runtime Capsule "
                           "or run MAKE_CHAT_CAPSULE.bat on Windows first. "
                           "The public ZIP intentionally contains no SDK binaries.")
    return path


def toolpaths(sdk):
    bt = sdk / "build-tools" / BUILD_TOOLS
    return {"android_jar": sdk / "platforms" / "android-35" / "android.jar",
            "aapt": bt / "aapt", "aapt2": bt / "aapt2", "zipalign": bt / "zipalign",
            "d8": bt / "lib" / "d8.jar", "apksigner": bt / "lib" / "apksigner.jar"}


def check_runtime_inventory(sdk):
    manifest = sdk.parent / "SDK_FILES.sha256.json"
    if not manifest.exists():
        return "not supplied; tool execution and real build still required"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    for name, expected in value.items():
        path = inside(sdk, name)
        if not path.is_file() or digest(path) != expected:
            raise CapsuleError("Runtime checksum failed: " + name)
    return "verified (" + str(len(value)) + " files)"


def doctor(sdk):
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise CapsuleError("This build profile runs on Linux x86_64. "
                           "The Windows launcher makes a Linux runtime for chat; "
                           "it does not claim Windows or ARM compilation support.")
    paths = toolpaths(sdk)
    inventory = check_runtime_inventory(sdk)
    for name, path in paths.items():
        if not path.is_file():
            raise CapsuleError("Required runtime file is missing: " + str(path))
        if name in ("aapt", "aapt2", "zipalign"):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
    for name in ("d8", "apksigner"):
        launcher = sdk / "build-tools" / BUILD_TOOLS / name
        if launcher.is_file():
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    java_version = run([java_command(), "-version"])
    compiler_version = run(java_tool("javac") + ["-version"])
    m = re.search(r'javac\s+(\d+)', compiler_version)
    if not m or int(m.group(1)) < 17:
        raise CapsuleError("A host JDK 17 or newer is required; found: " + compiler_version)
    values = {"host": platform.system(), "architecture": platform.machine(),
              "java": java_version, "javac": compiler_version, "sdk_inventory": inventory,
              "aapt": run([paths["aapt"], "version"]),
              "aapt2": run([paths["aapt2"], "version"]),
              "d8": run([java_command(), "-cp", paths["d8"], "com.android.tools.r8.D8", "--version"]),
              "apksigner": run([java_command(), "-jar", paths["apksigner"], "version"])}
    with tempfile.TemporaryDirectory(prefix="abc-align-") as folder:
        folder = Path(folder)
        with zipfile.ZipFile(folder / "probe.zip", "w") as z:
            z.writestr("probe.txt", "WAKKA Build Capsule\n", compress_type=zipfile.ZIP_STORED)
        run([paths["zipalign"], "-f", "-P", "16", "4", folder / "probe.zip", folder / "aligned.zip"])
        run([paths["zipalign"], "-c", "-P", "16", "4", folder / "aligned.zip"])
    values["zipalign"] = "real alignment and verification passed"
    print("TOOLCHAIN READY — Java, resources, DEX, alignment and signing tools execute.", flush=True)
    return values


def project_settings(project):
    path = project / "capsule-project.json"
    if not path.is_file():
        raise CapsuleError("Missing capsule-project.json. Existing preservation projects "
                           "with their own builder can use run-project instead.")
    c = json.loads(path.read_text(encoding="utf-8"))
    if c.get("profile") != "plain-java":
        raise CapsuleError("Only the plain-java profile is implemented in v0.1.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", c.get("package", "")):
        raise CapsuleError("Invalid Android package name.")
    for field in ("min_sdk", "target_sdk", "version_code"):
        if not isinstance(c.get(field), int) or isinstance(c[field], bool) or c[field] <= 0:
            raise CapsuleError(field + " must be a positive integer.")
    if c["min_sdk"] > c["target_sdk"] or c["target_sdk"] > API:
        raise CapsuleError("SDK levels must satisfy min_sdk <= target_sdk <= 35.")
    c.setdefault("sources", "src")
    c.setdefault("resources", "res")
    c.setdefault("assets", "assets")
    c.setdefault("manifest", "AndroidManifest.xml")
    c.setdefault("version_name", "0.1.0")
    if not isinstance(c["version_name"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,64}", c["version_name"]):
        raise CapsuleError("version_name must be a short filename-safe version string.")
    for field in ("sources", "resources", "assets", "manifest"):
        path = inside(project, c[field])
        if path.is_dir():
            for child in path.rglob("*"):
                if not child.resolve().is_relative_to(project.resolve()):
                    raise CapsuleError("Project symlink leaves its source folder: " + child.name)
    return c


def signing_options(args, project, env):
    if args.keystore:
        key = Path(args.keystore).resolve()
        if not key.is_file():
            raise CapsuleError("The specified signing keystore does not exist.")
        if not args.key_alias or not env.get(args.password_env):
            raise CapsuleError("Release signing needs --key-alias and the password in " + args.password_env)
        return key, args.key_alias, args.password_env, "owner-supplied identity"
    if project.resolve() != (ROOT / "examples" / "CapsuleDemo").resolve() and not args.debug_sign:
        raise CapsuleError("Supply your existing signing identity, or explicitly use --debug-sign "
                           "for a new test identity. Existing apps cannot update with a different key.")
    key = ROOT / ".private" / "signing" / "demo-debug.jks"
    key.parent.mkdir(parents=True, exist_ok=True)
    env["ABC_DEBUG_KEY_PASSWORD"] = "android"
    if not key.exists():
        run(java_tool("keytool") + ["-genkeypair", "-keystore", key, "-storetype", "JKS",
            "-storepass:env", "ABC_DEBUG_KEY_PASSWORD", "-keypass:env", "ABC_DEBUG_KEY_PASSWORD",
            "-alias", "capsule-demo", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=Local Capsule Demo, O=WAKKA", "-noprompt"], env=env)
        key.chmod(0o600)
    return key, "capsule-demo", "ABC_DEBUG_KEY_PASSWORD", "local test identity; not for release updates"


def build(args):
    sdk = sdk_path(args.sdk)
    tools = doctor(sdk)
    p = toolpaths(sdk)
    project = Path(args.project or ROOT / "examples" / "CapsuleDemo").resolve()
    c = project_settings(project)
    output = Path(args.output).resolve()
    if output.exists():
        raise CapsuleError("Output already exists. Choose a new output folder; builds do not overwrite releases.")
    output.mkdir(parents=True)
    env = os.environ.copy()
    logs = []
    with tempfile.TemporaryDirectory(prefix="abc-build-") as scratch:
        scratch = Path(scratch)
        generated, classes, dex = [scratch / x for x in ("generated", "classes", "dex")]
        for folder in (generated, classes, dex):
            folder.mkdir()
        compiled = scratch / "resources.zip"
        logs.append(run([p["aapt2"], "compile", "--dir", inside(project, c["resources"]), "-o", compiled]))
        unsigned = scratch / "unsigned.apk"
        cmd = [p["aapt2"], "link", "-o", unsigned, "-I", p["android_jar"],
               "--manifest", inside(project, c["manifest"]), "--java", generated,
               "--min-sdk-version", str(c["min_sdk"]), "--target-sdk-version", str(c["target_sdk"]),
               "--version-code", str(c["version_code"]), "--version-name", c["version_name"], compiled]
        assets = inside(project, c["assets"])
        if assets.is_dir():
            cmd += ["-A", assets]
        logs.append(run(cmd))
        sources = sorted(inside(project, c["sources"]).rglob("*.java")) + sorted(generated.rglob("*.java"))
        if not sources:
            raise CapsuleError("Project contains no Java source.")
        # Argfile avoids command length limits and quotes paths that contain spaces.
        argfile = scratch / "javac.args"
        compiler_args = ["-encoding", "UTF-8", "--release", "8", "-classpath",
                         str(p["android_jar"]), "-d", str(classes)] + [str(x) for x in sources]
        argfile.write_text("\n".join('"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
                                         for x in compiler_args), encoding="utf-8")
        logs.append(run(java_tool("javac") + ["@" + str(argfile)]))
        compiled_jar = scratch / "classes.jar"
        with zipfile.ZipFile(compiled_jar, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in sorted(classes.rglob("*.class")):
                z.write(f, f.relative_to(classes).as_posix())
        logs.append(run([java_command(), "-cp", p["d8"], "com.android.tools.r8.D8", "--lib",
                         p["android_jar"], "--min-api", str(c["min_sdk"]), "--output", dex, compiled_jar]))
        dex_files = sorted(dex.glob("classes*.dex"))
        if not dex_files:
            raise CapsuleError("D8 did not produce DEX bytecode.")
        with zipfile.ZipFile(unsigned, "a") as z:
            for f in dex_files:
                z.write(f, f.name, compress_type=zipfile.ZIP_STORED)
        aligned = scratch / "aligned.apk"
        logs.append(run([p["zipalign"], "-f", "-P", "16", "4", unsigned, aligned]))
        key, alias, password_env, signing_kind = signing_options(args, project, env)
        apk = output / (c["package"] + "_v" + c["version_name"] + ".apk")
        logs.append(run([java_command(), "-jar", p["apksigner"], "sign", "--ks", key,
                         "--ks-key-alias", alias, "--ks-pass", "env:" + password_env,
                         "--key-pass", "env:" + password_env, "--min-sdk-version", str(c["min_sdk"]),
                         "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
                         "--v3-signing-enabled", "true", "--v4-signing-enabled", "false",
                         "--out", apk, aligned], env=env))
        verification = run([java_command(), "-jar", p["apksigner"], "verify", "--verbose", "--print-certs", apk])
        for scheme in ("v1", "v2", "v3"):
            if not re.search(r"Verified using " + scheme + r" scheme.*:\s*true", verification):
                raise CapsuleError("Signature verification did not confirm " + scheme)
        run([p["zipalign"], "-c", "-P", "16", "4", apk])
        metadata = run([p["aapt"], "dump", "badging", apk])
        with zipfile.ZipFile(apk) as z:
            if z.testzip() is not None or "classes.dex" not in z.namelist():
                raise CapsuleError("APK archive or DEX check failed.")
        source_files = set(sources) - set(generated.rglob("*.java"))
        source_files |= {inside(project, c["manifest"]), project / "capsule-project.json"}
        for directory in (inside(project, c["resources"]), assets):
            if directory.is_dir():
                source_files |= {x for x in directory.rglob("*") if x.is_file()}
        evidence = {"capsule_version": VERSION, "built_at": timestamp(), "profile": "plain-java",
                    "project": c["package"], "version": c["version_name"], "apk": apk.name,
                    "apk_sha256": digest(apk), "fresh_java_compilation": True,
                    "fresh_dex_compilation": True, "dex_sha256": [digest(x) for x in dex_files],
                    "signing": signing_kind, "signature_verification": verification,
                    "alignment": "4-byte entries and 16 KiB native-library alignment checked",
                    "apk_badging": metadata, "tools": tools,
                    "source_sha256": {f.relative_to(project).as_posix(): digest(f) for f in sorted(source_files)},
                    "android_emulator": "not run", "physical_device": "not run",
                    "claim": "Source compiled, APK assembled, aligned, signed and verified; runtime behavior remains untested."}
        write_json(output / "BUILD_EVIDENCE.json", evidence)
        (output / "BUILD_LOG.txt").write_text("\n\n".join(logs + [verification, metadata]) + "\n", encoding="utf-8")
    print("APK READY: " + str(apk))
    print("SIGNATURES: v1 / v2 / v3 verified. DEVICE TEST: not run.")


def public_files():
    manifest = ROOT / "PUBLIC_FILES.sha256.json"
    if not manifest.is_file():
        raise CapsuleError("The public file manifest is missing.")
    files = json.loads(manifest.read_text(encoding="utf-8"))
    for name, expected in files.items():
        f = inside(ROOT, name)
        if not f.is_file() or digest(f) != expected:
            raise CapsuleError("Public core checksum failed: " + name)
    return sorted(files) + [manifest.name]


def safe_extract(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as z:
        total = sum(i.file_size for i in z.infolist())
        if total > 2_000_000_000:
            raise CapsuleError("Archive exceeds the 2 GB extraction limit.")
        names = set()
        for entry in z.infolist():
            name = entry.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or any(":" in s for s in parts):
                raise CapsuleError("Unsafe ZIP entry: " + name)
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise CapsuleError("ZIP symlinks are not accepted: " + name)
            if name in names and not entry.is_dir():
                raise CapsuleError("Duplicate ZIP entry: " + name)
            names.add(name)
            out = inside(destination, name)
            if name.endswith("/"):
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(entry) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            if entry.external_attr >> 16 & 0o111:
                out.chmod(out.stat().st_mode | stat.S_IXUSR)


def make_private_runtime(sdk, destination, provenance):
    destination = Path(destination).resolve()
    if destination.exists():
        raise CapsuleError("Runtime output already exists; choose a new output folder.")
    files = public_files()
    destination.mkdir(parents=True)
    for name in files:
        path = inside(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inside(ROOT, name), path)
    target = destination / "runtime" / "sdk"
    shutil.copytree(sdk, target)
    inventory = {x.relative_to(target).as_posix(): digest(x) for x in sorted(target.rglob("*")) if x.is_file()}
    write_json(destination / "runtime" / "SDK_FILES.sha256.json", inventory)
    write_json(destination / "PRIVATE_RUNTIME.json", {
        "distribution": "private-runtime", "capsule_version": VERSION, "created_at": timestamp(),
        "sdk_terms": TERMS_URL, "provenance": provenance,
        "public_redistribution": "not cleared; do not publish this generated SDK bundle",
        "host_jdk": "JDK 17+ supplied by the execution host; no JDK bundled",
        "contains_project_signing_keys": False})
    archive = Path(str(destination) + ".zip")
    if archive.exists():
        raise CapsuleError("Runtime ZIP already exists: " + str(archive))
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(destination.rglob("*")):
            if f.is_file():
                # Always forward slashes, regardless of the collecting host.
                z.write(f, destination.name + "/" + f.relative_to(destination).as_posix())
    print("PRIVATE CHAT CAPSULE: " + str(archive))
    print("Share the public core ZIP; keep this generated SDK runtime private.")
    return archive


def fetch_archive(record, cache):
    path = cache / record["filename"]
    if path.is_file() and path.stat().st_size == record["size_bytes"] and digest(path) == record["sha256"]:
        print("DOWNLOAD REUSED: " + record["filename"], flush=True)
        return path
    partial = path.with_suffix(path.suffix + ".partial")
    print("DOWNLOADING: " + record["filename"], flush=True)
    try:
        request = urllib.request.Request(record["url"], headers={"User-Agent": "WAKKA-Capsule/" + VERSION})
        with urllib.request.urlopen(request, timeout=60) as src, partial.open("wb") as out:
            shutil.copyfileobj(src, out)
        if (partial.stat().st_size != record["size_bytes"] or digest(partial) != record["sha256"]
                or digest(partial, "sha1") != record["sha1"]):
            raise CapsuleError("Official archive checksum mismatch: " + record["filename"])
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def fetch_runtime(args):
    if not args.accept_sdk_license:
        raise CapsuleError("Read the Android SDK agreement at " + TERMS_URL + ". If you personally "
                           "accept it, run this command with --accept-sdk-license. No license is accepted automatically.")
    records = json.loads((ROOT / "official-downloads.json").read_text(encoding="utf-8"))["archives"]
    cache = ROOT / ".private" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    receipts = []
    with tempfile.TemporaryDirectory(prefix="abc-sdk-") as folder:
        folder = Path(folder)
        sdk = folder / "sdk"
        for record in records:
            archive = fetch_archive(record, cache)
            unpack = folder / record["kind"]
            safe_extract(archive, unpack)
            candidates = sorted(unpack.glob("*/source.properties"))
            if len(candidates) != 1:
                raise CapsuleError("Unexpected official archive layout: " + record["filename"])
            origin = candidates[0].parent
            target = sdk / ("platforms/android-35" if record["kind"] == "platform" else "build-tools/35.0.0")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(origin, target)
            receipts.append({"url": record["url"], "sha256": digest(archive), "size_bytes": archive.stat().st_size})
        # Keep the repository's applicable license in the private runtime, not in the public core.
        req = urllib.request.Request("https://dl.google.com/android/repository/repository2-3.xml")
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read(2_000_000)
        tree = ET.fromstring(data)
        lic = next((x for x in tree if x.tag.rsplit("}", 1)[-1] == "license" and x.attrib.get("id") == "android-sdk-license"), None)
        if lic is None or not lic.text:
            raise CapsuleError("Google's SDK license text could not be retrieved; setup stopped.")
        (sdk / "SDK_LICENSE_FROM_GOOGLE.txt").write_text(lic.text, encoding="utf-8")
        make_private_runtime(sdk, args.output, {"route": "direct official downloads",
                             "sdk_license_accepted_by": "person invoking --accept-sdk-license",
                             "sdk_license_text_sha256": hashlib.sha256(lic.text.encode()).hexdigest(),
                             "archives": receipts})


def import_private(args):
    original = Path(args.capsule).resolve()
    if not original.is_file():
        raise CapsuleError("Original Capsule ZIP not found.")
    original_hash = digest(original)
    with tempfile.TemporaryDirectory(prefix="abc-import-") as folder:
        folder = Path(folder)
        with zipfile.ZipFile(original) as outer:
            names = [x for x in outer.namelist() if x.endswith(".zip")]
            base = [x for x in names if "Build_Toolkit_" in x]
            supplement = [x for x in names if "Linux_Build_Supplement" in x]
            if len(base) != 1 or len(supplement) != 1:
                raise CapsuleError("Expected one base toolkit and one Linux supplement in the original Capsule.")
            for name, target in ((base[0], "base"), (supplement[0], "linux")):
                archive = folder / (target + ".zip")
                with outer.open(name) as src, archive.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                safe_extract(archive, folder / target)
        platform_root = folder / "base" / "android-sdk" / "platforms" / "android-35"
        tools_root = folder / "linux" / "android-sdk-linux" / "build-tools" / BUILD_TOOLS
        if not platform_root.is_dir() or not tools_root.is_dir():
            raise CapsuleError("The expected API 35/Linux build-tools files are absent.")
        sdk = folder / "sdk"
        shutil.copytree(platform_root, sdk / "platforms" / "android-35")
        shutil.copytree(tools_root, sdk / "build-tools" / BUILD_TOOLS)
        make_private_runtime(sdk, args.output, {"route": "read-only import of owner-supplied private Capsule",
                             "original_capsule_sha256": original_hash,
                             "sdk_license": "existing owner installation; no new agreement accepted by this import"})
    if digest(original) != original_hash:
        raise CapsuleError("Original Capsule hash changed unexpectedly.")
    print("ORIGINAL CAPSULE: SHA-256 unchanged.")


def run_project(args):
    sdk = sdk_path(args.sdk)
    doctor(sdk)
    project = Path(args.project).resolve()
    script = inside(project, args.script)
    if not script.is_file():
        raise CapsuleError("Project build script not found: " + args.script)
    env = os.environ.copy()
    env.update({"ANDROID_SDK_ROOT": str(sdk), "ANDROID_HOME": str(sdk),
                "WAKKA_ANDROID_JAR": str(toolpaths(sdk)["android_jar"]),
                "ABC_SDK_ROOT": str(sdk), "ABC_CAPSULE_ROOT": str(ROOT)})
    with tempfile.TemporaryDirectory(prefix="abc-java-shims-") as folder:
        shims = Path(folder)
        import shlex
        for name in ("javac", "jar"):
            path = shims / name
            path.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(x) for x in java_tool(name)) + ' "$@"\n', encoding="utf-8")
            path.chmod(0o755)
        env["PATH"] = str(shims) + os.pathsep + str(sdk / "build-tools" / BUILD_TOOLS) + os.pathsep + env.get("PATH", "")
        # Stream the project's output; no generic 'build passed' claim is generated.
        result = subprocess.run(["bash", str(script)], cwd=project, env=env)
        if result.returncode:
            raise CapsuleError("Project builder exited with code " + str(result.returncode))
    print("PROJECT SCRIPT COMPLETED. Use the project's own APK/signature evidence to assess its output.")


def parser():
    p = argparse.ArgumentParser(description="WAKKA Android Build Capsule public core v" + VERSION)
    s = p.add_subparsers(dest="command", required=True)
    d = s.add_parser("doctor", help="Verify a Linux runtime by checksums and actual tool operations")
    d.add_argument("--sdk")
    b = s.add_parser("build", help="Compile a plain-Java project into a signed APK")
    b.add_argument("--sdk")
    b.add_argument("--project")
    b.add_argument("--output", required=True)
    b.add_argument("--keystore")
    b.add_argument("--key-alias")
    b.add_argument("--password-env", default="ABC_SIGNING_PASSWORD")
    b.add_argument("--debug-sign", action="store_true")
    f = s.add_parser("fetch-runtime", help="Download pinned official SDK archives into a private chat Capsule")
    f.add_argument("--output", required=True)
    f.add_argument("--accept-sdk-license", action="store_true")
    i = s.add_parser("import-private", help="Read an existing owner Capsule and make a separate smaller private runtime")
    i.add_argument("--capsule", required=True)
    i.add_argument("--output", required=True)
    r = s.add_parser("run-project", help="Provide the SDK to an existing preservation project's Bash builder")
    r.add_argument("--sdk")
    r.add_argument("--project", required=True)
    r.add_argument("--script", default="tools/build-apk.sh")
    s.add_parser("verify-public", help="Verify every file in the public core manifest")
    return p


def main():
    if sys.version_info < (3, 10):
        raise CapsuleError("Python 3.10 or newer is needed in the execution host.")
    args = parser().parse_args()
    if args.command == "doctor":
        print(json.dumps(doctor(sdk_path(args.sdk)), indent=2))
    elif args.command == "build":
        build(args)
    elif args.command == "fetch-runtime":
        fetch_runtime(args)
    elif args.command == "import-private":
        import_private(args)
    elif args.command == "run-project":
        run_project(args)
    elif args.command == "verify-public":
        print("PUBLIC CORE VERIFIED: " + str(len(public_files())) + " files.")


if __name__ == "__main__":
    try:
        main()
    except (CapsuleError, OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile) as error:
        print("CAPSULE STOPPED: " + str(error), file=sys.stderr)
        sys.exit(1)
