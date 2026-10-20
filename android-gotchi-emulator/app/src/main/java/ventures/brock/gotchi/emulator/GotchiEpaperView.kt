package ventures.brock.gotchi.emulator

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View

/**
 * 200x200 1-Bit Monochrome E-Paper Viewport & Refresh Physics Emulator (`GDEY0154D67-FT` V2.6).
 *
 * Emulates the exact 200x200 pixel layout from `poc/gotchi_poc.py` and `firmware/src/epd_panel.cpp`:
 * - 9 states: `idle`, `listening`, `transcribing`, `thinking`, `synthesizing`, `speaking`, `error`, `busy`, `offline`.
 * - Dual skins: `gotchi` (vector companion face) and `zero` (1-bit pre-baked sprites in `assets/zero_skin/`).
 * - Realistic warm e-ink substrate (`#EAE6DC`) and carbon pigment (`#141418`) with flush optical cover-glass sheen.
 * - `RefreshTracker` partial/full refresh policy (`maxConsecutivePartials = 8`, `fullRefreshMinutes = 15.0`).
 */
class GotchiEpaperView(context: Context) : View(context) {

    companion object {
        const val EPD_WIDTH = 200
        const val EPD_HEIGHT = 200
        const val PARTIAL_REFRESH_MS = 300L
        const val FULL_REFRESH_MS = 2000L

        val EINK_PAPER_COLOR = Color.rgb(234, 230, 220)
        val EINK_INK_COLOR = Color.rgb(20, 20, 24)

        val VALID_STATES = setOf(
            "idle", "listening", "transcribing", "thinking",
            "synthesizing", "speaking", "error", "busy", "offline"
        )
    }

    data class RefreshTracker(
        val maxConsecutivePartials: Int = 8,
        val fullRefreshMinutes: Double = 15.0,
        val busyTimeoutSeconds: Double = 30.0,
        var hasDrawnInitial: Boolean = false,
        var consecutivePartials: Int = 0,
        var lastFullRefreshMs: Long = 0L,
        val history: MutableList<String> = mutableListOf()
    ) {
        fun selectRefreshMode(nowMs: Long = SystemClock.elapsedRealtime(), forceFull: Boolean = false): String {
            if (forceFull || !hasDrawnInitial) return "full"
            if (consecutivePartials >= maxConsecutivePartials) return "full"
            if ((nowMs - lastFullRefreshMs) >= (fullRefreshMinutes * 60_000.0).toLong()) return "full"
            return "partial"
        }

        fun recordWrite(mode: String, succeeded: Boolean = true, nowMs: Long = SystemClock.elapsedRealtime()): String {
            val resolved = if (!succeeded && mode == "partial") "full" else mode
            if (resolved == "full") {
                hasDrawnInitial = true
                consecutivePartials = 0
                lastFullRefreshMs = nowMs
            } else {
                consecutivePartials += 1
            }
            history.add(resolved)
            return resolved
        }
    }

    data class UIState(
        var state: String = "idle",
        var transcript: String = "",
        var reply: String = "",
        var statusText: String = "READY (HOLD PTT)",
        var thinkingSeconds: Int = 0,
        var audioBytesReceived: Int = 0,
        var lastSampleRate: Int = 24000,
        var batteryPct: Int = 96,
        var skin: String = "zero", // "zero" | "gotchi"
        var lastRefreshMode: String = "full"
    )

    val refreshTracker = RefreshTracker()
    val uiState = UIState()
    private val frameBitmap = Bitmap.createBitmap(EPD_WIDTH, EPD_HEIGHT, Bitmap.Config.ARGB_8888)
    private val frameCanvas = Canvas(frameBitmap)
    private val destRect = RectF()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glassPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var fullFlashPhase: Int = 0 // 0=normal, 1=invert-black, 2=invert-white

    fun updateState(
        newState: String? = null,
        transcript: String? = null,
        reply: String? = null,
        statusText: String? = null,
        audioBytesDelta: Int = 0,
        sampleRate: Int? = null,
        forceFullRefresh: Boolean = false
    ) {
        newState?.let { uiState.state = if (it in VALID_STATES) it else "idle" }
        transcript?.let { uiState.transcript = it }
        reply?.let { uiState.reply = it }
        statusText?.let { uiState.statusText = it }
        if (audioBytesDelta > 0) uiState.audioBytesReceived += audioBytesDelta
        sampleRate?.let { uiState.lastSampleRate = it }

        val mode = refreshTracker.selectRefreshMode(forceFull = forceFullRefresh)
        uiState.lastRefreshMode = refreshTracker.recordWrite(mode, succeeded = true)
        render200x200Framebuffer()

        if (uiState.lastRefreshMode == "full") {
            fullFlashPhase = 1
            invalidate()
            postDelayed({ fullFlashPhase = 2; invalidate() }, 180L)
            postDelayed({ fullFlashPhase = 0; invalidate() }, 420L)
        } else {
            invalidate()
        }
    }

    fun render200x200Framebuffer(): Bitmap {
        val c = frameCanvas
        c.drawColor(EINK_PAPER_COLOR)

        val st = if (uiState.state in VALID_STATES) uiState.state else "idle"
        val badge = if (uiState.lastRefreshMode == "full") "FULL" else "PART"

        if (uiState.skin == "zero") {
            val assetPath = "zero_skin/zero_${st}_200x200_1bit.png"
            runCatching {
                context.assets.open(assetPath).use { stream ->
                    BitmapFactory.decodeStream(stream)?.let { rawBmp ->
                        // Tint pure white/black pixels to warm e-ink paper & carbon black
                        val tinted = Bitmap.createBitmap(EPD_WIDTH, EPD_HEIGHT, Bitmap.Config.ARGB_8888)
                        val pixels = IntArray(EPD_WIDTH * EPD_HEIGHT)
                        rawBmp.getPixels(pixels, 0, EPD_WIDTH, 0, 0, EPD_WIDTH, EPD_HEIGHT)
                        for (i in pixels.indices) {
                            val r = Color.red(pixels[i])
                            pixels[i] = if (r > 128) EINK_PAPER_COLOR else EINK_INK_COLOR
                        }
                        tinted.setPixels(pixels, 0, EPD_WIDTH, 0, 0, EPD_WIDTH, EPD_HEIGHT)
                        c.drawBitmap(tinted, 0f, 0f, null)
                    }
                }
            }
        } else {
            drawGotchiVectorFace(c, st)
        }

        // Top status bar (y = 0..20)
        paint.style = Paint.Style.FILL
        paint.color = EINK_INK_COLOR
        c.drawRect(0f, 0f, 200f, 20f, paint)

        paint.color = EINK_PAPER_COLOR
        paint.typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        paint.textSize = 10.5f
        val prefix = if (uiState.skin == "zero") "ZERO" else "GOTCHI"
        c.drawText("$prefix // ${st.uppercase()}", 5f, 14f, paint)
        c.drawText("${uiState.batteryPct}% $badge", 136f, 14f, paint)

        // Outer 1-bit border
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f
        paint.color = EINK_INK_COLOR
        c.drawRect(1f, 1f, 199f, 199f, paint)

        // Bottom caption tray (y = 148..199)
        paint.style = Paint.Style.FILL
        paint.color = EINK_PAPER_COLOR
        c.drawRect(2f, 149f, 198f, 198f, paint)
        paint.color = EINK_INK_COLOR
        c.drawLine(0f, 148f, 200f, 148f, paint)

        val primaryText = when {
            uiState.reply.isNotBlank() -> uiState.reply
            uiState.transcript.isNotBlank() -> uiState.transcript
            else -> uiState.statusText
        }
        val line1 = primaryText.take(26)
        val line2 = if (primaryText.length > 26) {
            primaryText.substring(26, minOf(52, primaryText.length))
        } else {
            "SR:${uiState.lastSampleRate / 1000}k ${uiState.skin.uppercase()} SKIN V2.6"
        }

        paint.typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        paint.textSize = 11.5f
        c.drawText(line1, 6f, 165f, paint)

        paint.typeface = Typeface.create(Typeface.MONOSPACE, Typeface.NORMAL)
        paint.textSize = 10.0f
        c.drawText(line2.take(28), 6f, 182f, paint)

        return frameBitmap
    }

    private fun drawGotchiVectorFace(c: Canvas, st: String) {
        paint.color = EINK_INK_COLOR
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 3f
        c.drawRoundRect(RectF(42f, 30f, 158f, 134f), 18f, 18f, paint)

        paint.style = Paint.Style.FILL
        val leftEar = Path().apply { moveTo(56f, 30f); lineTo(66f, 18f); lineTo(76f, 30f); close() }
        val rightEar = Path().apply { moveTo(124f, 30f); lineTo(134f, 18f); lineTo(144f, 30f); close() }
        c.drawPath(leftEar, paint)
        c.drawPath(rightEar, paint)

        when (st) {
            "idle" -> {
                c.drawOval(RectF(66f, 62f, 82f, 78f), paint)
                c.drawOval(RectF(118f, 62f, 134f, 78f), paint)
                paint.color = EINK_PAPER_COLOR
                c.drawOval(RectF(70f, 65f, 75f, 70f), paint)
                c.drawOval(RectF(122f, 65f, 127f, 70f), paint)
                paint.color = EINK_INK_COLOR
                paint.style = Paint.Style.STROKE
                c.drawArc(RectF(82f, 88f, 118f, 110f), 15f, 150f, false, paint)
            }
            "listening" -> {
                paint.style = Paint.Style.STROKE
                c.drawOval(RectF(62f, 58f, 84f, 80f), paint)
                c.drawOval(RectF(116f, 58f, 138f, 80f), paint)
                c.drawOval(RectF(91f, 94f, 109f, 112f), paint)
                paint.style = Paint.Style.FILL
                c.drawOval(RectF(69f, 65f, 77f, 73f), paint)
                c.drawOval(RectF(123f, 65f, 131f, 73f), paint)
            }
            "transcribing" -> {
                c.drawRect(64f, 66f, 84f, 76f, paint)
                c.drawRect(116f, 66f, 136f, 76f, paint)
                val bars = intArrayOf(6, 14, 10, 18, 8, 14, 6)
                for (i in bars.indices) {
                    val bx = 72f + i * 9f
                    val h = bars[i] / 2f
                    c.drawRect(bx, 104f - h, bx + 5f, 104f + h, paint)
                }
            }
            "thinking", "synthesizing" -> {
                c.drawOval(RectF(66f, 56f, 82f, 72f), paint)
                c.drawOval(RectF(118f, 56f, 134f, 72f), paint)
                paint.style = Paint.Style.STROKE
                c.drawLine(84f, 102f, 116f, 102f, paint)
                c.drawOval(RectF(162f, 48f, 170f, 56f), paint)
                c.drawOval(RectF(172f, 34f, 186f, 48f), paint)
            }
            "speaking" -> {
                paint.style = Paint.Style.STROKE
                c.drawLine(64f, 74f, 74f, 62f, paint)
                c.drawLine(74f, 62f, 84f, 74f, paint)
                c.drawLine(116f, 74f, 126f, 62f, paint)
                c.drawLine(126f, 62f, 136f, 74f, paint)
                paint.style = Paint.Style.FILL
                c.drawArc(RectF(80f, 90f, 120f, 118f), 0f, 180f, true, paint)
            }
            else -> {
                paint.style = Paint.Style.STROKE
                c.drawLine(64f, 60f, 82f, 78f, paint)
                c.drawLine(82f, 60f, 64f, 78f, paint)
                c.drawLine(118f, 60f, 136f, 78f, paint)
                c.drawLine(136f, 60f, 118f, 78f, paint)
                c.drawArc(RectF(82f, 98f, 118f, 118f), 195f, 150f, false, paint)
            }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = minOf(width, height).toFloat()
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        destRect.set(left, top, left + size, top + size)

        when (fullFlashPhase) {
            1 -> {
                paint.style = Paint.Style.FILL
                paint.color = EINK_INK_COLOR
                canvas.drawRect(destRect, paint)
            }
            2 -> {
                paint.style = Paint.Style.FILL
                paint.color = EINK_PAPER_COLOR
                canvas.drawRect(destRect, paint)
            }
            else -> {
                paint.isFilterBitmap = false
                canvas.drawBitmap(frameBitmap, null, destRect, paint)
                // Subtle diagonal GDEY0154D67-FT optical cover-glass reflection sweep
                glassPaint.shader = LinearGradient(
                    left, top, left + size, top + size,
                    intArrayOf(
                        Color.argb(24, 255, 255, 255),
                        Color.argb(6, 255, 255, 255),
                        Color.argb(0, 255, 255, 255)
                    ),
                    floatArrayOf(0f, 0.42f, 1f),
                    Shader.TileMode.CLAMP
                )
                canvas.drawRect(destRect, glassPaint)
            }
        }
    }
}
