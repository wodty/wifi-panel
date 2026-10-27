package io.github.wodty.wifipanel;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * wifi-panel 的安卓外壳：一个 WebView + 一个填写中枢地址的设置页。
 *
 * 面板本体仍然是中枢托管的网页，所以这里刻意不打包任何前端资源——
 * 中枢更新了新功能，App 不用重新装。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "wifi_panel";
    private static final String K_HOST = "host";
    private static final String K_TOKEN = "token";
    private static final int DEFAULT_PORT = 8765;

    private static final int BG = 0xFF101420;
    private static final int TEXT = 0xFFEEF2FA;
    private static final int MUTED = 0xFF8892A6;
    private static final int FIELD = 0xFF1B2233;
    private static final int FIELD_LINE = 0xFF2C3550;
    private static final int ACCENT = 0xFF56CCBE;
    private static final int DANGER = 0xFFFF7A7A;

    private SharedPreferences sp;
    private FrameLayout root;
    private WebView web;
    private ScrollView setupView;
    private EditText etHost;
    private EditText etToken;
    private TextView tvErr;
    private boolean pageLoaded;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        sp = getSharedPreferences(PREFS, MODE_PRIVATE);

        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        setContentView(root);

        buildWebView();
        buildSetupView();

        root.addView(web, matchParent());
        root.addView(setupView, matchParent());

        if (sp.getString(K_HOST, "").isEmpty()) {
            showSetup(getString(R.string.tip_first_run));
        } else {
            loadPanel();
        }
    }

    /* ---------------- WebView ---------------- */

    @SuppressLint("SetJavaScriptEnabled")
    private void buildWebView() {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);              // 面板用 localStorage 存令牌和布局
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        web.setBackgroundColor(BG);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVisibility(View.GONE);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;                      // 站内跳转都留在 WebView 里
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageLoaded = true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showSetup("连不上中枢：" + error.getDescription());
                }
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (Build.VERSION.SDK_INT < 23) {
                    showSetup("连不上中枢：" + description);
                }
            }
        });

        // WebView 一般会自己吃掉长按，回调可能不来；真正可靠的是返回键（见 onKeyDown）
        web.setOnLongClickListener(v -> {
            showMenu();
            return true;
        });
    }

    /* ---------------- 设置页 ---------------- */

    private void buildSetupView() {
        setupView = new ScrollView(this);
        setupView.setFillViewport(true);
        setupView.setBackgroundColor(BG);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        col.setPadding(dp(24), dp(56), dp(24), dp(24));
        setupView.addView(col, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextColor(TEXT);
        title.setTextSize(30f);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        col.addView(title, wrap());

        TextView sub = new TextView(this);
        sub.setText(R.string.setup_sub);
        sub.setTextColor(MUTED);
        sub.setTextSize(14f);
        sub.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subLp = wrap();
        subLp.topMargin = dp(8);
        col.addView(sub, subLp);

        etHost = new EditText(this);
        etHost.setHint(R.string.setup_host_hint);
        etHost.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        etHost.setSingleLine(true);
        styleField(etHost);
        LinearLayout.LayoutParams hostLp = full();
        hostLp.topMargin = dp(28);
        col.addView(etHost, hostLp);

        etToken = new EditText(this);
        etToken.setHint(R.string.setup_token_hint);
        etToken.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        etToken.setSingleLine(true);
        styleField(etToken);
        LinearLayout.LayoutParams tokLp = full();
        tokLp.topMargin = dp(12);
        col.addView(etToken, tokLp);

        Button btn = new Button(this);
        btn.setText(R.string.setup_connect);
        btn.setAllCaps(false);
        btn.setTextSize(16f);
        btn.setTextColor(0xFF0B1020);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setBackgroundTintList(ColorStateList.valueOf(ACCENT));
        btn.setStateListAnimator(null);
        btn.setOnClickListener(v -> onConnectClick());
        LinearLayout.LayoutParams btnLp = full();
        btnLp.topMargin = dp(20);
        btnLp.height = dp(50);
        col.addView(btn, btnLp);

        tvErr = new TextView(this);
        tvErr.setTextColor(DANGER);
        tvErr.setTextSize(13f);
        tvErr.setGravity(Gravity.CENTER);
        tvErr.setVisibility(View.GONE);
        LinearLayout.LayoutParams errLp = full();
        errLp.topMargin = dp(14);
        col.addView(tvErr, errLp);

        TextView tip = new TextView(this);
        tip.setText(R.string.setup_tip);
        tip.setTextColor(MUTED);
        tip.setTextSize(12.5f);
        tip.setLineSpacing(dp(4), 1f);
        LinearLayout.LayoutParams tipLp = full();
        tipLp.topMargin = dp(28);
        col.addView(tip, tipLp);
    }

    private void styleField(EditText et) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(FIELD);
        g.setCornerRadius(dp(12));
        g.setStroke(dp(1), FIELD_LINE);
        et.setBackground(g);
        et.setPadding(dp(16), dp(14), dp(16), dp(14));
        et.setTextColor(TEXT);
        et.setHintTextColor(MUTED);
        et.setTextSize(15f);
    }

    private void onConnectClick() {
        String host = normalizeHost(etHost.getText().toString());
        String token = etToken.getText().toString().trim();

        if (host.isEmpty()) {
            showErr(getString(R.string.err_host_empty));
            return;
        }
        if (!host.matches("[A-Za-z0-9._\\-]+:\\d{1,5}")) {
            showErr(getString(R.string.err_host_format));
            return;
        }
        sp.edit().putString(K_HOST, host).putString(K_TOKEN, token).apply();
        etHost.setText(host);
        loadPanel();
    }

    private void showErr(String msg) {
        tvErr.setText(msg);
        tvErr.setVisibility(View.VISIBLE);
    }

    private void showSetup(String msg) {
        pageLoaded = false;
        if (web != null) {
            web.stopLoading();
            web.setVisibility(View.GONE);
        }
        etHost.setText(sp.getString(K_HOST, ""));
        etToken.setText(sp.getString(K_TOKEN, ""));
        if (msg == null || msg.isEmpty()) {
            tvErr.setVisibility(View.GONE);
        } else {
            showErr(msg);
        }
        setupView.setVisibility(View.VISIBLE);
    }

    /* ---------------- 加载面板 ---------------- */

    private void loadPanel() {
        String host = sp.getString(K_HOST, "");
        String token = sp.getString(K_TOKEN, "");
        if (host.isEmpty()) {
            showSetup(getString(R.string.tip_first_run));
            return;
        }

        // 带 host+token 参数，网页会自动连上，省掉每次开机手点「连接」
        StringBuilder url = new StringBuilder("http://").append(host).append('/');
        if (!token.isEmpty()) {
            url.append("?host=").append(host).append("&token=").append(Uri.encode(token));
        }

        pageLoaded = false;
        setupView.setVisibility(View.GONE);
        tvErr.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        web.loadUrl(url.toString());
    }

    /* ---------------- 返回键 / 菜单 ---------------- */

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (web.getVisibility() == View.VISIBLE && web.canGoBack()) {
                web.goBack();
                return true;
            }
            showMenu();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private void showMenu() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.menu_title)
                .setItems(new String[]{
                        getString(R.string.menu_reload),
                        getString(R.string.menu_host),
                        getString(R.string.menu_quit)
                }, (d, which) -> {
                    if (which == 0) {
                        if (sp.getString(K_HOST, "").isEmpty()) {
                            showSetup(null);
                        } else if (web.getVisibility() == View.VISIBLE) {
                            web.reload();
                        } else {
                            loadPanel();
                        }
                    } else if (which == 1) {
                        showSetup(null);
                    } else {
                        finish();
                    }
                })
                .setNegativeButton(R.string.menu_cancel, null)
                .show();
    }

    /* ---------------- 小工具 ---------------- */

    /** 把「http://192.168.1.10:8765/」这类输入整理成「192.168.1.10:8765」，缺端口补默认 8765 */
    private String normalizeHost(String raw) {
        String h = raw == null ? "" : raw.trim();
        if (h.isEmpty()) {
            return "";
        }
        h = h.replaceAll("(?i)^[a-z][a-z0-9+.\\-]*://", "");
        int cut = -1;
        for (int i = 0; i < h.length(); i++) {
            char c = h.charAt(i);
            if (c == '/' || c == '?' || c == '#') {
                cut = i;
                break;
            }
        }
        if (cut >= 0) {
            h = h.substring(0, cut);
        }
        while (h.endsWith("/")) {
            h = h.substring(0, h.length() - 1);
        }
        if (!h.isEmpty() && h.indexOf(':') < 0) {
            h = h + ":" + DEFAULT_PORT;
        }
        return h;
    }

    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }

    private static ViewGroup.LayoutParams matchParent() {
        return new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private static LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams full() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    @Override
    protected void onPause() {
        super.onPause();
        // 切后台立刻断开长连接，中枢会释放这台设备按住的按键，避免「一直按着」
        if (web != null) {
            web.evaluateJavascript("window.__wpPause&&window.__wpPause()", null);
            web.onPause();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) {
            web.onResume();
            web.evaluateJavascript("window.__wpResume&&window.__wpResume()", null);
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.loadUrl("about:blank");
            web.destroy();
        }
        super.onDestroy();
    }
}
