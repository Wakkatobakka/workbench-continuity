(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const engine = () => window.ContinuityEngine;
  let workspace = null;
  let tab = 'overview';
  let dirty = false;
  let selectedFile = null;
  let fileFilter = 'all';
  let fileSearch = '';
  let database = null;
  let storageAvailable = false;
  let working = false;
  let restored = false;
  let messageTimer = null;
  let exportCallback = null;
  let destination = 'packet';
  let lastSigningReceipt = null;
  const sourcePattern = /\.(java|kt|kts|js|jsx|ts|tsx|html|htm|css|scss|py|c|h|cpp|hpp|cc|rs|go|swift|xml|gradle|sh|bat|ps1|cmake|toml|properties|json|yaml|yml)$/i;
  const textPattern = /\.(java|kt|kts|js|jsx|ts|tsx|html|htm|css|scss|py|c|h|cpp|hpp|cc|rs|go|swift|xml|gradle|sh|bat|ps1|cmake|toml|properties|json|yaml|yml|txt|md|csv|tsv|log|ini|manifest|gitignore|gitattributes|sha256)$/i;
  const evidencePattern = /(^|\/)(evidence|receipts|proof|logs|results|verification|reports|output|builds)(\/|$)|receipt|report|result|verification|\.apk$|\.mp4$|\.png$|\.jpg$/i;
  const continuityPattern = /passport|handoff|start_here|decisions|continuity|next_action|workbench_state/i;

  function folderPickerAvailable() { return !window.WorkbenchNative && 'webkitdirectory' in $('folder-input'); }
  function humanBytes(n) { if (n < 1024) return n + ' B'; if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'; if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB'; return (n / 1073741824).toFixed(2) + ' GB'; }
  function bytesOf(value) { if (value instanceof Uint8Array) return value; if (value instanceof ArrayBuffer) return new Uint8Array(value); if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength); if (Array.isArray(value)) return new Uint8Array(value); if (typeof value === 'string') return new TextEncoder().encode(value); return new Uint8Array(); }
  function filesOf(ws) {
    if (!ws) return [];
    if (engine() && typeof engine().fileRecords === 'function') return engine().fileRecords(ws).map(file => ({...file, size:file.size == null ? (file.blob ? file.blob.size : bytesOf(file.bytes).length) : file.size}));
    const files = ws.files;
    const source = files instanceof Map ? Array.from(files.entries()).map(([path, bytes]) => ({path, bytes:bytesOf(bytes)})) : Array.isArray(files) ? files.map(f => ({path:f.path, bytes:bytesOf(f.bytes)})) : Object.entries(files || {}).map(([path, bytes]) => ({path, bytes:bytesOf(bytes)}));
    const cargo = ws.cargo instanceof Map ? Array.from(ws.cargo.entries()).map(([path, file]) => ({path, ...file})) : [];
    return source.concat(cargo).map(file => ({...file,size:file.size == null ? (file.blob ? file.blob.size : file.bytes.length) : file.size}));
  }
  function rawOf(file) { return file.blob || file.bytes; }
  function projectInfo() {
    const candidates = workspace && workspace.candidates || [];
    const chosen = candidates.find(c => c.root === workspace.selectedRoot) || (candidates.length === 1 ? candidates[0] : {});
    const p = workspace && workspace.passport || {};
    const identity = p.artifact || p.project || p.identity || {};
    const originName = workspace.origin && (workspace.origin.filename || workspace.origin.label);
    return {name:chosen.name || identity.name || p.name || workspace.label || (originName && originName.replace(/\.zip$/i, '')) || 'Your project', id:chosen.id || identity.id || p.project_id || p.passport_id || '', version:chosen.version || identity.version || p.version || ''};
  }
  function state() {
    if (!workspace) return {};
    if (engine().getState) return engine().getState(workspace) || {};
    const h = workspace.handoff || {}, p = workspace.passport || {};
    return {status:h.status || p.status || 'working', objective:h.objective || h.purpose || '', nextAction:h.next_action || h.nextAction || '', decisions:h.decisions || p.decisions || [], buildState:h.build_state || h.buildState || '', phoneStatus:h.phone_status || h.phoneStatus || ''};
  }
  function multiline(value) { if (Array.isArray(value)) return value.map(v => typeof v === 'string' ? v : v.text || v.decision || v.description || JSON.stringify(v)).join('\n'); if (value && typeof value === 'object') return JSON.stringify(value, null, 2); return value || ''; }
  function observed(value) { if (typeof value === 'object' && value) return value.note || value.owner_note || value.description || JSON.stringify(value, null, 2); return value || ''; }
  function announce(message, error) {
    clearTimeout(messageTimer);
    $('message').className = 'message' + (error ? ' error' : '');
    $('message').innerHTML = '<button aria-label="Dismiss message" id="dismiss-message">×</button>' + escape(message);
    $('dismiss-message').onclick = () => $('message').classList.add('hidden');
    $('live-status').textContent = message;
    messageTimer = setTimeout(() => $('message').classList.add('hidden'), error ? 16000 : 8000);
  }
  function setBusy(label) { working = !!label; $('busy-label').textContent = label || ''; $('busy').classList.toggle('hidden', !label); controls(); }
  function controls() {
    const ready = !!workspace;
    document.body.classList.toggle('no-project', !ready);
    $('export-private').disabled = !ready || working;
    const publicBlocked = !!workspace && workspace.privacy && workspace.privacy.canExportPublic === false;
    $('export-public').disabled = !ready || working || publicBlocked;
    $('export-public').title = publicBlocked ? 'This packet is private or contains material that cannot be included in a public copy. The sharing record explains why.' : 'Save a separately checked shareable copy';
    $('import-top').disabled = working;
    if($('load-runtime'))$('load-runtime').disabled=working;
    if($('download-setup'))$('download-setup').disabled=working;
    if ($('add-top')) $('add-top').disabled = !workspace || working;
    if ($('sign-returned-top')) $('sign-returned-top').disabled = working;
  }
  function storageMessage(text) { $('storage-status').textContent = text; }
  async function initStorage() {
    if (!window.indexedDB) { storageMessage('Download a packet to keep your work.'); return null; }
    try {
      database = await new Promise((resolve, reject) => {
        const req = indexedDB.open('workbench-continuity-standalone', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('workspaces');
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
        req.onblocked = () => reject(new Error('Local storage is currently unavailable.'));
      });
      storageAvailable = true;
      storageMessage('Ready to save on this device.');
      return database;
    } catch (error) { storageAvailable = false; storageMessage('Local save unavailable · download a packet to keep your work.'); return null; }
  }
  async function persist() {
    if (!database || !workspace) return false;
    if (filesOf(workspace).reduce((total,file) => total + file.size, 0) > 67108864) {
      storageMessage('Large project open · save a work packet to keep it.');
      try { const tx = database.transaction('workspaces', 'readwrite'); tx.objectStore('workspaces').delete('last'); } catch (_) {}
      return false;
    }
    try {
      await new Promise((resolve, reject) => {
        const tx = database.transaction('workspaces', 'readwrite');
        tx.objectStore('workspaces').put({workspace, savedAt:new Date().toISOString()}, 'last');
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
      });
      storageMessage('Saved on this device · download a packet to move it.');
      return true;
    } catch (error) { storageAvailable = false; storageMessage('Local save failed · download a packet to keep your work.'); return false; }
  }
  async function restore() {
    if (!database) await initStorage();
    if (!database) return false;
    try {
      const record = await new Promise((resolve, reject) => { const req = database.transaction('workspaces').objectStore('workspaces').get('last'); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
      if (record && record.workspace && record.workspace.files) {
        const rehydrate = engine().restoreWorkspace || engine().rehydrateWorkspace;
        const recovered = rehydrate ? await rehydrate(record.workspace) : record.workspace;
        workspace = recovered; restored = true; dirty = false; tab = 'overview'; selectedFile = null;
        storageMessage('Restored your last project from this device.'); render(); return true;
      }
    } catch (error) { storageMessage('Could not restore local work · open your downloaded packet.'); }
    return false;
  }
  function canReplace() { return !dirty || window.confirm('You have changes that haven’t been applied yet. Open another project and discard those edits?'); }
  async function acceptWorkspace(next, label) {
    workspace = next; dirty = false; restored = false; tab = 'overview'; selectedFile = null; fileSearch = ''; fileFilter = 'all';
    render(); await persist();
    const count = filesOf(workspace).length;
    announce((label || 'Project') + ' opened. ' + count + ' files carried forward.');
    return workspace;
  }
  async function importBytes(bytes, filename, skipConfirm) {
    if (!skipConfirm && !canReplace()) return null;
    setBusy('Opening and checking your packet…');
    try { const next = await engine().importZip(bytes instanceof Blob ? bytes : bytesOf(bytes), filename || 'work-packet.zip'); return await acceptWorkspace(next, filename || 'Work packet'); }
    catch (error) { announce('Could not open this packet. ' + (error.message || error) + (workspace ? ' Your current project is still here.' : ''), true); throw error; }
    finally { setBusy(null); }
  }
  async function importFileEntries(entries, label, skipConfirm) {
    if (!skipConfirm && !canReplace()) return null;
    setBusy('Opening and checking your project…');
    try { const next = await engine().importFiles(entries, label || 'Project folder'); return await acceptWorkspace(next, label || 'Project folder'); }
    catch (error) { announce('Could not open this project. ' + (error.message || error) + (workspace ? ' Your current project is still here.' : ''), true); throw error; }
    finally { setBusy(null); }
  }
  async function openSelection(selected, add) {
    const files = Array.from(selected || []);
    if (!files.length) return null;
    if (!add && !canReplace()) return null;
    setBusy(add && workspace ? 'Adding files to your project…' : 'Opening your project…');
    try {
      let next;
      if (add && workspace) {
        if (dirty) await saveChanges(true);
        next = await engine().importAttachments(workspace, files);
        workspace = next || workspace; dirty = false; render(); await persist();
        announce(files.length + ' file' + (files.length === 1 ? '' : 's') + ' added. Your project and records stay together.');
        return workspace;
      }
      const zipped = files.filter(file => /\.zip$/i.test(file.name));
      const initial = zipped.find(file => /source|project/i.test(file.name)) || zipped.find(file => /capsule|preservation/i.test(file.name)) || zipped[0] || files[0];
      next = /\.zip$/i.test(initial.name) ? await engine().importZip(initial, initial.name) : await engine().importAsset(initial, initial.name);
      const remaining = files.filter(file => file !== initial);
      if (remaining.length) next = (await engine().importAttachments(next, remaining)) || next;
      return await acceptWorkspace(next, projectInfoFromName(initial.name));
    } catch (error) {
      announce('Could not ' + (add ? 'add these files. ' : 'open this project. ') + (error.message || error) + (workspace ? ' Your current project is still here.' : ''), true);
      throw error;
    } finally { setBusy(null); }
  }
  function projectInfoFromName(name) { return String(name || 'Project').replace(/\.zip$/i, ''); }
  async function addFiles(files) { return openSelection(files, true); }
  function decodeBase64(s) { const raw = atob(s); const bytes = new Uint8Array(raw.length); for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i); return bytes; }
  async function loadExample() {
    const sample = window.EMBEDDED_SAMPLE_PACKET;
    if (!sample) { announce('The included example is unavailable. Open a project packet instead.', true); return null; }
    const bytes = typeof sample === 'string' ? decodeBase64(sample) : sample.base64 ? decodeBase64(sample.base64) : bytesOf(sample.bytes || sample);
    return importBytes(bytes, sample.filename || 'Workbench-Continuity-Example.zip');
  }
  function markDirty() { dirty = true; const el = $('unsaved'); if (el) el.textContent = 'Changes ready to apply'; }
  async function saveChanges(quiet) {
    if (!workspace) return workspace;
    if ($('edit-objective')) {
      const changes = {status:$('edit-status').value, objective:$('edit-objective').value.trim(), nextAction:$('edit-next').value.trim(), decisions:$('edit-decisions').value, buildState:$('edit-build').value.trim(), phoneStatus:$('edit-phone').value.trim()};
      for (const field of ['status','objective','nextAction']) if (!changes[field]) delete changes[field];
      workspace = (await engine().updateState(workspace, changes)) || workspace;
    }
    dirty = false; const saved = await persist(); render();
    if (!quiet) announce(saved ? 'Changes applied and saved on this device.' : 'Changes applied. Download a work packet to keep them.');
    return workspace;
  }
  async function nativeDownload(raw, filename, mime, carrierDestination, carrierMetadata) {
    const bridge = window.WorkbenchNative;
    if (!bridge || typeof bridge.exportBegin !== 'function') return false;
    if (exportCallback) throw new Error('Another save is still finishing.');
    const completion = new Promise((resolve, reject) => {
      exportCallback = (success, message) => { exportCallback = null; success ? resolve(message || filename) : reject(new Error(message || 'The file was not saved.')); };
    });
    try {
      if (bridge.exportBegin(filename, mime) === false) throw new Error('Could not begin saving this file.');
      const total = raw instanceof Blob ? raw.size : raw.length;
      for (let start = 0; start < total; start += 65536) {
        const chunk = raw instanceof Blob ? new Uint8Array(await raw.slice(start, Math.min(start + 65536, total)).arrayBuffer()) : raw.subarray(start, Math.min(start + 65536, total));
        let binary = ''; for (let i = 0; i < chunk.length; i++) binary += String.fromCharCode(chunk[i]);
        if (bridge.exportChunk(btoa(binary)) === false) throw new Error('The file could not be written completely.');
        if (start % (65536 * 16) === 0) { if (working) $('busy-label').textContent = 'Writing ' + humanBytes(Math.min(start + chunk.length,total)) + ' / ' + humanBytes(total) + '…'; await new Promise(resolve => setTimeout(resolve, 0)); }
      }
      const finished = carrierDestination && typeof bridge.exportFinishWithCarriers === 'function' ? bridge.exportFinishWithCarriers(carrierDestination, JSON.stringify(carrierMetadata || {})) : bridge.exportFinish();
      if (finished === false) throw new Error('Could not finish saving this file.');
      await completion; return true;
    } catch (error) { if (exportCallback) exportCallback = null; completion.catch(() => {}); if (typeof bridge.exportAbort === 'function') { try { bridge.exportAbort(); } catch (_) {} } throw error; }
  }
  window.nativeExportResult = function (success, message) { if (exportCallback) exportCallback(success === true || success === 'true', message); };
  function signingHandoff() {
    const carriers = window.ContinuityCarriers;
    if (carriers && typeof carriers.signingHandoff === 'function') return carriers.signingHandoff(workspace);
    return {format:'continuity-private-signing-handoff/1',passport_id:workspace && workspace.passport && workspace.passport.passport_id || null,workflow:'edit anywhere → build anywhere → sign privately on the owner device → install/update',credentials:'Signing keys and passwords stay outside AI packets. Select the existing owner keystore directly in the Android native signer.',ai_build:{preserve_application_id:true,version_code:'Increase versionCode above the installed/reference app for the requested update.',signature:'Return an unsigned or temporarily debug-signed APK when supported; do not invent a replacement release key.'},return_files:['Actual built APK','Complete updated source/work packet and Passport','Build evidence with its actual verification scope'],owner_finalization:{application:'Workbench Continuity Android · Sign returned APK',reference:'Installed app or known-good APK',checks:['Package','Version','Matching owner signing certificate','Final signature verification'],update_claim:'A checked matching reference is required for an update-compatible claim; signing alone does not establish installation or device behavior.'}};
  }
  function signingMarkup() {
    const native = window.WorkbenchNative && typeof window.WorkbenchNative.openLocalSigning === 'function';
    return '<section class="card signing-card"><div class="eyebrow">Finish your update</div><h3>Use your own signing identity.</h3><p class="help">Bring back the APK from your chat. ' + (native ? 'Select your existing owner keystore in the private signer and compare with your installed app or a known-good APK. Your key stays outside every AI packet.' : 'Open the APK in Workbench Continuity Android to sign it with your existing private key and check whether it can update your installed app.') + '</p><div class="actions" style="margin-top:16px"><button id="sign-returned">Sign returned APK</button>' + (lastSigningReceipt ? '<button class="subtle" id="save-signing-receipt">Save signing receipt</button>' : '') + '</div>' + (lastSigningReceipt ? '<p class="help">Last signing result: ' + escape(lastSigningReceipt.updateStatus === 'compatible' ? 'update compatible with the checked reference' : 'signed; update compatibility ' + (lastSigningReceipt.updateStatus || 'not verified')) + '. Installation and device behavior remain separate checks.</p>' : '') + '</section>';
  }
  async function openLocalSigning() {
    if (working) return false;
    if (dirty) await saveChanges(true);
    const bridge = window.WorkbenchNative;
    if (!bridge || typeof bridge.openLocalSigning !== 'function') { announce('Use Workbench Continuity Android → Sign returned APK. The standalone HTML carries the project and build tools; the Android app performs private local APK signing.'); return false; }
    const opened = bridge.openLocalSigning();
    if (opened === false) announce('Could not open the signer while another Android file operation is active. Finish that operation, then tap Sign returned APK.', true);
    return opened !== false;
  }
  function publicSigningReceipt(raw) {
    const value = typeof raw === 'string' ? engine().parseJSONText(raw, 'Local signing receipt') : raw;
    if (!value || value.format !== 'workbench-local-signing/1' || value.status !== 'signed-and-verified') throw new Error('The signer returned an unsupported receipt.');
    const apk = source => {
      if (source == null) return null;
      if (typeof source !== 'object' || !/^[a-fA-F0-9]{64}$/.test(source.sha256 || '')) throw new Error('The signer receipt has no valid APK digest.');
      const out = {};
      for (const key of ['packageName','versionName','versionCode','minSdkVersion','splitName','size','sha256','verified']) if (['string','number','boolean'].includes(typeof source[key]) || source[key] === null) out[key] = source[key];
      out.certificateSha256 = (Array.isArray(source.certificateSha256) ? source.certificateSha256 : []).filter(v => typeof v === 'string' && /^[a-fA-F0-9]{64}$/.test(v));
      out.schemes = {}; for (const key of ['v1','v2','v3','v31']) if (typeof source.schemes?.[key] === 'boolean') out.schemes[key] = source.schemes[key];
      out.verificationErrors = (Array.isArray(source.verificationErrors) ? source.verificationErrors : []).filter(v => typeof v === 'string').slice(0,20);
      return out;
    };
    if (!['compatible','no-reference','incompatible'].includes(value.updateStatus)) throw new Error('The signer receipt has no valid update status.');
    const receipt = {format:value.format,status:value.status,recordedAt:new Date().toISOString(),input:apk(value.input),output:apk(value.output),reference:apk(value.reference),updateCompatible:value.updateCompatible === true,updateStatus:value.updateStatus,updateReasons:(Array.isArray(value.updateReasons) ? value.updateReasons : []).filter(v => typeof v === 'string').slice(0,20),installObserved:false,savedOnDevice:value.savedOnDevice === true,autoReferenceSource:['chosen APK','installed package','none'].includes(value.autoReferenceSource) ? value.autoReferenceSource : 'not recorded',verificationScope:'Native signer receipt for these exact APK bytes and reference only. Installation and runtime behavior were not established by signing.'};
    if (!receipt.output || receipt.output.verified !== true || !receipt.output.certificateSha256.length) throw new Error('The returned APK has no successful signature verification receipt.');
    if (receipt.updateCompatible !== (receipt.updateStatus === 'compatible')) throw new Error('The signer receipt has conflicting update claims.');
    if (receipt.updateCompatible) {
      const reference = receipt.reference, signed = receipt.output;
      const certificates = apk => apk.certificateSha256.map(x => x.toLowerCase()).sort().join(',');
      const version = apk => /^[0-9]+$/.test(String(apk.versionCode)) ? BigInt(String(apk.versionCode)) : null;
      if (!reference || reference.verified !== true || signed.packageName !== reference.packageName || !reference.certificateSha256.length || certificates(signed) !== certificates(reference) || signed.splitName || reference.splitName || version(signed) == null || version(reference) == null || version(signed) < version(reference)) throw new Error('The signer receipt does not bind its update claim to a matching certificate, package and the same or higher versionCode.');
    }
    return receipt;
  }
  async function receiveSigningResult(success, raw) {
    if (!(success === true || success === 'true')) { announce(typeof raw === 'string' ? raw : 'Local signing was cancelled or could not finish.', true); return false; }
    try {
      const receipt = publicSigningReceipt(raw); lastSigningReceipt = receipt;
      if (workspace) {
        const path = 'evidence/local-signing/receipt-' + new Date().toISOString().replace(/[^0-9]/g,'') + '-' + Math.random().toString(36).slice(2,8) + '.json';
        workspace = await engine().importAttachments(workspace,[{path,bytes:new TextEncoder().encode(JSON.stringify(receipt,null,2)+'\n')}]);
        await persist();
      }
      render(); announce(receipt.updateCompatible ? 'Signed APK saved. Its package, version and certificate are update compatible with the checked reference.' + (workspace ? ' The public signing receipt is attached to this project.' : '') : 'Signed APK saved. Update compatibility is ' + (receipt.updateStatus === 'no-reference' ? 'unverified without a reference app.' : 'not established; read the signing receipt.') + (workspace ? ' The receipt is attached to this project.' : ''));
      return receipt;
    } catch (error) { announce('The APK signer returned a receipt that could not be attached: ' + (error.message || error), true); return false; }
  }
  window.nativeSigningResult = receiveSigningResult;
  async function downloadBytes(raw, filename, mime, options) {
    const bytes = raw instanceof Blob ? raw : bytesOf(raw);
    if (await nativeDownload(bytes, filename, mime || 'application/zip', options && options.carrierDestination, options && options.carrierMetadata)) return;
    const blob = bytes instanceof Blob ? bytes : new Blob([bytes], {type:mime || 'application/octet-stream'});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  async function exportPacket(mode) {
    if (!workspace) return null;
    try {
      if (dirty) await saveChanges(true);
      setBusy(mode === 'public' ? 'Checking and preparing a public copy…' : 'Packing your source and project record…');
      const result = await engine().exportPacket(workspace, {mode:mode || 'private',additionalFiles:new Map([['SIGNING_HANDOFF.json',new TextEncoder().encode(JSON.stringify(signingHandoff(),null,2)+'\n')]])});
      await downloadBytes(result.blob || result.bytes, result.filename, 'application/zip');
      announce(mode === 'public' ? 'Public copy saved. Keep your private packet as the complete working copy.' : 'Work packet saved. Open this ZIP here or give it to your next chat.');
      await persist(); return result;
    } catch (error) { announce('Packet was not saved. ' + (error.message || error), true); throw error; }
    finally { setBusy(null); }
  }
  function carrierInventory(target) {
    const carriers = window.ContinuityCarriers;
    if (!carriers || typeof carriers.inventory !== 'function' || target === 'packet') return [];
    const result = carriers.inventory(target);
    return Array.isArray(result) ? result : (result && result.files || []);
  }
  function destinationDetails() {
    if (destination === 'packet') return '<p class="help">One ZIP with your current project, its original files, records, and opening instructions.</p>';
    const files = carrierInventory(destination), carriers = window.ContinuityCarriers;
    const targetName = destination === 'claude' ? 'Claude' : 'Grok';
    let capability = null;
    try { capability = workspace && carriers && typeof carriers.assessProject === 'function' ? carriers.assessProject(workspace) : null; } catch (_) {}
    if(window.WorkbenchRuntime&&!window.WorkbenchRuntime.ready())return '<p class="help">Load your build runtime to include the tools. For first-time setup, extract Workbench on Windows and run SETUP_WORKBENCH.bat once. Then choose Load build runtime and select the generated ZIP.</p>';
    const adapterNote = capability && capability.adapterSupported === false ? '<p class="help" style="color:var(--warn)">Your project and the build tools will travel. This project needs a build adapter or additional tools before this runtime can compile it; the bundle records that gap.</p>' : '';
    return '<p class="help">Your project plus the proven ' + (destination === 'claude' ? 'PDF' : 'ZIP/runtime') + ' build carriers for ' + targetName + '. The bundle explains exactly which files to attach.</p>' + adapterNote + (files.length ? '<details><summary>Included build tools</summary><div class="receipt">' + files.map(file => escape(file.label || file.name || file.filename || file.path || String(file)) + (file.size != null ? ' · ' + humanBytes(file.size) : '')).join('<br>') + '</div></details>' : '') + '<p class="help">Private working bundle. Existing source and evidence stay intact.</p>';
  }
  async function prepareDestination(target) {
    if (!target || target === 'packet') return exportPacket('private');
    const carriers = window.ContinuityCarriers;
    if (!carriers || typeof carriers.prepare !== 'function') throw new Error('This copy does not contain the private destination carriers. Use Save work packet or open the private artifact.');
    try {
      if (dirty) await saveChanges(true);
      setBusy('Preparing your project for ' + (target === 'claude' ? 'Claude' : 'Grok') + '…');
      const useNativePlan = !window.WorkbenchRuntime && window.WorkbenchNative && typeof window.WorkbenchNative.exportFinishWithCarriers === 'function' && typeof carriers.preparePlan === 'function';
      const result = await (useNativePlan ? carriers.preparePlan(workspace, {destination:target}) : carriers.prepare(workspace, {destination:target}));
      await downloadBytes(result.blob || result.bytes, result.filename, 'application/zip', useNativePlan ? {carrierDestination:target, carrierMetadata:result.nativeMetadata} : null);
      announce((target === 'claude' ? 'Claude' : 'Grok') + ' bundle saved. Extract it and follow its START_HERE instructions to attach the included project and build tools.');
      await persist(); return result;
    } catch (error) { announce('Destination bundle was not saved. ' + (error.message || error), true); throw error; }
    finally { setBusy(null); }
  }
  async function clear() {
    if (!canReplace()) return false;
    workspace = null; dirty = false; selectedFile = null; tab = 'overview';
    if (database) await new Promise((resolve, reject) => { const tx = database.transaction('workspaces', 'readwrite'); tx.objectStore('workspaces').delete('last'); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
    render(); storageMessage(storageAvailable ? 'Ready to save on this device.' : 'Download a packet to keep your work.'); return true;
  }
  function privacyNotice() {
    const quarantine = workspace.quarantine instanceof Map ? workspace.quarantine.size : Array.isArray(workspace.quarantine) ? workspace.quarantine.length : workspace.quarantine && Object.keys(workspace.quarantine).length || 0;
    const privacy = workspace.privacy || {};
    return (quarantine ? '<div class="notice warn"><strong>Owner keys stay on this device.</strong> ' + quarantine + ' credential file' + (quarantine === 1 ? ' is' : 's are') + ' excluded from AI handoffs. The rest of your project can keep moving.</div>' : '') + '<p class="help">Private work packet by default. Public copy is a separate export checked against the project’s sharing record.</p>';
  }
  function verificationNotice() {
    const i = workspace.integrity || {}, issues = i.issues || [];
    const manifests = i.verifiedManifests;
    const count = Array.isArray(manifests) ? manifests.length : Number(manifests || 0);
    const failed = /fail|invalid|mismatch|bad/i.test(i.status || '') || issues.some(x => /mismatch|failed|missing/i.test(typeof x === 'string' ? x : JSON.stringify(x)));
    if (failed) return '<div class="notice bad"><strong>Verification needs attention.</strong> ' + escape(issues.map(x => typeof x === 'string' ? x : x.message || JSON.stringify(x)).join(' ')) + '</div>';
    if (count) return '<div class="notice"><strong>File verification: ' + escape(i.status || 'checked') + '.</strong> ' + count + ' carried manifest' + (count === 1 ? '' : 's') + ' checked. Imported test and build receipts are kept with the project.</div>';
    return '<div class="notice"><strong>' + escape(i.status || 'Files imported') + '.</strong> ' + (issues.length ? escape(issues.map(x => typeof x === 'string' ? x : x.message || JSON.stringify(x)).join(' ')) : 'No prior file manifest was supplied. Saving a work packet creates one for the next handoff.') + '</div>';
  }
  function welcomeMarkup() {
    return '<section class="card welcome drop-zone" id="project-drop"><div class="eyebrow">Giving all chats hands</div><h2>Bring your project.<br>Keep building.</h2><p>Open the source ZIP you already use. Include the APK, logs, game files, and notes. Then take the project and the proven build tools to Claude or Grok.</p><div class="actions"><button class="primary" id="welcome-open">Open project</button>' + (folderPickerAvailable() ? '<button id="welcome-folder">Open folder</button>' : '') + '<button class="subtle" id="welcome-example">Try example</button></div><div class="sample-info">Select several files together or drop them here. Existing Passports and build evidence travel with the project. Everything runs offline.</div></section>';
  }
  function sidebarMarkup() {
    const info = projectInfo(), s = state(), files = filesOf(workspace);
    const source = files.filter(f => sourcePattern.test(f.path)).length, evidence = files.filter(f => evidencePattern.test(f.path)).length;
    const candidates = workspace.candidates || [];
    return '<aside class="sidebar"><section class="card' + (candidates.length > 1 ? ' multiple-projects' : '') + '"><div class="eyebrow">Current project</div><div class="projectname">' + escape(info.name) + '</div><div class="projectid">' + escape(info.id) + '</div>' + (candidates.length > 1 ? '<div class="field" style="margin-top:18px"><label for="project-select">Project to continue</label><select id="project-select"><option value="">Choose a project…</option>' + candidates.map((c,index) => '<option value="r:' + index + '"' + (workspace.selectedRoot === c.root ? ' selected' : '') + '>' + escape(c.name || c.id || c.root || 'Root project') + ' · ' + escape(c.version || '') + '</option>').join('') + '</select></div>' : '') + '<dl class="meta"><div><dt>Version</dt><dd>' + escape(info.version || 'Not recorded') + '</dd></div><div><dt>Work state</dt><dd>' + escape(s.status || 'Needs a record') + '</dd></div><div><dt>Files carried</dt><dd>' + files.length + '</dd></div><div><dt>Privacy</dt><dd>' + escape((workspace.privacy || {}).classification || 'Private copy') + '</dd></div></dl></section><nav class="nav" aria-label="Workspace views"><button data-tab="overview" class="' + (tab === 'overview' ? 'active' : '') + '"' + (tab === 'overview' ? ' aria-current="page"' : '') + '>Build / carry <span class="count">↗</span></button><button data-tab="source" class="' + (tab === 'source' ? 'active' : '') + '"' + (tab === 'source' ? ' aria-current="page"' : '') + '>Files <span class="count">' + files.length + '</span></button><button data-tab="records" class="' + (tab === 'records' ? 'active' : '') + '"' + (tab === 'records' ? ' aria-current="page"' : '') + '>Records <span class="count">' + evidence + '</span></button></nav><p class="sidebar-note">' + source + ' source/configuration files. Add files keeps this project together.</p><button id="add-current" style="width:100%">Add files</button><button class="subtle" id="open-folder-current" style="width:100%;margin-top:8px">Open another project</button></aside>';
  }
  function overviewMarkup() {
    const s = state(), info = projectInfo();
    const standard = ['working','ready','blocked','complete','device-test-pending','device-tested'];
    if (s.status && !standard.includes(s.status)) standard.unshift(s.status);
    return '<div class="heading"><div><h2>' + escape(info.name) + '</h2><p>Your project is open. Add anything it needs, then keep building in the next chat.</p></div><span class="tag"><span class="dot"></span>' + (restored ? 'Restored locally' : 'Project opened') + '</span></div><section class="card continue-card"><div class="field"><label for="edit-next">What should the next chat do?</label><textarea id="edit-next" placeholder="E.g. continue from this working build and fix the first battle crash.">' + escape(s.nextAction || s.next_action || '') + '</textarea></div><div class="field"><label for="target-destination">Where are you continuing?</label><select id="target-destination"><option value="packet"' + (destination === 'packet' ? ' selected' : '') + '>Save a work packet</option>' + (window.ContinuityCarriers ? '<option value="claude"' + (destination === 'claude' ? ' selected' : '') + '>Claude · project + PDF build tools</option><option value="grok"' + (destination === 'grok' ? ' selected' : '') + '>Grok · project + ZIP/runtime build tools</option>' : '') + '</select><div id="destination-details">' + destinationDetails() + '</div></div><div class="actions"><button class="primary" id="prepare-destination">' + (destination === 'packet' ? 'Save work packet' : 'Prepare ' + (destination === 'claude' ? 'Claude' : 'Grok') + ' bundle') + '</button><button id="add-overview">Add files</button></div><p class="help" id="unsaved">' + (dirty ? 'Changes will be included when you save.' : 'Source, originals, records, and attachments travel together.') + '</p></section>' + signingMarkup() + privacyNotice() + '<section class="card"><details id="work-details"><summary>Project notes, decisions, and observed build state</summary><div class="field"><label for="edit-objective">Current objective</label><textarea id="edit-objective" placeholder="What does this pass need to deliver?">' + escape(s.objective || s.purpose || '') + '</textarea></div><div class="state-fields"><div class="field"><label for="edit-status">Work state</label><select id="edit-status">' + standard.map(v => '<option value="' + escape(v) + '"' + (s.status === v ? ' selected' : '') + '>' + escape(v.replace(/-/g, ' ')) + '</option>').join('') + '</select></div><div class="field"><label for="edit-phone">Device test / observed outcome</label><input id="edit-phone" value="' + escape(observed(s.phoneStatus || s.phone_status)) + '" placeholder="E.g. works on S25 Ultra"></div></div><div class="field"><label for="edit-build">Current build state</label><textarea id="edit-build" placeholder="Build results or what is still pending.">' + escape(observed(s.buildState || s.build_state)) + '</textarea><p class="help">Your observation. Original receipts retain the results they actually record.</p></div><div class="field"><label for="edit-decisions">Decisions to carry forward</label><textarea id="edit-decisions" placeholder="One decision per line" style="min-height:130px">' + escape(multiline(s.decisions)) + '</textarea></div><div class="save-row"><span class="changes">These notes travel with your project.</span><button id="save-changes">Apply notes</button></div></details></section><details class="verification-details"><summary>Import and file verification</summary>' + verificationNotice() + '</details>';
  }
  function recordsMarkup() {
    const files = filesOf(workspace), s = state();
    const records = files.filter(f => continuityPattern.test(f.path) || evidencePattern.test(f.path));
    return '<div class="heading"><div><h2>The record travels with the work.</h2><p>Passport, handoff, original receipts, and device evidence remain inspectable.</p></div></div>' + verificationNotice() + privacyNotice() + '<section class="card"><div class="eyebrow">Current project record</div><details open><summary>Current Passport</summary><pre class="receipt">' + escape(JSON.stringify(workspace.passport || {}, null, 2)) + '</pre></details><details><summary>Current handoff</summary><pre class="receipt">' + escape(JSON.stringify(workspace.handoff || {}, null, 2)) + '</pre></details><details><summary>File verification details</summary><pre class="receipt">' + escape(JSON.stringify(workspace.integrity || {}, null, 2)) + '</pre></details><details><summary>What intake carried or adapted</summary><pre class="receipt">' + escape(multiline(workspace.intakeWarnings || [])) + '</pre></details><details><summary>Sharing rules detected in this packet</summary><pre class="receipt">' + escape(JSON.stringify(workspace.privacy || {}, null, 2)) + '</pre></details></section><section class="card"><h3>Carried evidence and records · ' + records.length + '</h3><p class="help" style="margin-bottom:16px">These are the files actually present in this packet. A receipt records the test it describes; it doesn’t imply a new device test.</p>' + fileBrowserMarkup('records') + '</section>';
  }
  function filteredFiles(scope) {
    let files = filesOf(workspace);
    if (scope === 'records') files = files.filter(f => continuityPattern.test(f.path) || evidencePattern.test(f.path));
    if (fileFilter === 'source') files = files.filter(f => sourcePattern.test(f.path));
    if (fileFilter === 'records') files = files.filter(f => continuityPattern.test(f.path));
    if (fileFilter === 'evidence') files = files.filter(f => evidencePattern.test(f.path));
    if (fileSearch) files = files.filter(f => f.path.toLowerCase().includes(fileSearch.toLowerCase()));
    return files.sort((a, b) => a.path.localeCompare(b.path));
  }
  function fileBrowserMarkup(scope) {
    const files = filteredFiles(scope), shown = files.slice(0, 1000);
    return '<div class="file-toolbar"><input id="file-search" type="search" aria-label="Search project files" placeholder="Find a file…" value="' + escape(fileSearch) + '"><select id="file-filter" aria-label="Filter project files">' + [['all','All files'],['source','Source / config'],['records','Continuity records'],['evidence','Evidence / builds']].map(([v,l]) => '<option value="' + v + '"' + (fileFilter === v ? ' selected' : '') + '>' + l + '</option>').join('') + '</select></div><div class="file-layout"><div><div class="file-list">' + (shown.length ? shown.map(f => '<button class="file-item' + (selectedFile === f.path ? ' active' : '') + '" data-file="' + escape(f.path) + '"><span class="name">' + escape(f.path) + '</span><span class="size">' + humanBytes(f.size) + '</span></button>').join('') : '<div class="empty">No files match this view.</div>') + '</div><p class="help">' + files.length + ' matching files' + (files.length > shown.length ? ' · Showing first ' + shown.length + '; use search to narrow the list.' : '') + '</p></div><div class="file-preview" id="file-preview"><div class="empty">Choose a file to read its contents.</div></div></div>';
  }
  function sourceMarkup() { return '<div class="heading"><div><h2>Everything you brought.</h2><p>Source, APKs, logs, assets, and game files. Imported code is displayed as text.</p></div></div><section class="card">' + fileBrowserMarkup('all') + '</section>'; }
  function bindFiles() {
    const search = $('file-search'), filter = $('file-filter');
    if (search) search.oninput = () => { fileSearch = search.value; const start = search.selectionStart; render(); const next = $('file-search'); if (next) { next.focus(); next.setSelectionRange(start, start); } };
    if (filter) filter.onchange = () => { fileFilter = filter.value; render(); };
    document.querySelectorAll('[data-file]').forEach(button => button.onclick = () => { selectedFile = button.dataset.file; render(); });
    if (selectedFile && $('file-preview')) previewFile(selectedFile);
  }
  async function previewFile(path) {
    const file = filesOf(workspace).find(f => f.path === path), preview = $('file-preview');
    if (!file || !preview) return;
    const filename = path.split('/').pop(), size = file.size;
    const isText = textPattern.test(path) || /(^|\/)(README|LICENSE|NOTICE|Dockerfile|Makefile|CMakeLists\.txt|START_HERE)$/i.test(path);
    const raw = rawOf(file);
    const sample = isText ? file.blob ? new Uint8Array(await file.blob.slice(0,262144).arrayBuffer()) : bytesOf(file.bytes).subarray(0,262144) : null;
    if (selectedFile !== path || !document.contains(preview)) return;
    let text = isText ? new TextDecoder().decode(sample) : 'Binary file · ' + humanBytes(size) + '\n\nPreserved as project cargo. It is carried without running or interpreting it.';
    if (isText && size > 262144) text += '\n\n[Preview limited to the first 256 KB. The complete file is preserved.]';
    preview.innerHTML = '<p class="file-path">' + escape(path) + '</p><div class="pill-row"><span class="tag quiet">' + humanBytes(size) + '</span><button class="subtle" id="download-file">Download file</button></div><div class="hash" id="file-hash">' + escape(file.sha256 ? 'SHA-256 · ' + file.sha256 : file.blob ? 'SHA-256 is calculated in bounded chunks when the packet is saved.' : 'Checking SHA-256…') + '</div><pre>' + escape(text) + '</pre>';
    $('download-file').onclick = async () => { try { await downloadBytes(raw, filename, isText ? 'text/plain' : 'application/octet-stream'); announce(filename + ' saved.'); } catch (error) { announce('File was not saved. ' + (error.message || error), true); } };
    if (!file.sha256 && !file.blob && window.crypto && crypto.subtle) {
      try { const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', file.bytes)); const hex = Array.from(hash, b => b.toString(16).padStart(2, '0')).join(''); if (selectedFile === path && $('file-hash')) $('file-hash').textContent = 'SHA-256 · ' + hex; } catch (_) { if ($('file-hash')) $('file-hash').textContent = 'The complete file is preserved. Saved packets include its digest.'; }
    }
  }
  function render() {
    controls();
    const content = $('content');
    if (!workspace) {
      content.innerHTML = welcomeMarkup() + signingMarkup();
      bindSigningActions();
      $('welcome-open').onclick = () => $('zip-input').click();
      if ($('welcome-folder')) $('welcome-folder').onclick = () => $('folder-input').click();
      $('welcome-example').onclick = () => loadExample().catch(() => {});
      $('welcome-example').disabled = !window.EMBEDDED_SAMPLE_PACKET;
      return;
    }
    content.innerHTML = '<div class="layout">' + sidebarMarkup() + '<main>' + (tab === 'source' ? sourceMarkup() : tab === 'records' ? recordsMarkup() : overviewMarkup()) + '</main></div>';
    document.querySelectorAll('[data-tab]').forEach(button => button.onclick = async () => { if (dirty) { try { await saveChanges(true); } catch (error) { announce(error.message || error, true); return; } } tab = button.dataset.tab; render(); });
    if ($('project-select')) $('project-select').onchange = async event => {
      const value = event.target.value;
      if (!value) return;
      const candidate = (workspace.candidates || [])[Number(value.slice(2))];
      if (!candidate) return;
      const root = candidate.root;
      if (dirty && !window.confirm('Switch projects and discard the unapplied edits?')) { render(); return; }
      try { workspace = (await engine().selectProject(workspace, root)) || workspace; dirty = false; selectedFile = null; render(); await persist(); }
      catch (error) { announce('Could not switch projects. ' + (error.message || error), true); render(); }
    };
    $('open-folder-current').onclick = () => $('zip-input').click();
    if ($('add-current')) $('add-current').onclick = () => $('add-input').click();
    if ($('add-overview')) $('add-overview').onclick = () => $('add-input').click();
    if ($('save-changes')) $('save-changes').onclick = () => saveChanges().catch(error => announce(error.message || error, true));
    bindSigningActions();
    if ($('prepare-destination')) $('prepare-destination').onclick = () => prepareDestination(destination).catch(() => {});
    if ($('target-destination')) $('target-destination').onchange = event => { destination = event.target.value; $('destination-details').innerHTML = destinationDetails(); $('prepare-destination').textContent = destination === 'packet' ? 'Save work packet' : 'Prepare ' + (destination === 'claude' ? 'Claude' : 'Grok') + ' bundle'; };
    if ($('overview-records')) $('overview-records').onclick = async () => { if (dirty) { try { await saveChanges(true); } catch (error) { announce(error.message || error, true); return; } } tab = 'source'; render(); };
    ['edit-objective','edit-next','edit-status','edit-decisions','edit-build','edit-phone'].forEach(id => { if ($(id)) $(id).addEventListener('input', markDirty); });
    bindFiles();
    controls();
  }
  $('import-top').onclick = () => $('zip-input').click();
  function bindSigningActions() {
    if ($('sign-returned')) $('sign-returned').onclick = () => openLocalSigning().catch(error => announce(error.message || error, true));
    if ($('save-signing-receipt')) $('save-signing-receipt').onclick = () => downloadBytes(new TextEncoder().encode(JSON.stringify(lastSigningReceipt,null,2)+'\n'),'Workbench_Continuity_Local_Signing_Receipt.json','application/json').catch(error => announce(error.message || error, true));
  }
  if ($('sign-returned-top')) $('sign-returned-top').onclick = () => openLocalSigning().catch(error => announce(error.message || error, true));
  async function loadRuntime(file,persistRuntime=true){
    if(!file)return null;
    setBusy('Checking your build runtime…');
    try{
      const result=await window.WorkbenchRuntime.load(file);
      if(database&&persistRuntime)try{await new Promise((resolve,reject)=>{const tx=database.transaction('workspaces','readwrite');tx.objectStore('workspaces').put({blob:window.WorkbenchRuntime.blob()},'build-runtime');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}catch(_){announce('Runtime loaded for this session. Keep its original ZIP to load again.',true);render();return result;}
      render();announce('Build runtime ready. Your project stays unchanged.');return result;
    }catch(error){announce('Could not load this runtime. '+error.message,true);throw error;}
    finally{setBusy(null);}
  }
  $('load-runtime').onclick=()=>$('runtime-input').click();
  $('runtime-input').onchange=()=>{const file=$('runtime-input').files[0];$('runtime-input').value='';loadRuntime(file).catch(()=>{});};
  $('download-setup').onclick=()=>downloadBytes(window.WorkbenchRuntime.setupZip(),'Workbench_Continuity_First_Time_Setup.zip','application/zip').catch(error=>announce(error.message,true));
  $('export-private').onclick = () => exportPacket('private').catch(() => {});
  $('export-public').onclick = () => exportPacket('public').catch(() => {});
  $('add-top').onclick = () => $('add-input').click();
  $('zip-input').onchange = async event => { const files = Array.from(event.target.files || []); event.target.value = ''; try { await openSelection(files, false); } catch (_) {} };
  $('add-input').onchange = async event => { const files = Array.from(event.target.files || []); event.target.value = ''; try { await addFiles(files); } catch (_) {} };
  $('folder-input').onchange = async event => { const files = Array.from(event.target.files || []); event.target.value = ''; if (!files.length || !canReplace()) return; setBusy('Reading your project folder…'); try { const entries = []; for (const file of files) entries.push({path:file.webkitRelativePath || file.name, blob:file, size:file.size}); await importFileEntries(entries, (files[0].webkitRelativePath || 'Project folder').split('/')[0], true); } catch (error) { announce('Could not read this folder. ' + (error.message || error), true); } finally { setBusy(null); } };
  let dragDepth = 0;
  document.addEventListener('dragenter', event => { if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes('Files')) return; event.preventDefault(); dragDepth++; document.body.classList.add('dragging'); });
  document.addEventListener('dragover', event => { if (event.dataTransfer && Array.from(event.dataTransfer.types || []).includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
  document.addEventListener('dragleave', event => { event.preventDefault(); dragDepth = Math.max(0,dragDepth-1); if (!dragDepth) document.body.classList.remove('dragging'); });
  document.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; document.body.classList.remove('dragging'); if (working) return; openSelection(event.dataTransfer && event.dataTransfer.files, !!workspace).catch(() => {}); });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.ContinuityUI = {getWorkspace:() => workspace, importBytes, importFileEntries, openSelection, addFiles, loadExample, saveChanges, exportPacket, prepareDestination, restore, render, clear, getState:state, isDirty:() => dirty, isStorageAvailable:() => storageAvailable, downloadBytes, openLocalSigning, receiveSigningResult, publicSigningReceipt, signingHandoff, loadRuntime};
  async function boot() {
    render();
    if (!engine()) { announce('The bundled project engine could not start. Download the complete Workbench Continuity artifact again.', true); return; }
    await initStorage(); await restore();
    if(database&&window.WorkbenchRuntime)try{const stored=await new Promise((resolve,reject)=>{const req=database.transaction('workspaces').objectStore('workspaces').get('build-runtime');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});if(stored&&stored.blob)await loadRuntime(stored.blob,false);}catch(_){/* Original runtime ZIP remains the recovery copy. */}
  }
  window.ContinuityUI.ready = boot();
})();
