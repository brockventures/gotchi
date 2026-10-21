package ventures.brock.gotchi.forwarder

import android.Manifest
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
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStreamReader
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Headless Android Foreground Service for GOTCHI V1 "Smart Pipe" BLE Companion Relay (F18 / T4.2).
 *
 * Transport-agnostic upstream connectivity: connects over standard HTTPS (`443` via Cloudflare Tunnel /
 * reverse proxy), plain LAN HTTP (`:8765`), or optional VPN — Tailscale is NOT required on the phone.
 *
 * Responsibilities:
 * 1. Scans and auto-bonds to the GOTCHI BLE GATT UART service (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`),
 *    requesting BLE 5.0 2M PHY and 512-byte ATT MTU.
 * 2. Reassembles binary-framed PTT uplink streams (`AUDIO_CHUNK`, `IMAGE_FRAME` 0..4, `TURN_COMMIT`)
 *    validated via CRC-16/CCITT header checks and IEEE 802.3 CRC-32 payload trailers.
 * 3. Smart Pipe 4-Bit IMA ADPCM Transcoding (4x BLE air-time reduction):
 *    - Automatically transcodes incoming `FLAG_ADPCM` / `GAD1` (`64 kbps` @ 16 kHz) BLE audio into
 *      standard 16-bit mono RIFF WAV for `POST /api/voice/interact`.
 *    - When `audio_out_mode == "speaker"` over BLE, transcodes downstream 24 kHz 16-bit PCM TTS chunks
 *      into 4-bit IMA ADPCM (`GAD1`, `"format": "adpcm"`, `96 kbps`) before writing to `CHAR_RX`.
 * 4. Dead-Zone Store-and-Forward Spooling:
 *    - Buffers `journal` segments and offline turns locally in `filesDir/offline_spool` (up to 64 items)
 *      whenever the phone is in a cellular/Wi-Fi dead zone or the gateway is temporarily unreachable,
 *      acknowledging GOTCHI with `"status": "offline_queued"` and automatically replaying queued turns
 *      when network connectivity returns.
 * 5. Optional Coarse GPS Metadata Tagging:
 *    - Attaches cached passive/network coarse coordinates (`lat`, `lon`, `location_accuracy_m`) from
 *      `LocationManager.getLastKnownLocation` to `/api/voice/interact` multipart requests when
 *      `ACCESS_COARSE_LOCATION` is granted (zero active GPS polling drain).
 * 6. When `audio_out_mode == "ble_phone"`, decodes 24 kHz 16-bit mono PCM `audio_chunk` / `sentence`
 *    payloads and plays them locally on the phone / Bluetooth earbuds via Android `AudioTrack` while
 *    still forwarding sprite `state` / `done` events to GOTCHI.
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

        const val OFFLINE_SPOOL_DIR = "offline_spool"
        const val MAX_OFFLINE_SPOOL_ITEMS = 64
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val spoolMutex = Mutex()
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val reassembler = BleReassembler()
    private val audioStreamBuffer = ByteArrayOutputStream()
    private var audioStreamIsAdpcm: Boolean = false
    private val imageFrames = mutableMapOf<Int, ByteArray>()
    private var downlinkSeqNum: Int = 0
    private var negotiatedMaxPayload: Int = BleFramingCodec.DEFAULT_MAX_PAYLOAD
    private var activeGatt: BluetoothGatt? = null
    private var rxCharacteristic: BluetoothGattCharacteristic? = null
    private var networkCallbackRegistered: Boolean = false

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            serviceScope.launch {
                drainOfflineSpool()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        startForegroundWithNotification("Scanning for GOTCHI over BLE...")
        registerConnectivityWatcher()
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
        serviceScope.launch {
            drainOfflineSpool()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterConnectivityWatcher()
        activeGatt?.close()
        activeGatt = null
        serviceScope.cancel()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun registerConnectivityWatcher() {
        if (networkCallbackRegistered) return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        runCatching {
            cm.registerDefaultNetworkCallback(networkCallback)
            networkCallbackRegistered = true
        }
    }

    private fun unregisterConnectivityWatcher() {
        if (!networkCallbackRegistered) return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        runCatching {
            cm.unregisterNetworkCallback(networkCallback)
        }
        networkCallbackRegistered = false
    }

    internal fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return true
        val net = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(net) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    internal fun readCoarseLocationMeta(): JSONObject? {
        if (checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        val lm = getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null
        val candidates = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.PASSIVE_PROVIDER)
        var best: Location? = null
        for (provider in candidates) {
            val loc = runCatching { lm.getLastKnownLocation(provider) }.getOrNull() ?: continue
            if (best == null || loc.time > best.time) {
                best = loc
            }
        }
        val chosen = best ?: return null
        return JSONObject()
            .put("lat", chosen.latitude)
            .put("lon", chosen.longitude)
            .put("location_accuracy_m", chosen.accuracy.toDouble())
    }

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
                audioStreamIsAdpcm = false
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

    internal fun transcodeUplinkAudioIfNeeded(rawAudioBytes: ByteArray, isAdpcmFlagged: Boolean): ByteArray {
        if (rawAudioBytes.isEmpty()) return rawAudioBytes
        if (isAdpcmFlagged || ImaAdpcmCodec.isGad1Container(rawAudioBytes)) {
            return ImaAdpcmCodec.decodeGad1OrAdpcmToWav(rawAudioBytes, defaultSampleRate = 16000)
        }
        return rawAudioBytes
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
                        audioStreamIsAdpcm = false
                    }
                    if ((completed.flags and BleFramingCodec.FLAG_ADPCM) != 0) {
                        audioStreamIsAdpcm = true
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
                    val rawAudioBytes = audioStreamBuffer.toByteArray()
                    val isAdpcm = audioStreamIsAdpcm
                    val capturedImages = imageFrames.toSortedMap()
                    audioStreamBuffer.reset()
                    audioStreamIsAdpcm = false
                    imageFrames.clear()
                    val wavBytes = transcodeUplinkAudioIfNeeded(rawAudioBytes, isAdpcm)
                    val locationMeta = readCoarseLocationMeta()
                    serviceScope.launch {
                        forwardTurnToGateway(wavBytes, capturedImages, commitMeta, locationMeta)
                    }
                }
                BleFramingCodec.FrameType.CANCEL -> {
                    reassembler.reset()
                    audioStreamBuffer.reset()
                    audioStreamIsAdpcm = false
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

    internal suspend fun spoolTurnForOfflineReplay(
        wavBytes: ByteArray,
        images: Map<Int, ByteArray>,
        commitMeta: JSONObject?,
        locationMeta: JSONObject?
    ): File? = spoolMutex.withLock {
        val dir = File(filesDir, OFFLINE_SPOOL_DIR)
        if (!dir.exists() && !dir.mkdirs()) return@withLock null

        val existing = dir.listFiles { f -> f.name.endsWith(".json") }
            ?.sortedBy { it.name }
            ?: emptyList()
        if (existing.size >= MAX_OFFLINE_SPOOL_ITEMS) {
            existing.take(existing.size - MAX_OFFLINE_SPOOL_ITEMS + 1).forEach { it.delete() }
        }

        val ts = System.currentTimeMillis()
        val itemFile = File(dir, "spool_${ts}_${UUID.randomUUID().toString().take(6)}.json")
        val imagesObj = JSONObject()
        for ((idx, bytes) in images) {
            imagesObj.put(idx.toString(), Base64.encodeToString(bytes, Base64.NO_WRAP))
        }
        val envelope = JSONObject()
            .put("queued_at_ms", ts)
            .put("wav_b64", Base64.encodeToString(wavBytes, Base64.NO_WRAP))
            .put("images", imagesObj)
            .put("commit_meta", commitMeta ?: JSONObject())
        if (locationMeta != null) {
            envelope.put("location_meta", locationMeta)
        }
        itemFile.writeText(envelope.toString(), Charsets.UTF_8)
        itemFile
    }

    internal suspend fun drainOfflineSpool() = spoolMutex.withLock {
        if (!isNetworkAvailable()) return@withLock
        val dir = File(filesDir, OFFLINE_SPOOL_DIR)
        val queuedFiles = dir.listFiles { f -> f.name.endsWith(".json") }
            ?.sortedBy { it.name }
            ?: return@withLock

        for (file in queuedFiles) {
            val ok = runCatching {
                val obj = JSONObject(file.readText(Charsets.UTF_8))
                val wavB64 = obj.optString("wav_b64", "")
                val wavBytes = if (wavB64.isNotEmpty()) Base64.decode(wavB64, Base64.DEFAULT) else ByteArray(0)
                val imagesObj = obj.optJSONObject("images")
                val images = mutableMapOf<Int, ByteArray>()
                imagesObj?.keys()?.forEach { key ->
                    val idx = key.toIntOrNull() ?: return@forEach
                    val b64 = imagesObj.optString(key, "")
                    if (b64.isNotEmpty()) {
                        images[idx] = Base64.decode(b64, Base64.DEFAULT)
                    }
                }
                val commitMeta = obj.optJSONObject("commit_meta")
                val locationMeta = obj.optJSONObject("location_meta")
                executeGatewayPost(
                    wavBytes = wavBytes,
                    images = images,
                    commitMeta = commitMeta,
                    locationMeta = locationMeta,
                    isReplay = true
                )
            }.getOrDefault(false)

            if (ok) {
                file.delete()
            } else {
                break
            }
        }
    }

    private suspend fun forwardTurnToGateway(
        wavBytes: ByteArray,
        images: Map<Int, ByteArray>,
        commitMeta: JSONObject?,
        locationMeta: JSONObject? = null
    ) {
        if (!isNetworkAvailable()) {
            spoolTurnForOfflineReplay(wavBytes, images, commitMeta, locationMeta)
            emitOfflineQueuedToBle()
            return
        }

        val delivered = executeGatewayPost(
            wavBytes = wavBytes,
            images = images,
            commitMeta = commitMeta,
            locationMeta = locationMeta,
            isReplay = false
        )
        if (delivered) {
            drainOfflineSpool()
        }
    }

    private fun emitOfflineQueuedToBle() {
        val statusEvt = "event: status\ndata: {\"status\":\"offline_queued\",\"spooled\":true}\n\n"
        val doneEvt = "event: done\ndata: {\"offline_queued\":true,\"spooled\":true}\n\n"
        sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, statusEvt.toByteArray(Charsets.UTF_8))
        sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, doneEvt.toByteArray(Charsets.UTF_8))
    }

    private suspend fun executeGatewayPost(
        wavBytes: ByteArray,
        images: Map<Int, ByteArray>,
        commitMeta: JSONObject?,
        locationMeta: JSONObject?,
        isReplay: Boolean
    ): Boolean {
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
        val mode = commitMeta?.optString("mode")?.takeIf { it.isNotBlank() } ?: "interact"
        val prompt = commitMeta?.optString("prompt")?.takeIf { it.isNotBlank() }

        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("node_id", nodeId)
            .addFormDataPart("audio_out_mode", audioOutMode)
            .addFormDataPart("mode", mode)

        if (!prompt.isNullOrBlank()) {
            multipart.addFormDataPart("prompt", prompt)
        }

        val lat = commitMeta?.optDouble("lat")?.takeIf { !it.isNaN() }
            ?: locationMeta?.optDouble("lat")?.takeIf { !it.isNaN() }
        val lon = commitMeta?.optDouble("lon")?.takeIf { !it.isNaN() }
            ?: locationMeta?.optDouble("lon")?.takeIf { !it.isNaN() }
        val acc = commitMeta?.optDouble("location_accuracy_m")?.takeIf { !it.isNaN() }
            ?: locationMeta?.optDouble("location_accuracy_m")?.takeIf { !it.isNaN() }

        if (lat != null && lon != null) {
            multipart.addFormDataPart("lat", lat.toString())
            multipart.addFormDataPart("lon", lon.toString())
            if (acc != null) {
                multipart.addFormDataPart("location_accuracy_m", acc.toString())
            }
        }

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

        return try {
            httpClient.newCall(reqBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    if (response.code in listOf(502, 503, 504) && !isReplay) {
                        spoolTurnForOfflineReplay(wavBytes, images, commitMeta, locationMeta)
                        emitOfflineQueuedToBle()
                        return false
                    }
                    if (!isReplay) {
                        val errPayload = JSONObject()
                            .put("event", "error")
                            .put("status", response.code)
                            .toString()
                        sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, errPayload.toByteArray(Charsets.UTF_8))
                    }
                    return false
                }

                val body = response.body ?: return true
                val reader = BufferedReader(InputStreamReader(body.byteStream(), Charsets.UTF_8))
                var currentEvent = "message"
                val dataLines = mutableListOf<String>()

                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) {
                        if (dataLines.isNotEmpty()) {
                            val rawData = dataLines.joinToString("\n")
                            if (!isReplay) {
                                handleSseEvent(currentEvent, rawData, audioOutMode)
                            }
                            dataLines.clear()
                        }
                        currentEvent = "message"
                    } else if (line.startsWith("event:")) {
                        currentEvent = line.removePrefix("event:").trim()
                    } else if (line.startsWith("data:")) {
                        dataLines.add(line.removePrefix("data:").trim())
                    }
                }
                true
            }
        } catch (e: IOException) {
            if (!isReplay) {
                spoolTurnForOfflineReplay(wavBytes, images, commitMeta, locationMeta)
                emitOfflineQueuedToBle()
            }
            false
        } catch (e: Exception) {
            if (!isReplay) {
                val errPayload = JSONObject()
                    .put("event", "error")
                    .put("detail", e.message ?: "gateway_unreachable")
                    .toString()
                sendBleFrame(BleFramingCodec.FrameType.SSE_EVENT, errPayload.toByteArray(Charsets.UTF_8))
            }
            false
        }
    }

    internal fun transcodeDownlinkAudioEventToAdpcm(eventType: String, rawData: String): String {
        if (eventType != "sentence" && eventType != "audio_chunk") return rawData
        return runCatching {
            val obj = JSONObject(rawData)
            val fmt = obj.optString("format", "pcm")
            if (fmt == "adpcm") return@runCatching rawData
            val key = when {
                obj.has("audio_b64") -> "audio_b64"
                obj.has("data") -> "data"
                obj.has("pcm_b64") -> "pcm_b64"
                else -> return@runCatching rawData
            }
            val b64 = obj.optString(key, "")
            if (b64.isEmpty()) return@runCatching rawData
            val sampleRate = obj.optInt("sample_rate", 24000)
            val pcmBytes = Base64.decode(b64, Base64.DEFAULT)
            val gad1Bytes = ImaAdpcmCodec.encodePcmToGad1(pcmBytes, sampleRate)
            obj.put("format", "adpcm")
            obj.put(key, Base64.encodeToString(gad1Bytes, Base64.NO_WRAP))
            obj.toString()
        }.getOrDefault(rawData)
    }

    private suspend fun handleSseEvent(eventType: String, rawData: String, audioOutMode: String) {
        if ((eventType == "audio_chunk" || eventType == "sentence") && audioOutMode == "ble_phone") {
            runCatching {
                val obj = JSONObject(rawData)
                val b64 = obj.optString("pcm_b64", obj.optString("audio_b64", obj.optString("data", "")))
                val sampleRate = obj.optInt("sample_rate", 24000)
                if (b64.isNotEmpty()) {
                    val pcmBytes = Base64.decode(b64, Base64.DEFAULT)
                    playPcmOnPhoneSpeaker(pcmBytes, sampleRate)
                }
            }
            return
        }

        val outboundData = if ((eventType == "sentence" || eventType == "audio_chunk") && audioOutMode == "speaker") {
            transcodeDownlinkAudioEventToAdpcm(eventType, rawData)
        } else {
            rawData
        }

        val sseEnvelope = "event: $eventType\ndata: $outboundData\n\n"
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
