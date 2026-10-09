import dev.wakka.continuity.signing.LocalApkSigner;
import java.io.File;
import java.util.Arrays;

/** Host-only QA bridge. Passwords are environment inputs, never command arguments or output. */
public final class SigningHarness {
    public static void main(String[] args) {
        char[] store = System.getenv("QA_STORE_PASSWORD").toCharArray();
        char[] key = System.getenv("QA_KEY_PASSWORD").toCharArray();
        try {
            if ("aliases".equals(args[0])) {
                String[] aliases = LocalApkSigner.listAliases(new File(args[1]), store);
                Arrays.sort(aliases);
                StringBuilder json = new StringBuilder("{\"aliases\":[");
                for (int i = 0; i < aliases.length; i++) {
                    if (i > 0) json.append(',');
                    json.append('"').append(aliases[i].replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
                }
                System.out.println(json.append("]}").toString());
            } else {
                File reference = "-".equals(args[5]) ? null : new File(args[5]);
                LocalApkSigner.Result result = LocalApkSigner.sign(new File(args[1]), new File(args[2]), new File(args[3]), store, args[4], key, reference);
                System.out.println(result.toJsonString());
            }
        } catch (Exception e) {
            System.out.println("{\"failed\":true,\"error_class\":\"" + e.getClass().getName() + "\"}");
            System.exit(2);
        } finally {
            Arrays.fill(store, '\0');
            Arrays.fill(key, '\0');
        }
    }
}
