package com.example.storypaint

import android.content.Context
import java.io.File
import java.io.FileOutputStream

object StorageHelper {
    fun saveBytesAsImage(ctx: Context, bytes: ByteArray): String? {
        return try {
            val fileName = "activity_img_${System.currentTimeMillis()}.png"
            val f = File(ctx.getExternalFilesDir(null), fileName)
            FileOutputStream(f).use { it.write(bytes) }
            f.absolutePath
        } catch (e: Exception) {
            null
        }
    }
}
