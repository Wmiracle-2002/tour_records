package com.miracle.footmarks.data.local.dao

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.miracle.footmarks.data.local.entity.CityEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CityDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(city: CityEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(cities: List<CityEntity>)

    @Update
    suspend fun update(city: CityEntity)

    @Delete
    suspend fun delete(city: CityEntity)

    @Query("SELECT * FROM cities WHERE id = :id")
    suspend fun getById(id: Long): CityEntity?

    @Query("SELECT * FROM cities ORDER BY name ASC")
    fun getAllCities(): Flow<List<CityEntity>>

    @Query("SELECT * FROM cities WHERE name LIKE '%' || :query || '%' ORDER BY name ASC")
    fun searchCities(query: String): Flow<List<CityEntity>>

    @Query("""
        SELECT c.*, COUNT(DISTINCT r.id) as recordCount
        FROM cities c
        LEFT JOIN records r ON c.id = r.cityId
        GROUP BY c.id
        HAVING recordCount > 0
        ORDER BY recordCount DESC
    """)
    fun getCitiesWithRecordCount(): Flow<List<CityWithRecordCount>>
}

data class CityWithRecordCount(
    val id: Long,
    val name: String,
    val provinceCode: String,
    val cityCode: String,
    val recordCount: Int
)
