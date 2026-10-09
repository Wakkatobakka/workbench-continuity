![WAKKA Android Build Capsule](WAKKA_Android_Build_Capsule_Social_Preview.jpg)

# WAKKA Android Build Capsule — Public Core

**Give chat hands.**

Give a chat with code execution the Android build tools it needs, then direct,
test and iterate on your app conversationally.

This first public candidate contains an MIT-licensed build runner, a Windows
runtime maker, an original example app, component decisions, and Artifact
Passport 0.7 context. It provides a clear preparation path without publishing
the SDK bundle from the original private Capsule.

## Why this exists

This started as a simple question: **why can't we give chat the tools it keeps asking me to use?**

The Capsule grew out of trying to remove the handoff between an AI that knew what needed to happen and the person who still had to perform every technical step manually.

**[Read “Give Chat Hands — How the Android Build Capsule Happened”](docs/GIVE_CHAT_HANDS_HISTORIA.md)**

## Start here

### Quick start

1. Download the public release ZIP.
2. Run `MAKE_CHAT_CAPSULE.bat`.
3. Upload the generated chat runtime to a coding chat.
4. Tell the chat to read `AI_START_HERE.txt` before it begins working.

That is the basic path. The sections below explain what each step does, what is included, and the current limits of the public Capsule.

On Windows, extract the public ZIP and double-click **MAKE_CHAT_CAPSULE.bat**.
Read Google's SDK agreement. If you accept it, the maker downloads the pinned
official API 35 platform and Linux Build Tools 35.0.0, verifies their SHA-256
checksums and creates a separate private runtime ZIP. It needs neither Python
nor Java on the collecting Windows PC. Keep this runtime for later chats.

Upload the generated runtime ZIP with your app's source/preservation package
in a chat that supports code execution. Tell the assistant to read
**AI_START_HERE.txt**. The execution host needs Linux x86_64, Python 3.10+ and
JDK 17+. The completed runtime builds offline; its setup downloads need internet.

**Share this public core. Keep generated SDK runtimes and signing keys private.**
The maker's downloads remain subject to Google's agreement and component
licenses. The MIT license covers this project's own code and example.

## What v0.1 does

| Capability | Status |
| --- | --- |
| Compile plain Java and Android resources into an APK | Implemented; example build tested on Linux x86_64 |
| Include offline HTML assets and a native Java bridge | Example included; source built and signature-verified |
| Align and sign; verify v1/v2/v3 signatures | Implemented and tested |
| Reuse an owner-provided Capsule without rewriting it | Read-only SDK import; tested |
| Supply this SDK to existing Bash project builders | Implemented; tested with the example preservation-style builder |
| Make a runtime directly from official SDK archives | Owner Windows setup completed; its generated runtime was freshly extracted and built the demo from source |
| Bundle Gradle, AGP, Wear/GMS caches, Kotlin, Compose or NDK | Not included in the first profile |
| Prove device behavior automatically | Not established; no Android device/emulator run performed |

The original private Capsule remains a separate artifact. This first public
profile is narrower than its full cached environment.

The public Windows setup-to-source-build route passed with the owner-generated
runtime on October 4, 2026. See [the follow-up test receipt](docs/PUBLIC_PATH_TEST.md).
Android device behavior is recorded separately and remains untested here.

## Commands for the assistant or developer

Run from the extracted runtime folder:

```bash
python3 abc.py verify-public
python3 abc.py doctor
python3 abc.py build --output /path/to/new-output-folder
```

The default project is the included CapsuleDemo. An output folder must be new;
the builder refuses to overwrite existing releases. Outputs are a signed APK,
BUILD_EVIDENCE.json and BUILD_LOG.txt. The example's local test identity is
generated under `.private/signing`; no key is distributed.

To build another plain-Java app, create its `capsule-project.json` using the
example as a template. Set its package, versions, SDK levels and source paths.
Android Java source, the manifest, resources and assets stay in that project.

```bash
python3 abc.py build --project /path/to/app --output /path/to/new-output \
  --keystore /path/to/owner-key.jks --key-alias owner-key \
  --password-env ABC_SIGNING_PASSWORD
```

Set `ABC_SIGNING_PASSWORD` securely in the execution environment. Do not paste
the password into command text. To intentionally make a new test app identity,
use `--debug-sign` instead. It cannot update an app signed with another key.

Java compiles with `--release 8`; D8 handles bytecode for the chosen minimum
API. External Java libraries and core-library desugaring are not implemented
in this profile. Apps requiring them should use their own project builder.

### Existing preservation projects

```bash
python3 abc.py run-project --project /path/to/preserved-app \
  --script tools/build-apk.sh
```

The command runs the project's own Bash builder with this SDK on PATH and
`ANDROID_SDK_ROOT`, `ANDROID_HOME` and `WAKKA_ANDROID_JAR` set. It supplies javac
and jar shims if their host launchers are absent but the JDK modules exist.
Inspect the builder first. It still needs any project-specific dependencies,
signing identity and checks. Script completion is not reported as device proof.

### Existing private Capsule: no new download

Run from the verified public core, using the owner's existing Capsule ZIP:

```bash
python3 abc.py import-private --capsule /path/to/Android-Build-Capsule.zip \
  --output /path/to/new-private-runtime
```

It reads the original, copies the API 35 platform and Linux Build Tools 35.0.0
into a separate runtime, and compares the original's SHA-256 before/after.
It does not copy the old Gradle/Wear cache, Windows SDK, personal projects or
signing directories. This resulting SDK ZIP is still private.

### Direct setup on Linux

Read [Google's SDK agreement](https://developer.android.com/studio/terms).
Only the person doing setup may choose to accept it:

```bash
python3 abc.py fetch-runtime --output /path/to/new-private-runtime \
  --accept-sdk-license
```

Without that explicit flag it stops before downloads. Archive names, sizes and
SHA-256 hashes are pinned in `official-downloads.json`. Pins were calculated
from official Google downloads and compared with Google's published SHA-1
values on October 4, 2026. Files and notices are retained in the private SDK.
No downloads execute an installer or change global Java or SDK settings.

## Example app

`examples/CapsuleDemo` contains an original offline HTML page and a native Java
counter. Tap its button: the native counter at the top should increment. Its
source, prebuilt test APK and build evidence are included. The APK has no
internet permission and is a separate package from existing Wakka apps.
Actual device behavior awaits a device run.

## Public packaging

The public release is generated from an explicit allowlist and checksum
manifest. Generated `.private/`, `runtime/`, and `Private_Capsules/` folders,
SDK binaries, Gradle caches and private keys are excluded. The only included
APK is the original example. To regenerate the public ZIP:

```bash
python3 tools/package_public.py --output /path/to/new-public-core.zip
```

See `docs/COMPONENT_REVIEW.md`, `COMPONENT_AUDIT.json`, `VERIFICATION.json` and
the Passport/Handoff for evidence, scope and remaining release checks.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover ZIP traversal/symlinks, backslash normalization, invalid
projects, license-consent gating, checksum validation and private-file
exclusion. They need no SDK. Real APK build evidence is recorded separately.

## License and credit

MIT, copyright 2026 Wakka, for this core, documentation and original example.
SDK tools obtained during personal setup keep their own terms and notices.
This project is independent of Google and OpenAI. It does not redistribute
their SDKs or promise an unlimited or universally supported chat environment.
