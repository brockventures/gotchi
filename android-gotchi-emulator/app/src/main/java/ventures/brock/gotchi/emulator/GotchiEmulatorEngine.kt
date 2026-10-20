package ventures.brock.gotchi.emulator

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.util.Base64
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.InputStreamReader
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.math.sqrt

/**
 * Hardware-Parity GOTCHI V1 Emulator Engine (Forked from `GotchiBleRelayService.kt`).
 *
 * Implements the complete ESP32-S3 firmware state machine and wire contracts on Android:
 * - `POST /api/voice/interact` multipart WAV (`16 kHz` PCM16) + single (`image`) / 5-frame burst (`image_0`..`image_4`)
 *   upload and streaming SSE parser (`state`, `transcript`, `reply`, `sentence` / `audio_chunk` `24 kHz` PCM16, `done`, `error`).
 * - `/api/live/ws` RFC 6455 bidirectional Go Live streaming with hardware `AcousticEchoCanceler`,
 *   300ms full-duplex speech barge-in (`{"type":"barge_in"}`), and mid-session camera injection.
 * - `POST /api/journal/ingest` (`mode="journal"`) duty-cycled acoustic VAD segment dispatch.
 */
class GotchiEmulatorEngine(
    private val onStateUpdate: (state: String?, transcript: String?, reply: String?, status: String?, audioBytes: Int, sampleRate: Int?) -> Unit
) {

    companion object {
        const val MIC_SAMPLE_RATE = 16000
        const val TTS_DEFAULT_SAMPLE_RATE = 24000
        const val PRE_ROLL_MS = 500
        const val DEFAULT_PTT_SILENCE_MS = 1500L
        const val DEFAULT_LIVE_SILENCE_MS = 15000L
        const val BARGE_IN_SPEECH_MS = 300L
        const val DEFAULT_RMS_THRESHOLD = 50.0
        const val DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765"
        const val DEFAULT_NODE_ID = "gotchi-android-emu-01"

        val NODE_ID_REGEX = Regex("^[A-Za-z0-9_-]{1,64}$")
        val VALID_AUDIO_OUT_MODES = setOf("speaker", "discord_voice", "ble_phone")

        fun validateNodeId(nodeId: String): Boolean = NODE_ID_REGEX.matches(nodeId)

        /**
         * Wrap raw 16-bit signed little-endian PCM bytes in a standard 44-byte RIFF WAV header.
         */
        fun wrapPcm16ToWav(pcmBytes: ByteArray, sampleRate: Int = MIC_SAMPLE_RATE, channels: Int = 1): ByteArray {
            val byteRate = sampleRate * channels * 2
            val blockAlign = channels * 2
            val dataSize = pcmBytes.size
            val buf = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN)
            buf.put("RIFF".toByteArray(Charsets.US_ASCII))
            buf.putInt(36 + dataSize)
            buf.put("WAVE".toByteArray(Charsets.US_ASCII))
            buf.put("fmt ".toByteArray(Charsets.US_ASCII))
            buf.putInt(16)
            buf.putShort(1) // PCM format
            buf.putShort(channels.toShort())
            buf.putInt(sampleRate)
            buf.putInt(byteRate)
            buf.putShort(blockAlign.toShort())
            buf.putShort(16) // 16-bit
            buf.put("data".toByteArray(Charsets.US_ASCII))
            buf.putInt(dataSize)
            buf.put(pcmBytes)
            return buf.array()
        }

        /**
         * Walk RIFF/WAV chunks to the `data` subchunk (matching `parseWAVHeader` in firmware
         * and `extract_pcm_from_wav_or_raw` in `backend/voice_gateway.py`), or return raw PCM.
         */
        fun extractPcmFromWavOrRaw(raw: ByteArray, defaultSampleRate: Int = TTS_DEFAULT_SAMPLE_RATE): Pair<ByteArray, Int> {
            if (raw.size < 44) return Pair(raw, defaultSampleRate)
            val headerTag = String(raw, 0, 4, Charsets.US_ASCII)
            val waveTag = String(raw, 8, 4, Charsets.US_ASCII)
            if (headerTag != "RIFF" || waveTag != "WAVE") {
                return Pair(raw, defaultSampleRate)
            }
            var offset = 12
            var sampleRate = defaultSampleRate
            while (offset + 8 <= raw.size) {
                val chunkId = String(raw, offset, 4, Charsets.US_ASCII)
                val chunkSize = ByteBuffer.wrap(raw, offset + 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
                val dataStart = offset + 8
                if (chunkSize < 0 || dataStart > raw.size) break
                if (chunkId == "fmt " && chunkSize >= 16 && dataStart + 8 <= raw.size) {
                    sampleRate = ByteBuffer.wrap(raw, dataStart + 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
                } else if (chunkId == "data") {
                    val end = minOf(raw.size, dataStart + chunkSize)
                    return Pair(raw.copyOfRange(dataStart, end), sampleRate)
                }
                offset = dataStart + chunkSize + (chunkSize and 1)
            }
            return Pair(raw.copyOfRange(44, raw.size), sampleRate)
        }

        fun computePcm16Rms(pcmBytes: ByteArray, length: Int = pcmBytes.size): Double {
            val sampleCount = length / 2
            if (sampleCount <= 0) return 0.0
            var sumSq = 0.0
            val buf = ByteBuffer.wrap(pcmBytes, 0, sampleCount * 2).order(ByteOrder.LITTLE_ENDIAN)
            for (i in 0 until sampleCount) {
                val s = buf.short.toDouble()
                sumSq += s * s
            }
            return sqrt(sumSq / sampleCount)
        }
    }

    data class Config(
        var gatewayUrl: String = DEFAULT_GATEWAY_URL,
        var bearerToken: String = "",
        var nodeId: String = DEFAULT_NODE_ID,
        var sessionId: String = "sess-android-01",
        var audioOutMode: String = "speaker", // "speaker" | "discord_voice" | "ble_phone"
        var pttSilenceMs: Long = DEFAULT_PTT_SILENCE_MS,
        var liveSilenceMs: Long = DEFAULT_LIVE_SILENCE_MS,
        var liveBargeIn: Boolean = false,
        var journalMode: Boolean = false
    )

    val config = Config()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val preRollCapacityBytes = (MIC_SAMPLE_RATE * 2 * PRE_ROLL_MS) / 1000
    private val preRollRing = ByteArray(preRollCapacityBytes)
    private var preRollWritePos = 0
    private var preRollFilled = false

    private val pendingBurstImages = mutableMapOf<Int, ByteArray>()
    private var recordingJob: Job? = null
    private var isPttRecording = false
    private var activeLiveWs: WebSocket? = null
    private var liveSessionActive = false

    fun writePreRollBytes(chunk: ByteArray, len: Int = chunk.size) {
        for (i in 0 until len) {
            preRollRing[preRollWritePos] = chunk[i]
            preRollWritePos = (preRollWritePos + 1) % preRollCapacityBytes
            if (preRollWritePos == 0) preRollFilled = true
        }
    }

    fun snapshotPreRollBytes(): ByteArray {
        if (!preRollFilled) {
            return preRollRing.copyOfRange(0, preRollWritePos)
        }
        val out = ByteArray(preRollCapacityBytes)
        val tailLen = preRollCapacityBytes - preRollWritePos
        System.arraycopy(preRollRing, preRollWritePos, out, 0, tailLen)
        System.arraycopy(preRollRing, 0, out, tailLen, preRollWritePos)
        return out
    }

    fun attachSnapshot(jpegBytes: ByteArray, frameIndex: Int = 0) {
        pendingBurstImages[frameIndex.coerceIn(0, 4)] = jpegBytes
        onStateUpdate(null, null, null, "SNAP #${frameIndex + 1} (${jpegBytes.size / 1024}KB)", 0, null)
    }

    @SuppressLint("MissingPermission")
    fun startPttCapture(autoVadStop: Boolean = false) {
        if (isPttRecording) return
        if (liveSessionActive) {
            stopLiveSession()
            return
        }
        isPttRecording = true
        onStateUpdate("listening", "", "", "REC 16kHz PDM MIC...", 0, null)

        recordingJob = scope.launch {
            val pcmStream = ByteArrayOutputStream()
            val preRoll = snapshotPreRollBytes()
            if (preRoll.isNotEmpty()) pcmStream.write(preRoll)

            val minBuf = AudioRecord.getMinBufferSize(
                MIC_SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            ).coerceAtLeast(3200)

            val recorder = runCatching {
                AudioRecord(
                    MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    MIC_SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuf
                )
            }.getOrNull()

            val readBuf = ByteArray(1600) // 50ms @ 16kHz PCM16
            var lastVoiceMs = System.currentTimeMillis()
            var heardSpeech = false

            try {
                recorder?.startRecording()
                while (isActive && isPttRecording) {
                    val read = recorder?.read(readBuf, 0, readBuf.size) ?: -1
                    if (read > 0) {
                        pcmStream.write(readBuf, 0, read)
                        val rms = computePcm16Rms(readBuf, read)
                        if (rms >= DEFAULT_RMS_THRESHOLD) {
                            heardSpeech = true
                            lastVoiceMs = System.currentTimeMillis()
                        } else if (autoVadStop && heardSpeech &&
                            (System.currentTimeMillis() - lastVoiceMs) >= config.pttSilenceMs
                        ) {
                            isPttRecording = false
                            break
                        }
                    } else {
                        delay(25)
                    }
                }
            } finally {
                runCatching { recorder?.stop(); recorder?.release() }
            }

            val rawPcm = pcmStream.toByteArray()
            val wavBytes = wrapPcm16ToWav(rawPcm, MIC_SAMPLE_RATE, 1)
            val images = pendingBurstImages.toSortedMap()
            pendingBurstImages.clear()
            dispatchVoiceTurn(wavBytes = wavBytes, images = images)
        }
    }

    fun stopPttAndCommit() {
        if (!isPttRecording) return
        isPttRecording = false
    }

    fun dispatchStandaloneSnapshotTurn(images: Map<Int, ByteArray>, prompt: String? = null) {
        scope.launch {
            dispatchVoiceTurn(wavBytes = ByteArray(0), images = images, prompt = prompt)
        }
    }

    suspend fun dispatchVoiceTurn(
        wavBytes: ByteArray,
        images: Map<Int, ByteArray> = emptyMap(),
        prompt: String? = null,
        mode: String? = null
    ) {
        val safeNodeId = if (validateNodeId(config.nodeId)) config.nodeId else DEFAULT_NODE_ID
        val safeAudioOut = if (config.audioOutMode in VALID_AUDIO_OUT_MODES) config.audioOutMode else "speaker"

        onStateUpdate("transcribing", null, null, "UPLOADING TURN...", 0, null)

        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("node_id", safeNodeId)
            .addFormDataPart("session_id", config.sessionId)
            .addFormDataPart("audio_out_mode", safeAudioOut)

        if (!prompt.isNullOrBlank()) {
            multipart.addFormDataPart("prompt", prompt)
        }
        if (!mode.isNullOrBlank()) {
            multipart.addFormDataPart("mode", mode)
        }
        if (wavBytes.isNotEmpty()) {
            multipart.addFormDataPart(
                "audio",
                "ptt.wav",
                wavBytes.toRequestBody("audio/wav".toMediaType())
            )
        }
        if (images.size == 1 && images.containsKey(0)) {
            multipart.addFormDataPart(
                "image",
                "snap.jpg",
                images.getValue(0).toRequestBody("image/jpeg".toMediaType())
            )
        } else {
            for ((idx, jpeg) in images) {
                multipart.addFormDataPart(
                    "image_$idx",
                    "snap_$idx.jpg",
                    jpeg.toRequestBody("image/jpeg".toMediaType())
                )
            }
        }

        val baseUrl = config.gatewayUrl.trimEnd('/')
        val reqBuilder = Request.Builder()
            .url("$baseUrl/api/voice/interact")
            .post(multipart.build())
        if (config.bearerToken.isNotBlank()) {
            reqBuilder.header("Authorization", "Bearer ${config.bearerToken}")
        }

        try {
            httpClient.newCall(reqBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    onStateUpdate("error", null, null, "HTTP ${response.code}", 0, null)
                    return
                }
                val body = response.body ?: return
                val reader = BufferedReader(InputStreamReader(body.byteStream(), Charsets.UTF_8))
                var curEvent = "message"
                val dataLines = mutableListOf<String>()

                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) {
                        if (dataLines.isNotEmpty()) {
                            handleSseEvent(curEvent, dataLines.joinToString("\n"), safeAudioOut)
                            dataLines.clear()
                        }
                        curEvent = "message"
                    } else if (line.startsWith("event:")) {
                        curEvent = line.removePrefix("event:").trim()
                    } else if (line.startsWith("data:")) {
                        dataLines.add(line.removePrefix("data:").trim())
                    }
                }
            }
        } catch (e: Exception) {
            onStateUpdate("error", null, null, (e.message ?: "offline").take(24), 0, null)
        }
    }

    internal fun handleSseEvent(eventType: String, rawData: String, audioOutMode: String) {
        val obj = runCatching { JSONObject(rawData) }.getOrNull() ?: JSONObject()
        when (eventType) {
            "state" -> {
                val st = obj.optString("state", "idle")
                onStateUpdate(st, null, null, st.uppercase(), 0, null)
            }
            "transcript" -> {
                val tr = obj.optString("transcript", "")
                onStateUpdate(null, tr, null, "HEARD", 0, null)
            }
            "thinking" -> {
                val sec = obj.optInt("elapsed_seconds", 0)
                onStateUpdate("thinking", null, null, "THINKING (${sec}s)", 0, null)
            }
            "reply" -> {
                val rep = obj.optString("reply", "")
                onStateUpdate(null, null, rep, "SPEAKING", 0, null)
            }
            "sentence", "audio_chunk" -> {
                val b64 = when {
                    obj.has("audio_b64") -> obj.optString("audio_b64", "")
                    obj.has("pcm_b64") -> obj.optString("pcm_b64", "")
                    else -> obj.optString("data", "")
                }
                val defaultSr = obj.optInt("sample_rate", TTS_DEFAULT_SAMPLE_RATE)
                if (b64.isNotEmpty()) {
                    val decoded = Base64.decode(b64, Base64.DEFAULT)
                    val (pcmBytes, sr) = extractPcmFromWavOrRaw(decoded, defaultSr)
                    onStateUpdate("speaking", null, null, "PLAYING ${sr / 1000}kHz", pcmBytes.size, sr)
                    if (audioOutMode != "discord_voice") {
                        playPcmOnSpeaker(pcmBytes, sr)
                    }
                }
            }
            "error" -> {
                val msg = obj.optString("message", obj.optString("error", "error"))
                onStateUpdate("error", null, null, msg.take(24), 0, null)
            }
            "done" -> {
                val dur = obj.optInt("duration_ms", 0)
                onStateUpdate("idle", null, null, "DONE (${dur}ms)", 0, null)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun startLiveSession() {
        if (liveSessionActive) return
        liveSessionActive = true
        val wsUrl = config.gatewayUrl.trimEnd('/')
            .replaceFirst("https://", "wss://")
            .replaceFirst("http://", "ws://") + "/api/live/ws"

        val reqBuilder = Request.Builder().url(wsUrl)
        if (config.bearerToken.isNotBlank()) {
            reqBuilder.header("Authorization", "Bearer ${config.bearerToken}")
        }

        onStateUpdate("listening", "", "", "GO LIVE // CONNECTING", 0, null)
        activeLiveWs = httpClient.newWebSocket(reqBuilder.build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                val hello = JSONObject()
                    .put("type", "hello")
                    .put("node_id", config.nodeId)
                    .put("sample_rate", MIC_SAMPLE_RATE)
                    .put("live_barge_in", config.liveBargeIn)
                webSocket.send(hello.toString())
                onStateUpdate("listening", null, null, "GO LIVE // ACTIVE", 0, null)
                launchLiveAudioLoop(webSocket)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val obj = runCatching { JSONObject(text) }.getOrNull() ?: return
                when (obj.optString("type")) {
                    "audio" -> {
                        val b64 = obj.optString("audio_b64", obj.optString("data", ""))
                        val sr = obj.optInt("sample_rate", TTS_DEFAULT_SAMPLE_RATE)
                        if (b64.isNotEmpty()) {
                            val pcm = Base64.decode(b64, Base64.DEFAULT)
                            onStateUpdate("speaking", null, null, "LIVE // SPEAKING", pcm.size, sr)
                            playPcmOnSpeaker(pcm, sr)
                        }
                    }
                    "transcript" -> onStateUpdate(null, obj.optString("text", ""), null, "LIVE // HEARD", 0, null)
                    "reply" -> onStateUpdate(null, null, obj.optString("text", ""), "LIVE // REPLY", 0, null)
                    "state" -> onStateUpdate(obj.optString("state", "listening"), null, null, "LIVE", 0, null)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                liveSessionActive = false
                onStateUpdate("error", null, null, "LIVE DISCONNECTED", 0, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                liveSessionActive = false
                onStateUpdate("idle", null, null, "LIVE ENDED", 0, null)
            }
        })
    }

    @SuppressLint("MissingPermission")
    private fun launchLiveAudioLoop(ws: WebSocket) {
        scope.launch {
            val minBuf = AudioRecord.getMinBufferSize(
                MIC_SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            ).coerceAtLeast(3200)
            val recorder = runCatching {
                AudioRecord(
                    MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    MIC_SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuf
                )
            }.getOrNull()

            val aec = runCatching {
                if (recorder != null && AcousticEchoCanceler.isAvailable()) {
                    AcousticEchoCanceler.create(recorder.audioSessionId)?.apply { enabled = true }
                } else null
            }.getOrNull()

            val buf = ByteArray(1600) // 50ms frame
            var lastVoiceMs = System.currentTimeMillis()
            var continuousVoiceMs = 0L

            try {
                recorder?.startRecording()
                while (isActive && liveSessionActive) {
                    val read = recorder?.read(buf, 0, buf.size) ?: -1
                    if (read > 0) {
                        val slice = buf.copyOfRange(0, read)
                        val rms = computePcm16Rms(slice)
                        if (rms >= DEFAULT_RMS_THRESHOLD) {
                            lastVoiceMs = System.currentTimeMillis()
                            continuousVoiceMs += 50L
                            if (config.liveBargeIn && continuousVoiceMs >= BARGE_IN_SPEECH_MS) {
                                ws.send(JSONObject().put("type", "barge_in").toString())
                                continuousVoiceMs = 0L
                            }
                        } else {
                            continuousVoiceMs = 0L
                            if ((System.currentTimeMillis() - lastVoiceMs) >= config.liveSilenceMs) {
                                stopLiveSession()
                                break
                            }
                        }
                        val frameMsg = JSONObject()
                            .put("type", "audio")
                            .put("sample_rate", MIC_SAMPLE_RATE)
                            .put("audio_b64", Base64.encodeToString(slice, Base64.NO_WRAP))
                        ws.send(frameMsg.toString())
                    } else {
                        delay(25)
                    }
                }
            } finally {
                runCatching { aec?.release() }
                runCatching { recorder?.stop(); recorder?.release() }
            }
        }
    }

    fun sendLiveCameraFrames(frames: List<ByteArray>) {
        val ws = activeLiveWs ?: return
        if (frames.size == 1) {
            val msg = JSONObject()
                .put("type", "image")
                .put("image_b64", Base64.encodeToString(frames[0], Base64.NO_WRAP))
            ws.send(msg.toString())
        } else if (frames.isNotEmpty()) {
            val arr = JSONArray()
            frames.take(5).forEach { arr.put(Base64.encodeToString(it, Base64.NO_WRAP)) }
            val msg = JSONObject().put("type", "image_burst").put("images_b64", arr)
            ws.send(msg.toString())
        }
    }

    fun stopLiveSession() {
        liveSessionActive = false
        activeLiveWs?.close(1000, "user_exit")
        activeLiveWs = null
        onStateUpdate("idle", null, null, "READY (HOLD PTT)", 0, null)
    }

    private fun playPcmOnSpeaker(pcmBytes: ByteArray, sampleRate: Int) {
        if (pcmBytes.isEmpty()) return
        runCatching {
            val minBuf = AudioTrack.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            ).coerceAtLeast(pcmBytes.size)
            val track = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(sampleRate)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(minBuf)
                .setTransferMode(AudioTrack.MODE_STATIC)
                .build()
            track.write(pcmBytes, 0, pcmBytes.size)
            track.play()
        }
    }

    fun shutdown() {
        stopLiveSession()
        scope.cancel()
    }
}
