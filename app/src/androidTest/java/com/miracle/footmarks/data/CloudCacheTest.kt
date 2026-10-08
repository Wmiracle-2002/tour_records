package com.miracle.footmarks.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.gson.Gson
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.remote.RemoteRecord
import com.miracle.footmarks.data.remote.RemoteImage
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.TripSyncPage
import com.miracle.footmarks.data.repository.CloudCache
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CloudCacheTest {
    @Test
    fun syncPagesStayWithinActiveAccountAndPersistCursor() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        try {
            val cache = CloudCache(db)
            val first = RemoteTrip(9, "320000", "320100", "南京市", "2026-10-01", "2026-10-03", emptyList())
            val second = RemoteTrip(10, "310000", "310100", "上海市", "2026-10-01", "2026-10-03", emptyList())
            cache.activateAccount(1)
            cache.applySyncPage(1, TripSyncPage(listOf(first), emptyList(), "d:1", false))
            assertEquals("d:1", cache.cursor(1))
            cache.activateAccount(2)
            assertEquals(null, cache.getTripByServerId(9))
            cache.applySyncPage(2, TripSyncPage(listOf(second), emptyList(), "d:2", false))
            assertEquals(null, cache.getTripByServerId(9))
            cache.activateAccount(1)
            assertEquals(9L, cache.getTripByServerId(9)?.serverId)
            assertEquals(null, cache.getTripByServerId(10))
            cache.applySyncPage(1, TripSyncPage(emptyList(), listOf(9), "d:3", false))
            assertEquals(null, cache.getTripByServerId(9))
            assertEquals("d:3", cache.cursor(1))
        } finally {
            db.close()
        }
    }

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

    @Test
    fun refreshStoresRemoteImageMetadataForCoil() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        try {
            val cache = CloudCache(db)
            cache.replaceRemoteTrips(
                listOf(
                    RemoteTrip(
                        9,
                        "110000",
                        "110100",
                        "Beijing",
                        "2026-09-01",
                        "2026-09-03",
                        listOf(
                            RemoteRecord(
                                17,
                                9,
                                "FOOD",
                                "Food",
                                "2026-09-02",
                                null,
                                null,
                                null,
                                listOf(
                                    RemoteImage(
                                        27,
                                        17,
                                        "records/17/photo.jpg",
                                        "photo.jpg",
                                        "image/jpeg",
                                        128,
                                        "https://images.test/records/17/photo.jpg"
                                    )
                                )
                            )
                        )
                    )
                )
            )

            val record = db.recordDao().getByServerId(17)!!
            assertEquals("27", record.remotePhotoIds)
            assertEquals("https://images.test/records/17/photo.jpg", record.remotePhotoUrls)
        } finally {
            db.close()
        }
    }

    @Test
    fun signedImageUrlRefreshStaysInActiveAccount() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        try {
            val cache = CloudCache(db)
            cache.activateAccount(7)
            cache.applySyncPage(7, com.miracle.footmarks.data.remote.TripSyncPage(
                listOf(RemoteTrip(9, "110000", "110100", "北京", "2026-09-01", "2026-09-03",
                    listOf(RemoteRecord(17, 9, "FOOD", "烤鸭", "2026-09-02", null, null, null, emptyList())))),
                emptyList(), "d:1", false,
            ))
            val newImage = RemoteImage(27, 17, "records/17/a.jpg", "a.jpg", "image/jpeg", 10, "https://new-url")
            assertEquals(null, cache.updateImageUrls(8, 17, listOf(newImage)))
            assertEquals(null, db.recordDao().getByServerId(17)?.remotePhotoUrls)
            assertEquals("https://new-url", cache.updateImageUrls(7, 17, listOf(newImage))?.remotePhotoUrls)
        } finally {
            db.close()
        }
    }

    @Test
    fun refreshKeepsRecordsWhenServerImageFieldIsNull() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        try {
            val cityId = db.cityDao().insert(CityEntity(name = "北京市", provinceCode = "110000", cityCode = "110100"))
            val tripId = db.tripDao().insert(
                TripEntity(
                    cityId = cityId,
                    startDate = 1,
                    endDate = 2,
                    serverId = 9
                )
            )
            db.recordDao().insert(
                RecordEntity(
                    tripId = tripId,
                    type = RecordType.FOOD,
                    name = "旧缓存",
                    date = 1,
                    remotePhotoIds = "27",
                    remotePhotoUrls = "https://images.test/records/17/old.jpg",
                    serverId = 17
                )
            )
            val remoteRecord = Gson().fromJson<RemoteRecord>(
                """{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":null,"notes":null,"images":null}""",
                RemoteRecord::class.java
            )
            CloudCache(db).replaceRemoteTrips(
                listOf(
                    RemoteTrip(
                        9,
                        "110000",
                        "110100",
                        "北京市",
                        "2026-09-01",
                        "2026-09-03",
                        listOf(remoteRecord)
                    )
                )
            )

            assertEquals("烤鸭", db.recordDao().getByServerId(17)?.name)
            assertEquals("27", db.recordDao().getByServerId(17)?.remotePhotoIds)
        } finally {
            db.close()
        }
    }
}
