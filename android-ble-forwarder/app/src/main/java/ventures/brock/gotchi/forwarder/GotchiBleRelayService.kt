package ventures.brock.gotchi.forwarder

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Build
import android.os.IBinder
import android.os.ParcelUuid
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.InputStreamReader
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Headless Android Foreground Service for GOTCHI V1 BLE-to-Tailscale Relay (F18 / T4.2).
 *
 * Responsibilities:
 * 1. Scans and auto-bonds to the GOTCHI BLE GATT UART service (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`),
 *    requesting BLE 5.0 2M PHY and 512-byte ATT MTU.
 * 2. Reassembles binary-framed PTT uplink streams (`AUDIO_CHUNK`, `IMAGE_FRAME` 0..4, `TURN_COMMIT`)
 *    validated via CRC-16/CCITT header checks and IEEE 802.3 CRC-32 payload trailers.
 * 3. Relays assembled voice/vision turns over Tailscale (`POST /api/voice/interact`) with
 *    `Authorization: Bearer <token>` and `audio_out_mode` metadata.
 * 4. Streams returned SSE events (`state`, `transcript`, `reply`, `audio_chunk`, `done`, `error`)
 *    back down BLE as fragmented `SSE_EVENT` frames so GOTCHI updates its e-paper sprite and speaker.
 * 5. When `audio_out_mode == "ble_phone"`, decodes 24 kHz 16-bit mono PCM `audio_chunk` payloads
 *    and plays them locally on the phone / Bluetooth earbuds via Android `AudioTrack` while still
 *    forwarding sprite `state` / `done` events to GOTCHI.
 */
@SuppressLint("MissingPermission")
class GotchiBleRelayService : Service() {

    companion object {
        private const val TAG = "GotchiBleRelay"
        private const val CHANNEL_ID = "gotchi_ble_relay"
        private const val NOTIFICATION_ID = 4742

        val SERVICE_UUID: UUID = UUID.fromString("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        val CHAR_TX_UUID: UUID = UUID.fromString("6E400003-B5A3-F393-E0A9-E50E24DCCA9E") // GOTCHI -> Phone (Notify)
        val CHAR_RX_UUID: UUID = UUID.fromString("6E400002-B5A3-F393-E0A9-E50E24DCCA9E") // Phone -> GOTCHI (Write)
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

        const val PREFS_NAME = "gotchi_relay_prefs"
        const val KEY_GATEWAY_URL = "gateway_url"
        const val KEY_BEARER_TOKEN = "bearer_token"
        const val KEY_NODE_ID = "node_id"
        const val KEY_AUDIO_OUT_MODE = "audio_out_mode"

        const val DEFAULT_GATEWAY_URL = "http://gotchi.local:8765"
        const val DEFAULT_NODE_ID = "gotchi-v1"
        const val DEFAULT_AUDIO_OUT_MODE = "speaker"
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val reassembler = BleReassembler()
    private val audioStreamBuffer = ByteArrayOutputStream()
    private val imageFrames = mutableMapOf<Int, ByteArray>()
    private var downlinkSeqNum: Int = 0
    private var negotiatedMaxPayload: Int = BleFramingCodec.DEFAULT_MAX_PAYLOAD
    private var activeGatt: BluetoothGatt? = null
    private var rxCharacteristic: BluetoothGattCharacteristic? = null

    override fun onCreate() {
        super.onCreate()
        startForegroundWithNotification("Scanning for GOTCHI over BLE...")
        startBleScan()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        intent?.let {
            val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            it.getStringExtra(KEY_GATEWAY_URL)?.let { url -> prefs.putString(KEY_GATEWAY_URL, url) }
            it.getStringExtra(KEY_BEARER_TOKEN)?.let { tok -> prefs.putString(KEY_BEARER_TOKEN, tok) }
            it.getStringExtra(KEY_NODE_ID)?.let { node -> prefs.putString(KEY_NODE_ID, node) }
            it.getStringExtra(KEY_AUDIO_OUT_MODE)?.let { mode -> prefs.putString(KEY_AUDIO_OUT_MODE, mode) }
            prefs.apply()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        activeGatt?.close()
        activeGatt = null
        serviceScope.cancel()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startForegroundWithNotification(statusText: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "GOTCHI BLE Relay",
                NotificationManager.IMPORTANCE_LOW
            )
            nm.createNotificationChannel(channel)
        }
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("GOTCHI Companion Relay")
                .setContentText(statusText)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setOngoing(true)
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("GOTCHI Companion Relay")
                .setContentText(statusText)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setOngoing(true)
                .build()
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun startBleScan() {
        val btManager = getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter: BluetoothAdapter? = btManager?.adapter
        val scanner = adapter?.bluetoothLeScanner ?: return

        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER)
            .build()

        scanner.startScan(listOf(filter), settings, scanCallback)
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device: BluetoothDevice = result.device ?: return
            if (activeGatt != null) return
            val btManager = getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            btManager?.adapter?.bluetoothLeScanner?.stopScan(this)
            activeGatt = device.connectGatt(this@GotchiBleRelayService, true, gattCallback, BluetoothDevice.TRANSPORT_LE)
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    gatt.setPreferredPhy(
                        BluetoothDevice.PHY_LE_2M_MASK,
                        BluetoothDevice.PHY_LE_2M_MASK,
                        BluetoothDevice.PHY_OPTION_NO_PREFERRED
                    )
                }
                gatt.requestMtu(BleFramingCodec.DEFAULT_GATT_MTU)
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                reassembler.resetSequenceTracking()
                audioStreamBuffer.reset()
                imageFrames.clear()
                rxCharacteristic = null
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS && mtu > BleFramingCodec.OVERHEAD_BYTES + 3) {
                negotiatedMaxPayload = minOf(
                    mtu - 3 - BleFramingCodec.OVERHEAD_BYTES,
                    BleFramingCodec.DEFAULT_MAX_PAYLOAD
                )
            }
            gatt.discoverServices()
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) return
            val service = gatt.getService(SERVICE_UUID) ?: return
            rxCharacteristic = service.getCharacteristic(CHAR_RX_UUID)
            val txChar = service.getCharacteristic(CHAR_TX_UUID) ?: return
            gatt.setCharacteristicNotification(txChar, true)
            txChar.getDescriptor(CCCD_UUID)?.let { desc ->
                desc.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                gatt.writeDescriptor(desc)
            }
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            if (characteristic.uuid == CHAR_TX_UUID) {
                handleIncomingBlePacket(characteristic.value ?: return)
            }
        }
    }

    internal fun handleIncomingBlePacket(rawPacket: ByteArray) {
        try {
            val completed = reassembler.pushPacket(rawPacket) ?: return
            if ((completed.flags and BleFramingCodec.FLAG_REQUIRES_ACK) != 0) {
                val ackPayload = ByteArray(2) { idx ->
                    ((completed.seqNum shr (idx * 8)) and 0xFF).toByte()
                }
                sendBleFrame(BleFramingCodec.FrameType.ACK, ackPayload)
            }
            when (completed.frameType) {
                BleFramingCodec.FrameType.AUDIO_CHUNK -> {
                    if ((completed.flags and BleFramingCodec.FLAG_FIRST_CHUNK) != 0 &&
                        audioStreamBuffer.size() == 0
                    ) {
                        audioStreamBuffer.reset()
                    }
                    audioStreamBuffer.write(completed.payload)
                }
                BleFramingCodec.FrameType.IMAGE_FRAME -> {
                    imageFrames[completed.frameIndex] = completed.payload
                }
                BleFramingCodec.FrameType.TURN_COMMIT -> {
                    val commitMeta = if (completed.payload.isNotEmpty()) {
                        runCatching { JSONObject(String(completed.payload, Charsets.UTF_8)) }.getOrNull()
                    } else null
                    val wavBytes = audioStreamBuffer.toByteArray()
                    val capturedImages = imageFrames.toSortedMap()
                    audioStreamBuffer.reset()
                    imageFrames.clear()
                    serviceScope.launch {
                        forwardTurnToGateway(wavBytes, capturedImages, commitMeta)
                    }
                }
                BleFramingCodec.FrameType.CANCEL -> {
                    reassembler.reset()
                    audioStreamBuffer.reset()
                    imageFrames.clear()
                }
                else -> Unit
            }
        } catch (e: Exception) {
            Log.w(TAG, "BLE packet error: ${e.message}")
            val errJson = JSONObject()
                .put("event", "error")
                .put("detail", e.message ?: "framing_error")
                .toString()
            sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, errJson.toByteArray(Charsets.UTF_8))
        }
    }

    private suspend fun forwardTurnToGateway(
        wavBytes: ByteArray,
        images: Map<Int, ByteArray>,
        commitMeta: JSONObject?
    ) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val gatewayUrl = (commitMeta?.optString("hub_url")?.takeIf { it.isNotBlank() }
            ?: prefs.getString(KEY_GATEWAY_URL, DEFAULT_GATEWAY_URL)
            ?: DEFAULT_GATEWAY_URL).trimEnd('/')
        val bearerToken = prefs.getString(KEY_BEARER_TOKEN, "") ?: ""
        val nodeId = commitMeta?.optString("node_id")?.takeIf { it.isNotBlank() }
            ?: prefs.getString(KEY_NODE_ID, DEFAULT_NODE_ID)
            ?: DEFAULT_NODE_ID
        val audioOutMode = commitMeta?.optString("audio_out_mode")?.takeIf { it.isNotBlank() }
            ?: prefs.getString(KEY_AUDIO_OUT_MODE, DEFAULT_AUDIO_OUT_MODE)
            ?: DEFAULT_AUDIO_OUT_MODE

        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("node_id", nodeId)
            .addFormDataPart("audio_out_mode", audioOutMode)

        if (wavBytes.isNotEmpty()) {
            multipart.addFormDataPart(
                "audio",
                "utterance.wav",
                wavBytes.toRequestBody("audio/wav".toMediaType())
            )
        }

        if (images.size == 1 && images.containsKey(0)) {
            multipart.addFormDataPart(
                "image",
                "snapshot.jpg",
                images.getValue(0).toRequestBody("image/jpeg".toMediaType())
            )
        } else {
            for ((idx, jpeg) in images) {
                multipart.addFormDataPart(
                    "image_$idx",
                    "burst_$idx.jpg",
                    jpeg.toRequestBody("image/jpeg".toMediaType())
                )
            }
        }

        val reqBuilder = Request.Builder()
            .url("$gatewayUrl/api/voice/interact")
            .post(multipart.build())
        if (bearerToken.isNotBlank()) {
            reqBuilder.header("Authorization", "Bearer $bearerToken")
        }

        try {
            httpClient.newCall(reqBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val errPayload = JSONObject()
                        .put("event", "error")
                        .put("status", response.code)
                        .toString()
                    sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, errPayload.toByteArray(Charsets.UTF_8))
                    return
                }

                val body = response.body ?: return
                val reader = BufferedReader(InputStreamReader(body.byteStream(), Charsets.UTF_8))
                var currentEvent = "message"
                val dataLines = mutableListOf<String>()

                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) {
                        if (dataLines.isNotEmpty()) {
                            val rawData = dataLines.joinToString("\n")
                            handleSseEvent(currentEvent, rawData, audioOutMode)
                            dataLines.clear()
                        }
                        currentEvent = "message"
                    } else if (line.startsWith("event:")) {
                        currentEvent = line.removePrefix("event:").trim()
                    } else if (line.startsWith("data:")) {
                        dataLines.add(line.removePrefix("data:").trim())
                    }
                }
            }
        } catch (e: Exception) {
            val errPayload = JSONObject()
                .put("event", "error")
                .put("detail", e.message ?: "gateway_unreachable")
                .toString()
            sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, errPayload.toByteArray(Charsets.UTF_8))
        }
    }

    private suspend fun handleSseEvent(eventType: String, rawData: String, audioOutMode: String) {
        if (eventType == "audio_chunk" && audioOutMode == "ble_phone") {
            runCatching {
                val obj = JSONObject(rawData)
                val b64 = obj.optString("pcm_b64", obj.optString("audio_b64", ""))
                val sampleRate = obj.optInt("sample_rate", 24000)
                if (b64.isNotEmpty()) {
                    val pcmBytes = Base64.decode(b64, Base64.DEFAULT)
                    playPcmOnPhoneSpeaker(pcmBytes, sampleRate)
                }
            }
            return
        }

        val sseEnvelope = "event: $eventType\ndata: $rawData\n\n"
        sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, sseEnvelope.toByteArray(Charsets.UTF_8))
        delay(2)
    }

    private fun playPcmOnPhoneSpeaker(pcmBytes: ByteArray, sampleRate: Int) {
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

    private fun sendBleFrame(
        frameType: BleFramingCodec.FrameType,
        payload: ByteArray,
        flags: Int = BleFramingCodec.FLAG_NONE,
        frameIndex: Int = 0
    ) {
        val gatt = activeGatt ?: return
        val rxChar = rxCharacteristic ?: return
        val (packets, nextSeq) = BleFramingCodec.fragmentPayload(
            frameType = frameType,
            flags = flags,
            startSeqNum = downlinkSeqNum,
            payload = payload,
            maxPayload = negotiatedMaxPayload,
            frameIndex = frameIndex
        )
        downlinkSeqNum = nextSeq
        for (pkt in packets) {
            rxChar.value = pkt
            rxChar.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            gatt.writeCharacteristic(rxChar)
        }
    }
}
