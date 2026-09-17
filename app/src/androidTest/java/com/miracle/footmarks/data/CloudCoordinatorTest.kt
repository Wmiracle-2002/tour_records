package com.miracle.footmarks.data

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
import com.miracle.footmarks.data.repository.CloudCache
import com.miracle.footmarks.data.repository.CloudCoordinator
import java.time.LocalDate
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
            val coordinator = CloudCoordinator(CloudCache(db), session)

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
            val coordinator = CloudCoordinator(CloudCache(db), session)
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
            val coordinator = CloudCoordinator(cache, session)
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
                CloudSession(FootmarksApi.create(server.url("/").toString()), store)
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
}
