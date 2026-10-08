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

    @Query("SELECT records.* FROM records INNER JOIN trips ON records.tripId = trips.id WHERE records.id = :id AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)")
    suspend fun getById(id: Long): RecordEntity?

    @Query("SELECT records.* FROM records INNER JOIN trips ON records.tripId = trips.id WHERE records.serverId = :serverId AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0) LIMIT 1")
    suspend fun getByServerId(serverId: Long): RecordEntity?

    @Query("SELECT records.* FROM records INNER JOIN trips ON records.tripId = trips.id WHERE tripId = :tripId AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0) ORDER BY records.date ASC, records.createdAt ASC")
    suspend fun getRecordsForTrip(tripId: Long): List<RecordEntity>

    @Query("SELECT COUNT(*) FROM records INNER JOIN trips ON records.tripId = trips.id WHERE tripId = :tripId AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)")
    suspend fun getRecordCountForTrip(tripId: Long): Int

    @Query("""
        SELECT records.* FROM records
        INNER JOIN trips ON records.tripId = trips.id
        WHERE trips.cityId = :cityId AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)
        ORDER BY records.date DESC
    """)
    fun getRecordsByCity(cityId: Long): Flow<List<RecordEntity>>

    @Query("SELECT records.* FROM records INNER JOIN trips ON records.tripId = trips.id WHERE trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0) ORDER BY records.date DESC")
    fun getAllRecords(): Flow<List<RecordEntity>>

    @Query("""
        SELECT records.*, cities.name AS cityName FROM records
        INNER JOIN trips ON records.tripId = trips.id
        INNER JOIN cities ON trips.cityId = cities.id
        WHERE trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)
        ORDER BY records.date DESC
    """)
    fun getAllRecordsWithCity(): Flow<List<RecordWithCity>>

    @Query("SELECT records.* FROM records INNER JOIN trips ON records.tripId = trips.id WHERE records.type = :type AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0) ORDER BY records.date DESC")
    fun getRecordsByType(type: RecordType): Flow<List<RecordEntity>>

    @Query("SELECT COUNT(*) FROM records INNER JOIN trips ON records.tripId = trips.id WHERE trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)")
    fun getTotalRecordCount(): Flow<Int>

    @Query("""
        SELECT COUNT(DISTINCT trips.cityId) FROM records
        INNER JOIN trips ON records.tripId = trips.id
        WHERE trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)
    """)
    fun getTotalCityCount(): Flow<Int>

    @Query("SELECT COALESCE(SUM(cost), 0) FROM records INNER JOIN trips ON records.tripId = trips.id WHERE records.cost IS NOT NULL AND trips.ownerId = COALESCE((SELECT userId FROM active_account WHERE id = 1), 0)")
    fun getTotalCost(): Flow<Float>
}

data class RecordWithCity(
    @Embedded val record: RecordEntity,
    val cityName: String
)
