package com.miracle.footmarks.data.repository

import android.net.Uri
import androidx.room.withTransaction
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.dao.RecordDao
import com.miracle.footmarks.data.local.dao.TripDao
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import java.time.LocalDate
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject

class RecordRepository @Inject constructor(
    private val database: FootmarksDatabase,
    private val recordDao: RecordDao,
    private val tripDao: TripDao
) {
    fun getAllRecords(): Flow<List<RecordEntity>> = recordDao.getAllRecords()

    fun getRecordsByCity(cityId: Long): Flow<List<RecordEntity>> = recordDao.getRecordsByCity(cityId)

    fun getRecordsByType(type: RecordType): Flow<List<RecordEntity>> = recordDao.getRecordsByType(type)

    fun getTotalRecordCount(): Flow<Int> = recordDao.getTotalRecordCount()

    fun getTotalCityCount(): Flow<Int> = recordDao.getTotalCityCount()

    fun getTotalCost(): Flow<Float> = recordDao.getTotalCost()

    suspend fun getRecordById(id: Long): RecordEntity? = recordDao.getById(id)

    suspend fun insertRecord(record: RecordEntity): Long = recordDao.insert(record)

    suspend fun updateRecord(record: RecordEntity) = recordDao.update(record)

    suspend fun deleteRecord(record: RecordEntity) = recordDao.delete(record)

    suspend fun createRecord(
        cityId: Long,
        type: RecordType,
        name: String,
        date: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoUris: List<Uri>
    ): Long = database.withTransaction {
        val dateMillis = date.toEpochDay() * DAY_MILLIS
        val tripId = tripDao.insert(
            TripEntity(cityId = cityId, startDate = dateMillis, endDate = dateMillis)
        )
        insertRecord(
            buildRecord(tripId, type, name, dateMillis, rating, cost, notes, photoUris)
        )
    }

    suspend fun createRecordForTrip(
        tripId: Long,
        type: RecordType,
        name: String,
        date: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoUris: List<Uri>
    ): Long {
        val trip = requireNotNull(tripDao.getById(tripId)) { "旅行不存在" }
        val dateMillis = date.toEpochDay() * DAY_MILLIS
        require(dateMillis in trip.startDate..trip.endDate) { "记录日期必须在旅行日期范围内" }
        return insertRecord(
            buildRecord(tripId, type, name, dateMillis, rating, cost, notes, photoUris)
        )
    }

    suspend fun updateRecordWithTrip(
        record: RecordEntity,
        cityId: Long,
        date: LocalDate
    ) = database.withTransaction {
        val trip = requireNotNull(tripDao.getById(record.tripId)) { "旅行不存在" }
        val dateMillis = date.toEpochDay() * DAY_MILLIS
        tripDao.update(trip.copy(cityId = cityId, startDate = dateMillis, endDate = dateMillis))
        recordDao.update(record.copy(date = dateMillis))
    }

    private fun buildRecord(
        tripId: Long,
        type: RecordType,
        name: String,
        dateMillis: Long,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoUris: List<Uri>
    ) = RecordEntity(
        tripId = tripId,
        type = type,
        name = name,
        date = dateMillis,
        rating = rating,
        cost = cost,
        notes = notes,
        photoUris = photoUris.takeIf { it.isNotEmpty() }?.joinToString(",")
    )

    private companion object {
        const val DAY_MILLIS = 86_400_000L
    }
}
