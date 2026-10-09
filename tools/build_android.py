#!/usr/bin/env python3
"""Workbench Android builder, derived from the WAKKA Build Capsule MIT core.

Adds a pinned Android apksig program library without changing any carrier or SDK.
Python standard library; offline API 35 runtime and host JDK 17+ required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION = "0.2.0-preview.3"
WORKBENCH_VERSION = "1.2.0"
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
            "d8": bt / "lib" / "d8.jar", "apksigner": bt / "lib" / "apksigner.jar",
            "lambda_stubs": bt / "core-lambda-stubs.jar"}


def android_compiler_flags(sdk):
    # Android's own API stubs define the platform. This also works on hosts
    # with a compiler module but without javac or ct.sym. source/target alone
    # would leave desktop JDK APIs available. The SDK lambda stubs are needed
    # by javac for Java 8 lambda expressions before D8 desugaring.
    p = toolpaths(sdk)
    return ["-encoding", "UTF-8", "-source", "8", "-target", "8",
            "-bootclasspath", os.pathsep.join([str(p["lambda_stubs"]), str(p["android_jar"])])]


def check_android_compiler(sdk):
    with tempfile.TemporaryDirectory(prefix="abc-compiler-") as folder:
        folder = Path(folder)
        source = folder / "AndroidCompilerProbe.java"
        source.write_text("import android.app.Activity;\npublic final class AndroidCompilerProbe extends Activity { Runnable r = () -> {}; }\n", encoding="utf-8")
        positive = folder / "positive"
        positive.mkdir()
        compiler = java_tool("javac")
        flags = android_compiler_flags(sdk)
        output = run(compiler + flags + ["-d", positive, source], timeout=12)
        data = (positive / "AndroidCompilerProbe.class").read_bytes()
        if data[:4] != b"\xca\xfe\xba\xbe" or struct.unpack(">H", data[6:8])[0] != 52:
            raise CapsuleError("The Android compiler probe did not produce Java 8 bytecode.")
        negative = folder / "DesktopOnly.java"
        negative.write_text("public class DesktopOnly { java.awt.Frame frame; }\n", encoding="utf-8")
        result = subprocess.run([str(x) for x in compiler + flags + ["-d", positive, negative]],
                                capture_output=True, text=True, timeout=12)
        if result.returncode == 0 or "package java.awt does not exist" not in result.stderr:
            raise CapsuleError("The compiler did not enforce the Android API boundary.")
        return {"android_activity_and_lambda_compiled": True, "fresh_class_major": 52,
                "positive_class_sha256": hashlib.sha256(data).hexdigest(),
                "desktop_api_rejected": True, "negative_compile_exit_code": result.returncode,
                "compiler": compiler, "flags": flags, "positive_output": output,
                "negative_output": result.stderr}


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
    values["compiler_api_check"] = check_android_compiler(sdk)
    print("TOOLCHAIN READY — Java, resources, DEX, alignment and signing tools execute.", flush=True)
    return values


def project_settings(project):
    path = project / "capsule-project.json"
    if not path.is_file():
        raise CapsuleError("Missing capsule-project.json. Existing preservation projects "
                           "with their own builder can use run-project instead.")
    c = json.loads(path.read_text(encoding="utf-8"))
    if c.get("profile") != "plain-java":
        raise CapsuleError("Only the plain-java profile is implemented in the current Capsule profile.")
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
    library = inside(project, "libs/apksig-35.0.0.jar")
    pins = json.loads((ROOT.parent / "third-party/APKSIG_PINS.json").read_text())
    if not library.is_file() or digest(library) != pins["filtered_jar_sha256"]:
        raise CapsuleError("Run tools/prepare_signing_library.py against the pinned SDK first.")
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
        compiler_args = android_compiler_flags(sdk) + ["-classpath", str(library), "-d", str(classes)] + [str(x) for x in sources]
        argfile.write_text("\n".join('"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
                                         for x in compiler_args), encoding="utf-8")
        logs.append(run(java_tool("javac") + ["@" + str(argfile)]))
        compiled_jar = scratch / "classes.jar"
        with zipfile.ZipFile(compiled_jar, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in sorted(classes.rglob("*.class")):
                z.write(f, f.relative_to(classes).as_posix())
        logs.append(run([java_command(), "-cp", p["d8"], "com.android.tools.r8.D8", "--lib",
                         p["android_jar"], "--min-api", str(c["min_sdk"]), "--output", dex, compiled_jar, library]))
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
        # Probe all emitted schemes explicitly. For minSdk 28 the verifier normally
        # ignores v1 because every supported device already accepts v2/v3.
        verification = run([java_command(), "-jar", p["apksigner"], "verify", "--verbose", "--print-certs", "--min-sdk-version", "23", apk])
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
        evidence = {"workbench_version": WORKBENCH_VERSION, "library_sha256": {"apksig-35.0.0.jar": digest(library)}, "capsule_version": VERSION, "built_at": timestamp(), "profile": "plain-java",
                    "project": c["package"], "version": c["version_name"], "apk": apk.name,
                    "apk_sha256": digest(apk), "fresh_java_compilation": True,
                    "fresh_dex_compilation": True, "dex_sha256": [digest(x) for x in dex_files],
                    "signing": signing_kind, "signature_verification": verification,
                    "signature_scheme_probe_min_sdk": 23,
                    "application_min_sdk": c["min_sdk"],
                    "alignment": "4-byte entries and 16 KiB native-library alignment checked",
                    "apk_badging": metadata, "tools": tools,
                    "source_sha256": {f.relative_to(project).as_posix(): digest(f) for f in sorted(source_files)},
                    "android_emulator": "not run", "physical_device": "not run",
                    "claim": "Source compiled, APK assembled, aligned, signed and verified; runtime behavior remains untested."}
        write_json(output / "BUILD_EVIDENCE.json", evidence)
        (output / "BUILD_LOG.txt").write_text("\n\n".join(logs + [verification, metadata]) + "\n", encoding="utf-8")
    print("APK READY: " + str(apk))
    print("SIGNATURES: v1 / v2 / v3 verified. DEVICE TEST: not run.")



def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--keystore", required=True)
    ap.add_argument("--key-alias", required=True)
    ap.add_argument("--password-env", default="CONTINUITY_OWNER_PASSWORD")
    ap.set_defaults(debug_sign=False)
    try:
        build(ap.parse_args())
    except CapsuleError as exc:
        raise SystemExit(str(exc))

if __name__ == "__main__":
    main()
