package kr.araba.araba

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.Manifest
import android.content.pm.PackageManager
import android.provider.Settings
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var permissionReply: MethodChannel.Result? = null
    companion object {
        private const val METHOD_CHANNEL = "araba/notifications"
        private const val PHONE_PERMISSION_CHANNEL = "araba/device_permissions"
        private const val REQUEST_ALL_PERMISSIONS = 5021
        private const val LIVE_KEEP_ALIVE_CHANNEL = "araba/live_keep_alive"
        private const val NOTIFICATION_CHANNEL_ID = "araba_updates"
        private const val NOTIFICATION_CHANNEL_NAME = "ARABA 업데이트"
        private const val NOTIFICATION_ID = 1001
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        createNotificationChannel()
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            PHONE_PERMISSION_CHANNEL,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "firstRunNeeded" -> result.success(
                    !getSharedPreferences("araba_permissions", MODE_PRIVATE)
                        .getBoolean("onboarding_completed", false)
                )
                "markFirstRunComplete" -> {
                    getSharedPreferences("araba_permissions", MODE_PRIVATE)
                        .edit().putBoolean("onboarding_completed", true).apply()
                    result.success(true)
                }
                "status" -> result.success(permissionStatus())
                "requestAll" -> requestAllPermissions(result)
                "openSettings" -> {
                    val intent = Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:$packageName"),
                    )
                    startActivity(intent)
                    result.success(true)
                }
                "placeCall" -> {
                    val raw = call.argument<String>("phone") ?: ""
                    val number = raw.replace(Regex("[^0-9+]"), "")
                    if (!Regex("^\\+?[0-9]{7,15}$").matches(number)) {
                        result.error("INVALID_PHONE", "전화번호가 유효하지 않습니다.", null)
                    } else if (checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
                        result.error("PHONE_PERMISSION", "전화 권한이 필요합니다. 권한 설정에서 허용해주세요.", null)
                    } else {
                        try {
                            startActivity(Intent(Intent.ACTION_CALL, Uri.fromParts("tel", number, null)))
                            result.success(true)
                        } catch (ex: Exception) {
                            result.error("CALL_FAILED", "휴대전화 발신을 시작하지 못했습니다.", null)
                        }
                    }
                }
                else -> result.notImplemented()
            }
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            METHOD_CHANNEL,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "showUpdateNotification" -> {
                    val title = call.argument<String>("title")
                        ?: "ARABA 새 버전 준비됨"
                    val body = call.argument<String>("body")
                        ?: "알림을 눌러 최신 개발 버전으로 업데이트하세요."
                    val url = call.argument<String>("url")

                    showUpdateNotification(title, body, url)
                    result.success(null)
                }

                else -> result.notImplemented()
            }
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            LIVE_KEEP_ALIVE_CHANNEL,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    val intent = Intent(
                        this,
                        LiveKeepAliveService::class.java,
                    ).apply {
                        action = LiveKeepAliveService.ACTION_START
                    }
                    ContextCompat.startForegroundService(
                        this,
                        intent,
                    )
                    result.success(null)
                }

                "stop" -> {
                    val intent = Intent(
                        this,
                        LiveKeepAliveService::class.java,
                    )
                    stopService(intent)
                    result.success(null)
                }

                else -> result.notImplemented()
            }
        }
    }

    private fun supportedPermissions(): List<String> {
        val permissions = mutableListOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.CAMERA,
            Manifest.permission.CALL_PHONE,
        )
        if (Build.VERSION.SDK_INT >= 33) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        return permissions
    }

    private fun permissionStatus(): Map<String, Boolean> {
        fun granted(name: String) =
            checkSelfPermission(name) == PackageManager.PERMISSION_GRANTED
        return mapOf(
            "microphone" to granted(Manifest.permission.RECORD_AUDIO),
            "location" to (
                granted(Manifest.permission.ACCESS_FINE_LOCATION) ||
                granted(Manifest.permission.ACCESS_COARSE_LOCATION)
            ),
            "camera" to granted(Manifest.permission.CAMERA),
            "phone" to granted(Manifest.permission.CALL_PHONE),
            "notifications" to (
                Build.VERSION.SDK_INT < 33 ||
                granted(Manifest.permission.POST_NOTIFICATIONS)
            ),
        )
    }

    private fun requestAllPermissions(result: MethodChannel.Result) {
        if (permissionReply != null) {
            result.error("BUSY", "다른 권한 요청이 진행 중입니다.", null)
            return
        }
        val missing = supportedPermissions().filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) {
            result.success(permissionStatus())
            return
        }
        permissionReply = result
        requestPermissions(missing.toTypedArray(), REQUEST_ALL_PERMISSIONS)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_ALL_PERMISSIONS) {
            permissionReply?.success(permissionStatus())
            permissionReply = null
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }

        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            NOTIFICATION_CHANNEL_ID,
            NOTIFICATION_CHANNEL_NAME,
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "ARABA 새 버전 및 중요 업데이트 알림"
            enableVibration(true)
        }

        manager.createNotificationChannel(channel)
    }

    private fun showUpdateNotification(
        title: String,
        body: String,
        url: String?,
    ) {
        val intent = if (!url.isNullOrBlank()) {
            Intent(Intent.ACTION_VIEW, Uri.parse(url))
        } else {
            Intent(this, MainActivity::class.java)
        }.apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }
            .setSmallIcon(applicationInfo.icon)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setPriority(Notification.PRIORITY_HIGH)

        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, builder.build())
    }
}
