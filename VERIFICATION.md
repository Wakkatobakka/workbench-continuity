# Verification scope

This preparation keeps the original v1.2.0 project engine, native signing activity, APK signer, keystore handling and manifest inspection byte-for-byte unchanged. `evidence/PRESERVED_SOURCE.json` records their hashes. The native shell changes only its fixed private-carrier table; the public edition saves its generated runtime bundle through the existing streamed save path. Android activity class names remain the same, with an explicit manifest and separate public application ID.

| Check | Observed result |
| --- | --- |
| Public source UI/signing workflow contracts | 7 checks passed |
| Native key/WebView privacy boundary | 14 checks passed |
| Native signer with the published public Maven dependency | 13 host-JVM checks passed |
| Actual public HTML → loaded existing public-setup runtime → Claude PDF carriers → recovery → current example Java/DEX/APK build | Passed; actual emitted carrier bytes used |
| Actual public HTML → loaded existing public-setup runtime → Grok ZIP carriers → recovery → current example Java/DEX/APK build | Passed; actual emitted carrier bytes used |
| Work packet state and source round trip | Passed |
| Invalid runtime replacement | Rejected; previous valid runtime preserved |
| Private runtime extras | Excluded; only pinned SDK files and trusted public core selected |
| Public Android app compilation | Passed; Java and DEX freshly compiled |
| Public APK signature and alignment | v1/v2/v3 and 4-byte/16 KiB alignment checks passed |
| Nested public files, APK, JAR, example/setup ZIPs and HTML embedded setup | Audited; no owner keys or SDK runtime payloads |

The default runtime test uses a clearly identified SDK-free test fixture. The release's real-runtime receipt instead uses the owner's previously generated **public ABC setup runtime**, which is kept outside public source and assets. Each new Claude/Grok carrier is generated and hash-checked; preparation reconstructs the current source and runtime and prints a build command. The test then executes that explicit current-example command and verifies its actual output. It does not build an old fixture as a fallback.

The public runner and Windows setup machinery come from upstream commit `51c8f110c14c7e4e0c0a00a83b5ff48f10bf97ac`. Their code is unchanged. The vendored inventory was refreshed to match current public documentation; a missing upstream `.gitignore` was recovered by its public inventory hash. Upstream's public Windows setup-to-source-build receipt records the prior successful owner run. This preparation did not rerun the Windows agreement dialog or make a new agreement decision.

Fresh physical-device installation, Android WebView/SAF interaction, on-phone runtime import/export/signing, and live external Claude/Grok sessions remain **unobserved** for this public APK. A rendered-browser attempt was blocked by this execution host's browser socket restriction; no rendered-browser pass is claimed. DOM/JavaScript tests and source compilation do not establish those results.

The Google SDK profile and original adapters retain their existing limits. A receiving chat's upload quotas and code-execution restrictions still matter. Local IndexedDB persistence is best effort; keep exported projects and the original runtime ZIP. No universal Android project or all-chat compatibility is claimed.
