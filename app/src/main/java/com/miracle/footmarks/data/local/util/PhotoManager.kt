package com.miracle.footmarks.data.local.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.BufferedSink
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
            if (isManagedPhoto(path)) File(path).delete()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    suspend fun deletePhotos(paths: List<String>) = withContext(Dispatchers.IO) {
        paths.forEach { deletePhoto(it) }
    }

    fun createOriginalUploadPart(uri: Uri): MultipartBody.Part? {
        val resolver = context.contentResolver
        val contentType = resolver.getType(uri) ?: "image/jpeg"
        if (!contentType.startsWith("image/")) return null
        val fileName = resolver.query(
            uri,
            arrayOf(OpenableColumns.DISPLAY_NAME),
            null,
            null,
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: uri.lastPathSegment?.substringAfterLast('/') ?: "image"
        val body = object : RequestBody() {
            override fun contentType() = contentType.toMediaTypeOrNull()

            override fun contentLength(): Long = runCatching {
                resolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
            }.getOrDefault(-1L)

            override fun writeTo(sink: BufferedSink) {
                resolver.openInputStream(uri)?.use { input ->
                    input.copyTo(sink.outputStream())
                } ?: error("Unable to open selected image")
            }
        }
        return MultipartBody.Part.createFormData("file", fileName, body)
    }

    fun isManagedPhoto(path: String): Boolean {
        val file = File(path)
        return try {
            file.canonicalFile.parentFile == photoDir.canonicalFile
        } catch (_: Exception) {
            false
        }
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
