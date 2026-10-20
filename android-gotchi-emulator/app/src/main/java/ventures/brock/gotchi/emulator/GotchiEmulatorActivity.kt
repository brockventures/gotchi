package ventures.brock.gotchi.emulator

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.ByteArrayOutputStream

/**
 * Interactive Pocket Hardware Emulator Activity for GOTCHI V1 (`ventures.brock.gotchi.emulator`).
 *
 * Features:
 * - 1:1 200x200 1-bit monochrome e-paper display (`GotchiEpaperView`) with `gotchi` & `zero` skins.
 * - Tactile `BTN_TOP` (Hold PTT / Tap VAD / Double-Tap Go Live) & `BTN_BOT` (Single Snap / Hold 5-Burst).
 * - Physical hardware key mapping: `KEYCODE_VOLUME_UP` = `BTN_TOP`, `KEYCODE_VOLUME_DOWN` = `BTN_BOT`.
 * - Runtime configuration via UI drawer or ADB intent (`gateway_url`, `bearer_token`, `node_id`,
 *   `audio_out_mode`, `ptt_silence_ms`, `skin`).
 */
class GotchiEmulatorActivity : Activity() {

    companion object {
        const val PREFS_NAME = "gotchi_emulator_prefs"
        const val KEY_GATEWAY_URL = "gateway_url"
        const val KEY_BEARER_TOKEN = "bearer_token"
        const val KEY_NODE_ID = "node_id"
        const val KEY_AUDIO_OUT_MODE = "audio_out_mode"
        const val KEY_PTT_SILENCE_MS = "ptt_silence_ms"
        const val KEY_SKIN = "skin"
        private const val DOUBLE_TAP_WINDOW_MS = 350L
        private const val BURST_HOLD_MS = 500L
    }

    private lateinit var epaperView: GotchiEpaperView
    private lateinit var engine: GotchiEmulatorEngine
    private lateinit var gatewayInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var nodeInput: EditText
    private lateinit var silenceToggleBtn: Button
    private lateinit var skinToggleBtn: Button

    private var lastBtnTopDownMs: Long = 0L
    private var btnBotDownMs: Long = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        requestRuntimePermissionsIfNeeded()

        epaperView = GotchiEpaperView(this)
        engine = GotchiEmulatorEngine { state, transcript, reply, status, audioBytes, sampleRate ->
            runOnUiThread {
                epaperView.updateState(
                    newState = state,
                    transcript = transcript,
                    reply = reply,
                    statusText = status,
                    audioBytesDelta = audioBytes,
                    sampleRate = sampleRate
                )
            }
        }

        loadPreferencesAndIntent(intent)
        setContentView(buildPocketEmulatorLayout())
        epaperView.updateState(newState = "idle", statusText = "READY (HOLD PTT)", forceFullRefresh = true)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        loadPreferencesAndIntent(intent)
    }

    override fun onDestroy() {
        super.onDestroy()
        engine.shutdown()
    }

    private fun requestRuntimePermissionsIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val needed = mutableListOf<String>()
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.RECORD_AUDIO)
            }
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.CAMERA)
            }
            if (needed.isNotEmpty()) {
                requestPermissions(needed.toTypedArray(), 1001)
            }
        }
    }

    private fun loadPreferencesAndIntent(incoming: Intent?) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val edit = prefs.edit()

        incoming?.let {
            it.getStringExtra(KEY_GATEWAY_URL)?.let { v -> edit.putString(KEY_GATEWAY_URL, v) }
            it.getStringExtra(KEY_BEARER_TOKEN)?.let { v -> edit.putString(KEY_BEARER_TOKEN, v) }
            it.getStringExtra(KEY_NODE_ID)?.let { v -> edit.putString(KEY_NODE_ID, v) }
            it.getStringExtra(KEY_AUDIO_OUT_MODE)?.let { v -> edit.putString(KEY_AUDIO_OUT_MODE, v) }
            it.getStringExtra(KEY_SKIN)?.let { v -> edit.putString(KEY_SKIN, v) }
            if (it.hasExtra(KEY_PTT_SILENCE_MS)) {
                edit.putLong(KEY_PTT_SILENCE_MS, it.getLongExtra(KEY_PTT_SILENCE_MS, 1500L))
            }
            edit.apply()
        }

        engine.config.gatewayUrl = prefs.getString(KEY_GATEWAY_URL, GotchiEmulatorEngine.DEFAULT_GATEWAY_URL)
            ?: GotchiEmulatorEngine.DEFAULT_GATEWAY_URL
        engine.config.bearerToken = prefs.getString(KEY_BEARER_TOKEN, "") ?: ""
        engine.config.nodeId = prefs.getString(KEY_NODE_ID, GotchiEmulatorEngine.DEFAULT_NODE_ID)
            ?: GotchiEmulatorEngine.DEFAULT_NODE_ID
        engine.config.audioOutMode = prefs.getString(KEY_AUDIO_OUT_MODE, "speaker") ?: "speaker"
        engine.config.pttSilenceMs = prefs.getLong(KEY_PTT_SILENCE_MS, GotchiEmulatorEngine.DEFAULT_PTT_SILENCE_MS)
        epaperView.uiState.skin = prefs.getString(KEY_SKIN, "gotchi") ?: "gotchi"
    }

    private fun buildPocketEmulatorLayout(): ScrollView {
        val density = resources.displayMetrics.density
        fun dp(v: Int): Int = (v * density).toInt()

        val rootScroll = ScrollView(this).apply {
            setBackgroundColor(Color.rgb(22, 25, 32))
        }
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(20), dp(24), dp(20), dp(24))
        }

        val title = TextView(this).apply {
            text = "GOTCHI // POCKET HARDWARE EMULATOR"
            setTextColor(Color.rgb(255, 202, 56))
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, dp(12))
        }
        container.addView(title)

        // 200x200 E-Paper Bezel Frame (scaled 1.5x in dp)
        val bezelFrame = LinearLayout(this).apply {
            setBackgroundColor(Color.rgb(48, 54, 66))
            setPadding(dp(12), dp(12), dp(12), dp(12))
            gravity = Gravity.CENTER
        }
        bezelFrame.addView(epaperView, LinearLayout.LayoutParams(dp(280), dp(280)))
        container.addView(bezelFrame)

        // Hardware Tactile Button Row (BTN_TOP + BTN_BOT)
        val btnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, dp(16), 0, dp(12))
        }

        val btnTop = Button(this).apply {
            text = "BTN_TOP (PTT / 2x LIVE)"
            setOnTouchListener { _, ev ->
                handleBtnTopTouch(ev.actionMasked)
                true
            }
        }
        val btnBot = Button(this).apply {
            text = "BTN_BOT (SNAP / 5-BURST)"
            setOnTouchListener { _, ev ->
                handleBtnBotTouch(ev.actionMasked)
                true
            }
        }
        btnRow.addView(btnTop, LinearLayout.LayoutParams(0, dp(60), 1f))
        btnRow.addView(btnBot, LinearLayout.LayoutParams(0, dp(60), 1f))
        container.addView(btnRow, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))

        // Quick Toggles Row: Skin (Gotchi / Zero) + Trailing Silence VAD (800 / 1000 / 1500 ms)
        val toggleRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        skinToggleBtn = Button(this).apply {
            text = "SKIN: ${epaperView.uiState.skin.uppercase()}"
            setOnClickListener {
                epaperView.uiState.skin = if (epaperView.uiState.skin == "gotchi") "zero" else "gotchi"
                text = "SKIN: ${epaperView.uiState.skin.uppercase()}"
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putString(KEY_SKIN, epaperView.uiState.skin).apply()
                epaperView.updateState(forceFullRefresh = true)
            }
        }
        silenceToggleBtn = Button(this).apply {
            text = "VAD: ${engine.config.pttSilenceMs}ms"
            setOnClickListener {
                engine.config.pttSilenceMs = when (engine.config.pttSilenceMs) {
                    1500L -> 800L
                    800L -> 1000L
                    else -> 1500L
                }
                text = "VAD: ${engine.config.pttSilenceMs}ms"
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putLong(KEY_PTT_SILENCE_MS, engine.config.pttSilenceMs).apply()
            }
        }
        toggleRow.addView(skinToggleBtn, LinearLayout.LayoutParams(0, dp(48), 1f))
        toggleRow.addView(silenceToggleBtn, LinearLayout.LayoutParams(0, dp(48), 1f))
        container.addView(toggleRow, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))

        // Gateway Configuration Inputs
        gatewayInput = EditText(this).apply {
            hint = "Gateway URL (e.g. https://gotchi.example.com)"
            setText(engine.config.gatewayUrl)
            setTextColor(Color.WHITE)
        }
        tokenInput = EditText(this).apply {
            hint = "Device Bearer Token"
            setText(engine.config.bearerToken)
            setTextColor(Color.WHITE)
        }
        nodeInput = EditText(this).apply {
            hint = "Node ID (gotchi-android-emu-01)"
            setText(engine.config.nodeId)
            setTextColor(Color.WHITE)
        }
        val saveBtn = Button(this).apply {
            text = "SAVE GATEWAY CONFIG"
            setOnClickListener {
                engine.config.gatewayUrl = gatewayInput.text.toString().trim()
                engine.config.bearerToken = tokenInput.text.toString().trim()
                engine.config.nodeId = nodeInput.text.toString().trim().ifEmpty { GotchiEmulatorEngine.DEFAULT_NODE_ID }
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putString(KEY_GATEWAY_URL, engine.config.gatewayUrl)
                    .putString(KEY_BEARER_TOKEN, engine.config.bearerToken)
                    .putString(KEY_NODE_ID, engine.config.nodeId)
                    .apply()
                epaperView.updateState(statusText = "CONFIG SAVED")
            }
        }

        container.addView(gatewayInput)
        container.addView(tokenInput)
        container.addView(nodeInput)
        container.addView(saveBtn)
        rootScroll.addView(container)
        return rootScroll
    }

    internal fun handleBtnTopTouch(action: Int) {
        val now = SystemClock.elapsedRealtime()
        when (action) {
            MotionEvent.ACTION_DOWN -> {
                if ((now - lastBtnTopDownMs) <= DOUBLE_TAP_WINDOW_MS) {
                    lastBtnTopDownMs = 0L
                    engine.startLiveSession()
                } else {
                    lastBtnTopDownMs = now
                    engine.startPttCapture(autoVadStop = false)
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                engine.stopPttAndCommit()
            }
        }
    }

    internal fun handleBtnBotTouch(action: Int) {
        val now = SystemClock.elapsedRealtime()
        when (action) {
            MotionEvent.ACTION_DOWN -> {
                btnBotDownMs = now
            }
            MotionEvent.ACTION_UP -> {
                val heldMs = now - btnBotDownMs
                if (heldMs >= BURST_HOLD_MS) {
                    val burst = (0 until 5).associateWith { idx -> captureSnapshotJpeg(idx) }
                    engine.dispatchStandaloneSnapshotTurn(burst, prompt = "Analyze this 5-frame camera burst.")
                } else {
                    val snap = captureSnapshotJpeg(0)
                    engine.attachSnapshot(snap, frameIndex = 0)
                }
            }
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) {
            if (event?.repeatCount == 0) handleBtnTopTouch(MotionEvent.ACTION_DOWN)
            return true
        }
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            if (event?.repeatCount == 0) handleBtnBotTouch(MotionEvent.ACTION_DOWN)
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) {
            handleBtnTopTouch(MotionEvent.ACTION_UP)
            return true
        }
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            handleBtnBotTouch(MotionEvent.ACTION_UP)
            return true
        }
        return super.onKeyUp(keyCode, event)
    }

    private fun captureSnapshotJpeg(frameIndex: Int): ByteArray {
        val bmp = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.drawColor(Color.rgb(30, 36, 44))
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 18f
        }
        c.drawText("GOTCHI CAM FRAME #${frameIndex + 1}", 24f, 120f, p)
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        return out.toByteArray()
    }
}
