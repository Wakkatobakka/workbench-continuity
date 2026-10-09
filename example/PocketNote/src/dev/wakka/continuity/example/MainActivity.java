package dev.wakka.continuity.example;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
public class MainActivity extends Activity {
 @Override public void onCreate(Bundle state) { super.onCreate(state); TextView note = new TextView(this); note.setText("Pocket Note\nMy project came with me."); note.setTextSize(26); note.setPadding(32,48,32,32); setContentView(note); }
}
