package com.miracle.footmarks.di

import android.content.Context
import androidx.room.Room
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.dao.CityDao
import com.miracle.footmarks.data.local.dao.RecordDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(
        @ApplicationContext context: Context
    ): FootmarksDatabase {
        return Room.databaseBuilder(
            context,
            FootmarksDatabase::class.java,
            "footmarks_db"
        ).build()
    }

    @Provides
    fun provideCityDao(database: FootmarksDatabase): CityDao {
        return database.cityDao()
    }

    @Provides
    fun provideRecordDao(database: FootmarksDatabase): RecordDao {
        return database.recordDao()
    }
}
