package com.miracle.footmarks.data.repository

import androidx.room.withTransaction
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.remote.RemoteTrip
import java.time.LocalDate
import javax.inject.Inject

class CloudCache @Inject constructor(private val database: FootmarksDatabase) {
    suspend fun hasLocalTrips(): Boolean = database.tripDao().countLocalTrips() > 0

    suspend fun getTrip(id: Long): TripEntity? = database.tripDao().getById(id)

    suspend fun getCity(id: Long): CityEntity? = database.cityDao().getById(id)

    suspend fun getRecord(id: Long): RecordEntity? = database.recordDao().getById(id)

    suspend fun getLocalRecord(serverId: Long): RecordEntity? =
        database.recordDao().getByServerId(serverId)

    suspend fun recordCount(tripId: Long): Int = database.recordDao().getRecordCountForTrip(tripId)

    suspend fun replaceRemoteTrips(trips: List<RemoteTrip>) {
        database.withTransaction {
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
                    serverId = remote.id
                )
                val localTripId = if (previous == null) tripDao.insert(trip) else {
                    tripDao.update(trip)
                    trip.id
                }
                for (item in remote.records) {
                    val oldRecord = recordDao.getByServerId(item.id)
                    val record = RecordEntity(
                        id = oldRecord?.id ?: 0,
                        tripId = localTripId,
                        type = RecordType.valueOf(item.type),
                        name = item.name,
                        date = item.date.toMillis(),
                        rating = item.rating?.toFloat(),
                        cost = item.cost?.toFloat(),
                        notes = item.notes,
                        createdAt = oldRecord?.createdAt ?: System.currentTimeMillis(),
                        serverId = item.id
                    )
                    if (oldRecord == null) recordDao.insert(record) else recordDao.update(record)
                }
                val serverRecordIds = remote.records.map { it.id }.toSet()
                recordDao.getRecordsForTrip(localTripId)
                    .filter { it.serverId != null && it.serverId !in serverRecordIds }
                    .forEach { recordDao.delete(it) }
            }
            val serverTripIds = trips.map { it.id }.toSet()
            tripDao.getServerTrips()
                .filter { it.serverId !in serverTripIds }
                .forEach { tripDao.delete(it) }
        }
    }

    private fun String.toMillis(): Long = LocalDate.parse(this).toEpochDay() * 86_400_000L
}
