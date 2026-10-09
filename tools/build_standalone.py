#!/usr/bin/env python3
"""Build SDK-free public HTML and Android assets from the existing Workbench UI."""
import base64,hashlib,io,json,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def script(text):
    return '<script>\n'+text.replace('</script','<\\/script')+'\n</script>'
def main():
    vendor=ROOT/'vendor/android-build-capsule'
    manifest=json.loads((vendor/'PUBLIC_FILES.sha256.json').read_text())
    for name,digest in manifest.items():
        if hashlib.sha256((vendor/name).read_bytes()).hexdigest()!=digest:
            raise SystemExit('Integrated public setup file differs: '+name)
    setup=io.BytesIO()
    with zipfile.ZipFile(setup,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT/'SETUP_WORKBENCH.bat','SETUP_WORKBENCH.bat')
        z.writestr('START_HERE.txt','On Windows, double-click SETUP_WORKBENCH.bat. Read and personally accept the SDK agreement to continue. Load the generated ZIP into Workbench using Load build runtime. No separate Build Capsule download is needed. Keep generated runtimes private.\n')
        for name in [*manifest,'PUBLIC_FILES.sha256.json']:
            z.write(vendor/name,'vendor/android-build-capsule/'+name)
    public={
        'sdkPins':json.loads((ROOT/'runtime/SDK_PINS.json').read_text()),
        'coreFiles':{name:base64.b64encode((vendor/name).read_bytes()).decode() for name in [*manifest,'PUBLIC_FILES.sha256.json']},
        'abcSha256':hashlib.sha256((vendor/'abc.py').read_bytes()).hexdigest(),
        'launcherTemplate':(ROOT/'tools/prepare_build_template.py').read_text(),
        'setupZip':base64.b64encode(setup.getvalue()).decode()}
    html=(ROOT/'src/ui.html').read_text()
    csp='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; object-src \'none\'; frame-src \'none\'; base-uri \'none\'; form-action \'none\'">'
    favicon='<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'+base64.b64encode((ROOT/'artwork/favicon.svg').read_bytes()).decode()+'">'
    html=html.replace('<head>','<head>\n'+csp+'\n'+favicon,1)
    sample={'filename':'PocketNote.zip','base64':base64.b64encode((ROOT/'example/PocketNote.zip').read_bytes()).decode()}
    pieces=[(ROOT/'src/continuity-engine.js').read_text(),'window.EMBEDDED_SAMPLE_PACKET='+json.dumps(sample)+';',
        'window.WORKBENCH_PUBLIC_SETUP='+json.dumps(public)+';',
        (ROOT/'src/continuity-runtime.js').read_text(),(ROOT/'src/continuity-carriers.js').read_text(),(ROOT/'src/continuity-ui.js').read_text()]
    html=html.replace('<!-- BUNDLE_SCRIPTS -->','\n'.join(script(p) for p in pieces))
    for path in[ROOT/'dist/Workbench_Continuity_v1.2.0_PUBLIC.html',ROOT/'android/assets/index.html']:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(html,encoding='utf-8')
        print(json.dumps({'path':str(path.relative_to(ROOT)),'size_bytes':path.stat().st_size,'sdk_payload':False}))
    (ROOT/'dist/Workbench_Continuity_First_Time_Setup.zip').write_bytes(setup.getvalue())
    notices=ROOT/'android/assets/third-party';notices.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'third-party/APACHE-2.0.txt',notices/'APACHE-2.0.txt')
    shutil.copy2(ROOT/'third-party/NOTICE.txt',notices/'NOTICE.txt')
if __name__=='__main__':main()
