package kr.araba.araba

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val METHOD_CHANNEL = "araba/notifications"
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
