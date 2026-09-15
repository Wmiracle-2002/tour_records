package com.miracle.footmarks.data.local.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class PhotoManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val photoDir: File
        get() = File(context.filesDir, "photos").also { it.mkdirs() }

    suspend fun savePhoto(uri: Uri): String? = withContext(Dispatchers.IO) {
        try {
            val bitmap = context.contentResolver.openInputStream(uri)?.use { inputStream ->
                BitmapFactory.decodeStream(inputStream)
            } ?: return@withContext null

            val compressed = compressBitmap(bitmap, TARGET_LONG_EDGE)
            val fileName = "${UUID.randomUUID()}.jpg"
            val file = File(photoDir, fileName)

            FileOutputStream(file).use { outputStream ->
                compressed.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, outputStream)
            }

            compressed.recycle()
            if (compressed != bitmap) bitmap.recycle()

            file.absolutePath
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    suspend fun deletePhoto(path: String) = withContext(Dispatchers.IO) {
        try {
            File(path).delete()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    suspend fun deletePhotos(paths: List<String>) = withContext(Dispatchers.IO) {
        paths.forEach { deletePhoto(it) }
    }

    private fun compressBitmap(bitmap: Bitmap, targetLongEdge: Int): Bitmap {
        val width = bitmap.width
        val height = bitmap.height
        val longEdge = maxOf(width, height)

        if (longEdge <= targetLongEdge) {
            return bitmap
        }

        val scale = targetLongEdge.toFloat() / longEdge
        val newWidth = (width * scale).toInt()
        val newHeight = (height * scale).toInt()

        return Bitmap.createScaledBitmap(bitmap, newWidth, newHeight, true)
    }

    companion object {
        private const val TARGET_LONG_EDGE = 1080
        private const val JPEG_QUALITY = 80
    }
}
