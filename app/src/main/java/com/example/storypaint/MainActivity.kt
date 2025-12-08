package com.example.storypaint

import android.graphics.Bitmap
import android.os.Bundle
import android.widget.Button
import android.widget.ProgressBar
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var dibujoView: DibujoView
    private lateinit var btnGenerate: Button
    private lateinit var progress: ProgressBar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        dibujoView = findViewById(R.id.dibujoView)
        btnGenerate = findViewById(R.id.btnGenerate)
        progress = findViewById(R.id.progressBar)

        btnGenerate.setOnClickListener {
            val bmp = dibujoView.getBitmap()
            if (bmp.width == 0 || bmp.height == 0) {
                Toast.makeText(this, "Dibuja algo primero", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            generarActividad(bmp)
        }
    }

    private fun generarActividad(bitmap: Bitmap) {
        btnGenerate.isEnabled = false
        progress.visibility = ProgressBar.VISIBLE

        IAClient.generarActividad(
            activity = this,
            bitmap = bitmap,
            onSuccess = { result ->
                progress.visibility = ProgressBar.GONE
                btnGenerate.isEnabled = true
                // Mostrar diálogo de preview
                val dlg = PreviewDialogFragment(
                    activityText = result.activityText,
                    generatedImageBase64 = result.imageBitmapBase64,
                    onNewActivity = { generarActividad(bitmap) },
                    onSaveImage = null
                )
                dlg.show(supportFragmentManager, "preview")
            },
            onError = { msg ->
                progress.visibility = ProgressBar.GONE
                btnGenerate.isEnabled = true
                Toast.makeText(this, "Error: $msg", Toast.LENGTH_LONG).show()
            }
        )
    }
}
