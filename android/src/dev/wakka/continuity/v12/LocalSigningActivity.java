package dev.wakka.continuity.v12;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.TextUtils;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import dev.wakka.continuity.signing.LocalApkSigner;

import org.json.JSONObject;

import java.io.File;
import java.io.BufferedInputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Private native key entry. No key, URI or password ever crosses the WebView bridge. */
public final class LocalSigningActivity extends Activity {
    private static final int PICK_APK = 501, PICK_KEY = 502, PICK_REFERENCE = 503;
    private static final int SAVE_APK = 504, SAVE_RECEIPT = 505;
    private static final long MAX_APK_BYTES = 2L * 1024L * 1024L * 1024L;
    private static final long MAX_KEY_BYTES = 16L * 1024L * 1024L;
    private static final int BUFFER_BYTES = 64 * 1024;
    private static final String SESSION_PREFIX = "continuity-signing-";
    private static final Set<String> ACTIVE_SESSIONS = Collections.synchronizedSet(new HashSet<String>());

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final List<Button> actions = new ArrayList<>();
    private volatile boolean destroyed;
    private volatile boolean busy;
    private volatile boolean cancelRequested;
    private volatile Thread runningThread;
    private Future<?> task;
    private File session, inputApk, keyFile, referenceApk, signedApk;
    private LocalApkSigner.ApkInfo inputInfo;
    private String receipt, outputName;
    private boolean savedApk;
    private boolean pickerPending;
    private TextView status, apkLabel, keyLabel, referenceLabel;
    private EditText alias, storePassword, keyPassword;
    private Button signButton, saveButton, receiptButton, closeButton;

    /** A new process removes previous cache-only sessions; live workers retain ownership. */
    static void removeAbandonedSessions(Context context) {
        File[] files = context.getCacheDir().listFiles();
        if (files != null) for (File file : files) {
            if (file.isDirectory() && file.getName().startsWith(SESSION_PREFIX) &&
                    !ACTIVE_SESSIONS.contains(file.getAbsolutePath())) deleteTree(file);
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        removeAbandonedSessions(this);
        session = new File(getCacheDir(), SESSION_PREFIX + UUID.randomUUID().toString());
        if (!session.mkdir()) {
            android.widget.Toast.makeText(this, "Could not prepare private signing storage. Check free space and try again.", android.widget.Toast.LENGTH_LONG).show();
            finish(); return;
        }
        ACTIVE_SESSIONS.add(session.getAbsolutePath());
        getWindow().setStatusBarColor(0xff07111b);
        getWindow().setNavigationBarColor(0xff07111b);
        getWindow().setFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE,
                android.view.WindowManager.LayoutParams.FLAG_SECURE);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(0xff07111b);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(20), dp(24), dp(20), dp(32));
        scroll.addView(body);
        TextView title = label("Sign on this device", 26);
        title.setTextColor(0xff6de4ed);
        body.addView(title);
        body.addView(label("Bring back the APK. Your signing key stays on this device, outside your project and AI packets.", 16));
        body.addView(button("Choose returned APK or result ZIP", () -> pick(PICK_APK)));
        apkLabel = label("No returned APK selected", 14); body.addView(apkLabel);
        body.addView(button("Choose my signing key", () -> pick(PICK_KEY)));
        keyLabel = label("Choose the original JKS/PKCS12 key, or the private ZIP containing it.", 14); body.addView(keyLabel);
        storePassword = passwordField("Store password", body);
        alias = field("Signing alias", body, false);
        body.addView(button("Find aliases", this::findAliases));
        keyPassword = passwordField("Key password (leave empty to use store password)", body);
        body.addView(button("Choose reference APK (optional)", () -> pick(PICK_REFERENCE)));
        referenceLabel = label("If available, the installed app is checked automatically. A chosen reference APK replaces that check.", 14);
        body.addView(referenceLabel);
        body.addView(button("Use installed app instead", () -> {
            if (referenceApk != null) referenceApk.delete();
            referenceApk = null;
            invalidateSigned();
            referenceLabel.setText("The installed app will be checked if Android makes it available. Otherwise update compatibility remains unknown.");
        }));
        status = label("Choose the returned build and your private key, then sign.", 15); body.addView(status);
        signButton = button("Sign privately", this::sign); body.addView(signButton);
        saveButton = button("Save signed APK", () -> save(SAVE_APK)); body.addView(saveButton);
        receiptButton = button("Save signing receipt", () -> save(SAVE_RECEIPT)); body.addView(receiptButton);
        closeButton = new Button(this); closeButton.setText("Back to Workbench");
        closeButton.setOnClickListener(view -> {
            if (busy) cancelTask(); else finishWithReceipt();
        });
        body.addView(closeButton);
        setContentView(scroll);
        refresh();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView label(String text, int size) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size);
        view.setTextColor(0xffd5e2eb); view.setPadding(0, dp(7), 0, dp(9));
        return view;
    }
    private Button button(String text, Runnable action) {
        Button button = new Button(this); button.setText(text);
        button.setOnClickListener(view -> action.run()); actions.add(button); return button;
    }
    private EditText field(String hint, LinearLayout body, boolean password) {
        EditText field = new EditText(this); field.setHint(hint); field.setTextColor(Color.WHITE);
        field.setHintTextColor(0xff91a3b5); field.setSingleLine(true);
        field.setSaveEnabled(false); field.setFreezesText(false);
        if (android.os.Build.VERSION.SDK_INT >= 26) field.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        field.setInputType(password ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD :
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        body.addView(field); return field;
    }
    private EditText passwordField(String hint, LinearLayout body) { return field(hint, body, true); }
    private static char[] readSecret(EditText field) {
        char[] value = new char[field.length()];
        TextUtils.getChars(field.getText(), 0, value.length, value, 0); return value;
    }
    private void clearPasswords() {
        if (storePassword != null) storePassword.getText().clear();
        if (keyPassword != null) keyPassword.getText().clear();
    }
    private void refresh() {
        boolean ready = !busy && !pickerPending;
        for (Button button : actions) button.setEnabled(ready);
        storePassword.setEnabled(ready); keyPassword.setEnabled(ready); alias.setEnabled(ready);
        signButton.setEnabled(ready && inputApk != null && keyFile != null);
        saveButton.setEnabled(ready && signedApk != null && receipt != null);
        receiptButton.setEnabled(ready && savedApk && receipt != null);
        closeButton.setEnabled(!pickerPending);
        closeButton.setText(busy ? "Cancel current operation" : "Back to Workbench");
    }
    private void post(Runnable action) { runOnUiThread(() -> { if (!destroyed) action.run(); }); }
    private void work(String message, Runnable action) {
        if (busy || pickerPending || destroyed) return;
        busy = true; cancelRequested = false; status.setText(message); refresh();
        task = worker.submit(() -> {
            runningThread = Thread.currentThread();
            // Always enter the action's finally blocks, including password-array wiping,
            // even if cancellation happened while it was waiting for the worker.
            if (cancelRequested) runningThread.interrupt();
            try { action.run(); }
            finally {
                runningThread = null;
                if (destroyed) cleanup();
                post(() -> {
                    if (cancelRequested) status.setText("Operation canceled. Your project remains saved.");
                    busy = false; task = null; refresh();
                });
            }
        });
    }
    private static void checkCanceled() throws IOException {
        if (Thread.currentThread().isInterrupted()) throw new IOException("Canceled");
    }
    private void cancelTask() {
        cancelRequested = true;
        Thread active = runningThread; if (active != null) active.interrupt();
        clearPasswords();
        status.setText("Canceling. Waiting for the current signing step to finish safely…");
    }

    private void pick(int request) {
        if (busy || pickerPending) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { pickerPending = true; refresh(); startActivityForResult(intent, request); }
        catch (ActivityNotFoundException e) {
            pickerPending = false; refresh(); status.setText("No document picker is available.");
        }
    }
    private String documentName(Uri uri) {
        try (Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                String value = cursor.getString(0); if (value != null) return value;
            }
        } catch (RuntimeException ignored) { }
        return "selected file";
    }
    private void openChosen(Uri uri, int request) {
        final String selectedName = documentName(uri);
        work("Reading the selected file privately…", () -> {
            File incoming = new File(session, UUID.randomUUID().toString() + ".selected");
            try {
                boolean keyArchive = false;
                try (InputStream raw = getContentResolver().openInputStream(uri)) {
                    if (raw == null) throw new IOException("No input");
                    BufferedInputStream stream = new BufferedInputStream(raw, BUFFER_BYTES);
                    stream.mark(4);
                    int first = stream.read(), second = stream.read();
                    stream.reset();
                    keyArchive = request == PICK_KEY && first == 'P' && second == 'K';
                    copy(stream, incoming, request == PICK_KEY && !keyArchive ? MAX_KEY_BYTES : MAX_APK_BYTES, -1, -1);
                }
                if (request == PICK_KEY) {
                    checkCanceled();
                    if (keyArchive) chooseKeyFromArchive(incoming);
                    else acceptKey(incoming, selectedName);
                    return;
                }
                List<String> candidates = new ArrayList<>();
                try (ZipFile zip = new ZipFile(incoming)) {
                    if (zip.getEntry("AndroidManifest.xml") != null) {
                        acceptApk(incoming, request, selectedName); return;
                    }
                    java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
                    while (entries.hasMoreElements()) {
                        ZipEntry entry = entries.nextElement();
                        if (!entry.isDirectory() && entry.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".apk")) {
                            if (candidates.size() >= 200) throw new IOException("Too many APK choices");
                            candidates.add(entry.getName());
                        }
                    }
                }
                if (candidates.isEmpty()) throw new IOException("No APK");
                if (candidates.size() == 1) { extractApk(incoming, candidates.get(0), request); return; }
                post(() -> new AlertDialog.Builder(this).setTitle("Choose the APK in this result ZIP")
                        .setItems(candidates.toArray(new String[0]), (dialog, which) ->
                                work("Extracting the chosen APK…", () -> {
                                    try { extractApk(incoming, candidates.get(which), request); }
                                    catch (Exception e) { incoming.delete(); showReadError(request); }
                                }))
                        .setOnCancelListener(dialog -> incoming.delete()).show());
            } catch (Exception e) { incoming.delete(); showReadError(request); }
        });
    }
    private void showReadError(int request) {
        final boolean canceled = Thread.currentThread().isInterrupted();
        post(() -> status.setText(canceled ? "Operation canceled." :
                request == PICK_KEY ? "Could not read a private key. Choose JKS/PKCS12, or a ZIP containing .keystore, .jks, .p12 or .pfx, and check free storage." :
                "Could not read an APK from this file. Choose an APK or result ZIP and check free storage."));
    }
    private void acceptKey(File file, String displayName) {
        post(() -> {
            if (keyFile != null) keyFile.delete(); keyFile = file;
            keyLabel.setText("Private key selected: " + displayName);
            clearPasswords(); alias.getText().clear(); invalidateSigned();
            status.setText("Enter your store password and find the signing alias.");
        });
    }
    private void chooseKeyFromArchive(File archive) throws Exception {
        List<String> choices = new ArrayList<>();
        try (ZipFile zip = new ZipFile(archive)) {
            java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String name = entry.getName().toLowerCase(java.util.Locale.ROOT);
                if (!entry.isDirectory() && name.matches(".*\\.(keystore|jks|p12|pfx)")) {
                    if (choices.size() >= 200 || entry.getSize() > MAX_KEY_BYTES) throw new IOException("Invalid key archive");
                    choices.add(entry.getName());
                }
            }
        }
        if (choices.isEmpty()) throw new IOException("No local signing key in ZIP");
        if (choices.size() == 1) { extractKey(archive, choices.get(0)); return; }
        post(() -> new AlertDialog.Builder(this).setTitle("Choose your private key from this ZIP")
                .setItems(choices.toArray(new String[0]), (dialog, which) -> work("Reading the chosen key privately…", () -> {
                    try { extractKey(archive, choices.get(which)); }
                    catch (Exception e) { archive.delete(); showReadError(PICK_KEY); }
                }))
                .setOnCancelListener(dialog -> archive.delete()).show());
    }
    private void extractKey(File archive, String name) throws Exception {
        File extracted = new File(session, UUID.randomUUID().toString() + ".private-key");
        try {
            try (ZipFile zip = new ZipFile(archive)) {
                ZipEntry entry = zip.getEntry(name);
                if (entry == null || entry.isDirectory() || entry.getSize() > MAX_KEY_BYTES) throw new IOException("Invalid key entry");
                try (InputStream input = zip.getInputStream(entry)) {
                    copy(input, extracted, MAX_KEY_BYTES, entry.getSize(), entry.getCrc());
                }
            }
            checkCanceled(); acceptKey(extracted, name);
        } catch (Exception e) { extracted.delete(); throw e; }
        finally { archive.delete(); }
    }
    private void extractApk(File archive, String name, int request) throws Exception {
        File extracted = new File(session, UUID.randomUUID().toString() + ".apk");
        try {
            try (ZipFile zip = new ZipFile(archive)) {
                ZipEntry entry = zip.getEntry(name);
                if (entry == null || entry.isDirectory() || entry.getSize() > MAX_APK_BYTES) throw new IOException("Invalid APK entry");
                try (InputStream input = zip.getInputStream(entry)) {
                    copy(input, extracted, MAX_APK_BYTES, entry.getSize(), entry.getCrc());
                }
            }
            checkCanceled(); acceptApk(extracted, request, name);
        } catch (Exception e) { extracted.delete(); throw e; }
        finally { archive.delete(); }
    }
    private void acceptApk(File apk, int request, String displayName) throws Exception {
        LocalApkSigner.ApkInfo info = LocalApkSigner.inspect(apk); checkCanceled();
        if (request == PICK_REFERENCE && !info.verified) throw new IOException("Reference APK signature not verified");
        post(() -> {
            invalidateSigned();
            if (request == PICK_REFERENCE) {
                if (referenceApk != null) referenceApk.delete(); referenceApk = apk;
                referenceLabel.setText("Reference: " + info.packageName + " · version code " + info.versionCode);
            } else {
                if (inputApk != null) inputApk.delete(); inputApk = apk; inputInfo = info;
                apkLabel.setText(info.packageName + " · version code " + info.versionCode + "\n" + displayName);
            }
            status.setText("APK selected. Sign with your original local key."); refresh();
        });
    }
    private static void copy(InputStream input, File output, long limit, long expectedSize, long expectedCrc) throws IOException {
        boolean complete = false; long total = 0; CRC32 crc = new CRC32();
        try (OutputStream stream = new FileOutputStream(output)) {
            byte[] buffer = new byte[BUFFER_BYTES]; int count;
            while ((count = input.read(buffer)) != -1) {
                checkCanceled(); total += count;
                if (total > limit) throw new IOException("File exceeds local size limit");
                crc.update(buffer, 0, count); stream.write(buffer, 0, count);
            }
            checkCanceled();
            if (total == 0 || expectedSize >= 0 && total != expectedSize || expectedCrc >= 0 && crc.getValue() != expectedCrc)
                throw new IOException("Incomplete or corrupt file");
            stream.flush(); complete = true;
        } finally { if (!complete) output.delete(); }
    }

    private void findAliases() {
        if (keyFile == null) { status.setText("Choose your signing key first."); return; }
        final char[] password = readSecret(storePassword);
        work("Reading signing aliases locally…", () -> {
            try {
                final String[] names = LocalApkSigner.listAliases(keyFile, password); checkCanceled();
                post(() -> {
                    if (names.length == 1) { alias.setText(names[0]); status.setText("Signing alias found."); }
                    else if (names.length > 1) new AlertDialog.Builder(this).setTitle("Choose your signing alias")
                            .setItems(names, (dialog, which) -> alias.setText(names[which])).show();
                    else status.setText("This file contains no usable signing alias.");
                });
            } catch (Exception e) { post(() -> status.setText("Could not read aliases. Check the key file and store password.")); }
            finally { Arrays.fill(password, '\0'); }
        });
    }
    private void invalidateSigned() {
        if (signedApk != null) signedApk.delete(); signedApk = null;
        receipt = null; outputName = null; savedApk = false; refresh();
    }
    private void sign() {
        if (inputApk == null || inputInfo == null || keyFile == null) return;
        final String chosenAlias = alias.getText().toString().trim();
        if (chosenAlias.isEmpty()) { status.setText("Find or enter the signing alias first."); return; }
        final char[] store = readSecret(storePassword);
        char[] suppliedKey = readSecret(keyPassword);
        final char[] key = suppliedKey.length == 0 ? store.clone() : suppliedKey;
        clearPasswords(); invalidateSigned();
        final File chosenInput = inputApk, chosenKey = keyFile, chosenReference = referenceApk;
        final String packageName = inputInfo.packageName;
        work("Signing privately and verifying the result…", () -> {
            File automaticReference = null;
            File output = new File(session, "signed-update.apk");
            try {
                File baseline = chosenReference; String source = baseline != null ? "chosen APK" : "none";
                if (baseline == null) {
                    try {
                        ApplicationInfo installed = getPackageManager().getApplicationInfo(packageName, 0);
                        automaticReference = new File(session, "installed-reference.apk");
                        try (InputStream stream = new FileInputStream(installed.sourceDir)) {
                            copy(stream, automaticReference, MAX_APK_BYTES, -1, -1);
                        }
                        baseline = automaticReference; source = "installed package";
                    } catch (android.content.pm.PackageManager.NameNotFoundException | SecurityException | IOException e) {
                        // An automatic lookup is optional. A hidden or unreadable baseline
                        // cannot establish update compatibility, but must not prevent signing.
                        checkCanceled();
                        if (automaticReference != null) automaticReference.delete();
                    }
                }
                checkCanceled();
                LocalApkSigner.Result result = LocalApkSigner.sign(chosenInput, output, chosenKey, store, chosenAlias, key, baseline);
                checkCanceled();
                JSONObject report = new JSONObject(result.toJsonString());
                report.put("installObserved", false); report.put("savedOnDevice", false);
                report.put("autoReferenceSource", source);
                final String reportText = report.toString(2);
                final String name = result.output.packageName.replaceAll("[^A-Za-z0-9._-]", "_") + "_signed-update.apk";
                final String compatibility = result.updateCompatible ?
                        "Signer and package match the reference, with the same or a higher version code. Ready to save as an update." :
                        "The APK signature is verified. Update status: " + result.updateStatus + ". " + TextUtils.join(" ", result.updateReasons);
                post(() -> { signedApk = output; outputName = name; receipt = reportText;
                    status.setText(compatibility + " Installation has not been tested."); refresh(); });
            } catch (Exception e) {
                output.delete();
                post(() -> status.setText("Could not finish signing. Check the key, alias and passwords, APK format, and free storage. Your project remains saved."));
            } finally {
                Arrays.fill(store, '\0'); Arrays.fill(key, '\0');
                chosenKey.delete();
                if (automaticReference != null) automaticReference.delete();
                post(() -> { keyFile = null; keyLabel.setText("Private key cleared. Choose it again for another signing run."); clearPasswords(); });
            }
        });
    }

    private void save(int request) {
        if (busy || pickerPending || signedApk == null || receipt == null) return;
        Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT); save.addCategory(Intent.CATEGORY_OPENABLE);
        save.setType(request == SAVE_APK ? "application/vnd.android.package-archive" : "application/json");
        save.putExtra(Intent.EXTRA_TITLE, request == SAVE_APK ? outputName : outputName.replace(".apk", "_signing-receipt.json"));
        save.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try { pickerPending = true; refresh(); startActivityForResult(save, request); }
        catch (ActivityNotFoundException e) { pickerPending = false; refresh(); status.setText("No save-document picker is available."); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data); pickerPending = false; refresh();
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        if (uri == null) { status.setText("Selection canceled. Your project remains saved."); return; }
        if (request == PICK_APK || request == PICK_KEY || request == PICK_REFERENCE) { openChosen(uri, request); return; }
        if (request != SAVE_APK && request != SAVE_RECEIPT) return;
        work("Saving your selected document…", () -> {
            try {
                try (OutputStream output = getContentResolver().openOutputStream(uri, "w")) {
                    if (output == null) throw new IOException("No destination");
                    if (request == SAVE_APK) {
                        try (InputStream input = new FileInputStream(signedApk)) {
                            byte[] buffer = new byte[BUFFER_BYTES]; int count;
                            while ((count = input.read(buffer)) != -1) { checkCanceled(); output.write(buffer, 0, count); }
                        }
                    } else output.write(receipt.getBytes(StandardCharsets.UTF_8));
                    checkCanceled(); output.flush();
                }
                // Report saved only after the provider's stream closes successfully.
                if (request == SAVE_APK) {
                    JSONObject report = new JSONObject(receipt); report.put("savedOnDevice", true);
                    final String savedReceipt = report.toString(2);
                    post(() -> { savedApk = true; receipt = savedReceipt;
                        status.setText("Signed APK saved. Open that file to install it. You can also save its signing receipt."); refresh(); });
                } else post(() -> status.setText("Signing receipt saved. It contains build identity and verification only."));
            } catch (Exception e) {
                // This is the newly created destination, never the original source or key.
                try { android.provider.DocumentsContract.deleteDocument(getContentResolver(), uri); }
                catch (Exception ignored) { }
                post(() -> status.setText("Could not save the document. Check free storage and choose a destination again."));
            }
        });
    }
    private void finishWithReceipt() {
        clearPasswords();
        if (savedApk && receipt != null) setResult(RESULT_OK, new Intent().putExtra("receipt_json", receipt));
        finish();
    }
    @Override public void onBackPressed() { if (busy) cancelTask(); else finishWithReceipt(); }
    @Override protected void onDestroy() {
        destroyed = true; clearPasswords();
        cancelRequested = true;
        Thread active = runningThread; if (active != null) active.interrupt();
        worker.shutdown();
        // apksig may finish a bounded signing step before observing interruption. Its worker
        // owns the temporary files until then, so no open key file is deleted under it.
        if (runningThread == null) cleanup();
        super.onDestroy();
    }
    private void cleanup() {
        if (session != null) { deleteTree(session); ACTIVE_SESSIONS.remove(session.getAbsolutePath()); }
    }
    private static void deleteTree(File file) {
        if (file.isDirectory()) { File[] children = file.listFiles(); if (children != null) for (File child : children) deleteTree(child); }
        file.delete();
    }
}
