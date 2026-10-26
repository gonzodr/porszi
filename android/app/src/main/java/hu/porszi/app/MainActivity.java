package hu.porszi.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Insets;
import android.net.ConnectivityManager;
import android.net.DhcpInfo;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.window.OnBackInvokedDispatcher;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Porszi: a dashboard felülete WebView-ban, natív hálózati híddal.
 * A JS a window.PorsziNative objektumon keresztül küld HTTP kéréseket (így nincs CORS-gond),
 * a Wi-Fi-varázsló kérései pedig a Wi-Fi hálózathoz kötve mennek ki (a porszívó saját AP-jára),
 * akkor is, ha az Android a „nincs internet" miatt a mobilnetet használná.
 */
public class MainActivity extends Activity {
    private WebView web;
    private final ExecutorService pool = Executors.newFixedThreadPool(4);

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
        enableEdgeToEdge();

        // Edge-to-edge (Android 15+): a rendszersávok alá ne kerüljön tartalom.
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int l, t, r, b;
            if (Build.VERSION.SDK_INT >= 30) {
                Insets i = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime() | WindowInsets.Type.displayCutout());
                l = i.left; t = i.top; r = i.right; b = i.bottom;
            } else {
                l = insets.getSystemWindowInsetLeft(); t = insets.getSystemWindowInsetTop();
                r = insets.getSystemWindowInsetRight(); b = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(l, t, r, b);
            return insets;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        web.setBackgroundColor(getColor(R.color.page));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if ("file".equals(u.getScheme())) return false;
                openUrl(u.toString());
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "PorsziNative");
        web.loadUrl("file:///android_asset/www/index.html");

        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }
    }

    @SuppressWarnings("deprecation")
    private void enableEdgeToEdge() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    getWindow().getDecorView().getSystemUiVisibility()
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    private void handleBack() {
        web.evaluateJavascript("(window.porsziBack ? window.porsziBack() : false)", v -> {
            if (!"true".equals(v)) moveTaskToBack(true);
        });
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        handleBack();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.evaluateJavascript("window.dispatchEvent(new Event('porszi-resume'))", null);
    }

    @Override
    protected void onDestroy() {
        pool.shutdownNow();
        if (web != null) web.destroy();
        super.onDestroy();
    }

    private void openUrl(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
        }
    }

    private Network findWifiNetwork() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return null;
        for (Network n : cm.getAllNetworks()) {
            NetworkCapabilities nc = cm.getNetworkCapabilities(n);
            if (nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return n;
        }
        return null;
    }

    private void callback(String id, int status, String text, String err) {
        final String js = "window.__porsziCb(" + JSONObject.quote(id) + "," + status + ","
                + JSONObject.quote(text == null ? "" : text) + "," + (err == null ? "null" : JSONObject.quote(err)) + ")";
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    private void updateState(String state, String info) {
        final String js = "window.__porsziUpdate && window.__porsziUpdate(" + JSONObject.quote(state) + "," + JSONObject.quote(info) + ")";
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    private static String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        try (InputStream is = in; ByteArrayOutputStream bo = new ByteArrayOutputStream()) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = is.read(buf)) > 0) bo.write(buf, 0, n);
            return bo.toString(StandardCharsets.UTF_8.name());
        }
    }

    /** A JavaScriptből hívható natív függvények. */
    public class Bridge {
        @JavascriptInterface
        public void request(String id, String method, String url, String headersJson, String body, int timeoutMs, String route) {
            pool.execute(() -> {
                HttpURLConnection c = null;
                try {
                    URL u = new URL(url);
                    Network wifi = "wifi".equals(route) ? findWifiNetwork() : null;
                    c = (HttpURLConnection) (wifi != null ? wifi.openConnection(u) : u.openConnection());
                    c.setConnectTimeout(timeoutMs);
                    c.setReadTimeout(Math.max(timeoutMs, 15000));
                    c.setRequestMethod(method);
                    c.setUseCaches(false);
                    JSONObject h = new JSONObject(headersJson == null || headersJson.isEmpty() ? "{}" : headersJson);
                    for (Iterator<String> it = h.keys(); it.hasNext(); ) {
                        String k = it.next();
                        c.setRequestProperty(k, h.getString(k));
                    }
                    if (body != null && !body.isEmpty() && !"GET".equals(method)) {
                        c.setDoOutput(true);
                        byte[] data = body.getBytes(StandardCharsets.UTF_8);
                        c.setFixedLengthStreamingMode(data.length);
                        try (OutputStream os = c.getOutputStream()) { os.write(data); }
                    }
                    int status = c.getResponseCode();
                    String text = readAll(status >= 400 ? c.getErrorStream() : c.getInputStream());
                    callback(id, status, text, null);
                } catch (java.net.SocketTimeoutException e) {
                    callback(id, 0, "", "timeout");
                } catch (Exception e) {
                    callback(id, 0, "", "failed to connect: " + e.getClass().getSimpleName() + (e.getMessage() != null ? " " + e.getMessage() : ""));
                } finally {
                    if (c != null) c.disconnect();
                }
            });
        }

        @JavascriptInterface
        public void openExternal(String url) {
            runOnUiThread(() -> openUrl(url));
        }

        @JavascriptInterface
        public void openWifiSettings() {
            runOnUiThread(() -> {
                try {
                    startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS));
                } catch (Exception ignored) {
                }
            });
        }

        @SuppressWarnings("deprecation")
        @JavascriptInterface
        public String wifiGateway() {
            try {
                WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                DhcpInfo d = wm != null ? wm.getDhcpInfo() : null;
                if (d == null || d.gateway == 0) return "";
                int g = d.gateway;
                return (g & 0xff) + "." + ((g >> 8) & 0xff) + "." + ((g >> 16) & 0xff) + "." + ((g >> 24) & 0xff);
            } catch (Exception e) {
                return "";
            }
        }

        @JavascriptInterface
        public String appVersion() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (Exception e) {
                return "?";
            }
        }

        @SuppressWarnings("deprecation")
        @JavascriptInterface
        public long appVersionCode() {
            try {
                android.content.pm.PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
                return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
            } catch (Exception e) {
                return 0;
            }
        }

        /** Frissites letoltese es a rendszer telepitojenek megnyitasa. Allapot: window.__porsziUpdate(state, info). */
        @JavascriptInterface
        public void installUpdate(String url) {
            if (!getPackageManager().canRequestPackageInstalls()) {
                updateState("permission", "");
                runOnUiThread(() -> {
                    try {
                        startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + getPackageName())));
                    } catch (Exception ignored) {
                    }
                });
                return;
            }
            pool.execute(() -> {
                HttpURLConnection c = null;
                try {
                    File out = new File(ApkProvider.dir(MainActivity.this), "porszi-update.apk");
                    c = (HttpURLConnection) new URL(url).openConnection();
                    c.setInstanceFollowRedirects(true);
                    c.setConnectTimeout(15000);
                    c.setReadTimeout(30000);
                    c.setRequestProperty("User-Agent", "Porszi-app");
                    int code = c.getResponseCode();
                    if (code >= 300) throw new Exception("HTTP " + code);
                    long total = c.getContentLengthLong();
                    long done = 0;
                    int lastPct = -1;
                    try (InputStream in = c.getInputStream(); FileOutputStream fo = new FileOutputStream(out)) {
                        byte[] buf = new byte[32768];
                        int n;
                        while ((n = in.read(buf)) > 0) {
                            fo.write(buf, 0, n);
                            done += n;
                            int pct = total > 0 ? (int) (done * 100 / total) : -1;
                            if (pct != lastPct && pct % 10 == 0) { lastPct = pct; updateState("progress", String.valueOf(pct)); }
                        }
                    }
                    Uri uri = Uri.parse("content://" + ApkProvider.AUTHORITY + "/" + out.getName());
                    Intent i = new Intent(Intent.ACTION_VIEW);
                    i.setDataAndType(uri, "application/vnd.android.package-archive");
                    i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                    runOnUiThread(() -> {
                        try {
                            startActivity(i);
                            updateState("ready", "");
                        } catch (Exception e) {
                            updateState("error", e.toString());
                        }
                    });
                } catch (Exception e) {
                    updateState("error", e.getClass().getSimpleName() + (e.getMessage() != null ? " " + e.getMessage() : ""));
                } finally {
                    if (c != null) c.disconnect();
                }
            });
        }
    }
}
