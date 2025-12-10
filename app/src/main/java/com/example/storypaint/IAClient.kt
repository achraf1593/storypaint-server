package com.example.storypaint

import android.app.Activity
import android.graphics.Bitmap
import android.util.Base64
import android.util.Log
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
object IAClient {
    private const val TAG = "IAClient"
    private const val SERVER_URL = "https://storypaint-server.onrender.com/generar_imagen"
    private val JSON = "application/json; charset=utf-8".toMediaTypeOrNull()
    private val client = OkHttpClient.Builder()
        .callTimeout(120, TimeUnit.SECONDS)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    data class Result(val activityText: String, val imageBitmapBase64: String?)

    fun generarActividad(
        activity: Activity,
        bitmap: Bitmap,
        onSuccess: (Result) -> Unit,
        onError: (String) -> Unit
    ) {
        thread {
            try {
                val infoDibujo = analizarDibujo(bitmap)
                val prompt = generarPrompt(infoDibujo)

                // Reducir tamaño para envío
                val scaled = Bitmap.createScaledBitmap(bitmap, 512, 512, true)
                val baos = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.PNG, 90, baos)
                val base64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)

                // ---------------------------
                // LOGUEO DE BASE64
                // ---------------------------
                Log.d(TAG, "Base64 tamaño: ${base64.length}")
                Log.d(TAG, "Base64 prefijo: ${base64.take(80)}")

                val json = JSONObject().apply {
                    put("imagen", base64)
                    put("prompt", prompt)
                }

                val body = RequestBody.create(JSON, json.toString())
                val req = Request.Builder().url(SERVER_URL).post(body).build()

                val resp = client.newCall(req).execute()
                val bodyStr = resp.body?.string() ?: ""
                Log.d(TAG, "HTTP ${resp.code} -> $bodyStr")

                if (!resp.isSuccessful) {
                    activity.runOnUiThread { onError("Error del servidor ${resp.code}") }
                    return@thread
                }

                val j = JSONObject(bodyStr)
                val activityText = j.optString("actividad_generada", fallbackActividad(infoDibujo))
                val imgB64 = j.optString("imagen_generada", null)

                // ---------------------------
                // CHEQUEO DE LONGITUD DE IMAGEN
                // ---------------------------
                val validImage = imgB64 != null && imgB64.length > 200
                if (!validImage) {
                    Log.w(TAG, "Imagen recibida inválida o demasiado corta. Solo se mostrará la actividad.")
                }

                activity.runOnUiThread {
                    onSuccess(Result(activityText = activityText, imageBitmapBase64 = if (validImage) imgB64 else null))
                }

            } catch (e: Exception) {
                Log.e(TAG, "Error IAClient: ${e.message}")
                val infoDibujo = analizarDibujo(bitmap)
                activity.runOnUiThread {
                    onSuccess(Result(activityText = fallbackActividad(infoDibujo), imageBitmapBase64 = null))
                }
            }
        }
    }

    private fun analizarDibujo(bitmap: Bitmap): Map<String, Any> {
        val width = bitmap.width
        val height = bitmap.height
        val colorCount = mutableMapOf<Int, Int>()
        for (x in 0 until width step 10) {
            for (y in 0 until height step 10) {
                val color = bitmap.getPixel(x, y)
                colorCount[color] = (colorCount[color] ?: 0) + 1
            }
        }
        val topColor = colorCount.maxByOrNull { it.value }?.key ?: 0
        return mapOf("topColor" to topColor)
    }

    private fun generarPrompt(info: Map<String, Any>): String {
        val color = info["topColor"] as Int
        val colorName = when (color) {
            0xFFFF0000.toInt() -> "rojo"
            0xFF00FF00.toInt() -> "verde"
            0xFF0000FF.toInt() -> "azul"
            else -> "colorido"
        }
        return "El niño dibujó algo $colorName. " +
                "Genera una actividad creativa, divertida y segura para un niño de 5-8 años. " +
                "Instrucciones claras y breves, que pueda realizar sin ayuda constante."
    }

    private fun fallbackActividad(info: Map<String, Any>): String {
        return "¡Crea una historia o juego usando tu dibujo! " +
                "Puedes inventar nombres, colores y aventuras según lo que dibujaste."
    }
}
