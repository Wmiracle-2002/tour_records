package com.miracle.footmarks.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.repository.RecordRepository
import com.miracle.footmarks.data.repository.TripRepository
import java.time.LocalDate
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TripDataLayerTest {
    private lateinit var database: FootmarksDatabase

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        database = Room.inMemoryDatabaseBuilder(
            context,
            FootmarksDatabase::class.java
        ).allowMainThreadQueries().build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun tripDaoSupportsCrud() = runBlocking {
        val cityId = database.cityDao().insert(testCity())
        val tripDao = database.tripDao()
        val tripId = tripDao.insert(testTrip(cityId))

        val inserted = tripDao.getById(tripId)
        assertEquals(0L, inserted?.startDate)

        tripDao.update(inserted!!.copy(endDate = 3_000L))
        assertEquals(3_000L, tripDao.getById(tripId)?.endDate)

        tripDao.delete(inserted.copy(endDate = 3_000L))
        assertNull(tripDao.getById(tripId))
    }

    @Test
    fun recordRepositorySupportsCrudAndCityQuery() = runBlocking {
        val cityId = database.cityDao().insert(testCity())
        val tripId = database.tripDao().insert(testTrip(cityId))
        val repository = RecordRepository(
            database = database,
            recordDao = database.recordDao(),
            tripDao = database.tripDao()
        )

        val recordId = repository.createRecordForTrip(
            tripId = tripId,
            type = RecordType.ATTRACTION,
            name = "故宫",
            date = LocalDate.ofEpochDay(0),
            rating = 5f,
            cost = 60f,
            notes = "测试",
            photoUris = emptyList()
        )

        val inserted = repository.getRecordById(recordId)!!
        assertEquals("故宫", inserted.name)
        assertEquals(1, repository.getRecordsByCity(cityId).first().size)

        repository.updateRecord(inserted.copy(name = "故宫博物院"))
        assertEquals("故宫博物院", repository.getRecordById(recordId)?.name)

        repository.deleteRecord(inserted.copy(name = "故宫博物院"))
        assertNull(repository.getRecordById(recordId))
    }

    @Test
    fun recordDateMustBeInsideTripRange() = runBlocking {
        val cityId = database.cityDao().insert(testCity())
        val tripId = database.tripDao().insert(testTrip(cityId))
        val repository = RecordRepository(
            database = database,
            recordDao = database.recordDao(),
            tripDao = database.tripDao()
        )

        assertThrows(IllegalArgumentException::class.java) {
            runBlocking {
                repository.createRecordForTrip(
                    tripId = tripId,
                    type = RecordType.FOOD,
                    name = "测试美食",
                    date = LocalDate.ofEpochDay(10),
                    rating = null,
                    cost = null,
                    notes = null,
                    photoUris = emptyList()
                )
            }
        }
        Unit
    }

    @Test
    fun createRecordCreatesSingleDayTripForCurrentUi() = runBlocking {
        val cityId = database.cityDao().insert(testCity())
        val repository = RecordRepository(
            database = database,
            recordDao = database.recordDao(),
            tripDao = database.tripDao()
        )
        val date = LocalDate.of(2026, 9, 15)

        val recordId = repository.createRecord(
            cityId = cityId,
            type = RecordType.ATTRACTION,
            name = "测试景点",
            date = date,
            rating = null,
            cost = null,
            notes = null,
            photoUris = emptyList()
        )

        val record = repository.getRecordById(recordId)!!
        val trip = database.tripDao().getById(record.tripId)!!
        val expectedDate = date.toEpochDay() * DAY_MILLIS
        assertEquals(cityId, trip.cityId)
        assertEquals(expectedDate, trip.startDate)
        assertEquals(expectedDate, trip.endDate)
    }

    @Test
    fun updateRecordWithTripUpdatesRelationAndPreservesCreatedAt() = runBlocking {
        val firstCityId = database.cityDao().insert(testCity())
        val secondCityId = database.cityDao().insert(
            CityEntity(name = "上海", provinceCode = "上海市", cityCode = "310000")
        )
        val repository = RecordRepository(
            database = database,
            recordDao = database.recordDao(),
            tripDao = database.tripDao()
        )
        val recordId = repository.createRecord(
            cityId = firstCityId,
            type = RecordType.FOOD,
            name = "早餐",
            date = LocalDate.of(2026, 9, 14),
            rating = null,
            cost = null,
            notes = null,
            photoUris = emptyList()
        )
        val original = repository.getRecordById(recordId)!!
        val newDate = LocalDate.of(2026, 9, 15)

        repository.updateRecordWithTrip(
            record = original.copy(name = "午餐", date = newDate.toEpochDay() * DAY_MILLIS),
            cityId = secondCityId,
            date = newDate
        )

        val updated = repository.getRecordById(recordId)!!
        val trip = database.tripDao().getById(updated.tripId)!!
        assertEquals("午餐", updated.name)
        assertEquals(original.createdAt, updated.createdAt)
        assertEquals(secondCityId, trip.cityId)
        assertEquals(updated.date, trip.startDate)
        assertEquals(updated.date, trip.endDate)
    }

    @Test
    fun deletingCityCascadesToTripsAndRecords() = runBlocking {
        val city = testCity()
        val cityId = database.cityDao().insert(city)
        val tripId = database.tripDao().insert(testTrip(cityId))
        val repository = RecordRepository(
            database = database,
            recordDao = database.recordDao(),
            tripDao = database.tripDao()
        )
        val recordId = repository.createRecordForTrip(
            tripId = tripId,
            type = RecordType.ATTRACTION,
            name = "测试景点",
            date = LocalDate.ofEpochDay(0),
            rating = null,
            cost = null,
            notes = null,
            photoUris = emptyList()
        )

        database.cityDao().delete(city.copy(id = cityId))

        assertNull(database.tripDao().getById(tripId))
        assertNull(repository.getRecordById(recordId))
    }

    @Test
    fun tripRepositoryRejectsEndDateBeforeStartDate() {
        val repository = TripRepository(database.tripDao())

        assertThrows(IllegalArgumentException::class.java) {
            runBlocking {
                repository.createTrip(
                    cityId = 1,
                    startDate = 2_000L,
                    endDate = 1_000L
                )
            }
        }
    }

    @Test
    fun tripRepositorySupportsCrudAndCityQuery() = runBlocking {
        val cityId = database.cityDao().insert(testCity())
        val repository = TripRepository(database.tripDao())
        val tripId = repository.createTrip(cityId, 1_000L, 2_000L)

        val inserted = repository.getTripById(tripId)!!
        assertEquals(1, repository.getTripsByCity(cityId).first().size)

        repository.updateTrip(inserted.copy(endDate = 3_000L))
        assertEquals(3_000L, repository.getTripById(tripId)?.endDate)

        repository.deleteTrip(inserted.copy(endDate = 3_000L))
        assertNull(repository.getTripById(tripId))
    }

    private fun testCity() = CityEntity(
        name = "北京",
        provinceCode = "北京市",
        cityCode = "110000"
    )

    private fun testTrip(cityId: Long) = TripEntity(
        cityId = cityId,
        startDate = 0L,
        endDate = 2_000L
    )

    private companion object {
        const val DAY_MILLIS = 86_400_000L
    }
}
