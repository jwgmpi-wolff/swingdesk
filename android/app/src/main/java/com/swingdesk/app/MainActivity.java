package com.swingdesk.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.SafeBrowsingResponse;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.net.URI;
import java.net.URISyntaxException;

public final class MainActivity extends Activity {
    private static final String PREFERENCES = "swingdesk";
    private static final String SERVER_URL = "server_url";
    private static final String LEGACY_LOOPBACK_URL = "http://127.0.0.1:8787/";
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(createInterface());
        loadDashboard();
    }

    private LinearLayout createInterface() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(244, 245, 240));

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(12), dp(7), dp(8), dp(7));
        toolbar.setBackgroundColor(Color.rgb(20, 33, 29));

        TextView mark = new TextView(this);
        mark.setText("C");
        mark.setTextColor(Color.rgb(213, 43, 43));
        mark.setTextSize(24);
        mark.setGravity(Gravity.CENTER);
        mark.setTypeface(null, android.graphics.Typeface.BOLD);
        mark.setBackgroundColor(Color.WHITE);
        toolbar.addView(mark, new LinearLayout.LayoutParams(dp(34), dp(34)));

        TextView title = new TextView(this);
        title.setText("Swingdesk");
        title.setTextColor(Color.WHITE);
        title.setTextSize(17);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        title.setPadding(dp(10), 0, 0, 0);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(40), 1));

        Button reload = toolbarButton("Reload");
        reload.setOnClickListener(view -> webView.reload());
        toolbar.addView(reload);

        Button server = toolbarButton("Server");
        server.setOnClickListener(view -> showServerDialog());
        toolbar.addView(server);
        root.addView(toolbar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50)));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(244, 245, 240));
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(false);
        webView.getSettings().setAllowContentAccess(false);
        webView.getSettings().setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new DashboardClient());
        root.addView(webView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        return root;
    }

    private Button toolbarButton(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(Color.WHITE);
        button.setTextSize(11);
        button.setAllCaps(false);
        button.setBackgroundColor(Color.TRANSPARENT);
        button.setMinWidth(0);
        button.setMinimumWidth(0);
        button.setPadding(dp(10), 0, dp(10), 0);
        return button;
    }

    private void loadDashboard() {
        webView.loadUrl(serverUrl());
    }

    private String serverUrl() {
        String saved = getSharedPreferences(PREFERENCES, MODE_PRIVATE).getString(SERVER_URL, BuildConfig.DEFAULT_SERVER_URL);
        if (LEGACY_LOOPBACK_URL.equals(saved)) {
            getSharedPreferences(PREFERENCES, MODE_PRIVATE).edit().putString(SERVER_URL, BuildConfig.DEFAULT_SERVER_URL).apply();
            return BuildConfig.DEFAULT_SERVER_URL;
        }
        return saved;
    }

    private void showServerDialog() {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setSingleLine(true);
        input.setText(serverUrl());
        input.setSelectAllOnFocus(true);
        int padding = dp(20);
        LinearLayout container = new LinearLayout(this);
        container.setPadding(padding, dp(8), padding, 0);
        container.addView(input, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        new AlertDialog.Builder(this)
            .setTitle("Dashboard server")
            .setMessage("Enter the Windows dashboard URL on your trusted local network.")
            .setView(container)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Connect", (dialog, which) -> saveServerUrl(input.getText().toString()))
            .show();
    }

    private void saveServerUrl(String candidate) {
        String normalized = candidate.trim();
        if (!normalized.endsWith("/")) normalized += "/";
        try {
            URI uri = new URI(normalized);
            if (uri.getHost() == null || !("http".equals(uri.getScheme()) || "https".equals(uri.getScheme()))) {
                throw new URISyntaxException(normalized, "HTTP or HTTPS URL required");
            }
        } catch (URISyntaxException error) {
            Toast.makeText(this, "Enter a valid HTTP or HTTPS server URL", Toast.LENGTH_LONG).show();
            return;
        }
        getSharedPreferences(PREFERENCES, MODE_PRIVATE).edit().putString(SERVER_URL, normalized).apply();
        webView.loadUrl(normalized);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    private final class DashboardClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri target = request.getUrl();
            Uri server = Uri.parse(serverUrl());
            if (target.getHost() != null && target.getHost().equalsIgnoreCase(server.getHost())) return false;
            startActivity(new Intent(Intent.ACTION_VIEW, target));
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                Toast.makeText(MainActivity.this, "Cannot reach Swingdesk. Start the Windows server or change Server.", Toast.LENGTH_LONG).show();
            }
        }

        @Override
        public void onSafeBrowsingHit(WebView view, WebResourceRequest request, int threatType, SafeBrowsingResponse callback) {
            callback.backToSafety(true);
        }
    }
}