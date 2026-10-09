WAKKA ANDROID BUILD CAPSULE - PUBLIC CORE v0.1.0
==============================================

This is the shareable public core: our build runner, setup maker, example app,
tests, license records and Passport context. Its code and example are MIT licensed.
It does not contain Google's Android SDK binaries or the old Gradle/Wear cache.

FIRST USE ON A WINDOWS PC
------------------------
1. Extract this entire ZIP into a new folder. Keep all its files together.
2. Double-click MAKE_CHAT_CAPSULE.bat.
3. Read the Android SDK agreement in the window that opens. Click I accept
   only if you personally accept Google's agreement. Cancel exits setup.
4. Let the downloads, checks and ZIP creation finish. No Python or Java
   installation is needed on this Windows PC for the maker.
5. Explorer opens with your WAKKA_Chat_Runtime_[date_time].zip selected.
6. Upload THAT generated ZIP with your project's preservation/source package
   in a chat that can execute code. Ask the assistant to read AI_START_HERE.txt.

Do this setup once and keep the resulting runtime ZIP for later chats.
Internet is needed to make the runtime. Completed builds can run offline.
The chat host needs Linux x86_64, Python 3.10+ and JDK 17+; these are checked.

WHAT TO SHARE
-------------
Share the original PUBLIC CORE ZIP or its source files on GitHub.
Keep the generated Private_Capsules/ SDK bundles out of the public repository.
Do not add your existing private Capsule, keystores or game/media files.

TRY THE EXAMPLE
---------------
examples/CapsuleDemo/prebuilt/CapsuleDemo_v0.1.0.apk is an original small app.
It was compiled, aligned and signature-verified here. It has not yet been
run on an Android device. It is separate from your existing Wakka apps.
It includes an HTML page and a button that calls a native Java counter.
Its source and build evidence are included beside it.

YOUR EXISTING CAPSULE
--------------------
Your existing Capsule can supply the SDK without another download. The assistant
can use the read-only import-private command documented in README.md to create
a separate smaller PRIVATE runtime. This does not rewrite your original ZIP.
The import copies the API 35 platform and Linux build-tools. It leaves out the
old Windows SDK, Gradle cache, watch dependencies and all project signing keys.

SUPPORTED FIRST PROFILE
-----------------------
Plain Java Android apps with Android resources and optional offline HTML assets.
Existing Bash project builders can also use run-project for this SDK environment.
Gradle, Kotlin, Compose, Wear/GMS dependencies and NDK/C++ builds need their own
project tooling/dependencies; v0.1 does not promise they are bundled or validated.

Read README.md for developer commands and docs/COMPONENT_REVIEW.md for the
public packaging decision. Read VERIFICATION.json for the checks actually run.
