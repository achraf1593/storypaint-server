package com.example.storypaint

import android.app.Dialog
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.*
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.fragment.app.DialogFragment

class PreviewDialogFragment(
    private val activityText: String,
    private val generatedImageBase64: String?,
    private val onNewActivity: () -> Unit,
    private val onSaveImage: ((ByteArray) -> Unit)?
) : DialogFragment() {

    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        val d = Dialog(requireContext())
        d.requestWindowFeature(Window.FEATURE_NO_TITLE)
        val view = layoutInflater.inflate(R.layout.dialog_preview, null)
        d.setContentView(view)
        d.window?.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        val img = view.findViewById<ImageView>(R.id.previewImage)
        val tv = view.findViewById<TextView>(R.id.tvActivityText)
        val btnAnother = view.findViewById<Button>(R.id.btnAnother)
        val btnClose = view.findViewById<Button>(R.id.btnDiscard)

        tv.text = activityText
        tv.textSize = 18f
        tv.setTextColor(resources.getColor(android.R.color.black, null))
        tv.setPadding(12,12,12,12)

        if (!generatedImageBase64.isNullOrBlank()) {
            try {
                val decoded = android.util.Base64.decode(generatedImageBase64, android.util.Base64.DEFAULT)
                val bmp = BitmapFactory.decodeByteArray(decoded, 0, decoded.size)
                img.setImageBitmap(bmp)
                img.visibility = View.VISIBLE
            } catch (_: Exception) {
                img.visibility = View.GONE
            }
        } else {
            img.visibility = View.GONE
        }

        btnAnother.textSize = 18f
        btnAnother.setOnClickListener {
            onNewActivity()
            dismiss()
        }

        btnClose.textSize = 18f
        btnClose.setOnClickListener { dismiss() }

        return d
    }
}
