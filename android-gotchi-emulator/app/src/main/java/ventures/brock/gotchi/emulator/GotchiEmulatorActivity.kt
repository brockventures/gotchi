package ventures.brock.gotchi.emulator

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import java.io.ByteArrayOutputStream
import kotlin.math.hypot

/**
 * GOTCHI V2.6 "Arctic Purple" Pocket Hardware Emulator Activity (`ventures.brock.gotchi.emulator`).
 *
 * Skins the Android emulator to match the V2.6 Industrial Design Mockup:
 * - CNC 6061 Bead-Blasted Aluminum Perimeter Side-Rail (`34.8 x 51.0 mm` aspect ratio) with 45° specular chamfer
 *   and top PDM microphone pinhole.
 * - Translucent 90s "Arctic Purple" SLA Resin Front Plate revealing internal V2.5 matte-black PCB window,
 *   vertical Gold ENIG sensor bus rails, and copper/kapton warmth underneath.
 * - Flush `GDEY0154D67-FT` 200x200 1-bit e-paper viewport (`GotchiEpaperView`) in the upper 2.1mm bezel.
 * - Front-mounted machined aluminum tactile buttons (`BTN_TOP: PTT / LIVE` and `BTN_BOT: SNAP / 5x`),
 *   `OV5640` cyan-coated camera lens barrel on the lower-right chin, and V2.1 diffused LED glow bar at bottom seam.
 * - Top-right Hamburger Menu (`☰`) opening the runtime settings dialog (`skin`, `ptt_silence_ms`, `audio_out_mode`,
 *   `gateway_url`, `bearer_token`, `node_id`).
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
        const val KEY_OPEN_MENU = "open_menu"
        private const val DOUBLE_TAP_WINDOW_MS = 350L
        private const val BURST_HOLD_MS = 500L
    }

    private lateinit var epaperView: GotchiEpaperView
    private lateinit var chassisView: ArcticPurpleChassisView
    private lateinit var statusPill: TextView
    private lateinit var engine: GotchiEmulatorEngine

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
                updateStatusPill()
                chassisView.invalidate()
            }
        }

        loadPreferencesAndIntent(intent)
        setContentView(buildArcticPurpleMockupScreen())
        epaperView.updateState(newState = "idle", statusText = "READY (HOLD PTT)", forceFullRefresh = true)
        updateStatusPill()

        if (intent?.getBooleanExtra(KEY_OPEN_MENU, false) == true) {
            window.decorView.postDelayed({ showHamburgerSettingsDialog() }, 350L)
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        loadPreferencesAndIntent(intent)
        epaperView.updateState(forceFullRefresh = true)
        updateStatusPill()
        chassisView.invalidate()
        if (intent?.getBooleanExtra(KEY_OPEN_MENU, false) == true) {
            window.decorView.postDelayed({ showHamburgerSettingsDialog() }, 250L)
        }
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
        epaperView.uiState.skin = prefs.getString(KEY_SKIN, "zero") ?: "zero"
    }

    private fun buildArcticPurpleMockupScreen(): LinearLayout {
        val density = resources.displayMetrics.density
        fun dp(v: Int): Int = (v * density).toInt()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(14, 13, 24))
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(18), dp(18), dp(18), dp(18))
        }

        // Top App Bar: Title + Subtitle on Left, Hamburger Menu Button (`☰`) on Right
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(4), dp(4), dp(4), dp(12))
        }

        val titleCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        val mainTitle = TextView(this).apply {
            text = "GOTCHI V2.6 — 'Arctic Purple' SLA + CNC"
            setTextColor(Color.rgb(244, 242, 255))
            textSize = 15.5f
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val subTitle = TextView(this).apply {
            text = "34.8 × 51.0 × 14.5 mm  |  Flush GDEY0154D67-FT Glass"
            setTextColor(Color.rgb(168, 152, 224))
            textSize = 11.5f
        }
        titleCol.addView(mainTitle)
        titleCol.addView(subTitle)

        val hamburgerBtn = Button(this).apply {
            text = "☰"
            textSize = 20f
            setTextColor(Color.rgb(232, 224, 255))
            setPadding(0, 0, 0, 0)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(10).toFloat()
                setColor(Color.rgb(34, 28, 58))
                setStroke(dp(1), Color.rgb(124, 92, 214))
            }
            setOnClickListener { showHamburgerSettingsDialog() }
        }

        headerRow.addView(titleCol, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        headerRow.addView(hamburgerBtn, LinearLayout.LayoutParams(dp(46), dp(44)))
        root.addView(headerRow, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))

        // Main Hardware Enclosure Viewport (Custom CNC Aluminum + Translucent Arctic Purple Chassis)
        chassisView = ArcticPurpleChassisView(this, epaperView)
        root.addView(
            chassisView,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        )

        // Bottom Telemetry Pill matching the V2.6 Studio Render (`STATE: IDLE (96%)`)
        statusPill = TextView(this).apply {
            textSize = 12.5f
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setTextColor(Color.rgb(94, 234, 212))
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(8), dp(16), dp(8))
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(8).toFloat()
                setColor(Color.rgb(18, 28, 38))
                setStroke(dp(1), Color.rgb(45, 168, 196))
            }
        }
        val pillParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply {
            topMargin = dp(10)
            bottomMargin = dp(4)
        }
        root.addView(statusPill, pillParams)

        return root
    }

    private fun updateStatusPill() {
        if (!::statusPill.isInitialized) return
        val st = epaperView.uiState.state.uppercase()
        val skin = epaperView.uiState.skin.uppercase()
        val vad = engine.config.pttSilenceMs
        statusPill.text = "STATE: $st (${epaperView.uiState.batteryPct}%+)  •  SKIN: $skin  •  VAD: ${vad}ms"
    }

    private fun showHamburgerSettingsDialog() {
        val density = resources.displayMetrics.density
        fun dp(v: Int): Int = (v * density).toInt()

        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(16), dp(20), dp(8))
            setBackgroundColor(Color.rgb(24, 22, 38))
        }

        val skinBtn = Button(this).apply {
            text = "SKIN: ${epaperView.uiState.skin.uppercase()} (TAP TO SWITCH)"
            setOnClickListener {
                epaperView.uiState.skin = when (epaperView.uiState.skin) { "zero" -> "amos"; "amos" -> "gotchi"; else -> "zero" }
                text = "SKIN: ${epaperView.uiState.skin.uppercase()} (TAP TO SWITCH)"
                epaperView.updateState(forceFullRefresh = true)
                updateStatusPill()
                chassisView.invalidate()
            }
        }

        val vadBtn = Button(this).apply {
            text = "VAD TRAILING SILENCE: ${engine.config.pttSilenceMs}ms"
            setOnClickListener {
                engine.config.pttSilenceMs = when (engine.config.pttSilenceMs) {
                    1500L -> 800L
                    800L -> 1000L
                    else -> 1500L
                }
                text = "VAD TRAILING SILENCE: ${engine.config.pttSilenceMs}ms"
                updateStatusPill()
            }
        }

        val audioModeBtn = Button(this).apply {
            text = "AUDIO OUT: ${engine.config.audioOutMode.uppercase()}"
            setOnClickListener {
                engine.config.audioOutMode = when (engine.config.audioOutMode) {
                    "speaker" -> "ble_phone"
                    "ble_phone" -> "discord_voice"
                    else -> "speaker"
                }
                text = "AUDIO OUT: ${engine.config.audioOutMode.uppercase()}"
            }
        }

        val gatewayInput = EditText(this).apply {
            hint = "Gateway URL (http://127.0.0.1:8765)"
            setText(engine.config.gatewayUrl)
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        val tokenInput = EditText(this).apply {
            hint = "Device Bearer Token"
            setText(engine.config.bearerToken)
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        val nodeInput = EditText(this).apply {
            hint = "Node ID (gotchi-pixel8pro-01)"
            setText(engine.config.nodeId)
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }

        panel.addView(skinBtn)
        panel.addView(vadBtn)
        panel.addView(audioModeBtn)
        panel.addView(gatewayInput)
        panel.addView(tokenInput)
        panel.addView(nodeInput)

        AlertDialog.Builder(this)
            .setTitle("Gotchi V2.6 Settings")
            .setView(panel)
            .setPositiveButton("Save") { _, _ ->
                engine.config.gatewayUrl = gatewayInput.text.toString().trim().ifEmpty { GotchiEmulatorEngine.DEFAULT_GATEWAY_URL }
                engine.config.bearerToken = tokenInput.text.toString().trim()
                engine.config.nodeId = nodeInput.text.toString().trim().ifEmpty { GotchiEmulatorEngine.DEFAULT_NODE_ID }
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putString(KEY_GATEWAY_URL, engine.config.gatewayUrl)
                    .putString(KEY_BEARER_TOKEN, engine.config.bearerToken)
                    .putString(KEY_NODE_ID, engine.config.nodeId)
                    .putString(KEY_AUDIO_OUT_MODE, engine.config.audioOutMode)
                    .putLong(KEY_PTT_SILENCE_MS, engine.config.pttSilenceMs)
                    .putString(KEY_SKIN, epaperView.uiState.skin)
                    .apply()
                epaperView.updateState(statusText = "CONFIG SAVED")
                updateStatusPill()
            }
            .setNegativeButton("Cancel", null)
            .show()
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
            if (event?.repeatCount == 0) {
                chassisView.btnTopPressed = true
                chassisView.invalidate()
                handleBtnTopTouch(MotionEvent.ACTION_DOWN)
            }
            return true
        }
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            if (event?.repeatCount == 0) {
                chassisView.btnBotPressed = true
                chassisView.invalidate()
                handleBtnBotTouch(MotionEvent.ACTION_DOWN)
            }
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) {
            chassisView.btnTopPressed = false
            chassisView.invalidate()
            handleBtnTopTouch(MotionEvent.ACTION_UP)
            return true
        }
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            chassisView.btnBotPressed = false
            chassisView.invalidate()
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

    /**
     * Custom Viewgroup rendering the Gotchi V2.6 "Arctic Purple" Translucent SLA + CNC 6061 Aluminum
     * hardware enclosure around the live 200x200 `GotchiEpaperView`, with interactive front-mounted
     * machined aluminum physical buttons (`BTN_TOP` & `BTN_BOT`), `OV5640` camera lens, and V2.1 LED lightpipe.
     */
    inner class ArcticPurpleChassisView(
        context: Context,
        private val epdChild: GotchiEpaperView
    ) : FrameLayout(context) {

        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val outerRailRect = RectF()
        private val chamferRect = RectF()
        private val purplePlateRect = RectF()
        private val screenCutoutRect = RectF()
        private val chinWindowRect = RectF()
        private val ledBarRect = RectF()

        private var btnTopCx = 0f
        private var btnTopCy = 0f
        private var btnBotCx = 0f
        private var btnBotCy = 0f
        private var btnRadius = 0f

        var btnTopPressed = false
        var btnBotPressed = false
        private var activeTouchBtn: Int = 0 // 0=none, 1=top, 2=bot

        init {
            setWillNotDraw(false)
            addView(epdChild)
        }

        override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
            val w = (right - left).toFloat()
            val h = (bottom - top).toFloat()
            if (w <= 0f || h <= 0f) return

            // Exact V2.6 aspect ratio: 34.8 mm width x 51.0 mm height (1 : 1.4655)
            val targetAspect = 34.8f / 51.0f
            var caseW = w * 0.90f
            var caseH = caseW / targetAspect
            if (caseH > h * 0.96f) {
                caseH = h * 0.96f
                caseW = caseH * targetAspect
            }

            val cx = w / 2f
            val cy = h / 2f
            outerRailRect.set(cx - caseW / 2f, cy - caseH / 2f, cx + caseW / 2f, cy + caseH / 2f)

            val railWall = caseW * 0.052f
            chamferRect.set(
                outerRailRect.left + railWall * 0.32f,
                outerRailRect.top + railWall * 0.32f,
                outerRailRect.right - railWall * 0.32f,
                outerRailRect.bottom - railWall * 0.32f
            )
            purplePlateRect.set(
                outerRailRect.left + railWall,
                outerRailRect.top + railWall,
                outerRailRect.right - railWall,
                outerRailRect.bottom - railWall
            )

            // 200x200 E-Paper active area sits in upper portion of Arctic Purple plate with tight 2.1mm bezel
            val bezelMargin = purplePlateRect.width() * 0.068f
            val screenSize = purplePlateRect.width() - 2f * bezelMargin
            val screenLeft = purplePlateRect.left + bezelMargin
            val screenTop = purplePlateRect.top + bezelMargin * 1.05f
            screenCutoutRect.set(screenLeft, screenTop, screenLeft + screenSize, screenTop + screenSize)

            epdChild.layout(
                screenCutoutRect.left.toInt(),
                screenCutoutRect.top.toInt(),
                screenCutoutRect.right.toInt(),
                screenCutoutRect.bottom.toInt()
            )
        }

        override fun onDraw(canvas: Canvas) {
            val amber = epdChild.uiState.skin == "amos"
            if (outerRailRect.isEmpty) return
            val caseW = outerRailRect.width()
            val cornerR = caseW * 0.105f
            val plateR = caseW * 0.075f

            // 1. Soft studio drop shadow behind CNC aluminum case
            paint.style = Paint.Style.FILL
            paint.shader = null
            paint.color = Color.argb(110, 0, 0, 0)
            canvas.drawRoundRect(
                RectF(outerRailRect.left + 8f, outerRailRect.top + 16f, outerRailRect.right + 8f, outerRailRect.bottom + 16f),
                cornerR, cornerR, paint
            )

            // 2. CNC 6061 Bead-Blasted Aluminum Side-Rail Frame
            paint.shader = LinearGradient(
                outerRailRect.left, outerRailRect.top, outerRailRect.right, outerRailRect.bottom,
                intArrayOf(
                    Color.rgb(214, 222, 232),
                    Color.rgb(164, 174, 188),
                    Color.rgb(126, 136, 150),
                    Color.rgb(178, 186, 198)
                ),
                floatArrayOf(0f, 0.35f, 0.75f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawRoundRect(outerRailRect, cornerR, cornerR, paint)

            // 45° Diamond-Cut Specular Chamfer Highlight on Aluminum Rail
            paint.shader = null
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = caseW * 0.008f
            paint.color = Color.argb(185, 242, 247, 255)
            canvas.drawRoundRect(chamferRect, cornerR * 0.90f, cornerR * 0.90f, paint)

            // Top PDM Microphone Pinhole on CNC Aluminum Top Rail
            paint.style = Paint.Style.FILL
            val micR = caseW * 0.013f
            val micX = outerRailRect.centerX() - caseW * 0.07f
            val micY = (outerRailRect.top + purplePlateRect.top) / 2f
            paint.color = Color.rgb(32, 36, 44)
            canvas.drawCircle(micX, micY, micR, paint)

            // 3. Stepped Rabbet Recess & Translucent "Arctic Purple" SLA Resin Front Plate
            paint.style = Paint.Style.FILL
            paint.shader = LinearGradient(
                purplePlateRect.left, purplePlateRect.top, purplePlateRect.right, purplePlateRect.bottom,
                intArrayOf(
                    if (amber) Color.rgb(224, 140, 40) else Color.rgb(112, 78, 204),
                    if (amber) Color.rgb(196, 110, 24) else Color.rgb(84, 52, 168),
                    if (amber) Color.rgb(150, 78, 14) else Color.rgb(62, 36, 132),
                    if (amber) Color.rgb(176, 96, 20) else Color.rgb(74, 44, 154)
                ),
                floatArrayOf(0f, 0.42f, 0.82f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawRoundRect(purplePlateRect, plateR, plateR, paint)

            // 4. Internal V2.5 Hardware Ghosting Through Translucent Arctic Purple Resin
            val chinTop = screenCutoutRect.bottom + caseW * 0.040f
            val chinBottom = purplePlateRect.bottom - caseW * 0.048f
            val chinMargin = purplePlateRect.width() * 0.068f
            chinWindowRect.set(
                purplePlateRect.left + chinMargin,
                chinTop,
                purplePlateRect.right - chinMargin,
                chinBottom
            )

            // Recessed internal V2.5 Matte-Black / Deep-Indigo PCB Cavity visible through resin
            paint.shader = null
            paint.color = if (amber) Color.argb(120, 40, 22, 6) else Color.argb(120, 24, 14, 52)
            canvas.drawRoundRect(chinWindowRect, caseW * 0.03f, caseW * 0.03f, paint)

            // Left & Right Gold ENIG / Copper Sensor Bus Bars visible inside the translucent chin
            val busW = caseW * 0.026f
            paint.color = Color.argb(135, 198, 136, 96)
            canvas.drawRoundRect(
                RectF(chinWindowRect.left + busW * 0.6f, chinWindowRect.top + busW, chinWindowRect.left + busW * 1.7f, chinWindowRect.bottom - busW * 1.4f),
                4f, 4f, paint
            )
            canvas.drawRoundRect(
                RectF(chinWindowRect.right - busW * 1.7f, chinWindowRect.top + busW * 2.5f, chinWindowRect.right - busW * 0.6f, chinWindowRect.bottom - busW),
                4f, 4f, paint
            )

            // Diagonal Frosted Translucent Resin Specular Sheen across Arctic Purple Faceplate
            paint.shader = LinearGradient(
                purplePlateRect.left, purplePlateRect.top, purplePlateRect.right, purplePlateRect.bottom,
                intArrayOf(
                    if (amber) Color.argb(46, 255, 220, 170) else Color.argb(46, 216, 198, 255),
                    if (amber) Color.argb(12, 255, 200, 140) else Color.argb(12, 180, 150, 255),
                    if (amber) Color.argb(0, 220, 150, 80) else Color.argb(0, 120, 90, 220),
                    if (amber) Color.argb(28, 255, 210, 160) else Color.argb(28, 190, 165, 255)
                ),
                floatArrayOf(0f, 0.35f, 0.70f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawRoundRect(purplePlateRect, plateR, plateR, paint)
            paint.shader = null

            // Inner rabbet border around Arctic Purple plate
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = caseW * 0.007f
            paint.color = if (amber) Color.argb(170, 255, 190, 110) else Color.argb(170, 168, 140, 245)
            canvas.drawRoundRect(purplePlateRect, plateR, plateR, paint)

            // E-Paper 2.1mm Bezel Cutout Frame Shadow
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = caseW * 0.012f
            paint.color = if (amber) Color.rgb(40, 24, 8) else Color.rgb(22, 16, 42)
            canvas.drawRect(
                screenCutoutRect.left - 2f,
                screenCutoutRect.top - 2f,
                screenCutoutRect.right + 2f,
                screenCutoutRect.bottom + 2f,
                paint
            )

            // 5. OV5640 5MP Autofocus Camera Barrel & Cyan Multi-Coated Lens (Lower-Right Chin)
            val camCx = chinWindowRect.left + chinWindowRect.width() * 0.73f
            val camCy = chinWindowRect.centerY() - chinWindowRect.height() * 0.04f
            val camOuterR = caseW * 0.112f

            // Outer dark anodized step-ring housing
            paint.style = Paint.Style.FILL
            paint.color = Color.rgb(20, 22, 34)
            canvas.drawCircle(camCx, camCy, camOuterR, paint)

            paint.style = Paint.Style.STROKE
            paint.strokeWidth = caseW * 0.008f
            paint.color = Color.rgb(92, 82, 142)
            canvas.drawCircle(camCx, camCy, camOuterR, paint)

            // Cyan-Teal AR-Coated Optical Glass Lens (matching V2.6 render)
            val lensR = camOuterR * 0.72f
            paint.style = Paint.Style.FILL
            paint.shader = RadialGradient(
                camCx - lensR * 0.25f,
                camCy - lensR * 0.25f,
                lensR * 1.1f,
                intArrayOf(
                    Color.rgb(42, 184, 216),
                    Color.rgb(18, 118, 152),
                    Color.rgb(10, 56, 78)
                ),
                floatArrayOf(0f, 0.58f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawCircle(camCx, camCy, lensR, paint)
            paint.shader = null

            // Inner aperture pupil & specular reflection glint
            paint.color = Color.argb(145, 8, 22, 34)
            canvas.drawCircle(camCx, camCy, lensR * 0.42f, paint)
            paint.color = Color.argb(190, 185, 245, 255)
            canvas.drawCircle(camCx - lensR * 0.30f, camCy - lensR * 0.30f, lensR * 0.15f, paint)

            // 6. Front-Mounted Machined Aluminum Physical Tactile Buttons (`BTN_TOP` & `BTN_BOT`)
            btnRadius = caseW * 0.076f
            btnTopCx = chinWindowRect.left + chinWindowRect.width() * 0.24f
            btnBotCx = chinWindowRect.left + chinWindowRect.width() * 0.47f
            btnTopCy = camCy - chinWindowRect.height() * 0.04f
            btnBotCy = camCy - chinWindowRect.height() * 0.04f

            drawMachinedAluminumButton(
                canvas = canvas,
                cx = btnTopCx,
                cy = btnTopCy,
                radius = btnRadius,
                pressed = btnTopPressed,
                topLabel = "PTT",
                subLabel = "2x LIVE"
            )
            drawMachinedAluminumButton(
                canvas = canvas,
                cx = btnBotCx,
                cy = btnBotCy,
                radius = btnRadius,
                pressed = btnBotPressed,
                topLabel = "SNAP",
                subLabel = "HOLD 5x"
            )

            // 7. V2.1 Diffused LED Listening Glow Bar at Bottom Chin Seam
            val ledW = purplePlateRect.width() * 0.52f
            val ledH = caseW * 0.034f
            val ledLeft = purplePlateRect.centerX() - ledW / 2f
            val ledTop = purplePlateRect.bottom - ledH * 1.45f
            ledBarRect.set(ledLeft, ledTop, ledLeft + ledW, ledTop + ledH)

            val isActiveGlow = epaperView.uiState.state in setOf("listening", "speaking", "thinking")
            val glowColor = if (isActiveGlow) Color.rgb(56, 238, 255) else Color.rgb(168, 138, 255)
            val coreColor = if (isActiveGlow) Color.rgb(210, 252, 255) else Color.rgb(206, 188, 255)

            // Outer diffused bloom in translucent resin
            paint.style = Paint.Style.FILL
            paint.color = Color.argb(if (isActiveGlow) 130 else 75, Color.red(glowColor), Color.green(glowColor), Color.blue(glowColor))
            canvas.drawRoundRect(
                RectF(ledBarRect.left - 8f, ledBarRect.top - 6f, ledBarRect.right + 8f, ledBarRect.bottom + 6f),
                ledH, ledH, paint
            )
            // Inner acrylic lightpipe bar
            paint.color = coreColor
            canvas.drawRoundRect(ledBarRect, ledH * 0.45f, ledH * 0.45f, paint)
        }

        private fun drawMachinedAluminumButton(
            canvas: Canvas,
            cx: Float,
            cy: Float,
            radius: Float,
            pressed: Boolean,
            topLabel: String,
            subLabel: String
        ) {
            val offset = if (pressed) 2.5f else 0f

            // Machined bore collar in Arctic Purple resin
            paint.style = Paint.Style.FILL
            paint.shader = null
            paint.color = Color.rgb(26, 16, 48)
            canvas.drawCircle(cx, cy, radius * 1.16f, paint)

            // Drop shadow
            if (!pressed) {
                paint.color = Color.argb(120, 8, 4, 20)
                canvas.drawCircle(cx + 2f, cy + 4f, radius * 1.04f, paint)
            }

            // Bead-blasted 6061 Aluminum Cap with metallic gradient
            val capR = radius * (if (pressed) 0.96f else 1.0f)
            paint.shader = LinearGradient(
                cx - capR, cy - capR + offset, cx + capR, cy + capR + offset,
                if (pressed) {
                    intArrayOf(Color.rgb(148, 158, 174), Color.rgb(184, 194, 208))
                } else {
                    intArrayOf(Color.rgb(236, 242, 250), Color.rgb(182, 192, 206), Color.rgb(134, 144, 160))
                },
                null,
                Shader.TileMode.CLAMP
            )
            canvas.drawCircle(cx, cy + offset, capR, paint)
            paint.shader = null

            // Specular diamond-turned rim on button cap
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = radius * 0.08f
            paint.color = Color.argb(210, 248, 250, 255)
            canvas.drawCircle(cx, cy + offset, capR * 0.92f, paint)

            // Laser-etched button label on cap + sub-caption below bore
            textPaint.typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            textPaint.textAlign = Paint.Align.CENTER
            textPaint.textSize = radius * 0.42f
            textPaint.color = Color.rgb(28, 32, 44)
            canvas.drawText(topLabel, cx, cy + offset + radius * 0.15f, textPaint)

            textPaint.textSize = radius * 0.30f
            textPaint.color = Color.rgb(214, 198, 255)
            canvas.drawText(subLabel, cx, cy + radius * 1.48f, textPaint)
        }

        override fun onTouchEvent(event: MotionEvent): Boolean {
            val x = event.x
            val y = event.y
            val hitRadius = btnRadius * 1.45f

            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    if (hypot((x - btnTopCx).toDouble(), (y - btnTopCy).toDouble()) <= hitRadius) {
                        activeTouchBtn = 1
                        btnTopPressed = true
                        invalidate()
                        handleBtnTopTouch(MotionEvent.ACTION_DOWN)
                        return true
                    }
                    if (hypot((x - btnBotCx).toDouble(), (y - btnBotCy).toDouble()) <= hitRadius) {
                        activeTouchBtn = 2
                        btnBotPressed = true
                        invalidate()
                        handleBtnBotTouch(MotionEvent.ACTION_DOWN)
                        return true
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    if (activeTouchBtn == 1) {
                        btnTopPressed = false
                        activeTouchBtn = 0
                        invalidate()
                        handleBtnTopTouch(MotionEvent.ACTION_UP)
                        return true
                    }
                    if (activeTouchBtn == 2) {
                        btnBotPressed = false
                        activeTouchBtn = 0
                        invalidate()
                        handleBtnBotTouch(MotionEvent.ACTION_UP)
                        return true
                    }
                }
            }
            return super.onTouchEvent(event)
        }
    }
}
