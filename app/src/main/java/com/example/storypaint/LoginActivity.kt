package com.example.storypaint

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import androidx.appcompat.app.AppCompatActivity

class LoginActivity : AppCompatActivity() {
    private val PREFS = "storypaint_prefs"
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        val user = prefs.getString("user_name", null)
        if (!user.isNullOrBlank()) {
            startMain(); return
        }
        setContentView(R.layout.activity_login)
        val etName = findViewById<EditText>(R.id.etName)
        val btn = findViewById<Button>(R.id.btnEnter)
        btn.setOnClickListener {
            val name = etName.text.toString().trim()
            if (name.isNotBlank()) {
                prefs.edit().putString("user_name", name).apply()
                startMain()
            } else {
                etName.error = "Escribe tu nombre"
            }
        }
    }
    private fun startMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}
