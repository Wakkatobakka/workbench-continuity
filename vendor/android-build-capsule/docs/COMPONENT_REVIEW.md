# Public component decision — v0.1.0

The public candidate includes Wakka-owned orchestration, an original example,
tests and documentation under MIT. Its runtime setup obtains the existing
Android tools directly; no compiler, packager or signing implementation was
rewritten. The public core contains no Android SDK, Gradle/AGP cache, Google
service libraries, JDK, game data or production signing identity.

## Why the runtime is generated separately

Google's [SDK agreement](https://developer.android.com/studio/terms), checked
October 4, 2026, restricts redistribution generally in section 3.4, while
section 3.5 delegates open-source components to their own licenses. Clearing
one component does not clear an entire SDK bundle. This first candidate avoids
relying on unresolved component-by-component binary rights: people acquire
their own SDK during setup, preserving its notices in a private runtime.
The public core's MIT license does not relicense downloaded tools.

## Decisions

| Material | Role in the original | v0.1 public decision |
| --- | --- | --- |
| New public runner, maker, tests and demo source | Reusable orchestration and proof | Included under MIT |
| Original Linux verification/build wrapper logic | Established SDK environment and real alignment probe | Same approach retained in the new runner; original payload untouched |
| Android API 35 platform | Java API classes and resource linking | Official direct-download setup or owner read-only import; no public binary payload |
| Linux Build Tools 35.0.0 | AAPT/AAPT2, D8, zipalign and apksigner | Official direct-download setup or owner read-only import; tools retained as received |
| Windows SDK and platform-tools | Original local/watch workflow | Omitted from this Linux chat profile; original remains available privately |
| Gradle 8.13 and AGP/Maven dependency cache | Broader Gradle and watch builds | Omitted from first profile; project-specific preparation needed |
| Google Play/Wear service AARs | Watch communication dependencies | Omitted; no public redistribution claim made |
| JDK | Host Java execution and compilation | Host prerequisite; not bundled |
| NDK/PS2 tooling attached separately | Later native/C++ project work | Outside this candidate's audit and proof; not bundled |
| Project keys, accounts, ROMs, media and private source | Belong to individual projects | Never collected by public/runtime makers |

The full cached environment has not been declared unshareable in its entirety.
Some omitted tools may support a future redistributable binary module with
proper notices and any required source. They were omitted here because they
are unnecessary for the first proved profile and do not need to be redistributed
to retain that profile's build capability.

## Download provenance

`official-downloads.json` pins two Google repository archives: the API 35
platform revision 2 and Linux Build Tools 35.0.0. Their bytes were downloaded,
matched to Google's published SHA-1/size metadata, and hashed with SHA-256.
Both acquisition implementations check SHA-256 and size. The Python path
also checks published SHA-1 on a new download. A failed check stops setup.

The Windows maker displays the current repository agreement before SDK
downloads. The Linux command requires an explicit personal acceptance flag.
Neither path accepts agreements silently or publishes the resulting SDK ZIP.

## Release boundary

`PUBLIC_FILES.sha256.json` is the public allowlist. `tools/package_public.py`
refuses SDK/runtime directories and key/tool-binary extensions. The sole
allowed APK is the original demo, built from the included source. Default
debug signing creates a local private test key; only its public certificate
appears in the APK and evidence.

This is a documented packaging decision, not a promise that every future
dependency, app, trademark use or distribution venue has been cleared. Changes
to the release composition need a new component decision and verification.
