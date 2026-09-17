package com.miracle.footmarks.data.repository

import android.net.Uri
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RecordRequest
import com.miracle.footmarks.data.remote.TripRequest
import java.time.LocalDate
import javax.inject.Inject

class CloudCoordinator @Inject constructor(
    private val cache: CloudCache,
    private val session: CloudSession
) {
    val isCloudMode: Boolean get() = session.isCloudMode

    suspend fun login(username: String, password: String) {
        check(!cache.hasLocalTrips()) {
            "本机已有未同步的旅行，请先备份或使用空数据设备登录"
        }
        session.login(username, password)
        refresh()
    }

    suspend fun refresh() {
        cache.replaceRemoteTrips(session.getTrips())
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
        requireNoPhotos(photos)
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
        requireNoPhotos(photos)
        val remoteTripId = requireNotNull(cache.getTrip(localTripId)?.serverId) {
            "本地旅行不能加入云端记录"
        }
        val created = session.createRecord(
            remoteTripId, recordRequest(type, name, date, rating, cost, notes)
        )
        refresh()
        return requireNotNull(cache.getLocalRecord(created.id)).id
    }

    suspend fun updateRecordWithTrip(
        record: RecordEntity,
        city: CityEntity,
        date: LocalDate,
        photos: List<Uri>
    ) {
        requireNoPhotos(photos)
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

    private fun requireNoPhotos(photos: List<Uri>) {
        check(photos.isEmpty()) { "云端照片上传暂未开放，请先创建不带照片的记录" }
    }

    private fun Long.toLocalDate() = LocalDate.ofEpochDay(this / 86_400_000L)
}
