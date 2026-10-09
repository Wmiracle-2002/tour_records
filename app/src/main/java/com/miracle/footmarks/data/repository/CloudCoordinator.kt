package com.miracle.footmarks.data.repository

import android.net.Uri
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemoteImage
import com.miracle.footmarks.data.remote.RecordRequest
import com.miracle.footmarks.data.remote.TripRequest
import com.miracle.footmarks.data.local.util.PhotoManager
import java.time.LocalDate
import javax.inject.Inject

class CloudCoordinator @Inject constructor(
    private val cache: CloudCache,
    private val session: CloudSession,
    private val photoManager: PhotoManager
) {
    val isCloudMode: Boolean get() = session.isCloudMode

    suspend fun login(username: String, password: String, keepSignedIn: Boolean = true, rememberUsername: Boolean = false) {
        session.login(username, password, keepSignedIn, rememberUsername)
        session.accountId?.let {
            cache.clearAnonymousTrips()
            cache.activateAccount(it)
        }
        if (!session.requiresPasswordChange) refresh()
    }

    suspend fun register(username: String, password: String, keepSignedIn: Boolean = true, rememberUsername: Boolean = false) {
        session.register(username, password, keepSignedIn, rememberUsername)
        session.accountId?.let {
            cache.clearAnonymousTrips()
            cache.activateAccount(it)
        }
        refresh()
    }

    suspend fun logout() {
        try {
            session.logout()
        } finally {
            cache.activateAccount(0)
        }
    }

    suspend fun changePassword(currentPassword: String, newPassword: String) {
        session.changePassword(currentPassword, newPassword)
        cache.activateAccount(0)
    }

    suspend fun deleteMyAccount(password: String) {
        val userId = requireNotNull(session.accountId)
        session.deleteMyAccount(password)
        cache.deleteAccountCache(userId)
    }

    suspend fun refresh() {
        val userId = session.accountId
        if (userId == null) {
            cache.replaceRemoteTrips(session.getTrips())
            return
        }
        if (cache.activeAccountId() == 0L) cache.activateAccount(userId)
        check(cache.activeAccountId() == userId) { "账号已切换，请重试" }
        var cursor = cache.cursor(userId)
        var hasMore: Boolean
        do {
            val page = session.syncTrips(cursor)
            check(session.accountId == userId) { "账号已切换，忽略旧同步响应" }
            cache.applySyncPage(userId, page)
            cursor = page.nextCursor
            hasMore = page.hasMore
        } while (hasMore)
    }

    suspend fun refreshImageUrls(localRecordId: Long): RecordEntity? {
        val userId = session.accountId ?: return null
        val record = cache.getRecord(localRecordId) ?: return null
        val remoteId = record.serverId ?: return record
        val images = session.recordImages(remoteId)
        check(session.accountId == userId) { "账号已切换，忽略旧照片响应" }
        return cache.updateImageUrls(userId, remoteId, images)
    }

    suspend fun createTrip(
        city: CityEntity,
        startDate: LocalDate,
        endDate: LocalDate
    ): Long {
        val remoteTrip = session.createTrip(tripRequest(city, startDate, endDate))
        refresh()
        return requireNotNull(cache.getTripByServerId(remoteTrip.id)).id
    }

    suspend fun createTripWithRecord(
        city: CityEntity,
        startDate: LocalDate,
        endDate: LocalDate,
        type: RecordType,
        name: String,
        date: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photos: List<Uri>
    ): Long {
        requirePhotoCount(photos)
        val remoteTrip = session.createTrip(tripRequest(city, startDate, endDate))
        val record = try {
            session.createRecord(remoteTrip.id, recordRequest(type, name, date, rating, cost, notes))
        } catch (error: Exception) {
            try {
                session.deleteTrip(remoteTrip.id)
            } catch (_: Exception) {
                // Next refresh exposes the incomplete trip so it can be handled explicitly.
            }
            throw error
        }
        try {
            uploadImages(record.id, photos)
        } catch (error: Exception) {
            val recordDeleted = runCatching { session.deleteRecord(record.id) }.isSuccess
            if (!recordDeleted) runCatching { session.deleteTrip(remoteTrip.id) }
            throw error
        }
        refresh()
        return requireNotNull(cache.getLocalRecord(record.id)).id
    }

    suspend fun createRecordForTrip(
        localTripId: Long,
        type: RecordType,
        name: String,
        date: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photos: List<Uri>
    ): Long {
        requirePhotoCount(photos)
        val remoteTripId = requireNotNull(cache.getTrip(localTripId)?.serverId) {
            "本地旅行不能加入云端记录"
        }
        val created = session.createRecord(
            remoteTripId, recordRequest(type, name, date, rating, cost, notes)
        )
        try {
            uploadImages(created.id, photos)
        } catch (error: Exception) {
            runCatching { session.deleteRecord(created.id) }
            throw error
        }
        refresh()
        return requireNotNull(cache.getLocalRecord(created.id)).id
    }

    suspend fun updateRecordWithTrip(
        record: RecordEntity,
        city: CityEntity,
        date: LocalDate,
        photos: List<Uri>
    ) {
        requirePhotoCount(photos)
        val remoteRecordId = requireNotNull(record.serverId) { "本地记录不能同步到云端" }
        val trip = requireNotNull(cache.getTrip(record.tripId))
        val remoteTripId = requireNotNull(trip.serverId)
        val isSingleDayOnly = trip.startDate == trip.endDate && cache.recordCount(trip.id) == 1
        val start = if (isSingleDayOnly) date else trip.startDate.toLocalDate()
        val end = if (isSingleDayOnly) date else trip.endDate.toLocalDate()
        require(date in start..end) { "记录日期必须在旅行日期范围内" }
        if (!isSingleDayOnly) {
            session.updateTrip(remoteTripId, tripRequest(city, start, end))
        }
        val payload = recordRequest(record.type, record.name, date, record.rating, record.cost, record.notes)
        session.updateRecord(
            remoteRecordId,
            if (isSingleDayOnly) payload.copy(trip = tripRequest(city, start, end)) else payload
        )
        syncImages(record, remoteRecordId, photos)
        refresh()
    }

    suspend fun deleteRecord(record: RecordEntity) {
        val remoteId = requireNotNull(record.serverId) { "本地记录不能从云端删除" }
        session.deleteRecord(remoteId)
        refresh()
    }

    private fun tripRequest(city: CityEntity, start: LocalDate, end: LocalDate) =
        TripRequest(city.provinceCode, city.cityCode, city.name, start.toString(), end.toString())

    private fun recordRequest(
        type: RecordType, name: String, date: LocalDate, rating: Float?, cost: Float?, notes: String?
    ) = RecordRequest(type.name, name, date.toString(), rating?.toString(), cost?.toString(), notes)

    private suspend fun uploadImages(recordId: Long, photos: List<Uri>): List<RemoteImage> =
        photos.map { uri ->
            val part = photoManager.createOriginalUploadPart(uri)
                ?: throw IllegalArgumentException("无法读取照片: $uri")
            session.uploadImage(recordId, part)
        }

    private suspend fun syncImages(record: RecordEntity, remoteRecordId: Long, photos: List<Uri>) {
        val previousIds = record.remotePhotoIds.csvValues().mapNotNull { it.toLongOrNull() }
        val previousUrls = record.remotePhotoUrls.csvValues()
        val currentPhotos = photos.map(Uri::toString).toSet()
        val newlyUploaded = mutableListOf<RemoteImage>()

        try {
            photos.filter { it.toString() !in previousUrls }
                .forEach { uri ->
                    val part = photoManager.createOriginalUploadPart(uri)
                        ?: throw IllegalArgumentException("无法读取照片: $uri")
                    newlyUploaded += session.uploadImage(remoteRecordId, part)
                }
        } catch (error: Exception) {
            newlyUploaded.forEach { image -> runCatching { session.deleteImage(image.id) } }
            throw error
        }

        previousIds.zip(previousUrls)
            .filter { (_, url) -> url !in currentPhotos }
            .forEach { (imageId, _) -> session.deleteImage(imageId) }
    }

    private fun requirePhotoCount(photos: List<Uri>) {
        require(photos.size <= MAX_PHOTO_COUNT) { "每条记录最多选择9张照片" }
    }

    private fun String?.csvValues(): List<String> =
        this?.split(",")?.filter(String::isNotBlank) ?: emptyList()

    private companion object {
        const val MAX_PHOTO_COUNT = 9
    }

    private fun Long.toLocalDate() = LocalDate.ofEpochDay(this / 86_400_000L)
}
