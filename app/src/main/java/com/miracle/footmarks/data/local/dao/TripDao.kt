package com.miracle.footmarks.data.local.dao

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Embedded
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Relation
import androidx.room.Transaction
import androidx.room.Update
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.TripEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface TripDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(trip: TripEntity): Long

    @Update
    suspend fun update(trip: TripEntity)

    @Delete
    suspend fun delete(trip: TripEntity)

    @Query("SELECT * FROM trips WHERE id = :id")
    suspend fun getById(id: Long): TripEntity?

    @Query("SELECT * FROM trips WHERE serverId = :serverId LIMIT 1")
    suspend fun getByServerId(serverId: Long): TripEntity?

    @Query("SELECT * FROM trips WHERE serverId IS NOT NULL")
    suspend fun getServerTrips(): List<TripEntity>

    @Query("SELECT COUNT(*) FROM trips WHERE serverId IS NULL")
    suspend fun countLocalTrips(): Int

    @Query("SELECT * FROM trips WHERE cityId = :cityId ORDER BY startDate DESC")
    fun getTripsByCity(cityId: Long): Flow<List<TripEntity>>

    @Query("SELECT * FROM trips ORDER BY startDate DESC")
    fun getAllTrips(): Flow<List<TripEntity>>

    @Transaction
    @Query("""
        SELECT trips.*, cities.name AS cityName FROM trips
        INNER JOIN cities ON trips.cityId = cities.id
        ORDER BY trips.startDate DESC, trips.createdAt DESC
    """)
    fun getTimeline(): Flow<List<TripWithCityAndRecords>>

    @Query("""
        SELECT COUNT(DISTINCT cityId) AS cityCount,
               COUNT(*) AS tripCount,
               (SELECT COALESCE(SUM(cost), 0) FROM records) AS totalCost
        FROM trips
    """)
    fun getTravelStats(): Flow<TravelStats>
}

data class TripWithCityAndRecords(
    @Embedded val trip: TripEntity,
    val cityName: String,
    @Relation(parentColumn = "id", entityColumn = "tripId")
    val records: List<RecordEntity>
)

data class TravelStats(
    val cityCount: Int,
    val tripCount: Int,
    val totalCost: Float
)
