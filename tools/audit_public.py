#!/usr/bin/env python3
"""Audit public files and nested archives for keys and excluded runtime binaries."""
import argparse,base64,hashlib,io,json,re,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
KEY_SUFFIXES={'.p12','.pfx','.jks','.keystore','.key','.pem'}
SDK_NAMES={'android.jar','apksigner.jar','d8.jar','aapt','aapt2','zipalign','SDK_LICENSE_FROM_GOOGLE.txt'}
def digest(b):return hashlib.sha256(b).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths',nargs='*',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();pins=set(json.loads((ROOT/'runtime/SDK_PINS.json').read_text()).values())
    checked=0;nested=0
    def inspect(name,body,depth=0):
        nonlocal checked,nested
        checked+=1;path=PurePosixPath(name)
        if path.suffix.lower() in KEY_SUFFIXES:raise ValueError('Signing key file in public output: '+name)
        if path.name in SDK_NAMES or 'build-carriers/' in name or '/runtime/sdk/' in '/'+name:raise ValueError('SDK/carrier payload in public output: '+name)
        if digest(body) in pins:raise ValueError('Pinned private SDK binary in public output: '+name)
        if re.search(rb'(?m)^-----BEGIN (?:RSA |EC )?PRIVATE KEY-----\r?$',body):raise ValueError('Private key content in public output: '+name)
        if depth>8:raise ValueError('Unexpected archive nesting')
        if path.suffix.lower() in {'.zip','.apk','.jar'} or body.startswith(b'PK\x03\x04'):
            nested+=1
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                seen=set();total=0
                for entry in z.infolist():
                    member=entry.filename
                    if member in seen or '\\' in member or member.startswith('/') or '..' in PurePosixPath(member).parts:raise ValueError('Unsafe or duplicate public archive path')
                    seen.add(member);total+=entry.file_size
                    if total>300*1024*1024:raise ValueError('Unexpected expanded public archive size')
                    if not entry.is_dir():inspect(name+'!/'+member,z.read(entry),depth+1)
        if name.endswith('.html'):
            for match in re.finditer(r'window\.WORKBENCH_PUBLIC_SETUP=(\{.*?\});\n',body.decode('utf-8')):
                public=json.loads(match.group(1));inspect(name+'!/first-time-setup.zip',base64.b64decode(public['setupZip']),depth+1)
                for member,value in public['coreFiles'].items():inspect(name+'!/public-core/'+member,base64.b64decode(value),depth+1)
    paths=args.paths or [ROOT]
    for path in paths:
        for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if not file.is_file():continue
            if any(p in ['.private','__pycache__','.git'] for p in file.parts):continue
            inspect(file.name if not path.is_dir() else file.relative_to(path).as_posix(),file.read_bytes())
    report={'format':'workbench-public-content-audit/1','passed':True,'inspected_files_and_members':checked,'nested_archives':nested,'owner_keys_absent':True,'sdk_runtime_payloads_absent':True,'embedded_setup_and_core_inspected':True,'public_signing_library':'Apache-2.0 Maven artifact; included intentionally','scope':'File paths, byte hashes, key markers, nested archives and embedded public setup payloads.'}
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()
