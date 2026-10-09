package dev.wakka.continuity.signing;

import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** APK signing on owner selected local files. No build scripts, network or key export. */
public final class LocalApkSigner {
    private LocalApkSigner() {}

    public static String[] listAliases(File keystore, char[] storePassword) throws Exception {
        checkCancelled();
        return LocalKeyStore.aliases(keystore, storePassword);
    }

    public static ApkInfo inspect(File apk) throws Exception {
        checkCancelled();
        if (apk == null || !apk.isFile() || apk.length() == 0) throw new IOException("Select an APK file.");
        ApkManifest manifest = ApkManifest.read(apk);
        checkCancelled();
        ApkVerifier.Result verification = new ApkVerifier.Builder(apk).build().verify();
        checkCancelled();
        List<String> certificates = new ArrayList<String>();
        for (X509Certificate certificate : verification.getSignerCertificates())
            certificates.add(hex(MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded())));
        Collections.sort(certificates);
        List<String> errors = new ArrayList<String>();
        for (ApkVerifier.IssueWithParams error : verification.getAllErrors()) {
            if (errors.size() == 20) { errors.add("Additional signature verification errors omitted."); break; }
            errors.add(error.toString());
        }
        return new ApkInfo(manifest.packageName, manifest.versionName, manifest.splitName,
                manifest.versionCode, manifest.minSdkVersion, apk.length(), sha256(apk),
                verification.isVerified(), certificates,
                verification.isVerifiedUsingV1Scheme(), verification.isVerifiedUsingV2Scheme(),
                verification.isVerifiedUsingV3Scheme(), verification.isVerifiedUsingV31Scheme(), errors);
    }

    public static Result sign(File input, File output, File keystore, char[] storePassword,
            String alias, char[] keyPassword, File referenceApk) throws Exception {
        if (input == null || output == null || keystore == null) throw new IOException("Choose an APK, local keystore and output file.");
        String outputPath = output.getCanonicalPath();
        if (outputPath.equals(input.getCanonicalPath()) || outputPath.equals(keystore.getCanonicalPath())
                || (referenceApk != null && outputPath.equals(referenceApk.getCanonicalPath())))
            throw new IOException("The signed APK must be saved to a different file.");
        if (output.exists()) throw new IOException("The output file already exists; choose a new output file.");
        checkCancelled();
        ApkInfo inputInfo = inspect(input);
        if (!inputInfo.splitName.isEmpty()) throw new IOException("This is a split APK. Select a complete base APK; split-package installation is not supported here.");
        ApkInfo reference = referenceApk == null ? null : inspect(referenceApk);
        char[] storePass = storePassword == null ? null : storePassword.clone();
        char[] keyPass = keyPassword == null ? null : keyPassword.clone();
        LocalKeyStore.Identity identity = null;
        boolean success = false;
        try {
            identity = LocalKeyStore.load(keystore, storePass, alias, keyPass);
            checkCancelled();
            String expectedCertificate = hex(MessageDigest.getInstance("SHA-256").digest(identity.chain.get(0).getEncoded()));
            ApkSigner.SignerConfig signer = new ApkSigner.SignerConfig.Builder(
                    "CONTINUITY", identity.key, identity.chain).build();
            new ApkSigner.Builder(Collections.singletonList(signer))
                    .setInputApk(input)
                    .setOutputApk(output)
                    .setOtherSignersSignaturesPreserved(false)
                    .setAlignmentPreserved(true)
                    .setV1SigningEnabled(true)
                    .setV2SigningEnabled(true)
                    .setV3SigningEnabled(true)
                    .setV4SigningEnabled(false)
                    .setCreatedBy("Workbench Continuity local signing")
                    .build().sign();
            checkCancelled();
            ApkInfo signed = inspect(output);
            if (!signed.verified || signed.certificateSha256.size() != 1
                    || !expectedCertificate.equals(signed.certificateSha256.get(0)))
                throw new GeneralSecurityException("The signed APK did not pass verification with the selected owner certificate.");
            if (!inputInfo.packageName.equals(signed.packageName) || inputInfo.versionCode != signed.versionCode
                    || !inputInfo.splitName.equals(signed.splitName))
                throw new GeneralSecurityException("APK identity changed during signing; output was discarded.");
            Result result = new Result(inputInfo, signed, reference);
            success = true;
            return result;
        } finally {
            if (storePass != null) Arrays.fill(storePass, '\0');
            if (keyPass != null) Arrays.fill(keyPass, '\0');
            if (identity != null) identity.clear();
            if (!success && output.exists()) output.delete();
        }
    }

    static void checkCancelled() throws IOException {
        if (Thread.currentThread().isInterrupted()) throw new IOException("Local signing was cancelled.");
    }
    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[64 * 1024];
        try (FileInputStream in = new FileInputStream(file)) {
            int n;
            while ((n = in.read(buffer)) != -1) { checkCancelled(); digest.update(buffer, 0, n); }
        }
        return hex(digest.digest());
    }
    private static String hex(byte[] bytes) {
        final char[] alphabet = "0123456789abcdef".toCharArray();
        char[] result = new char[bytes.length * 2];
        for (int i = 0; i < bytes.length; i++) {
            result[2 * i] = alphabet[(bytes[i] & 255) >>> 4];
            result[2 * i + 1] = alphabet[bytes[i] & 15];
        }
        return new String(result);
    }

    public static final class ApkInfo {
        public final String packageName, versionName, splitName, sha256;
        public final long versionCode, size;
        public final int minSdkVersion;
        public final boolean verified, v1, v2, v3, v31;
        public final List<String> certificateSha256, verificationErrors;
        private ApkInfo(String packageName, String versionName, String splitName, long versionCode,
                int minSdkVersion, long size, String sha256, boolean verified,
                List<String> certificates, boolean v1, boolean v2, boolean v3, boolean v31,
                List<String> errors) {
            this.packageName = packageName;
            this.versionName = versionName;
            this.splitName = splitName;
            this.versionCode = versionCode;
            this.minSdkVersion = minSdkVersion;
            this.size = size;
            this.sha256 = sha256;
            this.verified = verified;
            this.certificateSha256 = Collections.unmodifiableList(new ArrayList<String>(certificates));
            this.verificationErrors = Collections.unmodifiableList(new ArrayList<String>(errors));
            this.v1 = v1; this.v2 = v2; this.v3 = v3; this.v31 = v31;
        }
        public String toJson() { return toJsonString(); }
        public String toJsonString() {
            return "{\"packageName\":" + quote(packageName) + ",\"versionName\":" + quote(versionName)
                    + ",\"versionCode\":" + versionCode + ",\"minSdkVersion\":" + minSdkVersion
                    + ",\"splitName\":" + quote(splitName) + ",\"size\":" + size
                    + ",\"sha256\":" + quote(sha256) + ",\"verified\":" + verified
                    + ",\"certificateSha256\":" + jsonList(certificateSha256)
                    + ",\"schemes\":{\"v1\":" + v1 + ",\"v2\":" + v2 + ",\"v3\":" + v3 + ",\"v31\":" + v31 + "}"
                    + ",\"verificationErrors\":" + jsonList(verificationErrors) + "}";
        }
    }

    public static final class Result {
        public final ApkInfo input, output, reference;
        public final boolean updateCompatible;
        public final String updateStatus;
        public final List<String> updateReasons;
        private Result(ApkInfo input, ApkInfo output, ApkInfo reference) {
            this.input = input; this.output = output; this.reference = reference;
            List<String> reasons = new ArrayList<String>();
            if (reference == null) reasons.add("No installed or reference APK was available. Update compatibility has not been established.");
            else {
                if (!reference.verified) reasons.add("The reference APK's signature did not verify.");
                if (!reference.splitName.isEmpty()) reasons.add("The reference is a split APK, not a complete single-APK installation.");
                if (!output.packageName.equals(reference.packageName)) reasons.add("Package name differs from the installed/reference APK.");
                if (reference.certificateSha256.isEmpty() || !output.certificateSha256.equals(reference.certificateSha256))
                    reasons.add("Signing certificate differs from the installed/reference APK. Use the original private signing key.");
                if (output.versionCode < reference.versionCode)
                    reasons.add("The returned build has a lower versionCode than the installed/reference APK. Android blocks this downgrade; ask the builder to preserve or increase the versionCode.");
            }
            updateCompatible = reference != null && reasons.isEmpty();
            updateStatus = reference == null ? "no-reference" : updateCompatible ? "compatible" : "incompatible";
            updateReasons = Collections.unmodifiableList(reasons);
        }
        public String toJson() { return toJsonString(); }
        public String toJsonString() {
            return "{\"format\":\"workbench-local-signing/1\",\"status\":\"signed-and-verified\",\"input\":"
                    + input.toJsonString() + ",\"output\":" + output.toJsonString()
                    + ",\"reference\":" + (reference == null ? "null" : reference.toJsonString())
                    + ",\"updateCompatible\":" + updateCompatible + ",\"updateStatus\":" + quote(updateStatus)
                    + ",\"updateReasons\":" + jsonList(updateReasons) + "}";
        }
    }
    private static String jsonList(List<String> list) {
        StringBuilder out = new StringBuilder("[");
        for (int i = 0; i < list.size(); i++) { if (i != 0) out.append(','); out.append(quote(list.get(i))); }
        return out.append(']').toString();
    }
    private static String quote(String text) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 32) { out.append("\\u"); String n = Integer.toHexString(c); for (int j = n.length(); j < 4; j++) out.append('0'); out.append(n); }
                    else out.append(c);
            }
        }
        return out.append('"').toString();
    }
}
