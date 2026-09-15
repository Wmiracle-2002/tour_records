package com.miracle.footmarks.data.repository

import android.net.Uri
import com.miracle.footmarks.data.local.dao.RecordDao
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import kotlinx.coroutines.flow.Flow
import java.time.LocalDate
import javax.inject.Inject

class RecordRepository @Inject constructor(
    private val recordDao: RecordDao
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
    ): Long {
        // TODO: 实现照片压缩和存储
        val photoUrisStr = if (photoUris.isNotEmpty()) {
            photoUris.joinToString(",") { it.toString() }
        } else null

        val record = RecordEntity(
            cityId = cityId,
            type = type,
            name = name,
            date = date.toEpochDay() * 86400000L, // LocalDate -> 时间戳
            rating = rating,
            cost = cost,
            notes = notes,
            photoUris = photoUrisStr
        )
        return insertRecord(record)
    }
}
