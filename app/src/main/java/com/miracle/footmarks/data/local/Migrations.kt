package com.miracle.footmarks.data.local

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("DROP INDEX IF EXISTS index_records_cityId")
        db.execSQL("DROP INDEX IF EXISTS index_records_date")
        db.execSQL("ALTER TABLE records RENAME TO records_v1")
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                cityId INTEGER NOT NULL,
                startDate INTEGER NOT NULL,
                endDate INTEGER NOT NULL,
                createdAt INTEGER NOT NULL,
                FOREIGN KEY(cityId) REFERENCES cities(id) ON UPDATE NO ACTION ON DELETE CASCADE
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS index_trips_cityId ON trips (cityId)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_trips_startDate ON trips (startDate)")
        db.execSQL(
            "INSERT INTO trips (id, cityId, startDate, endDate, createdAt) " +
                "SELECT id, cityId, date, date, createdAt FROM records_v1"
        )
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                tripId INTEGER NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                date INTEGER NOT NULL,
                rating REAL,
                cost REAL,
                notes TEXT,
                photoUris TEXT,
                createdAt INTEGER NOT NULL,
                FOREIGN KEY(tripId) REFERENCES trips(id) ON UPDATE NO ACTION ON DELETE CASCADE
            )
            """.trimIndent()
        )
        db.execSQL(
            "INSERT INTO records (id, tripId, type, name, date, rating, cost, notes, photoUris, createdAt) " +
                "SELECT id, id, type, name, date, rating, cost, notes, photoUris, createdAt FROM records_v1"
        )
        db.execSQL("DROP TABLE records_v1")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_records_tripId ON records (tripId)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_records_date ON records (date)")
    }
}
