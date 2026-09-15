package com.miracle.footmarks.data.repository

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import org.json.JSONArray

data class AdministrativeArea(
    val code: String,
    val name: String
)

data class AdministrativeCity(
    val code: String,
    val name: String,
    val areas: List<AdministrativeArea>
)

data class AdministrativeProvince(
    val code: String,
    val name: String,
    val cities: List<AdministrativeCity>
)

data class AdministrativeLocation(
    val code: String,
    val name: String,
    val provinceCode: String,
    val breadcrumb: String
)

@Singleton
class AdministrativeDivisionRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val cachedProvinces: List<AdministrativeProvince> by lazy(LazyThreadSafetyMode.SYNCHRONIZED) {
        context.assets.open(DATA_FILE).bufferedReader().use { parse(it.readText()) }
    }

    fun getProvinces(): List<AdministrativeProvince> = cachedProvinces

    fun getLocations(provinceCode: String): List<AdministrativeLocation> =
        cachedProvinces.firstOrNull { it.code == provinceCode }?.toLocations().orEmpty()

    fun search(query: String): List<AdministrativeLocation> {
        val keyword = query.trim()
        if (keyword.isEmpty()) return emptyList()
        return cachedProvinces.asSequence()
            .flatMap { it.toLocations().asSequence() }
            .filter { it.name.contains(keyword, ignoreCase = true) }
            .toList()
    }

    private fun AdministrativeProvince.toLocations(): List<AdministrativeLocation> = buildList {
        cities.forEach { city ->
            if (!city.isGroupingNode()) {
                val locationName = if (isMunicipality() && city.name == "市辖区") name else city.name
                add(
                    AdministrativeLocation(
                        code = if (locationName == name) code else city.code,
                        name = locationName,
                        provinceCode = code,
                        breadcrumb = if (locationName == name) name else "$name · ${city.name}"
                    )
                )
            }
            city.areas.forEach { area ->
                add(
                    AdministrativeLocation(
                        code = area.code,
                        name = area.name,
                        provinceCode = code,
                        breadcrumb = "$name · ${city.name} · ${area.name}"
                    )
                )
            }
        }
    }

    private fun AdministrativeProvince.isMunicipality(): Boolean =
        code in setOf("110000", "120000", "310000", "500000")

    private fun AdministrativeCity.isGroupingNode(): Boolean =
        name == "省直辖县级行政区划" || name == "自治区直辖县级行政区划"

    private fun parse(json: String): List<AdministrativeProvince> {
        val provinceArray = JSONArray(json)
        return List(provinceArray.length()) { provinceIndex ->
            val provinceObject = provinceArray.getJSONObject(provinceIndex)
            val cityArray = provinceObject.getJSONArray("children")
            AdministrativeProvince(
                code = provinceObject.getString("code").padEnd(6, '0'),
                name = provinceObject.getString("name"),
                cities = List(cityArray.length()) { cityIndex ->
                    val cityObject = cityArray.getJSONObject(cityIndex)
                    val areaArray = cityObject.optJSONArray("children") ?: JSONArray()
                    AdministrativeCity(
                        code = cityObject.getString("code").padEnd(6, '0'),
                        name = cityObject.getString("name"),
                        areas = List(areaArray.length()) { areaIndex ->
                            val areaObject = areaArray.getJSONObject(areaIndex)
                            AdministrativeArea(
                                code = areaObject.getString("code"),
                                name = areaObject.getString("name")
                            )
                        }
                    )
                }
            )
        }
    }

    private companion object {
        const val DATA_FILE = "administrative_divisions_2023.json"
    }
}
