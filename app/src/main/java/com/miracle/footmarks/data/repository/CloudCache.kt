package com.miracle.footmarks.data.repository

import androidx.room.withTransaction
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.local.entity.ActiveAccountEntity
import com.miracle.footmarks.data.local.entity.SyncCursorEntity
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.RemoteImage
import com.miracle.footmarks.data.remote.TripSyncPage
import java.time.LocalDate
import javax.inject.Inject

class CloudCache @Inject constructor(private val database: FootmarksDatabase) {
    suspend fun activateAccount(userId: Long) {
        database.accountDao().setActive(ActiveAccountEntity(userId = userId))
    }

    suspend fun cursor(userId: Long): String? = database.accountDao().cursor(userId)
    suspend fun activeAccountId(): Long = database.accountDao().activeUserId() ?: 0

    suspend fun deleteAccountCache(userId: Long) {
        database.withTransaction {
            database.tripDao().deleteOwnerTrips(userId)
            database.accountDao().deleteCursor(userId)
            database.accountDao().setActive(ActiveAccountEntity(userId = 0))
        }
    }

    suspend fun hasLocalTrips(): Boolean = database.tripDao().countLocalTrips() > 0

    suspend fun clearAnonymousTrips() {
        database.tripDao().deleteOwnerTrips(0)
    }

    suspend fun getTrip(id: Long): TripEntity? = database.tripDao().getById(id)

    suspend fun getTripByServerId(serverId: Long): TripEntity? =
        database.tripDao().getByServerId(serverId)

    suspend fun getCity(id: Long): CityEntity? = database.cityDao().getById(id)

    suspend fun getRecord(id: Long): RecordEntity? = database.recordDao().getById(id)

    suspend fun getLocalRecord(serverId: Long): RecordEntity? =
        database.recordDao().getByServerId(serverId)

    suspend fun updateImageUrls(userId: Long, serverRecordId: Long, images: List<RemoteImage>): RecordEntity? {
        return database.withTransaction {
            if (database.accountDao().activeUserId() != userId) return@withTransaction null
            val record = database.recordDao().getByServerId(serverRecordId) ?: return@withTransaction null
            if (database.tripDao().getById(record.tripId)?.ownerId != userId) return@withTransaction null
            val updated = record.copy(
                remotePhotoIds = images.takeIf { it.isNotEmpty() }?.joinToString(",") { it.id.toString() },
                remotePhotoUrls = images.takeIf { it.isNotEmpty() }?.joinToString(",") { it.url },
            )
            database.recordDao().update(updated)
            updated
        }
    }

    suspend fun recordCount(tripId: Long): Int = database.recordDao().getRecordCountForTrip(tripId)

    suspend fun replaceRemoteTrips(trips: List<RemoteTrip>) {
        database.withTransaction {
            upsertRemoteTrips(trips, database.accountDao().activeUserId() ?: 0)
            val serverTripIds = trips.map { it.id }.toSet()
            database.tripDao().getServerTrips()
                .filter { it.serverId !in serverTripIds }
                .forEach { database.tripDao().delete(it) }
        }
    }

    suspend fun applySyncPage(userId: Long, page: TripSyncPage) {
        database.withTransaction {
            check(database.accountDao().activeUserId() == userId) { "账号已切换，忽略旧同步响应" }
            upsertRemoteTrips(page.upserts, userId)
            page.deletedIds.forEach { serverId ->
                database.tripDao().getByServerId(serverId)?.let { database.tripDao().delete(it) }
            }
            database.accountDao().saveCursor(SyncCursorEntity(userId, page.nextCursor))
        }
    }

    private suspend fun upsertRemoteTrips(trips: List<RemoteTrip>, userId: Long) {
            val cityDao = database.cityDao()
            val tripDao = database.tripDao()
            val recordDao = database.recordDao()
            for (remote in trips) {
                val existingCity = cityDao.getByCityCode(remote.cityCode)
                if (existingCity != null &&
                    (existingCity.name != remote.cityName || existingCity.provinceCode != remote.provinceCode)
                ) {
                    cityDao.update(existingCity.copy(
                        name = remote.cityName, provinceCode = remote.provinceCode
                    ))
                }
                val cityId = existingCity?.id ?: cityDao.insert(
                    CityEntity(
                        name = remote.cityName,
                        provinceCode = remote.provinceCode,
                        cityCode = remote.cityCode
                    )
                )
                val previous = tripDao.getByServerId(remote.id)
                val trip = TripEntity(
                    id = previous?.id ?: 0,
                    cityId = cityId,
                    startDate = remote.startDate.toMillis(),
                    endDate = remote.endDate.toMillis(),
                    createdAt = previous?.createdAt ?: System.currentTimeMillis(),
                    serverId = remote.id,
                    ownerId = userId
                )
                val localTripId = if (previous == null) tripDao.insert(trip) else {
                    tripDao.update(trip)
                    trip.id
                }
                for (item in remote.records.orEmpty()) {
                    val oldRecord = recordDao.getByServerId(item.id)
                    val remoteImages = item.images
                    val record = RecordEntity(
                        id = oldRecord?.id ?: 0,
                        tripId = localTripId,
                        type = RecordType.valueOf(item.type),
                        name = item.name,
                        date = item.date.toMillis(),
                        rating = item.rating?.toFloat(),
                        cost = item.cost?.toFloat(),
                        notes = item.notes,
                        remotePhotoIds = when {
                            remoteImages == null -> oldRecord?.remotePhotoIds
                            remoteImages.isEmpty() -> null
                            else -> remoteImages.joinToString(",") { it.id.toString() }
                        },
                        remotePhotoUrls = when {
                            remoteImages == null -> oldRecord?.remotePhotoUrls
                            remoteImages.isEmpty() -> null
                            else -> remoteImages.joinToString(",") { it.url }
                        },
                        createdAt = oldRecord?.createdAt ?: System.currentTimeMillis(),
                        serverId = item.id
                    )
                    if (oldRecord == null) recordDao.insert(record) else recordDao.update(record)
                }
                val serverRecordIds = remote.records.orEmpty().map { it.id }.toSet()
                recordDao.getRecordsForTrip(localTripId)
                    .filter { it.serverId != null && it.serverId !in serverRecordIds }
                    .forEach { recordDao.delete(it) }
            }
    }

    private fun String.toMillis(): Long = LocalDate.parse(this).toEpochDay() * 86_400_000L
}
