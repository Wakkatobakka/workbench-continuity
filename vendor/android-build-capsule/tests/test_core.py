"""SDK-free checks for the public core's file and input boundaries."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wakka_capsule_test", ROOT / "abc.py")
abc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abc)


class CapsuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, name, text="fixture"):
        path = self.root / "fixture.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(name, text)
        return path

    def test_traversal_zip_is_rejected(self):
        with self.assertRaises(abc.CapsuleError):
            abc.safe_extract(self.archive("../outside.txt"), self.root / "out")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_windows_drive_zip_is_rejected(self):
        with self.assertRaises(abc.CapsuleError):
            abc.safe_extract(self.archive("C:\\outside.txt"), self.root / "out")

    def test_backslashes_become_real_directories(self):
        abc.safe_extract(self.archive("sdk\\build-tools\\aapt2"), self.root / "out")
        self.assertEqual((self.root / "out/sdk/build-tools/aapt2").read_text(), "fixture")

    def test_backslash_directory_entries_work(self):
        path = self.root / "directory.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("sdk\\", "")
            z.writestr("sdk\\file.txt", "fixture")
        abc.safe_extract(path, self.root / "out")
        self.assertTrue((self.root / "out/sdk/file.txt").is_file())

    def test_symlink_zip_is_rejected(self):
        path = self.root / "symlink.zip"
        with zipfile.ZipFile(path, "w") as z:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            z.writestr(entry, "../../outside")
        with self.assertRaises(abc.CapsuleError):
            abc.safe_extract(path, self.root / "out")

    def test_license_is_not_accepted_automatically(self):
        args = abc.parser().parse_args(["fetch-runtime", "--output", str(self.root / "runtime")])
        with patch.object(abc.urllib.request, "urlopen", side_effect=AssertionError("No network allowed")):
            with self.assertRaisesRegex(abc.CapsuleError, "personally"):
                abc.fetch_runtime(args)
        self.assertFalse((self.root / "runtime").exists())

    def test_runtime_checksum_failure_prevents_tool_use(self):
        sdk = self.root / "runtime/sdk"
        sdk.mkdir(parents=True)
        (sdk / "tool.txt").write_text("changed")
        abc.write_json(sdk.parent / "SDK_FILES.sha256.json", {"tool.txt": "0" * 64})
        with self.assertRaisesRegex(abc.CapsuleError, "checksum"):
            abc.check_runtime_inventory(sdk)

    def test_project_path_escape_is_rejected(self):
        project = self.root / "project"
        project.mkdir()
        settings = json.loads((ROOT / "examples/CapsuleDemo/capsule-project.json").read_text())
        settings["sources"] = "../outside"
        abc.write_json(project / "capsule-project.json", settings)
        with self.assertRaises(abc.CapsuleError):
            abc.project_settings(project)

    def test_version_cannot_escape_output_directory(self):
        project = self.root / "project"
        project.mkdir()
        settings = json.loads((ROOT / "examples/CapsuleDemo/capsule-project.json").read_text())
        settings["version_name"] = "../../../outside"
        abc.write_json(project / "capsule-project.json", settings)
        with self.assertRaises(abc.CapsuleError):
            abc.project_settings(project)

    def test_public_allowlist_does_not_collect_private_keys(self):
        core = self.root / "core"
        (core / ".private/signing").mkdir(parents=True)
        (core / ".private/signing/owner.jks").write_text("private fixture")
        (core / "entry.txt").write_text("public fixture")
        abc.write_json(core / "PUBLIC_FILES.sha256.json", {"entry.txt": abc.digest(core / "entry.txt")})
        with patch.object(abc, "ROOT", core):
            self.assertEqual(abc.public_files(), ["entry.txt", "PUBLIC_FILES.sha256.json"])

    def test_mismatched_download_does_not_become_cache(self):
        payload = self.root / "download.bin"
        payload.write_bytes(b"wrong bytes")
        record = {"filename": "archive.zip", "url": payload.as_uri(), "size_bytes": 11,
                  "sha1": "0" * 40, "sha256": "0" * 64}
        cache = self.root / "cache"
        cache.mkdir()
        with self.assertRaisesRegex(abc.CapsuleError, "checksum"):
            abc.fetch_archive(record, cache)
        self.assertFalse((cache / "archive.zip").exists())
        self.assertFalse((cache / "archive.zip.partial").exists())

    def test_transferred_sdk_executable_can_recover_its_mode(self):
        if abc.platform.system() != "Linux":
            self.skipTest("Linux executable mode check")
        tool = self.root / "sdk-tool"
        tool.write_text("#!/bin/sh\nprintf 'fixture-ready'\n")
        tool.chmod(0o600)
        self.assertEqual(abc.run([tool]), "fixture-ready")

    def test_runtime_zip_keeps_the_full_version_in_its_filename(self):
        core = self.root / "core"
        core.mkdir()
        (core / "entry.txt").write_text("public fixture")
        abc.write_json(core / "PUBLIC_FILES.sha256.json", {"entry.txt": abc.digest(core / "entry.txt")})
        sdk = self.root / "sdk"
        sdk.mkdir()
        (sdk / "tool.txt").write_text("SDK fixture")
        destination = self.root / "runtime-v0.1.0"
        with patch.object(abc, "ROOT", core):
            archive = abc.make_private_runtime(sdk, destination, {"route": "test fixture"})
        self.assertEqual(archive.name, "runtime-v0.1.0.zip")


if __name__ == "__main__":
    unittest.main()
