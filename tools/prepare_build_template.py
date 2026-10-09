#!/usr/bin/env python3
"""Restore the CURRENT project and personally generated verified Build Capsule SDK without executing
project code. Transport supports existing projects independently of their recipe.
Inspect the printed recipe and capability report before any authorized build.
No network, installations, license acceptance, publication, or fixture fallback.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
import tempfile
import time
import zipfile

PACKET_SHA256 = "__PACKET_SHA256__"
PROJECT_ROOT = __PROJECT_ROOT_JSON__
PASSPORT_ID = __PASSPORT_ID_JSON__
DESTINATION = "__DESTINATION__"
CARRIER_PINS = json.loads(__ROUTE_CARRIER_PINS_JSON_STRING__)
BOOTSTRAP_SHA256 = "ece88b95ca2c463a6c611d6bae6f1ae55f2a1a3e3e06dcef60527231e0e0f49c"
MAX_ZIP = 4 * 1024**3 - 1
MAX_MEMBER = 2 * 1024**3
MAX_EXPANDED = 8 * 1024**3
MAX_MEMBERS = 100000


def stopped(message):
    raise SystemExit("STOPPED: " + message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            stopped("Duplicate JSON property: " + key)
        value[key] = item
    return value


def parse(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)


def signing_handoff(package_name=None, version_name=None, apk=None, apk_sha256=None, version_code=None):
    """Public workflow facts only; release credentials never enter AI results."""
    return {
        "format": "continuity-private-signing-handoff/1", "passport_id": PASSPORT_ID,
        "workflow": "edit anywhere -> build anywhere -> sign privately on the owner device -> install/update",
        "credentials": "Existing owner keystore and passwords stay outside AI work packets. Do not request them or invent a replacement release identity.",
        "built_apk": {"package_name": package_name, "version_name": version_name, "version_code": version_code, "filename": apk, "sha256": apk_sha256},
        "ai_build": {"preserve_application_id": True, "version_code": "For an installed-app update, increase versionCode above the installed/reference app.", "signature": "Unsigned or temporarily debug-signed intermediate APK where supported. A debug signature is not the installed app's release identity."},
        "return_files": ["Actual built APK", "Complete updated source/work packet, Passport and next action", "Build evidence with the actual signing and verification scope"],
        "owner_finalization": {"application": "Workbench Continuity Android -> Sign returned APK", "key": "Select the existing owner keystore directly in the native signer; keep it out of Add files and AI uploads.", "reference": "Compare with the installed app or a known-good APK", "checks": ["Package", "Version compatibility", "Matching signing certificate", "Final APK signature verification"], "update_compatibility": "Unverified until the private signer checks an actual matching reference. No key replacement makes an unrelated signature update-compatible.", "device_state": "Signing does not establish installation or runtime behavior."},
        "receipt": "Attach the public local-signing receipt to the continuing project; no private signing material is included.",
    }


def safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 2048 or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or any(ord(c) < 32 for c in name):
        stopped("Unsafe archive path")
    value = name[:-1] if name.endswith("/") else name
    if any(p in ("", ".", "..") for p in value.split("/")):
        stopped("Unsafe archive path: " + name)
    return value


def archive_items(archive):
    items, seen, total = archive.infolist(), set(), 0
    if len(items) > MAX_MEMBERS:
        stopped("Too many archive members")
    for info in items:
        name = safe_name(info.filename)
        if name in seen:
            stopped("Duplicate archive path: " + name)
        seen.add(name)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or info.flag_bits & 1 or info.compress_type not in (0, 8):
            stopped("Unsupported archive entry: " + name)
        total += info.file_size
        if info.file_size > MAX_MEMBER or total > MAX_EXPANDED:
            stopped("Archive exceeds bounded extraction limits")
    return items


def unpack(source, folder, require_manifest=False, known_names=None):
    """Disk/stream extraction retains large native/content input without RAM copies."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    elif Path(source).stat().st_size > MAX_ZIP:
        stopped("ZIP exceeds standard ZIP input limit")
    with zipfile.ZipFile(source) as archive:
        items = archive_items(archive)
        if require_manifest:
            files = {i.filename for i in items if not i.is_dir()}
            if "FILES_SHA256.json" not in files:
                stopped("Current packet manifest is missing")
            manifest = parse(archive.read("FILES_SHA256.json"))
            if set(manifest) != files - {"FILES_SHA256.json"}:
                stopped("Current packet manifest does not cover exactly the files")
        else:
            manifest = None
        for info in items:
            name = safe_name(info.filename)
            if known_names is not None:
                if name in known_names:
                    stopped("Runtime payload duplicate: " + name)
                known_names.add(name)
            target = folder.joinpath(*PurePosixPath(name).parts)
            if target.is_symlink() or any(p.is_symlink() for p in target.parents if p.is_relative_to(folder)):
                stopped("Extraction target is a symlink")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            h, count = hashlib.sha256(), 0
            with archive.open(info) as src, target.open("wb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(block)
                    h.update(block)
                    count += len(block)
            if count != info.file_size:
                stopped("Extracted file size mismatch: " + name)
            if manifest is not None and name != "FILES_SHA256.json":
                rec = manifest.get(name, {})
                if rec.get("size_bytes") != count or rec.get("sha256") != h.hexdigest():
                    stopped("Current packet checksum mismatch: " + name)
            if (info.external_attr >> 16) & 0o111:
                target.chmod(target.stat().st_mode | 0o100)


def attachment(pdf, role):
    tag = ("/WAKKARole /" + role + "\n").encode("ascii")
    if pdf.count(tag) != 1:
        stopped("PDF must contain exactly one " + role + " attachment")
    start = pdf.index(tag)
    end = pdf.index(b">>", start)
    length = re.search(rb"/WAKKABytes ([0-9]+)", pdf[start:end])
    stream = re.match(rb">>\s*stream\r?\n", pdf[end:end + 40])
    if not length or not stream:
        stopped("PDF attachment metadata is missing")
    n = int(length[1])
    offset = end + stream.end()
    if n > MAX_ZIP or offset + n > len(pdf):
        stopped("PDF attachment exceeds bounds")
    return pdf[offset:offset + n]


def find_file(root, name):
    matches = [p for p in root.rglob(Path(name).name) if p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        stopped("Expected one uploaded " + Path(name).name + "; found " + str(len(matches)))
    return matches[0]


def project_packet(root, work):
    current = [p for p in root.rglob("PROJECT_WORK_PACKET.zip") if p.is_file() and not p.is_symlink()]
    if len(current) > 1:
        stopped("Several current project packets are present")
    if current:
        return current[0]
    if DESTINATION == "claude":
        single = list(root.rglob("PROJECT_WORK_PACKET.pdf"))
        if single:
            out = work / "PROJECT_WORK_PACKET.zip"
            out.write_bytes(attachment(find_file(root, "PROJECT_WORK_PACKET.pdf").read_bytes(), "ContinuityProject"))
            return out
        uploads = sorted(p for p in root.rglob("PROJECT_WORK_PACKET_part*.pdf") if p.is_file() and not p.is_symlink())
        if not uploads:
            stopped("Current-project PDF attachments are missing")
        manifests = [attachment(p.read_bytes(), "ContinuityPartsManifest") for p in uploads]
    else:
        uploads = sorted(p for p in root.rglob("PROJECT_WORK_PACKET_part*.zip") if p.is_file() and not p.is_symlink())
        if not uploads:
            stopped("Current-project ZIP attachments are missing")
        manifests = []
        for p in uploads:
            with zipfile.ZipFile(p) as z:
                archive_items(z)
                manifests.append(z.read("CONTINUITY_PROJECT_PARTS.json"))
    if len(set(manifests)) != 1:
        stopped("Project part manifests differ")
    manifest = parse(manifests[0])
    if manifest.get("format") != "continuity-project-parts/1":
        stopped("Unknown project cargo manifest")
    original, parts = manifest.get("original", {}), manifest.get("parts", [])
    if not 1 <= len(parts) <= 200 or len(parts) != len(uploads) or original.get("size_bytes", 0) > MAX_ZIP:
        stopped("Missing or excessive project parts")
    out = work / "PROJECT_WORK_PACKET.zip"
    h, offset = hashlib.sha256(), 0
    with out.open("xb") as dst:
        for i, record in enumerate(parts, 1):
            if record.get("index") != i or record.get("offset") != offset:
                stopped("Noncontiguous project parts")
            name = safe_name(record.get("name"))
            if "/" in name:
                stopped("Project part name must be an attachment basename")
            file = find_file(root, name)
            if DESTINATION == "claude":
                body = attachment(file.read_bytes(), "ContinuityProjectPart")
            else:
                with zipfile.ZipFile(file) as z:
                    body = z.read(safe_name(record.get("member")))
            if len(body) != record.get("size_bytes") or sha(body) != record.get("sha256"):
                stopped("Project cargo part changed: " + name)
            dst.write(body)
            h.update(body)
            offset += len(body)
    if offset != original.get("size_bytes") or h.hexdigest() != original.get("sha256"):
        stopped("Reconstructed project ZIP failed its hash/size pin")
    return out


def restore_tools(uploaded, work):
    """Reconstruct freshly generated PDF/ZIP carriers, then check every SDK file."""
    manifests=[]
    for file in uploaded.values():
        if DESTINATION == 'claude':
            manifests.append(attachment(file.read_bytes(), 'ContinuityRuntimeManifest'))
        else:
            with zipfile.ZipFile(file) as z:
                archive_items(z)
                manifests.append(z.read('RUNTIME_PARTS.json'))
    if not manifests or len(set(manifests)) != 1:
        stopped('Runtime part manifests differ')
    manifest=parse(manifests[0]);parts=manifest.get('parts',[]);original=manifest.get('original',{})
    if manifest.get('format')!='continuity-runtime-parts/1' or not 1<=len(parts)<=200 or len(parts)!=len(uploaded):
        stopped('Runtime part set is incomplete')
    runtime=work/'verified-runtime.zip';offset=0;h=hashlib.sha256()
    with runtime.open('xb') as dst:
        for i,rec in enumerate(parts,1):
            if rec.get('index')!=i or rec.get('offset')!=offset:stopped('Runtime parts are not contiguous')
            name=safe_name(rec.get('name'));file=uploaded.get(name)
            if not file:stopped('Required runtime part missing')
            if DESTINATION=='claude':body=attachment(file.read_bytes(),'ContinuityRuntimePart')
            else:
                with zipfile.ZipFile(file) as z:body=z.read(safe_name(rec.get('member')))
            if len(body)!=rec.get('size_bytes') or sha(body)!=rec.get('sha256'):stopped('Runtime part identity differs')
            offset+=len(body)
            if offset>MAX_ZIP:stopped('Runtime exceeds size limit')
            dst.write(body);h.update(body)
    if offset!=original.get('size_bytes') or h.hexdigest()!=original.get('sha256'):stopped('Reconstructed runtime differs')
    tools=work/'verified-build-tools';tools.mkdir();unpack(runtime,tools)
    inv=parse((tools/'BUNDLE_FILES.sha256.json').read_bytes())
    actual={p.relative_to(tools).as_posix() for p in tools.rglob('*') if p.is_file()}
    if actual!=set(inv)|{'BUNDLE_FILES.sha256.json'}:stopped('Runtime inventory coverage differs')
    for name,digest in inv.items():
        if file_sha(tools.joinpath(*PurePosixPath(safe_name(name)).parts))!=digest:stopped('Runtime file changed: '+name)
    sdk=tools/'runtime/sdk';sdk_inv=parse((tools/'runtime/SDK_FILES.sha256.json').read_bytes())
    for name,digest in sdk_inv.items():
        if file_sha(sdk.joinpath(*PurePosixPath(safe_name(name)).parts))!=digest:stopped('SDK file changed: '+name)
    return tools,sdk


def expand_source_archives(packet_dir, route):
    """Expand retained source first, then current projections win explicitly."""
    archives = route.get("source_archives", [])
    if not archives:
        return packet_dir
    source_dir = packet_dir.parent / "current-project-source"
    source_dir.mkdir()
    for rec in archives:
        source = packet_dir.joinpath(*PurePosixPath(safe_name(rec["path"])).parts)
        if source.stat().st_size != rec["size_bytes"] or file_sha(source) != rec["sha256"]:
            stopped("Retained source archive changed: " + rec["path"])
        extract_to = rec.get("extract_to", ".")
        target = source_dir if extract_to == "." else source_dir.joinpath(*PurePosixPath(safe_name(extract_to)).parts)
        target.mkdir(parents=True, exist_ok=True)
        unpack(source, target)
    for p in packet_dir.rglob("*"):
        if p.is_file():
            target = source_dir / p.relative_to(packet_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
    return source_dir


def recipes(project):
    result = []
    for p in sorted(project.rglob("*")):
        if p.is_file() and re.match(r"^(build.*|compile.*|make.*|gradlew|CMakeLists|Android\.mk|Application\.mk)(\.(py|sh|bat|ps1|gradle|kts|txt))?$", p.name, re.I):
            record = {"path": str(p), "sha256": file_sha(p), "auto_executed": False}
            if p.suffix == ".py" and p.stat().st_size < 512 * 1024:
                text = p.read_text(errors="replace")
                record["declared_arguments"] = sorted(set(re.findall(r"add_argument\(\s*['\"](--[a-zA-Z0-9-]+)['\"]", text)))
                record["requires_inspection"] = "Inspect source, required inputs, paths and signing behavior before running this imported recipe."
                if "build_v033_from_v032" in p.name:
                    record["historical_input_requirement"] = "Exact signed reBlue 0.0.32 APK (sha256 27a7610182aa6bd1ee6f0e0aacfcabb43035e3191b1dce921d3ccef39b46e7ee) and validated BT02 family stage. A 0.0.33 APK cannot satisfy this unchanged historical recipe's 0.0.32 guard."
            result.append(record)
    return result



def dex_strings(data):
    def u32(offset):
        return struct.unpack_from('<I', data, offset)[0]
    strings = []
    for i in range(u32(56)):
        p = u32(u32(60) + i * 4)
        for _ in range(6):
            b = data[p]
            p += 1
            if b < 128:
                break
        strings.append((p, bytes(data[p:data.index(0, p)])))
    return strings


def dex_classes(data):
    u32 = lambda o: struct.unpack_from('<I', data, o)[0]
    text = dex_strings(data)
    return [text[u32(u32(68) + u32(u32(100) + i * 32) * 4)][1].decode('utf-8') for i in range(u32(96))]


def dirge_patch(data):
    # The existing bounded Dirge recipe retains all baseline classes except
    # these two explicitly replaced TwinInput definitions. No imported module.
    changed = {'Lcom/wakka/dirge/core/TwinInput;', 'Lcom/wakka/dirge/core/TwinInput$Contact;'}
    b = bytearray(data)
    if b[:8] not in (b'dex\n035\0', b'dex\n038\0', b'dex\n039\0'):
        stopped('Unsupported Dirge baseline DEX version')
    classes = dex_classes(b)
    if not changed.issubset(set(classes)):
        stopped('Dirge baseline lacks replacement classes')
    off = struct.unpack_from('<I', b, 100)[0]
    kept = [bytes(b[off + i * 32:off + (i + 1) * 32]) for i, cls in enumerate(classes) if cls not in changed]
    b[off:off + 32 * len(kept)] = b''.join(kept)
    struct.pack_into('<I', b, 96, len(kept))
    for p, text in dex_strings(b):
        replacement = text.replace(b'0.2.3', b'0.2.4')
        b[p:p + len(text)] = replacement
    map_offset = struct.unpack_from('<I', b, 52)[0]
    for i in range(struct.unpack_from('<I', b, map_offset)[0]):
        p = map_offset + 4 + i * 12
        if struct.unpack_from('<H', b, p)[0] == 0x0006:
            struct.pack_into('<I', b, p + 4, len(kept))
    b[12:32] = hashlib.sha1(b[32:]).digest()
    struct.pack_into('<I', b, 8, zlib.adler32(b[12:]) & 0xffffffff)
    return bytes(b)


def build_adapter(args):
    """Explicit SDK-only adapters for inspected current bridge layouts.

    This is a separately invoked build, never part of preparation. It reads
    configuration as data and never imports/executes the project tools/build.py.
    """
    if not args.project or not args.sdk:
        stopped('Build adapter requires the current project and restored SDK paths')
    project, sdk = Path(args.project).resolve(), Path(args.sdk).resolve()
    output = Path(args.export_dir).resolve()
    if output.exists():
        stopped('Build output exists; select a new directory')
    if not project.is_dir() or not sdk.is_dir():
        stopped('Current project or verified SDK is unavailable')
    if args.signing != 'debug' and not args.keystore:
        stopped('Supply the owner key separately, or explicitly authorize --signing debug for a new test identity')
    inv = parse((sdk.parent / 'SDK_FILES.sha256.json').read_bytes())
    for name, digest in inv.items():
        if file_sha(sdk.joinpath(*PurePosixPath(safe_name(name)).parts)) != (digest if isinstance(digest, str) else digest.get('sha256')):
            stopped('Restored SDK checksum mismatch: ' + name)
    bt, jar = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    java = shutil.which('java')
    if not java:
        stopped('Host JDK 17+ is required')
    output.mkdir(parents=True)
    build = Path(tempfile.mkdtemp(prefix='continuity-bridge-build-'))
    logs, commands = [], []
    deadline=time.monotonic()+55.0
    def remaining(limit=50):
        left=deadline-time.monotonic()
        if left<=0:stopped('Supervised build budget reached; no automatic restart')
        return min(float(limit),left)
    def run(cmd):
        command = [str(x) for x in cmd]
        commands.append(command)
        result = subprocess.run(command, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=remaining())
        logs.append('+ ' + shlex.join(command) + '\n' + result.stdout)
        (output / 'BUILD_LOG.txt').write_text('\n\n'.join(logs))
        if result.returncode:
            stopped('Build command failed: ' + command[0] + '\n' + result.stdout[-3000:])
        return result.stdout
    def inside(name):
        return project.joinpath(*PurePosixPath(safe_name(name)).parts)
    classes, dex, gen = [build / n for n in ('classes', 'dex', 'generated')]
    for folder in (classes, dex, gen):
        folder.mkdir()
    source_hashes, retained_baseline = {}, None
    if args.build_adapter == 'sdk-bridge-project':
        cfg = parse((project / 'bridge-project.json').read_bytes())
        roots = cfg.get('source_roots')
        if not isinstance(roots, list) or not roots:
            stopped('Bridge has no source roots')
        manifest, assets, resources = inside('app/AndroidManifest.xml'), inside('app/assets'), inside('app/res')
        xml = ET.parse(manifest).getroot()
        if xml.get('package') != cfg.get('package') or xml.get('{http://schemas.android.com/apk/res/android}versionName') != cfg.get('version'):
            stopped('Bridge configuration and Android manifest differ')
        package, version = cfg['package'], cfg['version']
        sources = sorted(set(p for root in roots for p in inside(root).rglob('*.java')))
        payloads = [inside(n) for n in cfg.get('payload_jars', [])]
        for payload in payloads:
            if not payload.is_file():
                stopped('Missing project payload dependency: ' + str(payload))
        if cfg.get('provenance_java'):
            target = inside(cfg['provenance_java'])
            target.parent.mkdir(parents=True, exist_ok=True)
            cls, namespace = cfg['provenance_class'], cfg['provenance_package']
            if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', cls) or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$.]*', namespace):
                stopped('Unsafe provenance Java identity')
            target.write_text('package '+namespace+';\npublic final class '+cls+' {\n public static final String GAME_JAR_SHA256="'+file_sha(payloads[cfg['provenance_payload_index']])+'";\n private '+cls+'() {}\n}\n')
            sources = sorted(set(sources + [target]))
        source_hashes = {p.relative_to(project).as_posix(): file_sha(p) for p in sources}
        build_id = sha(json.dumps({'sources': source_hashes, 'manifest': file_sha(manifest), 'configuration': file_sha(project/'bridge-project.json'), 'payloads': {p.relative_to(project).as_posix(): file_sha(p) for p in payloads}}, sort_keys=True).encode())
        assets.mkdir(exist_ok=True)
        (assets/'bridge-build.json').write_text(json.dumps({'build_input_id':build_id,'app_version':version,'inputs':source_hashes},indent=2)+'\n')
        aapt_cmd = [bt/'aapt','package','-f','-m','-J',gen,'-M',manifest,'-S',resources,'-I',jar]
        if cfg.get('resource_package'):
            aapt_cmd += ['--custom-package', cfg['resource_package']]
        run(aapt_cmd)
        sources += sorted(gen.rglob('*.java'))
        if not sources:
            stopped('Bridge Java sources are missing')
        argfile = build/'javac.args'
        argfile.write_text('\n'.join('"'+str(p).replace('\\','\\\\').replace('"','\\"')+'"' for p in sources)+'\n')
        run([java,'-m','jdk.compiler/com.sun.tools.javac.Main','-source','8','-target','8','-Xlint:-options','-cp',jar,'-d',classes,'@'+str(argfile)])
        host = build/'host-classes.jar'
        with zipfile.ZipFile(host,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(classes.rglob('*.class')):
                z.write(p,p.relative_to(classes).as_posix())
        run([java,'-cp',bt/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',jar,'--output',dex,host,*payloads])
    elif args.build_adapter == 'dirge-additive-dex':
        manifest, assets, resources = inside('AndroidManifest.xml'), inside('assets'), inside('res')
        xml = ET.parse(manifest).getroot()
        package, version = xml.get('package'), xml.get('{http://schemas.android.com/apk/res/android}versionName')
        if version != '0.2.4':
            stopped('This bounded Dirge adapter supports the carried v0.2.4 additive recipe; inspect newer recipes separately')
        baseline = inside('baseline/Dirge_Bridge_v0.2.3.apk')
        if not baseline.is_file():
            stopped('Exact carried Dirge baseline 0.2.3 is missing')
        with zipfile.ZipFile(baseline) as z:
            if z.read('assets/expected-payload.properties') != (assets/'expected-payload.properties').read_bytes():
                stopped('Dirge payload allowlist differs from the carried baseline')
            filtered = dirge_patch(z.read('classes.dex'))
        retained_baseline = {'path':'baseline/Dirge_Bridge_v0.2.3.apk','sha256':file_sha(baseline),'scope':'Retained baseline DEX except the two explicitly replaced TwinInput classes and fixed-width display version'}
        filtered_file = build/'baseline-filtered.dex'; filtered_file.write_bytes(filtered)
        stubs = build/'stubs'; stubs.mkdir()
        stub_sources = sorted(inside('compile-only').rglob('*.java'))
        target = inside('src/main/java/com/wakka/dirge/core/TwinInput.java')
        source_hashes = {p.relative_to(project).as_posix():file_sha(p) for p in stub_sources+[target]}
        run([java,'-m','jdk.compiler/com.sun.tools.javac.Main','--release','8','-cp',jar,'-d',stubs,*stub_sources])
        stubjar = build/'compile-only.jar'
        with zipfile.ZipFile(stubjar,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stubs.rglob('*.class')):z.write(p,p.relative_to(stubs).as_posix())
        run([java,'-m','jdk.compiler/com.sun.tools.javac.Main','--release','8','-cp',str(jar)+os.pathsep+str(stubjar),'-d',classes,target])
        javap = shutil.which('javap')
        javap_command = [javap] if javap else [java,'-m','jdk.jdeps/com.sun.tools.javap.Main']
        disassembly=run([*javap_command,'-classpath',classes,'-c','-p','com.wakka.dirge.core.TwinInput'])
        if not all(marker in disassembly for marker in ('CameraAssist.PAD_LEFT','CameraAssist.PAD_RIGHT','getstatic')):
            stopped('Dirge PAD constants were inlined instead of runtime field reads')
        changes=build/'changes.jar'
        with zipfile.ZipFile(changes,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(classes.rglob('*.class')):z.write(p,p.relative_to(classes).as_posix())
        run([java,'-cp',bt/'lib/d8.jar','com.android.tools.r8.D8','--min-api','28','--lib',jar,'--output',dex,filtered_file,changes])
        if len(list(dex.glob('*.dex')))!=1:stopped('Dirge bounded recipe unexpectedly produced multidex')
        final_dex=(dex/'classes.dex').read_bytes()
        found=set(dex_classes(final_dex))
        shell_strings=b'\n'.join(raw for _,raw in dex_strings(final_dex))
        for marker in (b'WAKKAN // BRIDGEKEEPER',b'BRIDGEKEEPER TOOLS',b'DIRGE BRIDGE 0.2.4',b'FIELD CAMERA'):
            if marker not in shell_strings:stopped('Preserved Dirge shell marker missing: '+marker.decode())
        for cls in ('Lcom/nttdocomo/ui/AudioPresenter;','Lcom/nttdocomo/ui/MldDecoder;','Lcom/wakka/dirge/core/CameraAssist;','Lcom/wakka/dirge/core/TwinInput;','Lcom/wakka/dirgebridge/MainActivity;'):
            if cls not in found:stopped('Preserved Dirge class missing: '+cls)
    else:
        stopped('Unknown explicit bridge adapter')
    unsigned=build/'unsigned.apk'
    run([bt/'aapt','package','-f','-M',manifest,'-I',jar,'-A',assets,'-S',resources,'-F',unsigned])
    with zipfile.ZipFile(unsigned,'a',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(dex.glob('classes*.dex')):z.write(p,p.name)
    aligned=build/'aligned.apk';run([bt/'zipalign','-f','-P','16','4',unsigned,aligned])
    env=os.environ.copy()
    if args.keystore:
        if not args.key_alias or not env.get(args.password_env):stopped('Owner signing requires alias and password environment variable')
        key,alias=Path(args.keystore).resolve(),args.key_alias
    else:
        key,alias=build/'test-identity.jks','continuity-test'
        env[args.password_env]='android'
        cmd=[java,'-m','java.base/sun.security.tools.keytool.Main','-genkeypair','-keystore',str(key),'-storetype','JKS','-storepass:env',args.password_env,'-keypass:env',args.password_env,'-alias',alias,'-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=Workbench Continuity Test,O=WAKKA','-noprompt']
        subprocess.run(cmd,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=remaining(30))
        key.chmod(0o600)
    apk=output/(package+'_v'+version+'_CONTINUITY_TEST.apk')
    sign=[java,'-jar',str(bt/'lib/apksigner.jar'),'sign','--ks',str(key),'--ks-key-alias',alias,'--ks-pass','env:'+args.password_env,'--key-pass','env:'+args.password_env,'--v1-signing-enabled','true','--v2-signing-enabled','true','--v3-signing-enabled','true','--v4-signing-enabled','false','--out',str(apk),str(aligned)]
    result=subprocess.run(sign,env=env,capture_output=True,text=True,timeout=remaining(30))
    logs.append('+ '+shlex.join(sign)+'\n'+result.stdout+result.stderr)
    if result.returncode:stopped('APK signing failed')
    verification=run([java,'-jar',bt/'lib/apksigner.jar','verify','--verbose','--print-certs','--min-sdk-version','23',apk])
    for scheme in ('v1','v2','v3'):
        if not re.search('Verified using '+scheme+r' scheme.*:\s*true',verification):stopped('Signature verification missing '+scheme)
    run([bt/'zipalign','-c','-P','16','4',apk])
    badging=run([bt/'aapt','dump','badging',apk])
    with zipfile.ZipFile(apk) as z:
        if z.testzip() is not None or 'classes.dex' not in z.namelist():stopped('APK ZIP/DEX verification failed')
    for directory in (assets,resources):
        for p in sorted(directory.rglob('*')):
            if p.is_file():source_hashes[p.relative_to(project).as_posix()]=file_sha(p)
    if (project/'bridge-project.json').is_file():source_hashes['bridge-project.json']=file_sha(project/'bridge-project.json')
    source_hashes['AndroidManifest.xml' if args.build_adapter=='dirge-additive-dex' else 'app/AndroidManifest.xml']=file_sha(manifest)
    evidence={'format':'continuity-sdk-bridge-build/1','adapter':args.build_adapter,'project':package,'version':version,'apk':apk.name,'apk_sha256':file_sha(apk),'fresh_java_compilation':True,'fresh_dex_compilation':True,'retained_baseline':retained_baseline,'source_sha256':source_hashes,'signature_verification':verification,'signature_verification_floor':23,'signature_floor_scope':'Explicit cryptographic v1/v2/v3 verification floor; this does not lower the app manifest minSdk or claim older-device compatibility.','apk_badging':badging,'signing':'separately supplied owner identity; update compatibility not checked here' if args.keystore else 'temporary debug signature; finalize privately in Workbench Continuity Android','physical_device':'not run','android_emulator':'not run','installed_update_compatibility':'not checked by this build; private device signer must compare the actual reference app','claim':'Actual carried project compiled, assembled, aligned, signed and verified. Runtime behavior untested.'}
    (output/'BUILD_EVIDENCE.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (output/'BUILD_LOG.txt').write_text('\n\n'.join(logs))
    version_code=xml.get('{http://schemas.android.com/apk/res/android}versionCode')
    (output/'SIGNING_HANDOFF.json').write_text(json.dumps(signing_handoff(package,version,apk.name,evidence['apk_sha256'],version_code),indent=2)+'\n')
    result_files = {apk.name:apk, 'BUILD_EVIDENCE.json':output/'BUILD_EVIDENCE.json', 'BUILD_LOG.txt':output/'BUILD_LOG.txt', 'SIGNING_HANDOFF.json':output/'SIGNING_HANDOFF.json'}
    if args.work_packet:
        current_packet=Path(args.work_packet).resolve()
        if not current_packet.is_file():stopped('Complete current packet is missing')
        result_files['PROJECT_WORK_PACKET.zip']=current_packet
    for p in sorted(project.rglob('*')):
        if not p.is_file() or p.is_symlink():continue
        rel=p.relative_to(project)
        if any(part in ('signing','.private','.git','__pycache__') for part in rel.parts) or p.suffix.lower() in ('.jks','.keystore','.p12','.pfx','.pem','.key'):continue
        if rel.parts[0] in ('build','dist'):continue
        result_files['source/'+rel.as_posix()]=p
    result_manifest={name:{'size_bytes':p.stat().st_size,'sha256':file_sha(p)} for name,p in result_files.items()}
    with zipfile.ZipFile(output/'CAPSULE_RESULT.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name,p in result_files.items():z.write(p,name)
        start_text=b'Actual carried project source, APK and build evidence. Read BUILD_EVIDENCE.json and SIGNING_HANDOFF.json; physical-device behavior is pending. Bring the returned APK to Workbench Continuity Android -> Sign returned APK, select the existing owner keystore privately and compare with the installed app or a known-good APK. A temporary debug signature is an intermediate build result, not the installed update identity. PROJECT_WORK_PACKET.zip retains the complete current source/context/state/history/attachment cargo with its original verification scope. Restore that packet first, then overlay this source snapshot onto its selected project root; the snapshot includes authorized generated build inputs and current project Passport/handoff. Read source/artifact-passport.json and source/artifact-handoff.json for project context. No private signing keys are exported.\n'
        z.writestr('START_HERE.txt',start_text)
        result_manifest['START_HERE.txt']={'size_bytes':len(start_text),'sha256':sha(start_text)}
        z.writestr('FILES_SHA256.json',json.dumps(result_manifest,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir")
    parser.add_argument("--build-adapter", choices=("sdk-bridge-project", "dirge-additive-dex"))
    parser.add_argument("--project")
    parser.add_argument("--sdk")
    parser.add_argument("--work-packet", help="Complete verified current packet to retain in the returned build packet")
    parser.add_argument("--keystore")
    parser.add_argument("--key-alias")
    parser.add_argument("--password-env", default="CONTINUITY_SIGNING_PASSWORD")
    parser.add_argument("--export-dir", required=True, help="New directory on this host's real download mount")
    parser.add_argument("--signing", choices=("none", "debug"), default="none")
    args = parser.parse_args()
    if args.build_adapter:
        return build_adapter(args)
    if not args.input_dir:
        stopped("Preparation requires the actual input directory")
    root = Path(args.input_dir).resolve()
    if not root.is_dir():
        stopped("Uploaded input directory unavailable")
    work = Path(tempfile.mkdtemp(prefix="continuity-build-"))
    work.chmod(0o700)
    packet = project_packet(root, work)
    packet_hash = file_sha(packet)
    if PACKET_SHA256 and packet_hash != PACKET_SHA256:
        stopped("Current project packet does not match its preparation pin")
    uploaded = {}
    for name, rec in CARRIER_PINS.items():
        p = find_file(root, name)
        if p.stat().st_size != rec["size"] or file_sha(p) != rec["sha256"]:
            stopped("Proven build carrier checksum mismatch: " + name)
        uploaded[name] = p
    packet_dir = work / "current-packet"
    packet_dir.mkdir()
    unpack(packet, packet_dir, require_manifest=True)
    selected = parse((packet_dir / "workspace.json").read_bytes())
    if selected.get("selected_project_root") != PROJECT_ROOT or selected.get("project", {}).get("id") != PASSPORT_ID:
        stopped("Current packet project selection differs")
    restored = expand_source_archives(packet_dir, selected)
    project = restored.joinpath(*PurePosixPath(safe_name(PROJECT_ROOT)).parts) if PROJECT_ROOT else restored
    passport = parse((project / "artifact-passport.json").read_bytes())
    handoff = parse((project / "artifact-handoff.json").read_bytes())
    if passport.get("passport_id") != PASSPORT_ID or handoff.get("passport_id") != PASSPORT_ID or passport.get("artifact", {}).get("name") != handoff.get("artifact", {}).get("name") or passport.get("artifact", {}).get("version") != handoff.get("artifact", {}).get("version"):
        stopped("Current Passport/handoff identity mismatch")
    tools, sdk = restore_tools(uploaded, work)
    sdk_tools = sdk / "build-tools/35.0.0"
    command = None
    config_path = project / "capsule-project.json"
    config_warning = None
    try:
        config = parse(config_path.read_bytes()) if config_path.is_file() else {}
        if not isinstance(config, dict):
            config, config_warning = {}, "Build configuration is not an object; preserved as inert project data."
    except (ValueError, SystemExit) as error:
        config, config_warning = {}, str(error)
    try:
        for key in ("sources", "manifest"):
            safe_name(config.get(key, "src" if key == "sources" else "AndroidManifest.xml"))
    except SystemExit as error:
        config, config_warning = {}, str(error)
    # The already verified adapter remains exact. Missing config never blocks
    # transport or tool restoration and never silently selects its fixture.
    if not config_warning and config.get("profile", "plain-java") == "plain-java" and config_path.is_file():
        for key in ("sources", "manifest"):
            safe_name(config.get(key, "src" if key == "sources" else "AndroidManifest.xml"))
        command=['python3',str(tools/'abc.py'),'build','--sdk',str(sdk),'--project',str(project),'--output',str(Path(args.export_dir).resolve())]
        if args.signing=='debug':command.append('--debug-sign')
    capability_file = packet_dir / "BUILD_CAPABILITY.json"
    capability = parse(capability_file.read_bytes()) if capability_file.is_file() else {}
    adapter = capability.get("adapter")
    if adapter in ("sdk-bridge-project", "dirge-additive-dex"):
        command = ["python3", str(Path(__file__).resolve()), "--build-adapter", adapter, "--project", str(project), "--sdk", str(sdk), "--work-packet", str(packet), "--export-dir", str(Path(args.export_dir).resolve()), "--signing", args.signing]
    environment = {
        "ANDROID_SDK_ROOT": str(sdk), "ANDROID_HOME": str(sdk),
        "ANDROID_JAR": str(sdk / "platforms/android-35/android.jar"),
        "BUILD_TOOLS": str(sdk_tools), "ANDROID_BUILD_TOOLS": str(sdk_tools), "AAPT": str(sdk_tools / "aapt"),
        "AAPT2": str(sdk_tools / "aapt2"), "D8_JAR": str(sdk_tools / "lib/d8.jar"),
        "APKSIGNER_JAR": str(sdk_tools / "lib/apksigner.jar"), "ZIPALIGN": str(sdk_tools / "zipalign"),
    }
    report = {
        "format": "continuity-prepared-build/2", "destination": DESTINATION,
        "project_root": str(project), "passport_id": PASSPORT_ID,
        "current_packet_sha256": packet_hash, "external_current_packet_pin_verified": bool(PACKET_SHA256),
        "prior_carrier_bytes_verified": True, "sdk_files_verified": True,
        "tools_root": str(tools), "sdk": str(sdk), "sdk_environment": environment,
        "read_before_build": [str(project / "artifact-passport.json"), str(project / "artifact-handoff.json")],
        "build_capability": capability, "configuration_warning": config_warning, "recipe_candidates": recipes(project), "command": command,
        "signing": args.signing, "signing_note": "An unsigned or debug-signed APK is intermediate. Return the actual APK and complete source/work packet; final signing with the existing owner identity happens in Workbench Continuity Android on the owner's device. Never request the owner's release key or invent a replacement.",
        "signing_handoff": signing_handoff(),
        "verification_scope": "Bytes, selected current source and tool recovery verified. No imported project command, build or device test performed.",
        "next_action": "Inspect the current source, Passport/handoff and recipe. Use the explicit current-project command if available; otherwise adapt the carried actual recipe with these verified SDK paths. Missing native/compiler/content inputs stay explicit. Never build the historical fixture.",
        "runtime_route": "Integrated public ABC runner; new per-person PDF/ZIP carriers, no historical owner fixture.",
    }
    (work / "SDK_ENVIRONMENT.json").write_text(json.dumps(environment, indent=2) + "\n")
    (work / "SIGNING_HANDOFF.json").write_text(json.dumps(signing_handoff(), indent=2) + "\n")
    (work / "PREPARED_BUILD.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if command:
        print("\nINSPECT CURRENT PROJECT, THEN RUN ONCE WHEN AUTHORIZED:\n" + shlex.join(command))
    else:
        print("\nCURRENT PROJECT AND VERIFIED TOOLS RESTORED. INSPECT ITS ACTUAL RECIPE AND REPORTED INPUTS. NO FALLBACK FIXTURE WILL BE BUILT.")


if __name__ == "__main__":
    main()
