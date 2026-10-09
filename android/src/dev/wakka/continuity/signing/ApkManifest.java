package dev.wakka.continuity.signing;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Reads only the compiled manifest. APK code, assets and native libraries are never loaded. */
final class ApkManifest {
    static final int MAX_MANIFEST = 8 * 1024 * 1024;
    static final String ANDROID_NS = "http://schemas.android.com/apk/res/android";
    final String packageName, versionName, splitName;
    final long versionCode;
    final int minSdkVersion;

    private ApkManifest(String packageName, String versionName, String splitName,
            long versionCode, int minSdkVersion) {
        this.packageName = packageName;
        this.versionName = versionName;
        this.splitName = splitName;
        this.versionCode = versionCode;
        this.minSdkVersion = minSdkVersion;
    }

    static ApkManifest read(java.io.File apk) throws IOException {
        try (ZipFile zip = new ZipFile(apk)) {
            int matches = 0;
            java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
            Set<String> names = new HashSet<String>();
            while (entries.hasMoreElements()) {
                String name = entries.nextElement().getName();
                if (!names.add(name)) throw new IOException("APK has duplicate ZIP entries: " + name);
                if ("AndroidManifest.xml".equals(name)) matches++;
            }
            if (matches != 1) throw new IOException("Select a single APK with an Android manifest.");
            ZipEntry entry = zip.getEntry("AndroidManifest.xml");
            if (entry.getSize() > MAX_MANIFEST) throw new IOException("APK manifest is unusually large.");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[16384];
            try (InputStream in = zip.getInputStream(entry)) {
                int n;
                while ((n = in.read(buffer)) != -1) {
                    if (bytes.size() > MAX_MANIFEST - n) throw new IOException("APK manifest exceeds inspection limit.");
                    bytes.write(buffer, 0, n);
                }
            }
            return parse(bytes.toByteArray());
        }
    }

    static ApkManifest parse(byte[] data) throws IOException {
        Bounds b = new Bounds(data);
        if (b.u16(0) != 3) throw new IOException("APK manifest must be compiled Android binary XML.");
        int header = b.u16(2), documentSize = b.size(4);
        if (header < 8 || documentSize != data.length) throw new IOException("Malformed binary manifest header.");
        String[] strings = null;
        String pkg = null, versionName = "", split = "";
        long code = 0, major = 0;
        int minSdk = 1, depth = 0;
        ArrayList<String> openElements = new ArrayList<String>();
        boolean rootSeen = false, versionSeen = false, minSeen = false;
        for (int offset = header; offset < documentSize;) {
            b.check(offset, 8);
            int type = b.u16(offset), h = b.u16(offset + 2), size = b.size(offset + 4);
            if (h < 8 || size < h || size > documentSize - offset) throw new IOException("Malformed manifest chunk.");
            int end = offset + size;
            if (type == 1) {
                if (strings != null) throw new IOException("Duplicate manifest string pool.");
                strings = readStrings(b, offset, h, size);
            } else if (type == 0x102) {
                if (strings == null || h < 16) throw new IOException("Malformed manifest element.");
                int ext = offset + h;
                b.range(ext, 20, end);
                String tag = string(strings, b.i32(ext + 4));
                String elementNamespace = optionalString(strings, b.i32(ext));
                int start = b.u16(ext + 8), step = b.u16(ext + 10), count = b.u16(ext + 12);
                if (start < 20 || step < 20 || count > (end - ext - start) / step)
                    throw new IOException("Malformed manifest attributes.");
                boolean root = depth == 0;
                if (root) {
                    if (rootSeen || !"manifest".equals(tag)) throw new IOException("APK manifest has no unique manifest root.");
                    rootSeen = true;
                }
                Set<String> attributes = new HashSet<String>();
                for (int i = 0; i < count; i++) {
                    int a = ext + start + i * step;
                    b.range(a, 20, end);
                    String ns = optionalString(strings, b.i32(a));
                    String name = string(strings, b.i32(a + 4));
                    if (!attributes.add(ns + "\u0000" + name)) throw new IOException("Duplicate manifest attribute.");
                    if (b.u16(a + 12) != 8 || b.u8(a + 14) != 0) throw new IOException("Malformed manifest typed value.");
                    int valueType = b.u8(a + 15), value = b.i32(a + 16), raw = b.i32(a + 8);
                    if (root && ns.isEmpty() && "package".equals(name))
                        pkg = text(strings, raw, valueType, value);
                    else if (root && ns.isEmpty() && "split".equals(name))
                        split = text(strings, raw, valueType, value);
                    else if (root && ANDROID_NS.equals(ns) && "versionName".equals(name))
                        versionName = displayText(strings, raw, valueType, value);
                    else if (root && ANDROID_NS.equals(ns) && "versionCode".equals(name)) {
                        code = integer(strings, raw, valueType, value);
                        versionSeen = true;
                    } else if (root && ANDROID_NS.equals(ns) && "versionCodeMajor".equals(name)) {
                        major = integer(strings, raw, valueType, value);
                    } else if (depth == 1 && "uses-sdk".equals(tag) && ANDROID_NS.equals(ns)
                            && "minSdkVersion".equals(name)) {
                        if (minSeen) throw new IOException("Duplicate minSdkVersion declaration.");
                        long parsed = integer(strings, raw, valueType, value);
                        if (parsed > 10000 || parsed < 1) throw new IOException("Invalid minSdkVersion.");
                        minSdk = (int) parsed;
                        minSeen = true;
                    }
                }
                openElements.add(elementNamespace + "\u0000" + tag);
                depth++;
            } else if (type == 0x103) {
                if (h < 16 || depth == 0) throw new IOException("Malformed manifest end element.");
                int ext = offset + h;
                b.range(ext, 8, end);
                String closing = optionalString(strings, b.i32(ext)) + "\u0000"
                        + string(strings, b.i32(ext + 4));
                if (!closing.equals(openElements.remove(openElements.size() - 1)))
                    throw new IOException("Mismatched manifest start and end elements.");
                depth--;
            }
            offset = end;
        }
        if (!rootSeen || depth != 0 || pkg == null || !pkg.matches("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"))
            throw new IOException("Cannot establish the APK package identity.");
        if (!versionSeen) throw new IOException("APK has no versionCode; request a versioned build before signing an update.");
        if (major > 0x7fffffffL) throw new IOException("versionCodeMajor exceeds Android's signed long range.");
        return new ApkManifest(pkg, versionName, split, (major << 32) | code, minSdk);
    }

    private static long integer(String[] strings, int raw, int type, int value) throws IOException {
        if (type == 0x10 || type == 0x11) return value & 0xffffffffL;
        String text = text(strings, raw, type, value);
        try {
            long n = text.startsWith("0x") ? Long.parseLong(text.substring(2), 16) : Long.parseLong(text);
            if (n < 0 || n > 0xffffffffL) throw new NumberFormatException();
            return n;
        } catch (NumberFormatException e) {
            throw new IOException("Manifest identity requires an integer value; resource references or preview SDK names are not supported.");
        }
    }
    private static String text(String[] strings, int raw, int type, int value) throws IOException {
        if (type == 3) return string(strings, value);
        if (raw != -1) return string(strings, raw);
        throw new IOException("Manifest identity contains a resource reference instead of a direct value.");
    }
    private static String displayText(String[] strings, int raw, int type, int value) throws IOException {
        // versionName is a display label; it is not part of the update identity check.
        // A resource-backed label must not stop signing an otherwise valid APK.
        if (type == 1 || type == 2) return "@0x" + Integer.toHexString(value);
        if (type == 0) return "";
        if (type == 0x10 || type == 0x11) return Long.toString(value & 0xffffffffL);
        return text(strings, raw, type, value);
    }
    private static String optionalString(String[] strings, int index) throws IOException {
        return index == -1 ? "" : string(strings, index);
    }
    private static String string(String[] strings, int index) throws IOException {
        if (index < 0 || index >= strings.length) throw new IOException("Invalid manifest string index.");
        return strings[index];
    }
    private static String[] readStrings(Bounds b, int offset, int h, int size) throws IOException {
        if (h < 28) throw new IOException("Malformed manifest string pool.");
        int count = b.size(offset + 8), styleCount = b.size(offset + 12), flags = b.i32(offset + 16);
        int start = b.size(offset + 20), styleStart = b.size(offset + 24), end = offset + size;
        if (count > 100000 || styleCount > 100000 || (long) h + 4L * (count + styleCount) > size
                || start < h + 4L * (count + styleCount) || start > size)
            throw new IOException("Malformed manifest string offsets.");
        int stringEnd = styleStart == 0 ? end : offset + styleStart;
        if (stringEnd < offset + start || stringEnd > end) throw new IOException("Malformed manifest styles.");
        String[] strings = new String[count];
        boolean utf8 = (flags & 0x100) != 0;
        for (int i = 0; i < count; i++) {
            int relative = b.size(offset + h + i * 4);
            if (relative > stringEnd - offset - start) throw new IOException("Invalid manifest string offset.");
            int p = offset + start + relative;
            int[] first = length(b, p, stringEnd, utf8);
            p = first[1];
            if (utf8) {
                int[] second = length(b, p, stringEnd, true);
                p = second[1];
                b.range(p, second[0] + 1, stringEnd);
                if (b.u8(p + second[0]) != 0) throw new IOException("Unterminated UTF-8 manifest string.");
                strings[i] = new String(b.data, p, second[0], StandardCharsets.UTF_8);
            } else {
                if (first[0] > MAX_MANIFEST / 2) throw new IOException("Manifest string exceeds limit.");
                int bytes = first[0] * 2;
                b.range(p, bytes + 2, stringEnd);
                if (b.u16(p + bytes) != 0) throw new IOException("Unterminated UTF-16 manifest string.");
                strings[i] = new String(b.data, p, bytes, StandardCharsets.UTF_16LE);
            }
        }
        return strings;
    }
    private static int[] length(Bounds b, int p, int end, boolean utf8) throws IOException {
        b.range(p, utf8 ? 1 : 2, end);
        int a = utf8 ? b.u8(p) : b.u16(p), mask = utf8 ? 0x80 : 0x8000, shift = utf8 ? 8 : 16;
        p += utf8 ? 1 : 2;
        if ((a & mask) != 0) {
            b.range(p, utf8 ? 1 : 2, end);
            a = ((a & (mask - 1)) << shift) | (utf8 ? b.u8(p) : b.u16(p));
            p += utf8 ? 1 : 2;
        }
        return new int[] {a, p};
    }
    private static final class Bounds {
        final byte[] data;
        Bounds(byte[] data) { this.data = data; }
        void check(int p, int length) throws IOException { range(p, length, data.length); }
        void range(int p, int length, int end) throws IOException {
            if (p < 0 || length < 0 || p > end || length > end - p || end > data.length)
                throw new IOException("Truncated binary APK manifest.");
        }
        int u8(int p) throws IOException { check(p, 1); return data[p] & 255; }
        int u16(int p) throws IOException { check(p, 2); return u8(p) | (u8(p + 1) << 8); }
        int i32(int p) throws IOException { check(p, 4); return u16(p) | (u16(p + 2) << 16); }
        int size(int p) throws IOException { int n = i32(p); if (n < 0) throw new IOException("Manifest size overflows."); return n; }
    }
}
