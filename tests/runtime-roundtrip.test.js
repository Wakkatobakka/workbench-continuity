'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),os=require('node:os'),assert=require('node:assert/strict'),{webcrypto,createHash}=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),output=process.env.CONTINUITY_TEST_OUTPUT||fs.mkdtempSync(path.join(os.tmpdir(),'workbench-public-test-'));
const {DOM}=require('./dom-harness.js');
const hash=b=>createHash('sha256').update(b).digest('hex');
function load(){
 const document=DOM(root+'/src/ui.html');document.addEventListener=()=>{};
 const c={console,Blob,File,Response,TextEncoder,TextDecoder,Uint8Array,Uint16Array,Uint32Array,DataView,ArrayBuffer,Map,Set,DecompressionStream,crypto:webcrypto,structuredClone,atob,btoa,URL,document,addEventListener(){},setTimeout:(fn,ms)=>{const h=setTimeout(fn,ms);if(ms>1000)h.unref();return h},clearTimeout,confirm:()=>true};c.globalThis=c;c.window=c;
 vm.createContext(c);for(const m of fs.readFileSync(root+'/dist/Workbench_Continuity_v1.2.0_PUBLIC.html','utf8').matchAll(/<script>\n([\s\S]*?)\n<\/script>/g))vm.runInContext(m[1],c);
 return c;
}
(async()=>{
 const c=load();await c.ContinuityUI.ready;const E=c.ContinuityEngine,C=c.ContinuityCarriers,UI=c.ContinuityUI;
 const checks=[],record=(name,details={})=>{checks.push({name,passed:true,...details});console.log('PASS '+name)};
 fs.mkdirSync(output,{recursive:true});
 await UI.importBytes(new Uint8Array(fs.readFileSync(root+'/example/PocketNote.zip')),'PocketNote.zip',true);
 let ws=UI.getWorkspace();assert.equal(E.validate(ws.passport,ws.handoff).errors.length,0);
 const ownValidation=E.validate(JSON.parse(fs.readFileSync(root+'/artifact-passport.json')),JSON.parse(fs.readFileSync(root+'/artifact-handoff.json')));assert.equal(ownValidation.errors.length,0);record('Public product and practice-project Passport/handoff context validate');
 ws=await E.updateState(ws,{nextAction:'Build this exact Pocket Note source; do not substitute another project.',decisions:['Preserve the current project identity.']});
 const original=Object.fromEntries([...ws.files].map(([p,b])=>[p,hash(b)]));
 let runtimeFile=process.env.CONTINUITY_TEST_RUNTIME;
 if(!runtimeFile){
   // SDK-free fixture exercises the carriage contracts only; it is never build evidence.
   const jar=new TextEncoder().encode('deterministic-test-android-jar'),tool=new TextEncoder().encode('deterministic-test-tool');
   c.WORKBENCH_PUBLIC_SETUP.sdkPins={'platforms/android-35/android.jar':hash(jar),'build-tools/35.0.0/aapt':hash(tool)};
   runtimeFile=path.join(output,'fixture-runtime.PRIVATE.zip');
   const blob=await E.createZipBlob(new Map([['runtime/sdk/platforms/android-35/android.jar',jar],['runtime/sdk/build-tools/35.0.0/aapt',tool],['owner-personal-notes.txt',new TextEncoder().encode('PRIVATE_NOTES_MUST_NOT_TRAVEL')],['owner-key.p12',new TextEncoder().encode('PRIVATE_KEY_MUST_NOT_TRAVEL')]]));
   fs.writeFileSync(runtimeFile,Buffer.from(await blob.arrayBuffer()));
 }
 const loaded=await UI.loadRuntime(new Blob([fs.readFileSync(runtimeFile)]));
 assert.deepEqual(Object.fromEntries([...UI.getWorkspace().files].map(([p,b])=>[p,hash(b)])),original);
 assert(c.WorkbenchRuntime.ready());record('Runtime loads outside the project and preserves every source byte',{sdkFiles:loaded.files,realSDK:!!process.env.CONTINUITY_TEST_RUNTIME});
 const normalized=c.WorkbenchRuntime.blob(),entries=await E.zipEntriesBlob(normalized);
 assert(!entries.some(e=>/owner-personal|owner-key|\.p12$|\.jks$/.test(e.path)));
 record('Normalized runtime contains only pinned SDK files and trusted public core');
 const old=await E.sha256(normalized),invalid=await E.createZipBlob(new Map([['runtime/sdk/platforms/android-35/android.jar',new TextEncoder().encode('wrong-jar')]]));
 await assert.rejects(c.WorkbenchRuntime.load(invalid),/identity differs|missing/);assert.equal(await E.sha256(c.WorkbenchRuntime.blob()),old);
 record('Invalid runtime is rejected without replacing the last valid runtime');
 for(const destination of['claude','grok']){
   const plan=await C.prepare(ws,{destination}),folder=path.join(output,destination);fs.mkdirSync(folder,{recursive:true});
   fs.writeFileSync(path.join(folder,'route.PRIVATE.zip'),Buffer.from(await plan.blob.arrayBuffer()));
   for(const[name,body]of plan.generatedFiles)fs.writeFileSync(path.join(folder,name),Buffer.from(body instanceof Blob?await body.arrayBuffer():body));
   for(const file of c.EMBEDDED_BUILD_CARRIERS.routes[destination].files)fs.writeFileSync(path.join(folder,file.name),Buffer.from(await file.body.arrayBuffer()));
   const instruction=new TextDecoder().decode(plan.generatedFiles.get('START_HERE.txt'));for(const file of plan.manifest.upload_files)assert(instruction.includes(file));
   assert(!instruction.includes('Attach BOTH'));assert(plan.generatedFiles.has('SIGNING_HANDOFF.json'));
   const helper=destination==='grok'?plan.generatedFiles.get('prepare_build.py'):null;
   if(destination==='claude'){
     const projectPDF=Buffer.from(await plan.generatedFiles.get('PROJECT_WORK_PACKET.pdf').arrayBuffer());
     const tag=Buffer.from('/WAKKARole /ContinuityLauncher\n'),i=projectPDF.indexOf(tag),j=projectPDF.indexOf(Buffer.from('>>'),i),len=Number(/\/WAKKABytes (\d+)/.exec(projectPDF.subarray(i,j).toString())[1]);
     const stream=/^>>\s*stream\r?\n/.exec(projectPDF.subarray(j,j+40).toString());
     fs.writeFileSync(path.join(folder,'prepare_build.py'),projectPDF.subarray(j+stream[0].length,j+stream[0].length+len));
   }else assert(helper);
   const command=['python3',path.join(folder,'prepare_build.py'),'--input-dir',folder,'--export-dir',path.join(output,destination+'-build'),'--signing','debug'];
   const run=spawnSync(command[0],command.slice(1),{encoding:'utf8',timeout:180000});assert.equal(run.status,0,run.stderr||run.stdout);
   const jsonEnd=run.stdout.indexOf('\n\nINSPECT');const prepared=JSON.parse(run.stdout.slice(0,jsonEnd<0?run.stdout.indexOf('\n\nCURRENT'):jsonEnd));
   assert.equal(prepared.passport_id,ws.passport.passport_id);assert(prepared.sdk_files_verified);assert(prepared.command.includes('--project'));
   assert(prepared.command.some(s=>s.endsWith('abc.py')));assert.equal(prepared.current_packet_sha256,plan.manifest.project_packet_sha256);
   const packet=await E.importZip(plan.generatedFiles.get('PROJECT_WORK_PACKET.zip'),'PROJECT_WORK_PACKET.zip');
   assert.equal(E.getState(packet).nextAction,'Build this exact Pocket Note source; do not substitute another project.');
   for(const[p,b]of ws.files)if(!/artifact-(?:passport|handoff)\.json$/.test(p))assert.equal(hash(packet.files.get(p)),hash(b));
   if(process.env.CONTINUITY_TEST_RUNTIME){
     const result=spawnSync(prepared.command[0],prepared.command.slice(1),{encoding:'utf8',timeout:180000});assert.equal(result.status,0,result.stderr||result.stdout);
     const built=JSON.parse(fs.readFileSync(path.join(output,destination+'-build','BUILD_EVIDENCE.json'),'utf8'));assert(built.fresh_java_compilation&&built.fresh_dex_compilation);assert.equal(built.project,'dev.wakka.continuity.example');
     record(destination+' emitted route recovers the current project and builds its actual Java APK',{uploadFiles:plan.manifest.upload_files.length,apkSha256:built.apk_sha256});
   }else record(destination+' emitted route recovers the complete current source and SDK-free fixture',{uploadFiles:plan.manifest.upload_files.length});
 }
 const work=await E.exportPacket(ws,{mode:'private'}),roundtrip=await E.importZip(work.blob,'saved-work.zip');assert.equal(E.getState(roundtrip).nextAction,E.getState(ws).nextAction);
 record('Saved work packet reopens with the latest decisions and next action');
 const report={format:'workbench-public-runtime-roundtrip/1',passed:true,realSDK:!!process.env.CONTINUITY_TEST_RUNTIME,checks,scope:'Actual emitted HTML JavaScript and PDF/ZIP extraction; optional actual SDK source builds. No physical device or external AI chat run.'};
 fs.writeFileSync(path.join(output,'runtime-roundtrip-report.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({passed:true,report:path.join(output,'runtime-roundtrip-report.json')}));
})().catch(error=>{console.error(error);process.exitCode=1});
