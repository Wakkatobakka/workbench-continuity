package dev.wakka.continuity.v12;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.Toast;

import org.json.JSONObject;
import org.json.JSONArray;

import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.Deflater;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/** Offline document workspace. Only the bundled app is allowed to execute in this WebView. */
public final class MainActivity extends Activity {
    private static final String APP_URL = "file:///android_asset/index.html";
    private static final int OPEN_DOCUMENT = 401;
    private static final int CREATE_DOCUMENT = 402;
    private static final int LOCAL_SIGNING = 403;
    private static final int MAX_ENCODED_CHUNK = 256 * 1024;
    // This is a single-document transport limit, not a restriction on project languages
    // or contents. Staging, route assembly and copying use bounded buffers and long sizes.
    private static final long MAX_EXPORT_BYTES = 2L * 1024L * 1024L * 1024L;
    private static final int MAX_GENERATED_ROUTE_MEMBERS = 250;
    private static final String STAGE_PREFIX = "continuity-export-";

    private enum ExportPhase { IDLE, STAGING, PREPARING, PICKING, COPYING }

    private final Object exportLock = new Object();
    private final ExecutorService fileWorker = Executors.newSingleThreadExecutor();
    private WebView web;
    private ValueCallback<Uri[]> chooserCallback;
    private volatile boolean chooserPending;
    private volatile boolean signingPending;
    private volatile boolean destroyed;
    private volatile boolean bundleCanceled;
    private ExportPhase exportPhase = ExportPhase.IDLE;
    private File stagedFile;
    private OutputStream stagedOutput;
    private long stagedBytes;
    private String exportName;
    private String exportMime;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        removeAbandonedExports();
        LocalSigningActivity.removeAbandonedSessions(this);
        getWindow().setStatusBarColor(0xff07111b);
        getWindow().setNavigationBarColor(0xff07111b);

        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setFitsSystemWindows(true);
        screen.setBackgroundColor(0xff07111b);
        web = new WebView(this);
        web.setBackgroundColor(0xff07111b);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        // File input receives only URIs explicitly chosen through Android's document picker.
        // URL loading of content: is separately denied by the WebViewClient below.
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setBlockNetworkLoads(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        if (Build.VERSION.SDK_INT >= 26) settings.setSafeBrowsingEnabled(true);

        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !isAppUrl(url);
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !isAppUrl(request.getUrl().toString());
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
                return isAppUrl(url) ? null : deniedResource();
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return isAppUrl(request.getUrl().toString()) ? null : deniedResource();
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                    FileChooserParams params) {
                synchronized (exportLock) {
                    if (exportPhase != ExportPhase.IDLE || signingPending) {
                        callback.onReceiveValue(null);
                        Toast.makeText(MainActivity.this, "Finish signing or exporting first.", Toast.LENGTH_SHORT).show();
                        return true;
                    }
                    cancelChooser();
                    chooserCallback = callback;
                    chooserPending = true;
                }
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                // Source ZIPs, APKs, logs, game packets and split runtime files are all
                // legitimate cargo. The app inspects selected files; MIME is not a gate.
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                pick.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                try { startActivityForResult(pick, OPEN_DOCUMENT); }
                catch (ActivityNotFoundException e) {
                    cancelChooser();
                    Toast.makeText(MainActivity.this, "No document picker is available.", Toast.LENGTH_LONG).show();
                }
                return true;
            }
        });
        web.addJavascriptInterface(new ExportBridge(), "WorkbenchNative");
        screen.addView(web, new LinearLayout.LayoutParams(-1, -1));
        setContentView(screen);
        // Workspace content is restored by the app from its local IndexedDB at this fixed origin.
        web.loadUrl(APP_URL);
    }

    private static boolean isAppUrl(String url) {
        return APP_URL.equals(url) || (url != null && url.startsWith(APP_URL + "#"));
    }

    private static WebResourceResponse deniedResource() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
                Collections.<String, String>emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    private void removeAbandonedExports() {
        File[] files = getCacheDir().listFiles();
        if (files != null) for (File file : files) {
            if (file.isFile() && file.getName().startsWith(STAGE_PREFIX) && file.getName().endsWith(".stage")) {
                file.delete();
            }
        }
    }

    private void cancelChooser() {
        ValueCallback<Uri[]> callback = chooserCallback;
        chooserCallback = null;
        chooserPending = false;
        if (callback != null) callback.onReceiveValue(null);
    }

    /** Chunk acknowledgments are synchronous; final document-picker results are asynchronous. */
    private final class ExportBridge {
        /** Only a local native screen receives key selections or passwords. */
        @JavascriptInterface public boolean openLocalSigning() {
            synchronized (exportLock) {
                if (destroyed || chooserPending || signingPending || exportPhase != ExportPhase.IDLE) return false;
                signingPending = true;
            }
            runOnUiThread(() -> {
                if (destroyed) { signingPending = false; return; }
                try { startActivityForResult(new Intent(MainActivity.this, LocalSigningActivity.class), LOCAL_SIGNING); }
                catch (ActivityNotFoundException e) {
                    signingPending = false;
                    sendSigningResult(false, "The local signing screen could not open. Your project remains saved.");
                }
            });
            return true;
        }

        @JavascriptInterface public boolean exportBegin(String filename, String mime) {
            synchronized (exportLock) {
                if (destroyed || chooserPending || signingPending || exportPhase != ExportPhase.IDLE) return false;
                exportMime = supportedExportMime(mime);
                if (exportMime == null) {
                    sendExportResult(false, "This export type is not supported. Your project remains saved.");
                    return false;
                }
                exportName = safeExportName(filename, exportMime);
                stagedBytes = 0;
                bundleCanceled = false;
                try {
                    stagedFile = File.createTempFile(STAGE_PREFIX, ".stage", getCacheDir());
                    stagedOutput = new BufferedOutputStream(new FileOutputStream(stagedFile));
                    exportPhase = ExportPhase.STAGING;
                    return true;
                } catch (IOException e) {
                    discardStagedLocked();
                    sendExportResult(false, "Could not prepare an export. Check free storage and try again; your project remains saved.");
                    return false;
                }
            }
        }

        @JavascriptInterface public boolean exportChunk(String encoded) {
            synchronized (exportLock) {
                if (exportPhase != ExportPhase.STAGING || destroyed) return false;
                if (encoded == null || encoded.length() > MAX_ENCODED_CHUNK ||
                        encoded.length() % 4 != 0 || !encoded.matches("[A-Za-z0-9+/]*={0,2}")) {
                    discardStagedLocked();
                    sendExportResult(false, "The export contained an invalid data chunk. Your project remains saved.");
                    return false;
                }
                try {
                    byte[] bytes = Base64.decode(encoded, Base64.NO_WRAP);
                    if (stagedBytes + bytes.length > MAX_EXPORT_BYTES) {
                        discardStagedLocked();
                        sendExportResult(false, "This document exceeds the 2 GiB Android export limit. Save a smaller packet or split the cargo; your project remains saved.");
                        return false;
                    }
                    stagedOutput.write(bytes);
                    stagedBytes += bytes.length;
                    return true;
                } catch (IOException | IllegalArgumentException e) {
                    discardStagedLocked();
                    sendExportResult(false, "Could not stage the export. Check free storage and try again; your project remains saved.");
                    return false;
                }
            }
        }

        @JavascriptInterface public boolean exportFinish() {
            synchronized (exportLock) {
                if (exportPhase != ExportPhase.STAGING || destroyed) return false;
                if (stagedBytes == 0) {
                    discardStagedLocked();
                    sendExportResult(false, "The export was empty. Your project remains saved.");
                    return false;
                }
                try { stagedOutput.close(); stagedOutput = null; }
                catch (IOException e) {
                    discardStagedLocked();
                    sendExportResult(false, "Could not finish preparing the export. Your project remains saved.");
                    return false;
                }
                exportPhase = ExportPhase.PICKING;
            }
            launchSavePicker();
            return true;
        }

        @JavascriptInterface public boolean exportFinishWithCarriers(String destination, String metadataJson) {
            final CarrierAsset[] assets;
            final File generatedZip;
            final Set<String> generatedNames;
            synchronized (exportLock) {
                if (destroyed || exportPhase != ExportPhase.STAGING) return false;
                try {
                    if (metadataJson == null || metadataJson.getBytes(StandardCharsets.UTF_8).length > 128 * 1024) {
                        throw new IOException("Invalid route metadata");
                    }
                    JSONObject metadata = new JSONObject(metadataJson);
                    if (!"continuity-generated-route-zip/1".equals(metadata.optString("format")) ||
                            !destination.equals(metadata.optString("destination"))) {
                        throw new IOException("Invalid route metadata");
                    }
                    assets = carrierAssets(destination);
                    generatedNames = generatedRouteNames(metadata);
                    if (assets == null || !"application/zip".equals(exportMime) || stagedBytes == 0) {
                        throw new IOException("Invalid route destination");
                    }
                    stagedOutput.close();
                    stagedOutput = null;
                    generatedZip = stagedFile;
                    exportPhase = ExportPhase.PREPARING;
                } catch (Exception e) {
                    discardStagedLocked();
                    sendExportResult(false, "Could not prepare this destination bundle. Your project remains saved.");
                    return false;
                }
            }
            fileWorker.execute(() -> {
                File bundle = null;
                try {
                    bundle = File.createTempFile(STAGE_PREFIX, ".stage", getCacheDir());
                    bundleRouteZip(generatedZip, bundle, assets, generatedNames);
                    synchronized (exportLock) {
                        if (destroyed || bundleCanceled || exportPhase != ExportPhase.PREPARING) {
                            throw new IOException("Export canceled");
                        }
                        generatedZip.delete();
                        stagedFile = bundle;
                        stagedBytes = bundle.length();
                        exportPhase = ExportPhase.PICKING;
                    }
                    launchSavePicker();
                } catch (Exception e) {
                    if (bundle != null) bundle.delete();
                    synchronized (exportLock) { discardStagedLocked(); }
                    sendExportResult(false, bundleCanceled ? "Export canceled. Your project remains saved." :
                            "Could not prepare this destination bundle. Check free storage and the 2 GiB document limit; your project remains saved.");
                }
            });
            return true;
        }

        @JavascriptInterface public boolean exportAbort() {
            synchronized (exportLock) {
                if (exportPhase == ExportPhase.PREPARING) {
                    bundleCanceled = true;
                    return true;
                }
                // Once the save picker is open, its eventual result controls the export.
                if (exportPhase != ExportPhase.STAGING) return false;
                discardStagedLocked();
            }
            sendExportResult(false, "Export canceled. Your project remains saved.");
            return true;
        }
    }

    private void launchSavePicker() {
        runOnUiThread(() -> {
            final String name;
            final String mime;
            synchronized (exportLock) {
                if (destroyed || exportPhase != ExportPhase.PICKING) return;
                name = exportName;
                mime = exportMime;
            }
            Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            save.addCategory(Intent.CATEGORY_OPENABLE);
            save.setType(mime);
            save.putExtra(Intent.EXTRA_TITLE, name);
            save.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            try { startActivityForResult(save, CREATE_DOCUMENT); }
            catch (ActivityNotFoundException e) {
                synchronized (exportLock) { discardStagedLocked(); }
                sendExportResult(false, "No save-document picker is available. Your project remains saved.");
            }
        });
    }

    /** Exact app-generated entry list; imported cargo never chooses destination paths. */
    private static Set<String> generatedRouteNames(JSONObject metadata) throws Exception {
        JSONArray names = metadata.getJSONArray("generatedNames");
        if (names.length() == 0 || names.length() > MAX_GENERATED_ROUTE_MEMBERS) {
            throw new IOException("Invalid generated entry count");
        }
        Set<String> allowed = new HashSet<>();
        for (int i = 0; i < names.length(); i++) {
            String name = names.getString(i);
            if (!name.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,159}\\.(zip|pdf|json|txt|py)") ||
                    name.contains("..") || !allowed.add(name)) {
                throw new IOException("Invalid generated entry name");
            }
        }
        return Collections.unmodifiableSet(allowed);
    }

    private void bundleRouteZip(File generated, File bundle, CarrierAsset[] assets,
            Set<String> allowed)
            throws IOException {
        Set<String> seen = new HashSet<>();
        long[] expanded = new long[] { 0 };
        try (ZipInputStream incoming = new ZipInputStream(new FileInputStream(generated));
                ZipOutputStream outgoing = new ZipOutputStream(new LimitedOutputStream(
                        new BufferedOutputStream(new FileOutputStream(bundle))))) {
            // Existing ZIP/PDF payloads are already compressed. Streaming stored deflate blocks
            // avoids expensive whole-runtime recompression and keeps heap usage bounded.
            outgoing.setLevel(Deflater.NO_COMPRESSION);
            ZipEntry entry;
            while ((entry = incoming.getNextEntry()) != null) {
                String name = entry.getName();
                if (entry.isDirectory() || !allowed.contains(name) || !seen.add(name) ||
                        entry.getSize() > MAX_EXPORT_BYTES) throw new IOException("Unexpected generated entry");
                outgoing.putNextEntry(new ZipEntry(name));
                streamBounded(incoming, outgoing, expanded, null);
                outgoing.closeEntry();
                incoming.closeEntry();
            }
            if (!seen.equals(allowed)) throw new IOException("Generated route files are incomplete");
            for (CarrierAsset asset : assets) {
                if (!seen.add(asset.name)) throw new IOException("Duplicate carrier entry");
                MessageDigest digest;
                try { digest = MessageDigest.getInstance("SHA-256"); }
                catch (NoSuchAlgorithmException e) { throw new IOException("Hashing unavailable", e); }
                outgoing.putNextEntry(new ZipEntry(asset.name));
                long before = expanded[0];
                try (InputStream input = getAssets().open(asset.path)) {
                    streamBounded(input, outgoing, expanded, digest);
                }
                outgoing.closeEntry();
                if (expanded[0] - before != asset.size || !asset.sha256.equals(hex(digest.digest()))) {
                    throw new IOException("Carrier verification failed");
                }
            }
        }
    }

    private void streamBounded(InputStream input, OutputStream output, long[] expanded,
            MessageDigest digest) throws IOException {
        byte[] buffer = new byte[64 * 1024];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (destroyed || bundleCanceled) throw new IOException("Export canceled");
            expanded[0] += count;
            if (expanded[0] > MAX_EXPORT_BYTES) throw new IOException("Route exceeds export size limit");
            if (digest != null) digest.update(buffer, 0, count);
            output.write(buffer, 0, count);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            int unsigned = value & 255;
            text.append("0123456789abcdef".charAt(unsigned >>> 4));
            text.append("0123456789abcdef".charAt(unsigned & 15));
        }
        return text.toString();
    }

    private static final class LimitedOutputStream extends FilterOutputStream {
        private long written;
        LimitedOutputStream(OutputStream output) { super(output); }
        @Override public void write(int value) throws IOException {
            if (++written > MAX_EXPORT_BYTES) throw new IOException("Export size limit exceeded");
            out.write(value);
        }
        @Override public void write(byte[] bytes, int offset, int length) throws IOException {
            if (written + length > MAX_EXPORT_BYTES) throw new IOException("Export size limit exceeded");
            written += length;
            out.write(bytes, offset, length);
        }
    }

    private static final class CarrierAsset {
        final String name;
        final String path;
        final long size;
        final String sha256;
        CarrierAsset(String destination, String name, long size, String sha256) {
            this.name = name;
            this.path = "build-carriers/" + destination + "/" + name;
            this.size = size;
            this.sha256 = sha256;
        }
    }

    private static CarrierAsset[] carrierAssets(String destination) {
        // Public edition loads the person's verified runtime outside the project.
        // Its complete generated ZIP uses the existing streamed native save path.
        return null;
    }

    private static String supportedExportMime(String mime) {
        String type = mime == null ? "application/zip" : mime.split(";", 2)[0].trim().toLowerCase(java.util.Locale.ROOT);
        if ("application/zip".equals(type) || "application/pdf".equals(type) ||
                "text/plain".equals(type) || "application/json".equals(type) ||
                "application/octet-stream".equals(type) ||
                "application/vnd.android.package-archive".equals(type)) return type;
        return null;
    }

    private static String safeExportName(String filename, String mime) {
        String extension = "application/pdf".equals(mime) ? ".pdf" :
                "text/plain".equals(mime) ? ".txt" : "application/json".equals(mime) ? ".json" :
                "application/octet-stream".equals(mime) ? ".bin" :
                "application/vnd.android.package-archive".equals(mime) ? ".apk" : ".zip";
        String name = filename == null ? "Workbench_Continuity_Export" + extension : filename;
        name = name.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1);
        name = name.replaceAll("[^A-Za-z0-9._-]", "_");
        while (name.startsWith(".")) name = name.substring(1);
        while (name.endsWith(".")) name = name.substring(0, name.length() - 1);
        if (name.length() == 0) name = "Workbench_Continuity_Export" + extension;
        if (name.length() > 160) name = name.substring(0, 160);
        if (name.toUpperCase(java.util.Locale.ROOT).matches("(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\\..*)?")) name = "_" + name;
        // Source files and carried build outputs keep their original extensions.
        if (!"text/plain".equals(mime) && !"application/octet-stream".equals(mime) &&
                !name.toLowerCase(java.util.Locale.ROOT).endsWith(extension)) name += extension;
        return name;
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == LOCAL_SIGNING) {
            signingPending = false;
            String receipt = resultCode == RESULT_OK && data != null ? data.getStringExtra("receipt_json") : null;
            sendSigningResult(receipt != null, receipt != null ? receipt : "Local signing closed. Your project remains saved.");
            return;
        }
        if (requestCode == OPEN_DOCUMENT) {
            ValueCallback<Uri[]> callback = chooserCallback;
            chooserCallback = null;
            chooserPending = false;
            if (callback != null) {
                Set<Uri> selected = new LinkedHashSet<>();
                if (resultCode == RESULT_OK && data != null) {
                    ClipData clips = data.getClipData();
                    if (clips != null) for (int i = 0; i < clips.getItemCount(); i++) {
                        Uri uri = clips.getItemAt(i).getUri();
                        if (uri != null) selected.add(uri);
                    }
                    if (data.getData() != null) selected.add(data.getData());
                }
                callback.onReceiveValue(selected.isEmpty() ? null : selected.toArray(new Uri[0]));
            }
            return;
        }
        if (requestCode != CREATE_DOCUMENT) return;
        final Uri destination = resultCode == RESULT_OK && data != null ? data.getData() : null;
        final File source;
        final String name;
        synchronized (exportLock) {
            if (exportPhase != ExportPhase.PICKING) return;
            if (destination == null) {
                discardStagedLocked();
                sendExportResult(false, "Export canceled. Your project remains saved.");
                return;
            }
            source = stagedFile;
            name = exportName;
            exportPhase = ExportPhase.COPYING;
        }
        fileWorker.execute(() -> {
            boolean ok = false;
            try {
                try (FileInputStream input = new FileInputStream(source);
                        OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new IOException("No destination stream");
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                    output.flush();
                }
                ok = true;
            } catch (IOException | SecurityException e) {
                // Errors are shown without logging document locations or project contents.
            } finally {
                synchronized (exportLock) { discardStagedLocked(); }
            }
            sendExportResult(ok, ok ? "Saved " + name + "." :
                    "Could not write the chosen document. Your project remains saved.");
        });
    }

    /** Caller must hold exportLock. Never touches app IndexedDB or project data. */
    private void discardStagedLocked() {
        if (stagedOutput != null) try { stagedOutput.close(); } catch (IOException ignored) { }
        stagedOutput = null;
        if (stagedFile != null) stagedFile.delete();
        stagedFile = null;
        stagedBytes = 0;
        exportName = null;
        exportMime = null;
        exportPhase = ExportPhase.IDLE;
    }

    private void sendExportResult(boolean ok, String message) {
        final String script = "if (typeof window.nativeExportResult === 'function') " +
                "window.nativeExportResult(" + (ok ? "true" : "false") + "," + JSONObject.quote(message) + ");";
        runOnUiThread(() -> {
            if (!destroyed && web != null) web.evaluateJavascript(script, null);
        });
    }

    private void sendSigningResult(boolean ok, String publicReceiptOrMessage) {
        final String script = "if (typeof window.nativeSigningResult === 'function') " +
                "window.nativeSigningResult(" + (ok ? "true" : "false") + "," + JSONObject.quote(publicReceiptOrMessage) + ");";
        runOnUiThread(() -> {
            if (!destroyed && web != null) web.evaluateJavascript(script, null);
        });
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        bundleCanceled = true;
        cancelChooser();
        synchronized (exportLock) {
            if (exportPhase != ExportPhase.COPYING) discardStagedLocked();
        }
        // A document already selected by the user may finish copying on its worker thread.
        fileWorker.shutdown();
        if (web != null) {
            web.removeJavascriptInterface("WorkbenchNative");
            web.stopLoading();
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
