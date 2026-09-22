package com.miracle.footmarks.data

import android.net.Uri
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.FootmarksApi
import com.miracle.footmarks.data.remote.RemoteRecord
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.TokenStore
import com.miracle.footmarks.data.remote.Tokens
import com.miracle.footmarks.data.local.util.PhotoManager
import com.miracle.footmarks.data.repository.CloudCache
import com.miracle.footmarks.data.repository.CloudCoordinator
import java.time.LocalDate
import java.io.File
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CloudCoordinatorTest {
    @Test
    fun loginRejectsExistingLocalTripsWithoutDeletingThem() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        MockWebServer().use { server ->
            server.start()
            val city = db.cityDao().insert(CityEntity(name = "北京", provinceCode = "110000", cityCode = "110100"))
            val tripId = db.tripDao().insert(TripEntity(cityId = city, startDate = 1000, endDate = 2000))
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                override var tokens: Tokens? = null
            })
            val coordinator = CloudCoordinator(CloudCache(db), session, PhotoManager(context))

            val failure = runCatching { coordinator.login("shared", "password") }.exceptionOrNull()
            assertTrue(failure is IllegalStateException)
            assertTrue(!session.isCloudMode)
            assertEquals(tripId, db.tripDao().getById(tripId)?.id)
            assertEquals(0, server.requestCount)
        }
        db.close()
    }

    @Test
    fun createTextRecordWritesServerFirstThenRefreshesLocalCache() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        MockWebServer().use { server ->
            server.enqueue(json("""{"access_token":"access","refresh_token":"refresh","token_type":"bearer"}"""))
            server.enqueue(json("[]"))
            server.enqueue(json("""{"id":9,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03"}""", 201))
            server.enqueue(json("""{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null}""", 201))
            server.enqueue(json("""[{"id":9,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","records":[{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null}]}]"""))
            server.start()
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                override var tokens: Tokens? = null
            })
            val coordinator = CloudCoordinator(CloudCache(db), session, PhotoManager(context))
            coordinator.login("shared", "password")
            coordinator.createTripWithRecord(
                CityEntity(name = "北京市", provinceCode = "110000", cityCode = "110100"),
                LocalDate.parse("2026-09-01"), LocalDate.parse("2026-09-03"),
                RecordType.FOOD, "烤鸭", LocalDate.parse("2026-09-02"),
                null, 88.5f, null, emptyList()
            )

            assertEquals("烤鸭", db.recordDao().getByServerId(17)?.name)
            assertEquals(9L, db.tripDao().getByServerId(9)?.serverId)
            assertEquals("/api/v1/trips", listOf(server.takeRequest().path, server.takeRequest().path, server.takeRequest().path)[2])
        }
        db.close()
    }

    @Test
    fun createTripCreatesAnEmptyTripAndRefreshesLocalCache() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        MockWebServer().use { server ->
            server.enqueue(json("""{"access_token":"access","refresh_token":"refresh","token_type":"bearer"}"""))
            server.enqueue(json("[]"))
            server.enqueue(json("""{"id":21,"province_code":"110000","city_code":"110100","city_name":"Beijing","start_date":"2026-09-01","end_date":"2026-09-03"}""", 201))
            server.enqueue(json("""[{"id":21,"province_code":"110000","city_code":"110100","city_name":"Beijing","start_date":"2026-09-01","end_date":"2026-09-03","records":[]}]"""))
            server.start()
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                override var tokens: Tokens? = null
            })
            val coordinator = CloudCoordinator(CloudCache(db), session, PhotoManager(context))

            coordinator.login("shared", "password")
            val localTripId = coordinator.createTrip(
                CityEntity(name = "Beijing", provinceCode = "110000", cityCode = "110100"),
                LocalDate.parse("2026-09-01"),
                LocalDate.parse("2026-09-03")
            )

            val cached = db.tripDao().getById(localTripId)
            assertEquals(21L, cached?.serverId)
            assertEquals(0, db.recordDao().getRecordCountForTrip(localTripId))
            server.takeRequest() // login
            server.takeRequest() // initial refresh
            assertEquals("/api/v1/trips", server.takeRequest().path) // create trip
            assertEquals("/api/v1/trips", server.takeRequest().path) // refresh
        }
        db.close()
    }

    @Test
    fun createTripWithRecordUploadsOriginalPhotoBytes() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        val source = File(context.cacheDir, "cos-original-one.jpg")
        val originalBytes = "ORIGINAL_BYTES_123456789".toByteArray()
        source.writeBytes(originalBytes)
        try {
            MockWebServer().use { server ->
                server.enqueue(json("""{"access_token":"access","refresh_token":"refresh","token_type":"bearer"}"""))
                server.enqueue(json("[]"))
                server.enqueue(json("""{"id":9,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03"}""", 201))
                server.enqueue(json("""{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":null,"notes":null}""", 201))
                server.enqueue(json(imageJson(27, 17, "cos-original-one.jpg"), 201))
                server.enqueue(json(remoteTripJson(9, 17, "烤鸭", listOf(27))))
                server.start()
                val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                    override var tokens: Tokens? = null
                })
                val coordinator = CloudCoordinator(CloudCache(db), session, PhotoManager(context))

                coordinator.login("shared", "password")
                coordinator.createTripWithRecord(
                    CityEntity(name = "北京市", provinceCode = "110000", cityCode = "110100"),
                    LocalDate.parse("2026-09-01"), LocalDate.parse("2026-09-03"),
                    RecordType.FOOD, "烤鸭", LocalDate.parse("2026-09-02"),
                    null, null, null, listOf(Uri.fromFile(source))
                )

                val upload = server.takeRequest() // login
                server.takeRequest() // initial refresh
                server.takeRequest() // create trip
                server.takeRequest() // create record
                val uploadRequest = server.takeRequest()
                assertEquals("POST", uploadRequest.method)
                assertEquals("/api/v1/records/17/images", uploadRequest.path)
                val uploadBody = uploadRequest.body.readUtf8()
                assertTrue(uploadBody.contains(String(originalBytes)))
                assertTrue(uploadBody.contains("cos-original-one.jpg"))
                assertNotNull(upload)
                assertEquals("27", db.recordDao().getByServerId(17)?.remotePhotoIds)
            }
        } finally {
            source.delete()
            db.close()
        }
    }

    @Test
    fun createRecordForTripUploadsNineOriginalPhotos() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        val cityId = db.cityDao().insert(CityEntity(name = "北京市", provinceCode = "110000", cityCode = "110100"))
        val localTripId = db.tripDao().insert(
            TripEntity(
                cityId = cityId,
                startDate = LocalDate.parse("2026-09-01").toEpochDay() * 86_400_000L,
                endDate = LocalDate.parse("2026-09-03").toEpochDay() * 86_400_000L,
                serverId = 9
            )
        )
        val files = (1..9).map { index ->
            File(context.cacheDir, "cos-original-$index.jpg").also {
                it.writeText("ORIGINAL_$index")
            }
        }
        try {
            MockWebServer().use { server ->
                server.enqueue(json("""{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":null,"notes":null}""", 201))
                (1..9).forEach { index ->
                    server.enqueue(json(imageJson(26 + index.toLong(), 17, "cos-original-$index.jpg"), 201))
                }
                server.enqueue(json(remoteTripJson(9, 17, "烤鸭", (1..9).map { 26 + it })))
                server.start()
                val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                    override var tokens: Tokens? = Tokens("access", "refresh")
                })
                val coordinator = CloudCoordinator(CloudCache(db), session, PhotoManager(context))

                coordinator.createRecordForTrip(
                    localTripId,
                    RecordType.FOOD,
                    "烤鸭",
                    LocalDate.parse("2026-09-02"),
                    null,
                    null,
                    null,
                    files.map(Uri::fromFile)
                )

                repeat(1) { server.takeRequest() } // create record
                (1..9).forEach { index ->
                    val request = server.takeRequest()
                    assertEquals("/api/v1/records/17/images", request.path)
                    assertTrue(request.body.readUtf8().contains("ORIGINAL_$index"))
                }
                assertEquals("26,27,28,29,30,31,32,33,34", db.recordDao().getByServerId(17)?.remotePhotoIds)
            }
        } finally {
            files.forEach(File::delete)
            db.close()
        }
    }

    @Test
    fun updateRecordUploadsNewPhotoAndDeletesRemovedPhoto() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        val cache = CloudCache(db)
        val newPhoto = File(context.cacheDir, "cos-original-new.jpg").also {
            it.writeText("ORIGINAL_NEW")
        }
        try {
            cache.replaceRemoteTrips(
                listOf(
                    RemoteTrip(
                        9,
                        "110000",
                        "110100",
                        "北京市",
                        "2026-09-02",
                        "2026-09-02",
                        listOf(
                            RemoteRecord(
                                17,
                                9,
                                "FOOD",
                                "烤鸭",
                                "2026-09-02",
                                null,
                                null,
                                null,
                                listOf(
                                    com.miracle.footmarks.data.remote.RemoteImage(
                                        27,
                                        17,
                                        "records/17/old.jpg",
                                        "old.jpg",
                                        "image/jpeg",
                                        128,
                                        "https://images.test/records/17/old.jpg"
                                    )
                                )
                            )
                        )
                    )
                )
            )
            MockWebServer().use { server ->
                server.enqueue(json("""{"id":17,"trip_id":9,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":null,"notes":null}"""))
                server.enqueue(json(imageJson(28, 17, "cos-original-new.jpg"), 201))
                server.enqueue(MockResponse().setResponseCode(204))
                server.enqueue(json(remoteTripJson(9, 17, "烤鸭", listOf(28))))
                server.start()
                val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                    override var tokens: Tokens? = Tokens("access", "refresh")
                })
                val coordinator = CloudCoordinator(cache, session, PhotoManager(context))
                val record = db.recordDao().getByServerId(17)!!
                val city = db.cityDao().getById(db.tripDao().getByServerId(9)!!.cityId)!!

                coordinator.updateRecordWithTrip(
                    record,
                    city,
                    LocalDate.parse("2026-09-02"),
                    listOf(
                        Uri.parse("https://images.test/records/17/old.jpg"),
                        Uri.fromFile(newPhoto)
                    )
                )

                val update = server.takeRequest()
                val upload = server.takeRequest()
                val delete = server.takeRequest()
                val refresh = server.takeRequest()
                assertEquals("PATCH", update.method)
                assertEquals("/api/v1/records/17", update.path)
                assertTrue(upload.body.readUtf8().contains("ORIGINAL_NEW"))
                assertEquals("DELETE", delete.method)
                assertEquals("/api/v1/images/27", delete.path)
                assertEquals("/api/v1/trips", refresh.path)
                assertEquals("28", db.recordDao().getByServerId(17)?.remotePhotoIds)
            }
        } finally {
            newPhoto.delete()
            db.close()
        }
    }

    @Test
    fun invalidDateDoesNotPartiallyUpdateTripOnServer() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        MockWebServer().use { server ->
            server.start()
            val cache = CloudCache(db)
            cache.replaceRemoteTrips(listOf(com.miracle.footmarks.data.remote.RemoteTrip(
                9, "110000", "110100", "北京市", "2026-09-01", "2026-09-03",
                listOf(
                    com.miracle.footmarks.data.remote.RemoteRecord(17, 9, "FOOD", "烤鸭", "2026-09-01", null, null, null),
                    com.miracle.footmarks.data.remote.RemoteRecord(18, 9, "FOOD", "点心", "2026-09-03", null, null, null)
                )
            )))
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), object : TokenStore {
                override var tokens: Tokens? = Tokens("access", "refresh")
            })
            val coordinator = CloudCoordinator(cache, session, PhotoManager(context))
            val record = db.recordDao().getByServerId(17)!!
            val city = db.cityDao().getById(db.tripDao().getByServerId(9)!!.cityId)!!

            val failure = runCatching {
                coordinator.updateRecordWithTrip(
                    record, city, LocalDate.parse("2026-09-04"), emptyList()
                )
            }.exceptionOrNull()
            assertTrue(failure is IllegalArgumentException)
            assertEquals(0, server.requestCount)
        }
        db.close()
    }

    @Test
    fun refreshFailureKeepsCachedTripsForOfflineBrowsing() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = Room.inMemoryDatabaseBuilder(context, FootmarksDatabase::class.java).build()
        MockWebServer().use { server ->
            server.start()
            val cache = CloudCache(db)
            cache.replaceRemoteTrips(
                listOf(
                    RemoteTrip(
                        9,
                        "stress-province",
                        "stress-city",
                        "Offline City",
                        "2026-09-01",
                        "2026-09-03",
                        listOf(RemoteRecord(17, 9, "FOOD", "Cached Food", "2026-09-02", null, null, null))
                    )
                )
            )
            server.enqueue(MockResponse().setResponseCode(503))
            val store = object : TokenStore {
                override var tokens: Tokens? = Tokens("access", "refresh")
            }
            val coordinator = CloudCoordinator(
                cache,
                CloudSession(FootmarksApi.create(server.url("/").toString()), store),
                PhotoManager(context)
            )

            val failure = runCatching { coordinator.refresh() }.exceptionOrNull()

            assertNotNull(failure)
            assertEquals("Cached Food", db.recordDao().getByServerId(17)?.name)
            assertNotNull(db.tripDao().getByServerId(9))
        }
        db.close()
    }

    private fun json(body: String, status: Int = 200) = MockResponse()
        .setResponseCode(status).setBody(body).addHeader("Content-Type", "application/json")

    private fun imageJson(id: Long, recordId: Long, filename: String) =
        """{"id":$id,"record_id":$recordId,"object_key":"records/$recordId/$filename","original_filename":"$filename","content_type":"image/jpeg","size_bytes":128,"created_at":"2026-09-18T00:00:00Z","url":"https://images.test/records/$recordId/$filename"}"""

    private fun remoteTripJson(tripId: Long, recordId: Long, name: String, imageIds: List<Int>) =
        """[{"id":$tripId,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","records":[{"id":$recordId,"trip_id":$tripId,"type":"FOOD","name":"$name","date":"2026-09-02","rating":null,"cost":null,"notes":null,"images":[${imageIds.map { id -> imageJson(id.toLong(), recordId, "cos-original-${id - 26}.jpg") }.joinToString(",")}]}]}]"""

}
