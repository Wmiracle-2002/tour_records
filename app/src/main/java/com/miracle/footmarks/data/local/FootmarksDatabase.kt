package com.miracle.footmarks.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.miracle.footmarks.data.local.dao.CityDao
import com.miracle.footmarks.data.local.dao.RecordDao
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity

@Database(
    entities = [
        CityEntity::class,
        RecordEntity::class
    ],
    version = 1,
    exportSchema = false
)
@TypeConverters(Converters::class)
abstract class FootmarksDatabase : RoomDatabase() {
    abstract fun cityDao(): CityDao
    abstract fun recordDao(): RecordDao
}
