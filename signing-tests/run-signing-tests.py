#!/usr/bin/env python3
"""Host JVM tests for private local APK signing. No device installation is claimed.

Uses temporary generated keys. Optional --real-projects uses owner input archives
without copying credentials into reports, source packages, or command arguments.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(command, env=None):
    result = subprocess.run([str(v) for v in command], env=env, capture_output=True, text=True)
    if result.returncode:
        # Do not echo commands, full output or exception texts: owner credentials
        # and keytool implementations can put sensitive inputs there.
        raise AssertionError('Tool failed: ' + Path(str(command[0])).name + ', exit ' + str(result.returncode))
    return result.stdout


def payload_hashes(path: Path):
    with zipfile.ZipFile(path) as archive:
        found = {}
        for member in archive.infolist():
            if member.is_dir() or member.filename.upper().startswith('META-INF/'):
                continue
            h = hashlib.sha256()
            with archive.open(member) as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    h.update(block)
            found[member.filename] = {'size': member.file_size, 'sha256': h.hexdigest()}
        return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--real-projects', type=Path)
    parser.add_argument('--java-heap', help='Optional maximum JVM heap, for example 64m; does not bound native buffers or mapped files.')
    parser.add_argument('--report', type=Path, default=SOURCE / 'evidence/signing-v1.2/local-signing-verification.json')
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    tools = sdk / 'build-tools/35.0.0'
    apk_signer = tools / 'lib/apksigner.jar'
    signing_library = SOURCE / 'android/libs/apksig-35.0.0.jar'
    android_jar = sdk / 'platforms/android-35/android.jar'
    results = []

    def record(name, detail):
        results.append({'test': name, 'passed': True, **detail})

    with tempfile.TemporaryDirectory(prefix='continuity-signing-qa-') as working:
        working = Path(working)
        classes = working / 'classes'
        classes.mkdir()
        java_sources = sorted((SOURCE / 'android/src/dev/wakka/continuity/signing').glob('*.java'))
        tested_source_hashes = {str(p.relative_to(SOURCE)): digest(p) for p in java_sources}
        run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '8', '-target', '8', '-cp', signing_library, '-d', classes, *java_sources, HERE / 'SigningHarness.java'])
        classpath = str(classes) + os.pathsep + str(signing_library)
        default_pass = secrets.token_urlsafe(30)
        environment = dict(os.environ, QA_STORE_PASSWORD=default_pass, QA_KEY_PASSWORD=default_pass)

        def key_file(name, store_type, alias):
            path = working / name
            run(['java', '-m', 'java.base/sun.security.tools.keytool.Main', '-genkeypair', '-keystore', path, '-storetype', store_type, '-alias', alias, '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=Continuity QA,O=Temporary Test', '-storepass:env', 'QA_STORE_PASSWORD', '-keypass:env', 'QA_KEY_PASSWORD', '-noprompt'], environment)
            return path

        jks = key_file('qa.jks', 'JKS', 'qaowner')
        p12 = key_file('qa.p12', 'PKCS12', 'qap12')
        other = key_file('other.p12', 'PKCS12', 'qaother')

        def harness(command, *values, env=None, expected_failure=False):
            result = subprocess.run(['java', *(['-Xmx' + args.java_heap] if args.java_heap else []), '-cp', classpath, 'SigningHarness', command, *map(str, values)], env=env or environment, capture_output=True, text=True)
            try:
                obj = json.loads(result.stdout)
            except ValueError:
                raise AssertionError('Signing harness did not return public JSON') from None
            assert (result.returncode != 0) == expected_failure, 'Unexpected harness failure status'
            # Every receipt is searched against every private test password.
            for sensitive in (default_pass, (env or {}).get('QA_STORE_PASSWORD'), (env or {}).get('QA_KEY_PASSWORD')):
                if sensitive:
                    assert sensitive not in result.stdout, 'Credential reached public receipt'
            return obj

        def fixture(name, package, code, version, split=False):
            root = working / name
            root.mkdir()
            manifest = root / 'AndroidManifest.xml'
            manifest.write_text('<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + package + '"' + (' split="config.test"' if split else '') + ' android:versionCode="' + str(code) + '" android:versionName="' + version + '"><uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35"/><application android:label="Continuity Signing QA" android:hasCode="false"/></manifest>\n')
            target = root / 'unsigned.apk'
            run([tools / 'aapt', 'package', '-f', '-M', manifest, '-I', android_jar, '-F', target])
            with zipfile.ZipFile(target, 'a', zipfile.ZIP_DEFLATED) as z:
                z.writestr('assets/decisions.txt', b'Carry the current work forward.\n')
                z.writestr('lib/arm64-v8a/libretained.so', b'\x7fELF' + bytes(range(256)) * 512)
            return target

        def verify(path):
            text = run(['java', '-jar', apk_signer, 'verify', '--verbose', '--print-certs', '--min-sdk-version', '23', path])
            schemes = {v: bool(re.search(r'Verified using ' + v + r' scheme .*: true', text)) for v in ('v1', 'v2', 'v3')}
            assert all(schemes.values()), 'Missing verified signing scheme'
            certs = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})', text)
            assert len(certs) == 1
            return {'sha256': digest(path), 'certificate_sha256': certs[0], 'verified_schemes': schemes}

        def sign(source, name, key=jks, alias='qaowner', reference='-', env=None, expected_failure=False):
            output = working / name
            obj = harness('sign', source, output, key, alias, reference, env=env, expected_failure=expected_failure)
            if expected_failure:
                assert not output.exists(), 'Failed signing left an APK'
                return obj, output
            assert output.is_file()
            assert payload_hashes(source) == payload_hashes(output), 'APK source/native/assets changed while signing'
            verified = verify(output)
            assert verified['sha256'] in json.dumps(obj), 'Receipt does not carry actual output hash'
            return obj, output

        assert harness('aliases', jks)['aliases'] == ['qaowner']
        assert harness('aliases', p12)['aliases'] == ['qap12']
        record('JKS and PKCS12 key loading', {'store_formats': ['JKS', 'PKCS12']})
        wrong_env = dict(environment, QA_STORE_PASSWORD=secrets.token_urlsafe(30))
        harness('aliases', jks, env=wrong_env, expected_failure=True)
        harness('aliases', p12, env=wrong_env, expected_failure=True)
        record('Wrong store password rejected', {'store_formats': ['JKS', 'PKCS12']})

        old_unsigned = fixture('old', 'dev.wakka.signingqa', 4, '0.4')
        current_unsigned = fixture('current', 'dev.wakka.signingqa', 5, '0.5')
        old_obj, old = sign(old_unsigned, 'baseline.apk')
        assert old_obj.get('update_compatible', old_obj.get('updateCompatible')) is False
        record('No reference does not claim update compatibility', {'normal_update_metadata_compatible': False})
        debug_obj, debug = sign(current_unsigned, 'returned-debug.apk', other, 'qaother')
        owner_obj, owner = sign(debug, 'owner-update.apk', reference=old)
        assert owner_obj.get('update_compatible', owner_obj.get('updateCompatible')) is True, 'Same package, original owner certificate and higher code was not accepted'
        assert verify(owner)['certificate_sha256'] == verify(old)['certificate_sha256']
        assert verify(owner)['certificate_sha256'] != verify(debug)['certificate_sha256']
        record('Returned debug APK re-signed with original owner identity', {'normal_update_metadata_compatible': True, 'content_preserved': True, 'native_library_preserved': True, 'output_signature': verify(owner)})
        p12_obj, p12_signed = sign(current_unsigned, 'pkcs12-signed.apk', p12, 'qap12')
        record('PKCS12 owner signing verified', {'output_signature': verify(p12_signed)})

        for name, source, key, alias, reference, expected_compatible in (
                ('same version supports normal replacement', old_unsigned, jks, 'qaowner', old, True),
                ('lower version is not an update', fixture('lower', 'dev.wakka.signingqa', 3, '0.3'), jks, 'qaowner', old, False),
                ('wrong package is not an update', fixture('otherpkg', 'dev.wakka.otherqa', 20, '2.0'), jks, 'qaowner', old, False),
                ('different signer is not an update', current_unsigned, p12, 'qap12', old, False)):
            obj, target = sign(source, re.sub('[^a-z]+', '-', name) + '.apk', key, alias, reference)
            assert obj.get('update_compatible', obj.get('updateCompatible')) is expected_compatible, name
            record(name, {'normal_update_metadata_compatible': expected_compatible, 'signed_artifact_verified': True})

        sign(current_unsigned, 'wrong-alias.apk', alias='missing', expected_failure=True)
        wrong_env = dict(environment, QA_KEY_PASSWORD=secrets.token_urlsafe(30))
        sign(current_unsigned, 'wrong-key-password.apk', env=wrong_env, expected_failure=True)
        sign(current_unsigned, 'wrong-store-password.apk', env=dict(environment, QA_STORE_PASSWORD=secrets.token_urlsafe(30)), expected_failure=True)
        record('Wrong alias/key password/store password leave no output', {'rejected_cases': 3})

        split = fixture('split', 'dev.wakka.signingqa', 6, '0.6', split=True)
        sign(split, 'split-signed.apk', expected_failure=True)
        record('Split APK is rejected by single-APK signing flow', {'output_absent': True})

        def changed_manifest(source, name, change):
            path = working / name
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(path, 'w') as output:
                for info in original.infolist():
                    data = original.read(info)
                    if info.filename == 'AndroidManifest.xml':
                        data = change(bytearray(data))
                    output.writestr(info, data)
            return path

        truncated = changed_manifest(current_unsigned, 'truncated-manifest.apk', lambda data: data[:-1])
        sign(truncated, 'truncated-signed.apk', expected_failure=True)
        record('Truncated binary manifest is rejected', {'output_absent': True})

        def mismatch_end_tag(data):
            offset = struct.unpack_from('<H', data, 2)[0]
            root_name = None
            while offset < len(data):
                kind, header, length = struct.unpack_from('<HHI', data, offset)
                if kind == 0x102 and root_name is None:
                    root_name = struct.unpack_from('<I', data, offset + header + 4)[0]
                elif kind == 0x103:
                    struct.pack_into('<I', data, offset + header + 4, root_name)
                    return data
                offset += length
            raise AssertionError('Fixture lacks compiled manifest end tag')

        malformed = changed_manifest(current_unsigned, 'mismatched-end-manifest.apk', mismatch_end_tag)
        sign(malformed, 'mismatched-end-signed.apk', expected_failure=True)
        record('Mismatched binary manifest element is rejected', {'output_absent': True})

        if args.real_projects:
            project_root = args.real_projects.resolve()
            command = project_root / '07-Wakkan_Command_v0.1.19_Preservation.zip'
            with zipfile.ZipFile(command) as z:
                properties = next(n for n in z.namelist() if n.endswith('signing/local-signing.properties'))
                props = dict(line.split('=', 1) for line in z.read(properties).decode().splitlines() if '=' in line and not line.startswith('#'))
                owner_key = working / 'command-owner.keystore'
                owner_key.write_bytes(z.read(next(n for n in z.namelist() if n.endswith('signing/Wakkan_Command.keystore'))))
                original = working / 'command-original.apk'
                original.write_bytes(z.read(next(n for n in z.namelist() if n.endswith('.apk'))))
            private_env = dict(environment, QA_STORE_PASSWORD=props['storePassword'], QA_KEY_PASSWORD=props['keyPassword'])
            obj, target = sign(original, 'command-local-resigned.apk', owner_key, props['keyAlias'], original, env=private_env)
            assert verify(target)['certificate_sha256'] == verify(original)['certificate_sha256']
            assert obj.get('update_compatible', obj.get('updateCompatible')) is True, 'Same-version real APK should permit replacement with matching identity'
            record('Actual Wakkan Command owner key and APK round trip', {'original_sha256': digest(original), 'certificate_matches': True, 'content_preserved': True, 'same_version_replacement_metadata_compatible': True})

            reblue_source = project_root / '08-reBlue_Android_v0.0.33_Source_Update-1-.zip'
            with zipfile.ZipFile(reblue_source) as z:
                script = z.read(next(n for n in z.namelist() if n.endswith('build_v033_from_v032.py'))).decode()
                tree = ast.parse(script)
                sign_values = None
                for node in ast.walk(tree):
                    if isinstance(node, ast.List):
                        values = [x.value if isinstance(x, ast.Constant) else None for x in node.elts]
                        if '--ks-pass' in values and '--ks-key-alias' in values:
                            sign_values = values
                            break
                assert sign_values is not None
                store = sign_values[sign_values.index('--ks-pass') + 1].removeprefix('pass:')
                key_password = sign_values[sign_values.index('--key-pass') + 1].removeprefix('pass:')
                alias = sign_values[sign_values.index('--ks-key-alias') + 1]
                owner_key = working / 'reblue-owner.keystore'
                owner_key.write_bytes(z.read(next(n for n in z.namelist() if n.endswith('signing/prototype.keystore'))))
            original = project_root / '09-reBlue_0.0.33.apk'
            obj, target = sign(original, 'reblue-local-resigned.apk', owner_key, alias, original, env=dict(environment, QA_STORE_PASSWORD=store, QA_KEY_PASSWORD=key_password))
            assert verify(target)['certificate_sha256'] == verify(original)['certificate_sha256']
            assert obj.get('update_compatible', obj.get('updateCompatible')) is True
            retained = payload_hashes(original)
            native = {k: v for k, v in retained.items() if k.startswith('lib/') and k.endswith('.so')}
            record('Actual large reBlue native APK and owner key round trip', {'input_bytes': original.stat().st_size, 'original_sha256': digest(original), 'certificate_matches': True, 'all_non_signature_entries_preserved': True, 'native_libraries': native, 'same_version_replacement_metadata_compatible': True})
            del props, store, key_password, alias, private_env

    assert tested_source_hashes == {str(p.relative_to(SOURCE)): digest(p) for p in java_sources}, 'Signing source changed during verification'
    report = {'format': 'continuity-local-signing-qa/1', 'passed': True, 'signing_source_sha256': tested_source_hashes, 'maximum_java_heap': args.java_heap or 'host default; not constrained', 'tests': results, 'scope': 'Host JVM execution of Android-independent signing core with binary Android manifests; external SDK apksigner v1/v2/v3 verification; actual selected owner inputs when --real-projects is provided.', 'limitations': ['No physical Android device installation/update was executed.', 'Native Android UI, SAF, keystore-provider behavior and device storage handling require device verification.', 'Java heap constraints do not measure total process memory, native buffers or mapped file storage.', 'Metadata compatibility is a necessary update check; Android package/device policy can impose additional installation constraints.'], 'credentials': 'Temporary keys and owner input credentials were used privately and removed from test staging. Reports contain public hashes and certificates only.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'test_count': len(results), 'report': str(args.report)}))


if __name__ == '__main__':
    main()
