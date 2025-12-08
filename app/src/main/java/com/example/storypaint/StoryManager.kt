package com.example.storypaint

import android.content.Context
import org.json.JSONObject
import java.io.File

object StoryManager {
    private fun storiesDir(ctx: Context): File {
        val d = File(ctx.filesDir, "stories")
        if (!d.exists()) d.mkdirs()
        return d
    }
    fun saveStory(ctx: Context, title: String, pages: List<String>) : String {
        val file = File(storiesDir(ctx), "story_${System.currentTimeMillis()}.json")
        val obj = JSONObject()
        obj.put("title", title)
        obj.put("pages", pages) // lista base64 o texto
        file.writeText(obj.toString())
        return file.absolutePath
    }
    fun listStories(ctx: Context): List<File> = storiesDir(ctx).listFiles()?.toList() ?: emptyList()
    fun deleteStory(file: File) = file.delete()
}