package com.netease.controller

import android.annotation.SuppressLint
import android.content.Context
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private val PREFS_NAME = "netease_prefs"
    private val KEY_SERVER = "server_host"

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)

        setupWebView()

        swipeRefresh.setOnRefreshListener {
            webView.reload()
        }

        val serverHost = getSavedServer()
        if (serverHost.isNullOrEmpty()) {
            showServerConfigDialog()
        } else {
            loadServer(serverHost)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                swipeRefresh.isRefreshing = false
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                swipeRefresh.isRefreshing = false
                if (request?.isForMainFrame == true) {
                    Toast.makeText(this@MainActivity, "连接服务器失败，长按屏幕可重新设置 IP", Toast.LENGTH_LONG).show()
                }
            }
        }

        // Long press anywhere to configure server IP
        webView.setOnLongClickListener {
            showServerConfigDialog()
            true
        }
    }

    private fun loadServer(host: String) {
        val cleanHost = host.trim().removePrefix("http://").removePrefix("https://").removeSuffix("/")
        val url = "http://$cleanHost"
        webView.loadUrl(url)
    }

    private fun showServerConfigDialog() {
        val currentHost = getSavedServer() ?: "192.168.1.6:10010"
        val input = EditText(this)
        input.setText(currentHost)
        input.setSelection(currentHost.length)
        input.hint = getString(R.string.set_server_hint)

        AlertDialog.Builder(this)
            .setTitle(R.string.set_server_title)
            .setView(input)
            .setPositiveButton(R.string.connect) { _, _ ->
                val newHost = input.text.toString().trim()
                if (newHost.isNotEmpty()) {
                    saveServer(newHost)
                    loadServer(newHost)
                }
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun getSavedServer(): String? {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_SERVER, null)
    }

    private fun saveServer(host: String) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_SERVER, host).apply()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
