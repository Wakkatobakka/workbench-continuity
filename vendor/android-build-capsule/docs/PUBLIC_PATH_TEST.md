# Public setup and source-build confirmation

**Passed on October 4, 2026 for the included CapsuleDemo profile.**

Wakka ran the public Windows maker and supplied its completion screenshot and generated runtime ZIP. The screenshot shows official SDK downloads, extraction, hashing and ZIP creation finishing with READY. The runtime metadata records personal SDK agreement acceptance during that local setup.

The exact generated archive, WAKKA_Chat_Runtime_20261004_033146.zip, was then freshly extracted in this chat environment. Its public core matched all 25 manifest files; all 11,331 SDK inventory hashes verified. The builder used the SDK from that extraction explicitly.

The included demo was compiled from Java source and converted to DEX into a new build output folder. APK alignment passed and v1/v2/v3 signatures verified. No SDK acquisition or old private Capsule import was used during this build.

The execution host was Linux x86_64 with JDK 17.0.20. This records a fresh runtime extraction and build in the current chat environment; it does not claim that a different chat instance or host was used.

See [the setup receipt](PUBLIC_PATH_VERIFICATION.json) and [the full build evidence](PUBLIC_PATH_BUILD_EVIDENCE.json). The completion screenshot and private SDK runtime are not included in the public release.

The freshly built APK has SHA-256:

    0950ec975119dc6c12cafbc0e7bf8926ba3f497fef030f31975a0988e6b6a114

This follow-up APK uses a newly generated local test identity. The earlier prebuilt demo and its matching evidence remain unchanged in examples/CapsuleDemo/prebuilt.

## Remaining scope

No physical Android device or emulator run is recorded here. The successful public setup/build route applies to the included plain-Java example and the documented profile; it does not establish the broader Gradle/Wear/NDK profiles.

The public release's build runner, maker, download pins, tests and example source are unchanged. This preview preparation refreshes documentation, verification context and the public checksum manifest to record the result.
