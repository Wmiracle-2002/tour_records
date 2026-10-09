package com.miracle.footmarks.ui.screen.records

import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.local.entity.CityEntity

data class FootprintCounts(val cities: Map<String, Int>, val provinces: Map<String, Int>, val unmatched: Int)

fun footprintCounts(
    trips: List<TripWithCityAndRecords>, cities: List<CityEntity>, validCodes: Set<String>
): FootprintCounts {
    val codes = cities.associate { it.id to it.cityCode }
    val matched = trips.mapNotNull { codes[it.trip.cityId]?.takeIf(validCodes::contains) }
    return FootprintCounts(
        matched.groupingBy { it }.eachCount(),
        matched.groupingBy { mapProvinceCode(it)!! }.eachCount(),
        trips.size - matched.size
    )
}

fun tripsForMapCity(
    cityCode: String, trips: List<TripWithCityAndRecords>, cities: List<CityEntity>
): List<TripWithCityAndRecords> {
    val ids = cities.filter { it.cityCode == cityCode }.map { it.id }.toSet()
    return trips.filter { it.trip.cityId in ids }.sortedByDescending { it.trip.startDate }
}
