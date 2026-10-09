# Public/private boundary

Public source and release assets contain the Workbench code, small owned example, artwork, vendored public MIT setup/runner, public SDK file hash metadata and Apache-licensed apksig library. The included setup verifies official Android downloads and asks the person running it to read and decide on Google's agreement.

Owner-private HTML/APK/runtime carriers, original owner QA fixtures, real project archives, signing keys/passwords and personal reports are excluded from this release. Historical owner carrier receipts are not distributed as proof of the newly generated public routes.

Loading a runtime is separate from project intake. Workbench selects only known SDK files by their exact hashes and includes its trusted public runner. It does not carry extra notes, projects, keys or code from the imported runtime. It generates new private PDF/ZIP carriers with hashes and reconstruction manifests. A bad import leaves the previous runtime in place. Runtime persistence is separate from project persistence and best effort; retain your original runtime ZIP.

Source intake and packet credential filtering are unchanged. The Android signer selects keys in native code, never through the WebView/project file store. Keys and passwords are temporary private signing state; its public receipt contains verification facts and public certificate hashes. A public receipt does not establish a phone install or device behavior.

Share the PUBLIC ZIP, source ZIP, HTML, APK and public verification/checksum files. Do not publish generated runtime ZIPs, destination bundles, `.private` folders, signing backups or the owner's private source package.
