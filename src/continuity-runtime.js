/* Per-person SDK loading. No SDK, signing key or private fixture is embedded. */
(function(global){
  'use strict';
  const enc=new TextEncoder(),dec=new TextDecoder(),E=()=>global.ContinuityEngine;
  const json=v=>enc.encode(JSON.stringify(v,null,2)+'\n');
  const policy=()=>global.WORKBENCH_PUBLIC_SETUP;
  let runtime=null,carrierData=null;
  const bytes=async b=>new Uint8Array(await b.arrayBuffer());
  function fail(s){throw new Error(s);}
  async function extract(archive,entry){
    const compressed=await bytes(archive.slice(entry.start,entry.end));
    const body=entry.method===0?compressed:E().inflateRaw(compressed,entry.size);
    if(body.length!==entry.size||E().crc32(body)!==entry.crc)fail('Runtime ZIP integrity differs: '+entry.path);
    return body;
  }
  // Retain verified compressed SDK slices instead of inflating the whole SDK in memory.
  async function compressedZip(records){
    const locals=[],central=[];let offset=0;
    for(const r of records){
      const name=enc.encode(r.name),head=new Uint8Array(30+name.length),dv=new DataView(head.buffer);
      dv.setUint32(0,0x04034b50,true);dv.setUint16(4,20,true);dv.setUint16(6,0x800,true);dv.setUint16(8,r.method,true);
      dv.setUint32(14,r.crc,true);dv.setUint32(18,r.body.size,true);dv.setUint32(22,r.size,true);dv.setUint16(26,name.length,true);head.set(name,30);
      locals.push(head,r.body);
      const c=new Uint8Array(46+name.length),cv=new DataView(c.buffer);
      cv.setUint32(0,0x02014b50,true);cv.setUint16(4,0x314,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);cv.setUint16(10,r.method,true);
      cv.setUint32(16,r.crc,true);cv.setUint32(20,r.body.size,true);cv.setUint32(24,r.size,true);cv.setUint16(28,name.length,true);
      cv.setUint32(38,0o100755<<16,true);cv.setUint32(42,offset,true);c.set(name,46);central.push(c);
      offset+=head.length+r.body.size;
    }
    const end=new Uint8Array(22),dv=new DataView(end.buffer);
    dv.setUint32(0,0x06054b50,true);dv.setUint16(8,records.length,true);dv.setUint16(10,records.length,true);
    dv.setUint32(12,central.reduce((n,c)=>n+c.length,0),true);dv.setUint32(16,offset,true);
    return new Blob([...locals,...central,end],{type:'application/zip'});
  }
  function stored(name,body){return{name,body:new Blob([body]),size:body.length,method:0,crc:E().crc32(body)};}
  const pdfText=s=>String(s).replace(/[^\x20-\x7e]/g,'?').replace(/([\\()])/g,'\\$1');
  function runtimePDF(part,manifest){
    const meta=json(manifest),content=enc.encode('BT\n/F1 11 Tf\n45 750 Td\n'+[
      'WORKBENCH CONTINUITY - YOUR PRIVATE BUILD RUNTIME',
      'Runtime part '+part.index+' of '+manifest.parts.length,
      'Attach every numbered runtime PDF and every current-project PDF.',
      'The current-project PDF carries prepare_build.py and its extraction instructions.',
      'This PDF carries /ContinuityRuntimePart and /ContinuityRuntimeManifest.',
      'Runtime ZIP SHA-256: '+manifest.original.sha256,
      'Keep this generated SDK carrier private. No signing keys are carried.',
      'Building needs a chat with Linux x86_64, Python 3.10+ and JDK 17+.'
    ].map((s,i)=>(i?'0 -19 Td\n':'')+'('+pdfText(s)+') Tj').join('\n')+'\nET');
    const stream=(dict,body)=>[enc.encode('<< '+dict+' /Length '+body.size+' >>\nstream\n'),body,enc.encode('\nendstream')];
    const objects=[null,[enc.encode('<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(runtime.part) 8 0 R (RUNTIME_PARTS.json) 9 0 R] >> >> >>')],
      [enc.encode('<< /Type /Pages /Kids [3 0 R] /Count 1 >>')],
      [enc.encode('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>')],
      stream('',new Blob([content])),[enc.encode('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')],
      stream('/Type /EmbeddedFile /WAKKARole /ContinuityRuntimePart\n/WAKKABytes '+part.body.size,part.body),
      stream('/Type /EmbeddedFile /WAKKARole /ContinuityRuntimeManifest\n/WAKKABytes '+meta.length,new Blob([meta])),
      [enc.encode('<< /Type /Filespec /F (runtime.part) /EF << /F 6 0 R >> >>')],
      [enc.encode('<< /Type /Filespec /F (RUNTIME_PARTS.json) /EF << /F 7 0 R >> >>')]];
    const chunks=[enc.encode('%PDF-1.7\n%WorkbenchContinuity\n')],offsets=[0];let n=chunks[0].length;
    for(let i=1;i<objects.length;i++){offsets.push(n);for(const c of[enc.encode(i+' 0 obj\n'),...objects[i],enc.encode('\nendobj\n')]){chunks.push(c);n+=c.size??c.length;}}
    let tail='xref\n0 '+objects.length+'\n0000000000 65535 f \n';for(let i=1;i<offsets.length;i++)tail+=String(offsets[i]).padStart(10,'0')+' 00000 n \n';
    tail+='trailer\n<< /Size '+objects.length+' /Root 1 0 R >>\nstartxref\n'+n+'\n%%EOF\n';
    return new Blob([...chunks,enc.encode(tail)],{type:'application/pdf'});
  }
  async function makeRoutes(archive){
    const digest=await E().sha256(archive),routes={};
    for(const d of['claude','grok']){
      const step=(d==='claude'?20:12)*1024*1024,parts=[];
      for(let off=0,index=1;off<archive.size;off+=step,index++){
        const body=archive.slice(off,off+step),name=String(index).padStart(2,'0')+'_Workbench_Runtime_PRIVATE.'+(d==='claude'?'pdf':'zip');
        parts.push({index,offset:off,name,member:'runtime.part',size_bytes:body.size,sha256:await E().sha256(body),body});
      }
      const manifest={format:'continuity-runtime-parts/1',classification:'private-sdk-runtime',original:{name:'WORKBENCH_RUNTIME.zip',size_bytes:archive.size,sha256:digest},parts:parts.map(({body,...p})=>p)};
      const files=[];
      for(const part of parts){
        const body=d==='claude'?runtimePDF(part,manifest):await E().createZipBlob(new Map([['runtime.part',part.body],['RUNTIME_PARTS.json',json(manifest)]]));
        files.push({name:part.name,body,size:body.size,sha256:await E().sha256(body),kind:'your verified build runtime'});
      }
      routes[d]={files,uploadNames:files.map(f=>f.name),originalManifestSha256:await E().sha256(json(manifest)),verified_carrier_bytes:true};
    }
    return{format:'continuity-embedded-private-build-carriers/1',distribution:'per-person private SDK runtime; generated locally',build_profile:'Linux x86_64, Python 3.10+, JDK 17+, API 35/Build Tools 35',bootstrapSha256:policy().abcSha256,launcherTemplate:policy().launcherTemplate,routes,priorVerification:{method:'Public ABC setup reused; SDK files checked against official component identities; new carriers verified locally.',limitations:['No external AI execution or device run is established by export.']}};
  }
  async function load(archive){
    if(!(archive instanceof Blob))archive=new Blob([archive]);
    const entries=await E().zipEntriesBlob(archive),jars=entries.filter(e=>e.path.endsWith('runtime/sdk/platforms/android-35/android.jar'));
    if(jars.length!==1)fail('Choose the runtime ZIP generated by SETUP_WORKBENCH.bat.');
    const prefix=jars[0].path.slice(0,-'platforms/android-35/android.jar'.length),map=new Map(entries.map(e=>[e.path,e])),records=[],inventory={};
    for(const[name,hash]of Object.entries(policy().sdkPins)){
      const entry=map.get(prefix+name);if(!entry||entry.directory)fail('Required runtime file is missing: '+name);
      const body=await extract(archive,entry);
      if(await E().sha256(body)!==hash)fail('Official SDK identity differs: '+name);
      inventory[name]=hash;records.push({name:'runtime/sdk/'+name,body:archive.slice(entry.start,entry.end),size:entry.size,method:entry.method,crc:entry.crc});
    }
    const bundled={};
    for(const[name,base64]of Object.entries(policy().coreFiles)){
      const text=atob(base64),body=Uint8Array.from(text,c=>c.charCodeAt(0));records.push(stored(name,body));bundled[name]=await E().sha256(body);
    }
    const inv=json(inventory),receipt=json({distribution:'private-runtime',sdk_source:'Official API 35/Build Tools 35 identities checked by Workbench',contains_project_signing_keys:false,public_redistribution:'Keep generated SDK runtime private.'});
    for(const[name,body]of[['runtime/SDK_FILES.sha256.json',inv],['PRIVATE_RUNTIME.json',receipt]]){records.push(stored(name,body));bundled[name]=await E().sha256(body);}
    for(const[name,hash]of Object.entries(inventory))bundled['runtime/sdk/'+name]=hash;
    records.push(stored('BUNDLE_FILES.sha256.json',json(bundled)));
    const normalized=await compressedZip(records),data=await makeRoutes(normalized);
    // Publish only after every required input and generated carrier has passed.
    runtime=normalized;carrierData=data;global.EMBEDDED_BUILD_CARRIERS=data;
    return{files:Object.keys(inventory).length,size:normalized.size,sha256:await E().sha256(normalized)};
  }
  global.WorkbenchRuntime=Object.freeze({load,ready:()=>!!carrierData,blob:()=>runtime,hasEmbeddedAssets:false,
    setupZip:()=>new Blob([Uint8Array.from(atob(policy().setupZip),c=>c.charCodeAt(0))],{type:'application/zip'}),
    clear(){runtime=null;carrierData=null;delete global.EMBEDDED_BUILD_CARRIERS;}});
})(globalThis);
