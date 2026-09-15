package com.miracle.footmarks.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.miracle.footmarks.data.local.dao.CityDao
import com.miracle.footmarks.data.local.dao.RecordDao
import com.miracle.footmarks.data.local.dao.TripDao
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.TripEntity

@Database(
    entities = [
        CityEntity::class,
        TripEntity::class,
        RecordEntity::class
    ],
    version = 2,
    exportSchema = false
)
@TypeConverters(Converters::class)
abstract class FootmarksDatabase : RoomDatabase() {
    abstract fun cityDao(): CityDao
    abstract fun tripDao(): TripDao
    abstract fun recordDao(): RecordDao
}
