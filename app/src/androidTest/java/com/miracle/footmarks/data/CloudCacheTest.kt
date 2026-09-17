package com.miracle.footmarks.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.remote.RemoteRecord
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.repository.CloudCache
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CloudCacheTest {
    @Test
    fun refreshUpdatesRemoteRowsAndPreservesExistingLocalTrip() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        try {
            val cityId = db.cityDao().insert(CityEntity(name = "上海市", provinceCode = "310000", cityCode = "310100"))
            val legacyId = db.tripDao().insert(TripEntity(cityId = cityId, startDate = 1000, endDate = 2000))
            db.recordDao().insert(RecordEntity(tripId = legacyId, type = RecordType.FOOD, name = "本地照片", date = 1000, photoUris = "/app/photo.jpg"))
            val cache = CloudCache(db)
            val remote = RemoteTrip(9, "110000", "110100", "北京市", "2026-09-01", "2026-09-03", listOf(
                RemoteRecord(17, 9, "FOOD", "烤鸭", "2026-09-02", null, "88.50", null)
            ))

            cache.replaceRemoteTrips(listOf(remote))
            cache.replaceRemoteTrips(listOf(remote.copy(cityName = "北京城", records = listOf(remote.records.single().copy(name = "北京烤鸭")))))

            val cloudTrip = db.tripDao().getByServerId(9)!!
            assertEquals("北京烤鸭", db.recordDao().getByServerId(17)?.name)
            assertEquals("北京城", db.cityDao().getById(cloudTrip.cityId)?.name)
            assertEquals(1, db.recordDao().getRecordsForTrip(cloudTrip.id).size)
            assertNotNull(db.tripDao().getById(legacyId))

            cache.replaceRemoteTrips(emptyList())
            assertEquals(null, db.tripDao().getByServerId(9))
            assertEquals("本地照片", db.recordDao().getRecordsForTrip(legacyId).single().name)
        } finally {
            db.close()
        }
    }
}
