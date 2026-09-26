package com.miracle.footmarks.data.repository

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import org.json.JSONArray

private val MUNICIPALITY_CODES = setOf("110000", "120000", "310000", "500000")

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

internal fun locationsFor(province: AdministrativeProvince): List<AdministrativeLocation> = buildList {
    province.cities.forEach { city ->
        when {
            province.code in MUNICIPALITY_CODES -> {
                if (city.name == "市辖区") add(
                    AdministrativeLocation(province.code, province.name, province.code, province.name)
                )
            }
            city.name == "省直辖县级行政区划" || city.name == "自治区直辖县级行政区划" -> {
                city.areas.filter { it.name.endsWith("市") }.forEach { area ->
                    add(AdministrativeLocation(
                        area.code, area.name, province.code, "${province.name} · ${area.name}"
                    ))
                }
            }
            else -> add(AdministrativeLocation(
                city.code, city.name, province.code, "${province.name} · ${city.name}"
            ))
        }
    }
}

internal fun searchLocations(
    provinces: List<AdministrativeProvince>, query: String
): List<AdministrativeLocation> {
    val keyword = query.trim()
    if (keyword.isEmpty()) return emptyList()
    return provinces.flatMap { province ->
        val parentCodes = province.cities.asSequence()
            .filter { city -> city.areas.any { it.name.contains(keyword, ignoreCase = true) } }
            .map { city ->
                if (province.code in MUNICIPALITY_CODES)
                    province.code else city.code
            }.toSet()
        locationsFor(province).filter { location ->
            location.name.contains(keyword, ignoreCase = true) || location.code in parentCodes
        }
    }
}

@Singleton
class AdministrativeDivisionRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val cachedProvinces: List<AdministrativeProvince> by lazy(LazyThreadSafetyMode.SYNCHRONIZED) {
        context.assets.open(DATA_FILE).bufferedReader().use { parse(it.readText()) }
    }

    fun getProvinces(): List<AdministrativeProvince> = cachedProvinces

    fun getLocations(provinceCode: String): List<AdministrativeLocation> =
        cachedProvinces.firstOrNull { it.code == provinceCode }?.let(::locationsFor).orEmpty()

    fun search(query: String): List<AdministrativeLocation> = searchLocations(cachedProvinces, query)

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
