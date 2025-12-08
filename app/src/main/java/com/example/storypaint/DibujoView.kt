package com.example.storypaint

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View

class DibujoView(context: Context, attrs: AttributeSet?) : View(context, attrs) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        strokeWidth = 18f
    }

    private val backgroundColor = Color.WHITE
    private var bitmap: Bitmap? = null
    private var canvasBmp: Canvas? = null
    private val path = Path()
    private var lastX = 0f
    private var lastY = 0f

    init {
        isFocusable = true
        isFocusableInTouchMode = true
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (w <= 0 || h <= 0) return
        bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        canvasBmp = Canvas(bitmap!!)
        canvasBmp?.drawColor(backgroundColor)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        bitmap?.let { canvas.drawBitmap(it, 0f, 0f, null) }
        canvas.drawPath(path, paint)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val x = event.x
        val y = event.y
        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                path.reset()
                path.moveTo(x, y)
                lastX = x
                lastY = y
                invalidate()
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = Math.abs(x - lastX)
                val dy = Math.abs(y - lastY)
                if (dx >= 4f || dy >= 4f) {
                    path.quadTo(lastX, lastY, (x + lastX) / 2f, (y + lastY) / 2f)
                    lastX = x
                    lastY = y
                    invalidate()
                }
            }
            MotionEvent.ACTION_UP -> {
                path.lineTo(lastX, lastY)
                canvasBmp?.drawPath(path, paint)
                path.reset()
                invalidate()
            }
        }
        return true
    }

    fun clear() {
        bitmap?.eraseColor(backgroundColor)
        invalidate()
    }

    fun getBitmap(): Bitmap {
        return bitmap?.copy(Bitmap.Config.ARGB_8888, false)
            ?: Bitmap.createBitmap(width.coerceAtLeast(1), height.coerceAtLeast(1), Bitmap.Config.ARGB_8888)
    }
}
