#!/usr/bin/env python3
"""Inspect the native/UI separation. This does not execute an Android UI."""
import json
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
manifest = ET.parse(root / 'android/AndroidManifest.xml').getroot()
ns = '{http://schemas.android.com/apk/res/android}'
package = manifest.attrib['package']
source = root / 'android/src/dev/wakka/continuity/v12'
main = (source / 'MainActivity.java').read_text()
native = (source / 'LocalSigningActivity.java').read_text()
core = (root / 'android/src/dev/wakka/continuity/signing/LocalApkSigner.java').read_text()
tests = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    tests.append({'test': name, 'passed': True})

bridge = re.findall(r'@JavascriptInterface\s+public\s+\w+\s+(\w+)\(([^)]*)\)', main)
signing_methods = [(name, parameters.strip()) for name, parameters in bridge if 'sign' in name.lower() or 'key' in name.lower()]
check('Signing WebView entry has no key/password/file parameters', signing_methods == [('openLocalSigning', '')])
check('Native signing screen exposes no Javascript interfaces', '@JavascriptInterface' not in native and 'addJavascriptInterface' not in native)
check('Password fields are native and masked', 'TYPE_TEXT_VARIATION_PASSWORD' in native and 'readSecret(EditText field)' in native)
check('Native key/password fields are excluded from saved UI state and autofill', 'setSaveEnabled(false)' in native and 'setFreezesText(false)' in native and 'IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS' in native)
check('Native screen protects screenshots', 'FLAG_SECURE' in native)
check('Local signing activity is not externally exported', any(a.get(ns + 'name', '').endswith('.LocalSigningActivity') and a.get(ns + 'exported') == 'false' for a in manifest.findall('application/activity')))
check('App declares no network permission', not any(a.get(ns + 'name') == 'android.permission.INTERNET' for a in manifest.findall('uses-permission')))
check('Private key uses app cache staging rather than project assets or storage', 'getCacheDir()' in native and 'chosenKey.delete()' in native and 'removeAbandonedSessions' in native)
check('Private original ZIP key extraction remains in native code', 'extractKey(File archive, String name)' in native and 'new File(session,' in native and 'entry.getCrc()' in native and 'MAX_KEY_BYTES' in native)
check('Password buffers are wiped after signing', "Arrays.fill(store, '\\0')" in native and "Arrays.fill(key, '\\0')" in native)
check('Returned receipt is emitted only after successful save', 'if (savedApk && receipt != null) setResult' in native and 'report.put("savedOnDevice", true)' in native)
check('Receipt retains untested installation scope', 'report.put("installObserved", false)' in native)
check('APK signature name does not disclose owner alias', '"CONTINUITY", identity.key' in core)
check('Public signer receipt does not contain key, password, alias or key paths', not any(word in core[core.index('public static final class Result'): ] for word in ('storePassword', 'keyPassword', 'keystore', 'alias')))
files = [root / 'android/AndroidManifest.xml', source / 'MainActivity.java', source / 'LocalSigningActivity.java', root / 'android/src/dev/wakka/continuity/signing/LocalApkSigner.java']
report = {'format': 'continuity-local-signing-privacy-audit/1', 'passed': True, 'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, 'tests': tests, 'scope': 'Static native/UI boundary inspection of issued source. Host signer execution is reported separately.', 'limitations': ['No native Android UI, SAF picker, process-death recovery or physical-device installation was executed.']}
out = root / 'evidence/signing-v1.2/privacy-boundary-verification.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': True, 'test_count': len(tests), 'report': str(out)}))
