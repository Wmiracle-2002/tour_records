package com.miracle.footmarks.data.repository

import android.net.Uri
import androidx.room.withTransaction
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.dao.RecordDao
import com.miracle.footmarks.data.local.dao.RecordWithCity
import com.miracle.footmarks.data.local.dao.TripDao
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.local.util.PhotoManager
import java.time.LocalDate
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject

class RecordRepository @Inject constructor(
    private val database: FootmarksDatabase,
    private val recordDao: RecordDao,
    private val tripDao: TripDao,
    private val photoManager: PhotoManager
) {
    fun getAllRecords(): Flow<List<RecordEntity>> = recordDao.getAllRecords()

    fun getAllRecordsWithCity(): Flow<List<RecordWithCity>> = recordDao.getAllRecordsWithCity()

    fun getRecordsByCity(cityId: Long): Flow<List<RecordEntity>> = recordDao.getRecordsByCity(cityId)

    fun getRecordsByType(type: RecordType): Flow<List<RecordEntity>> = recordDao.getRecordsByType(type)

    fun getTotalRecordCount(): Flow<Int> = recordDao.getTotalRecordCount()

    fun getTotalCityCount(): Flow<Int> = recordDao.getTotalCityCount()

    fun getTotalCost(): Flow<Float> = recordDao.getTotalCost()

    suspend fun getRecordById(id: Long): RecordEntity? = recordDao.getById(id)

    suspend fun insertRecord(record: RecordEntity): Long = recordDao.insert(record)

    suspend fun updateRecord(record: RecordEntity) = recordDao.update(record)

    suspend fun deleteRecord(record: RecordEntity) {
        database.withTransaction {
            recordDao.delete(record)
        }
        photoManager.deletePhotos(parsePhotoPaths(record.photoUris))
    }

    suspend fun createRecord(
        cityId: Long,
        type: RecordType,
        name: String,
        date: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoUris: List<Uri>
    ): Long = createTripWithRecord(
        cityId = cityId,
        startDate = date,
        endDate = date,
        type = type,
        name = name,
        recordDate = date,
        rating = rating,
        cost = cost,
        notes = notes,
        photoUris = photoUris
    )

    suspend fun createTripWithRecord(
        cityId: Long,
        startDate: LocalDate,
        endDate: LocalDate,
        type: RecordType,
        name: String,
        recordDate: LocalDate,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoUris: List<Uri>
    ): Long {
        require(!endDate.isBefore(startDate)) { "结束日期不能早于开始日期" }
        require(recordDate in startDate..endDate) { "记录日期必须在旅行日期范围内" }
        val storedPhotos = storePhotos(photoUris)
        return try {
            database.withTransaction {
                val startMillis = startDate.toEpochDay() * DAY_MILLIS
                val endMillis = endDate.toEpochDay() * DAY_MILLIS
                val recordMillis = recordDate.toEpochDay() * DAY_MILLIS
                val tripId = tripDao.insert(
                    TripEntity(cityId = cityId, startDate = startMillis, endDate = endMillis)
                )
                insertRecord(
                    buildRecord(tripId, type, name, recordMillis, rating, cost, notes, storedPhotos)
                )
            }
        } catch (error: Exception) {
            photoManager.deletePhotos(storedPhotos)
            throw error
        }
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
        val storedPhotos = storePhotos(photoUris)
        return try {
            insertRecord(buildRecord(tripId, type, name, dateMillis, rating, cost, notes, storedPhotos))
        } catch (error: Exception) {
            photoManager.deletePhotos(storedPhotos)
            throw error
        }
    }

    suspend fun updateRecordWithTrip(
        record: RecordEntity,
        cityId: Long,
        date: LocalDate,
        photoUris: List<Uri>? = null
    ) {
        val previousPhotos = parsePhotoPaths(record.photoUris)
        val storedPhotos = photoUris?.let { storePhotos(it) } ?: previousPhotos
        val addedPhotos = storedPhotos - previousPhotos.toSet()
        try {
            database.withTransaction {
                val trip = requireNotNull(tripDao.getById(record.tripId)) { "旅行不存在" }
                val dateMillis = date.toEpochDay() * DAY_MILLIS
                val isOnlyRecordInSingleDayTrip =
                    trip.startDate == trip.endDate && recordDao.getRecordCountForTrip(trip.id) == 1
                if (isOnlyRecordInSingleDayTrip) {
                    tripDao.update(
                        trip.copy(cityId = cityId, startDate = dateMillis, endDate = dateMillis)
                    )
                } else {
                    require(dateMillis in trip.startDate..trip.endDate) {
                        "记录日期必须在旅行日期范围内"
                    }
                    tripDao.update(trip.copy(cityId = cityId))
                }
                recordDao.update(
                    record.copy(
                        date = dateMillis,
                        photoUris = storedPhotos.takeIf { it.isNotEmpty() }?.joinToString(",")
                    )
                )
            }
        } catch (error: Exception) {
            photoManager.deletePhotos(addedPhotos)
            throw error
        }
        photoManager.deletePhotos(previousPhotos - storedPhotos.toSet())
    }

    private fun buildRecord(
        tripId: Long,
        type: RecordType,
        name: String,
        dateMillis: Long,
        rating: Float?,
        cost: Float?,
        notes: String?,
        photoPaths: List<String>
    ) = RecordEntity(
        tripId = tripId,
        type = type,
        name = name,
        date = dateMillis,
        rating = rating,
        cost = cost,
        notes = notes,
        photoUris = photoPaths.takeIf { it.isNotEmpty() }?.joinToString(",")
    )

    private suspend fun storePhotos(photoUris: List<Uri>): List<String> = photoUris.map { uri ->
        val existingPath = uri.toString()
        if (photoManager.isManagedPhoto(existingPath)) {
            existingPath
        } else {
            requireNotNull(photoManager.savePhoto(uri)) { "照片保存失败" }
        }
    }

    private fun parsePhotoPaths(value: String?): List<String> =
        value?.split(",")?.filter { it.isNotBlank() } ?: emptyList()

    private companion object {
        const val DAY_MILLIS = 86_400_000L
    }
}
