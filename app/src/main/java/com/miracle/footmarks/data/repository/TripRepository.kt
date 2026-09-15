package com.miracle.footmarks.data.repository

import com.miracle.footmarks.data.local.dao.TripDao
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.local.entity.TripEntity
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject

class TripRepository @Inject constructor(
    private val tripDao: TripDao
) {
    fun getAllTrips(): Flow<List<TripEntity>> = tripDao.getAllTrips()

    fun getTripsByCity(cityId: Long): Flow<List<TripEntity>> = tripDao.getTripsByCity(cityId)

    fun getTimeline(): Flow<List<TripWithCityAndRecords>> = tripDao.getTimeline()

    fun getTravelStats(): Flow<TravelStats> = tripDao.getTravelStats()

    suspend fun getTripById(id: Long): TripEntity? = tripDao.getById(id)

    suspend fun insertTrip(trip: TripEntity): Long {
        require(trip.endDate >= trip.startDate) { "结束日期不能早于开始日期" }
        return tripDao.insert(trip)
    }

    suspend fun updateTrip(trip: TripEntity) {
        require(trip.endDate >= trip.startDate) { "结束日期不能早于开始日期" }
        tripDao.update(trip)
    }

    suspend fun deleteTrip(trip: TripEntity) = tripDao.delete(trip)

    suspend fun createTrip(cityId: Long, startDate: Long, endDate: Long): Long =
        insertTrip(
            TripEntity(
                cityId = cityId,
                startDate = startDate,
                endDate = endDate
            )
        )
}
