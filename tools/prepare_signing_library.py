#!/usr/bin/env python3
"""Verify or recover Workbench's public Apache-2.0 Maven apksig dependency."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
pins=json.loads((ROOT/'third-party/APKSIG_PINS.json').read_text())
target=ROOT/'android/libs/apksig-35.0.0.jar'
if not target.exists():
    with urllib.request.urlopen(pins['artifact_url'],timeout=60) as response:
        body=response.read(2*1024*1024+1)
    if len(body)>2*1024*1024 or hashlib.sha256(body).hexdigest()!=pins['filtered_jar_sha256']:
        raise SystemExit('Public signing dependency checksum differs.')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(body)
if hashlib.sha256(target.read_bytes()).hexdigest()!=pins['filtered_jar_sha256']:
    raise SystemExit('Public signing dependency checksum differs.')
print(json.dumps({'dependency':'com.android.tools.build:apksig:8.6.1','sha256':pins['filtered_jar_sha256'],'license':'Apache-2.0'}))
