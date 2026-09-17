package com.miracle.footmarks.data.local.dao

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Embedded
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import kotlinx.coroutines.flow.Flow

@Dao
interface RecordDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(record: RecordEntity): Long

    @Update
    suspend fun update(record: RecordEntity)

    @Delete
    suspend fun delete(record: RecordEntity)

    @Query("SELECT * FROM records WHERE id = :id")
    suspend fun getById(id: Long): RecordEntity?

    @Query("SELECT * FROM records WHERE serverId = :serverId LIMIT 1")
    suspend fun getByServerId(serverId: Long): RecordEntity?

    @Query("SELECT * FROM records WHERE tripId = :tripId ORDER BY date ASC, createdAt ASC")
    suspend fun getRecordsForTrip(tripId: Long): List<RecordEntity>

    @Query("SELECT COUNT(*) FROM records WHERE tripId = :tripId")
    suspend fun getRecordCountForTrip(tripId: Long): Int

    @Query("""
        SELECT records.* FROM records
        INNER JOIN trips ON records.tripId = trips.id
        WHERE trips.cityId = :cityId
        ORDER BY records.date DESC
    """)
    fun getRecordsByCity(cityId: Long): Flow<List<RecordEntity>>

    @Query("SELECT * FROM records ORDER BY date DESC")
    fun getAllRecords(): Flow<List<RecordEntity>>

    @Query("""
        SELECT records.*, cities.name AS cityName FROM records
        INNER JOIN trips ON records.tripId = trips.id
        INNER JOIN cities ON trips.cityId = cities.id
        ORDER BY records.date DESC
    """)
    fun getAllRecordsWithCity(): Flow<List<RecordWithCity>>

    @Query("SELECT * FROM records WHERE type = :type ORDER BY date DESC")
    fun getRecordsByType(type: RecordType): Flow<List<RecordEntity>>

    @Query("SELECT COUNT(*) FROM records")
    fun getTotalRecordCount(): Flow<Int>

    @Query("""
        SELECT COUNT(DISTINCT trips.cityId) FROM records
        INNER JOIN trips ON records.tripId = trips.id
    """)
    fun getTotalCityCount(): Flow<Int>

    @Query("SELECT COALESCE(SUM(cost), 0) FROM records WHERE cost IS NOT NULL")
    fun getTotalCost(): Flow<Float>
}

data class RecordWithCity(
    @Embedded val record: RecordEntity,
    val cityName: String
)
