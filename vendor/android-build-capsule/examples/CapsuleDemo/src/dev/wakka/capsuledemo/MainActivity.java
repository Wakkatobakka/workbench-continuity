package dev.wakka.capsuledemo;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private WebView web;
    private TextView status;
    private int count;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        count = savedInstanceState == null ? 0 : savedInstanceState.getInt("count", 0);
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setFitsSystemWindows(true);
        screen.setBackgroundColor(0xff07111b);
        status = new TextView(this);
        status.setTextColor(0xff56e2f2);
        status.setTextSize(16);
        status.setPadding(24, 20, 24, 20);
        screen.addView(status);
        web = new WebView(this);
        web.setBackgroundColor(0xff07111b);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.addJavascriptInterface(new Bridge(), "CapsuleNative");
        screen.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(screen);
        updateStatus();
        web.loadUrl("file:///android_asset/index.html");
    }

    private void updateStatus() { status.setText("Native Java counter: " + count); }

    private final class Bridge {
        @JavascriptInterface public void increment() {
            runOnUiThread(() -> { count++; updateStatus(); });
        }
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putInt("count", count);
        super.onSaveInstanceState(state);
    }

    @Override protected void onDestroy() {
        if (web != null) { web.removeJavascriptInterface("CapsuleNative"); web.destroy(); }
        super.onDestroy();
    }
}
