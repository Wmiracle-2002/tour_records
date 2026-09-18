package com.miracle.footmarks.data

import android.content.Context
import androidx.room.Room
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.MIGRATION_1_2
import com.miracle.footmarks.data.local.MIGRATION_2_3
import com.miracle.footmarks.data.local.MIGRATION_3_4
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DatabaseMigrationTest {

    @Test
    fun migrationFrom1To2PreservesEveryRecordAsSingleDayTrip() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val databaseName = "migration-1-2-test"
        context.deleteDatabase(databaseName)
        createVersionOneDatabase(context, databaseName).use { helper ->
            helper.writableDatabase.apply {
                execSQL("INSERT INTO cities (id, name, provinceCode, cityCode) VALUES (1, '北京', '北京市', '110000')")
                execSQL(
                    "INSERT INTO records (id, cityId, type, name, date, rating, cost, notes, photoUris, createdAt) " +
                        "VALUES (7, 1, 'ATTRACTION', '故宫', 1726358400000, 5.0, 60.0, '测试', NULL, 1000)"
                )
            }
        }

        val database = Room.databaseBuilder(context, FootmarksDatabase::class.java, databaseName)
            .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
            .build()

        val record = database.recordDao().getById(7)!!
        val trip = database.tripDao().getById(record.tripId)!!
        assertEquals(1L, trip.cityId)
        assertEquals(record.date, trip.startDate)
        assertEquals(record.date, trip.endDate)
        assertEquals("故宫", record.name)

        assertEquals(null, trip.serverId)
        assertEquals(null, record.serverId)
        database.close()
        context.deleteDatabase(databaseName)
        Unit
    }

    @Test
    fun migrationFrom2To3PreservesLocalDataWithoutServerIds() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val databaseName = "migration-2-3-test"
        context.deleteDatabase(databaseName)
        FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name(databaseName)
                .callback(object : SupportSQLiteOpenHelper.Callback(2) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE cities (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, name TEXT NOT NULL, provinceCode TEXT NOT NULL, cityCode TEXT NOT NULL)")
                        db.execSQL("CREATE TABLE trips (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, cityId INTEGER NOT NULL, startDate INTEGER NOT NULL, endDate INTEGER NOT NULL, createdAt INTEGER NOT NULL, FOREIGN KEY(cityId) REFERENCES cities(id) ON UPDATE NO ACTION ON DELETE CASCADE)")
                        db.execSQL("CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, tripId INTEGER NOT NULL, type TEXT NOT NULL, name TEXT NOT NULL, date INTEGER NOT NULL, rating REAL, cost REAL, notes TEXT, photoUris TEXT, createdAt INTEGER NOT NULL, FOREIGN KEY(tripId) REFERENCES trips(id) ON UPDATE NO ACTION ON DELETE CASCADE)")
                        db.execSQL("CREATE INDEX index_trips_cityId ON trips(cityId)")
                        db.execSQL("CREATE INDEX index_trips_startDate ON trips(startDate)")
                        db.execSQL("CREATE INDEX index_records_tripId ON records(tripId)")
                        db.execSQL("CREATE INDEX index_records_date ON records(date)")
                    }
                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
                }).build()
        ).use { helper ->
            helper.writableDatabase.apply {
                execSQL("INSERT INTO cities VALUES (1, '北京', '110000', '110100')")
                execSQL("INSERT INTO trips VALUES (3, 1, 1000, 2000, 1000)")
                execSQL("INSERT INTO records VALUES (4, 3, 'FOOD', '烤鸭', 1500, NULL, 88.5, NULL, NULL, 1000)")
            }
        }
        val database = Room.databaseBuilder(context, FootmarksDatabase::class.java, databaseName)
            .addMigrations(MIGRATION_2_3, MIGRATION_3_4).build()
        assertEquals(null, database.tripDao().getById(3)?.serverId)
        assertEquals(null, database.recordDao().getById(4)?.serverId)
        assertEquals("烤鸭", database.recordDao().getById(4)?.name)
        database.close()
        context.deleteDatabase(databaseName)
        Unit
    }

    private fun createVersionOneDatabase(
        context: Context,
        databaseName: String
    ): SupportSQLiteOpenHelper = FrameworkSQLiteOpenHelperFactory().create(
        SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(databaseName)
            .callback(object : SupportSQLiteOpenHelper.Callback(1) {
                override fun onCreate(db: SupportSQLiteDatabase) {
                    db.execSQL(
                        "CREATE TABLE IF NOT EXISTS cities (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                            "name TEXT NOT NULL, provinceCode TEXT NOT NULL, cityCode TEXT NOT NULL)"
                    )
                    db.execSQL(
                        "CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                            "cityId INTEGER NOT NULL, type TEXT NOT NULL, name TEXT NOT NULL, date INTEGER NOT NULL, " +
                            "rating REAL, cost REAL, notes TEXT, photoUris TEXT, createdAt INTEGER NOT NULL, " +
                            "FOREIGN KEY(cityId) REFERENCES cities(id) ON UPDATE NO ACTION ON DELETE CASCADE)"
                    )
                    db.execSQL("CREATE INDEX IF NOT EXISTS index_records_cityId ON records (cityId)")
                    db.execSQL("CREATE INDEX IF NOT EXISTS index_records_date ON records (date)")
                }

                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            })
            .build()
    )
}
