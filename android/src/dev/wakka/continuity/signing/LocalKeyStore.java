package dev.wakka.continuity.signing;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.Key;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Owner selected PKCS12/JKS reader. It never writes or exports private key material. */
final class LocalKeyStore {
    static final int MAX_KEYSTORE = 16 * 1024 * 1024;
    private static final int JKS_MAGIC = 0xfeedfeed;
    private static final byte[] JKS_OID = {0x2b, 0x06, 0x01, 0x04, 0x01, 0x2a, 0x02, 0x11, 0x01, 0x01};
    private LocalKeyStore() {}

    static String[] aliases(File file, char[] password) throws Exception {
        checkFile(file);
        if (isJks(file)) {
            Jks store = Jks.read(file, password);
            try { return store.entries.keySet().toArray(new String[store.entries.size()]); }
            finally { store.clear(); }
        }
        KeyStore store = pkcs12(file, password);
        List<String> aliases = new ArrayList<String>();
        Enumeration<String> names = store.aliases();
        while (names.hasMoreElements()) {
            String alias = names.nextElement();
            if (store.isKeyEntry(alias)) aliases.add(alias);
        }
        Collections.sort(aliases);
        return aliases.toArray(new String[aliases.size()]);
    }

    static Identity load(File file, char[] storePassword, String alias, char[] keyPassword) throws Exception {
        checkFile(file);
        if (alias == null || alias.isEmpty()) throw new GeneralSecurityException("Choose a private-key alias.");
        if (isJks(file)) {
            Jks store = Jks.read(file, storePassword);
            try {
                JksEntry entry = store.entries.get(alias);
                if (entry == null) throw new GeneralSecurityException("That alias is not a private-key entry in this keystore.");
                byte[] pkcs8 = decryptJks(entry.encrypted, keyPassword);
                try {
                    PrivateKey key = null;
                    PKCS8EncodedKeySpec specification = new PKCS8EncodedKeySpec(pkcs8);
                    for (String algorithm : new String[] {"RSA", "EC", "DSA"}) {
                        try { key = KeyFactory.getInstance(algorithm).generatePrivate(specification); break; }
                        catch (GeneralSecurityException ignored) { }
                    }
                    if (key == null) throw new GeneralSecurityException("The JKS private-key algorithm is not supported (RSA, EC and DSA are supported).");
                    return new Identity(key, entry.chain);
                } finally { Arrays.fill(pkcs8, (byte) 0); }
            } finally { store.clear(); }
        }
        KeyStore store = pkcs12(file, storePassword);
        if (!store.isKeyEntry(alias)) throw new GeneralSecurityException("That alias is not a private-key entry in this keystore.");
        Key key;
        try { key = store.getKey(alias, keyPassword); }
        catch (GeneralSecurityException e) { throw new GeneralSecurityException("The private-key password is incorrect or this PKCS12 encryption is unsupported.", e); }
        if (!(key instanceof PrivateKey)) throw new GeneralSecurityException("This alias does not contain a private signing key.");
        Certificate[] chain = store.getCertificateChain(alias);
        if (chain == null || chain.length == 0) throw new GeneralSecurityException("The signing key has no certificate chain.");
        List<X509Certificate> certs = new ArrayList<X509Certificate>();
        for (Certificate certificate : chain) {
            if (!(certificate instanceof X509Certificate)) throw new GeneralSecurityException("APK signing requires X.509 certificates.");
            certs.add((X509Certificate) certificate);
        }
        return new Identity((PrivateKey) key, certs);
    }

    private static void checkFile(File file) throws IOException {
        if (file == null || !file.isFile() || file.length() < 4 || file.length() > MAX_KEYSTORE)
            throw new IOException("Select a PKCS12 or JKS keystore of at most 16 MiB.");
    }
    private static boolean isJks(File file) throws IOException {
        try (DataInputStream in = new DataInputStream(new FileInputStream(file))) { return in.readInt() == JKS_MAGIC; }
    }
    private static KeyStore pkcs12(File file, char[] password) throws Exception {
        KeyStore store = KeyStore.getInstance("PKCS12");
        try (FileInputStream in = new FileInputStream(file)) {
            try { store.load(in, requirePassword(password)); }
            catch (Exception e) { throw new GeneralSecurityException("Keystore password is incorrect, or this is not a supported PKCS12/JKS keystore.", e); }
        }
        return store;
    }
    private static char[] requirePassword(char[] password) throws GeneralSecurityException {
        if (password == null) throw new GeneralSecurityException("Enter the keystore password (an empty password is allowed).");
        return password;
    }
    private static byte[] passwordBytes(char[] password) throws GeneralSecurityException {
        requirePassword(password);
        byte[] bytes = new byte[password.length * 2];
        for (int i = 0; i < password.length; i++) {
            bytes[i * 2] = (byte) (password[i] >>> 8);
            bytes[i * 2 + 1] = (byte) password[i];
        }
        return bytes;
    }

    /** Implements the documented legacy Sun JKS password protection, without Sun-only classes. */
    private static byte[] decryptJks(byte[] encrypted, char[] password) throws Exception {
        byte[] protectedKey = derProtectedKey(encrypted);
        byte[] pass = passwordBytes(password), clear = null, previous = null, checksum = null;
        boolean success = false;
        try {
            if (protectedKey.length <= 40) throw new GeneralSecurityException("Malformed encrypted JKS private key.");
            clear = new byte[protectedKey.length - 40];
            previous = Arrays.copyOfRange(protectedKey, 0, 20);
            MessageDigest digest = MessageDigest.getInstance("SHA-1");
            for (int pos = 0; pos < clear.length;) {
                LocalApkSigner.checkCancelled();
                digest.update(pass);
                digest.update(previous);
                byte[] block = digest.digest();
                Arrays.fill(previous, (byte) 0);
                previous = block;
                int n = Math.min(block.length, clear.length - pos);
                for (int i = 0; i < n; i++) clear[pos + i] = (byte) (protectedKey[20 + pos + i] ^ block[i]);
                pos += n;
            }
            digest.update(pass);
            digest.update(clear);
            checksum = digest.digest();
            byte[] supplied = Arrays.copyOfRange(protectedKey, protectedKey.length - 20, protectedKey.length);
            try {
                if (!MessageDigest.isEqual(checksum, supplied)) throw new GeneralSecurityException("The private-key password is incorrect.");
            } finally { Arrays.fill(supplied, (byte) 0); }
            success = true;
            return clear;
        } finally {
            Arrays.fill(protectedKey, (byte) 0);
            Arrays.fill(pass, (byte) 0);
            if (previous != null) Arrays.fill(previous, (byte) 0);
            if (checksum != null) Arrays.fill(checksum, (byte) 0);
            if (!success && clear != null) Arrays.fill(clear, (byte) 0);
        }
    }

    private static byte[] derProtectedKey(byte[] encoded) throws Exception {
        Der outer = new Der(encoded, 0, encoded.length);
        Der sequence = outer.element(0x30);
        if (!outer.done()) throw new GeneralSecurityException("Trailing encrypted-key data.");
        Der algorithm = sequence.element(0x30);
        Der oid = algorithm.element(0x06);
        if (!Arrays.equals(oid.copy(), JKS_OID)) throw new GeneralSecurityException("Only legacy JKS private-key protection is supported.");
        if (!algorithm.done()) {
            Der parameter = algorithm.element(0x05);
            if (!parameter.done() || !algorithm.done()) throw new GeneralSecurityException("Malformed JKS protection parameters.");
        }
        Der key = sequence.element(0x04);
        if (!sequence.done()) throw new GeneralSecurityException("Trailing encrypted-key fields.");
        return key.copy();
    }

    static final class Identity {
        PrivateKey key;
        final List<X509Certificate> chain;
        Identity(PrivateKey key, List<X509Certificate> chain) throws GeneralSecurityException {
            if (chain == null || chain.isEmpty()) throw new GeneralSecurityException("The signing key has no certificate chain.");
            this.key = key;
            this.chain = new ArrayList<X509Certificate>(chain);
        }
        void clear() {
            // Password and encoded-key buffers are wiped above. Provider key objects can be
            // destroyed where supported; providers otherwise release them with this session.
            if (key instanceof javax.security.auth.Destroyable) {
                try { ((javax.security.auth.Destroyable) key).destroy(); } catch (Exception ignored) { }
            }
            key = null;
            chain.clear();
        }
    }
    private static final class JksEntry {
        final byte[] encrypted;
        final List<X509Certificate> chain;
        JksEntry(byte[] encrypted, List<X509Certificate> chain) { this.encrypted = encrypted; this.chain = chain; }
    }
    private static final class Jks {
        final Map<String, JksEntry> entries = new LinkedHashMap<String, JksEntry>();
        static Jks read(File file, char[] password) throws Exception {
            byte[] bytes = new byte[(int) file.length()], pass = passwordBytes(password);
            Jks result = new Jks();
            boolean success = false;
            try {
                try (DataInputStream input = new DataInputStream(new FileInputStream(file))) { input.readFully(bytes); }
                if (bytes.length < 32) throw new GeneralSecurityException("Truncated JKS keystore.");
                MessageDigest digest = MessageDigest.getInstance("SHA-1");
                digest.update(pass);
                digest.update("Mighty Aphrodite".getBytes(java.nio.charset.StandardCharsets.UTF_8));
                digest.update(bytes, 0, bytes.length - 20);
                byte[] calculated = digest.digest(), supplied = Arrays.copyOfRange(bytes, bytes.length - 20, bytes.length);
                try {
                    if (!MessageDigest.isEqual(calculated, supplied)) throw new GeneralSecurityException("Keystore password is incorrect or the JKS file is damaged.");
                } finally { Arrays.fill(calculated, (byte) 0); Arrays.fill(supplied, (byte) 0); }
                try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes, 0, bytes.length - 20))) {
                    if (in.readInt() != JKS_MAGIC) throw new GeneralSecurityException("Invalid JKS header.");
                    int version = in.readInt(), count = in.readInt();
                    if ((version != 1 && version != 2) || count < 0 || count > 10000) throw new GeneralSecurityException("Unsupported or malformed JKS header.");
                    Map<String, Boolean> aliases = new LinkedHashMap<String, Boolean>();
                    CertificateFactory certificates = CertificateFactory.getInstance("X.509");
                    for (int i = 0; i < count; i++) {
                        LocalApkSigner.checkCancelled();
                        int tag = in.readInt();
                        String alias = in.readUTF();
                        in.readLong();
                        if (aliases.put(alias, Boolean.TRUE) != null) throw new GeneralSecurityException("Duplicate JKS alias.");
                        if (tag == 1) {
                            byte[] protectedKey = block(in);
                            List<X509Certificate> chain = new ArrayList<X509Certificate>();
                            try {
                                int n = in.readInt();
                                if (n < 1 || n > 100) throw new GeneralSecurityException("Invalid JKS certificate chain.");
                                for (int j = 0; j < n; j++) chain.add(certificate(in, certificates, version));
                                result.entries.put(alias, new JksEntry(protectedKey, chain));
                            } catch (Exception e) { Arrays.fill(protectedKey, (byte) 0); throw e; }
                        } else if (tag == 2) certificate(in, certificates, version);
                        else throw new GeneralSecurityException("Unsupported JKS entry type.");
                    }
                    if (in.available() != 0) throw new GeneralSecurityException("Trailing JKS data.");
                }
                success = true;
                return result;
            } finally {
                Arrays.fill(bytes, (byte) 0);
                Arrays.fill(pass, (byte) 0);
                if (!success) result.clear();
            }
        }
        void clear() { for (JksEntry entry : entries.values()) Arrays.fill(entry.encrypted, (byte) 0); entries.clear(); }
        private static byte[] block(DataInputStream in) throws IOException {
            int n = in.readInt();
            if (n < 1 || n > in.available()) throw new IOException("Truncated JKS entry.");
            byte[] bytes = new byte[n];
            in.readFully(bytes);
            return bytes;
        }
        private static X509Certificate certificate(DataInputStream in, CertificateFactory factory, int version) throws Exception {
            String type = version == 1 ? "X.509" : in.readUTF();
            if (!"X.509".equalsIgnoreCase(type) && !"X509".equalsIgnoreCase(type)) throw new GeneralSecurityException("JKS certificate type is not X.509.");
            byte[] encoded = block(in);
            try { return (X509Certificate) factory.generateCertificate(new ByteArrayInputStream(encoded)); }
            finally { Arrays.fill(encoded, (byte) 0); }
        }
    }
    private static final class Der {
        final byte[] bytes;
        int position;
        final int end;
        Der(byte[] bytes, int position, int end) { this.bytes = bytes; this.position = position; this.end = end; }
        boolean done() { return position == end; }
        byte[] copy() { return Arrays.copyOfRange(bytes, position, end); }
        Der element(int tag) throws GeneralSecurityException {
            if (position >= end || (bytes[position++] & 255) != tag || position >= end) throw new GeneralSecurityException("Malformed encrypted-key DER.");
            int length = bytes[position++] & 255;
            if ((length & 128) != 0) {
                int n = length & 127;
                if (n == 0 || n > 4 || n > end - position) throw new GeneralSecurityException("Invalid encrypted-key DER length.");
                long value = 0;
                for (int i = 0; i < n; i++) value = (value << 8) | (bytes[position++] & 255);
                if (value > Integer.MAX_VALUE) throw new GeneralSecurityException("Encrypted-key DER exceeds limit.");
                length = (int) value;
            }
            if (length < 0 || length > end - position) throw new GeneralSecurityException("Truncated encrypted-key DER.");
            Der value = new Der(bytes, position, position + length);
            position += length;
            return value;
        }
    }
}
