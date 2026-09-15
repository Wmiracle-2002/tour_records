package com.miracle.footmarks.data.repository

import com.miracle.footmarks.data.local.dao.CityDao
import com.miracle.footmarks.data.local.dao.CityWithRecordCount
import com.miracle.footmarks.data.local.entity.CityEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import javax.inject.Inject

class CityRepository @Inject constructor(
    private val cityDao: CityDao
) {
    fun getAllCities(): Flow<List<CityEntity>> = cityDao.getAllCities()

    fun getCitiesWithRecordCount(): Flow<List<CityWithRecordCount>> = cityDao.getCitiesWithRecordCount()

    fun searchCities(query: String): Flow<List<CityEntity>> = cityDao.searchCities(query)

    suspend fun getCityById(id: Long): CityEntity? = cityDao.getById(id)

    suspend fun insertCity(city: CityEntity): Long = cityDao.insert(city)

    suspend fun updateCity(city: CityEntity) = cityDao.update(city)

    suspend fun deleteCity(city: CityEntity) = cityDao.delete(city)

    /**
     * 确保城市存在，如果不存在则创建
     * @return 城市ID
     */
    suspend fun ensureCityExists(name: String, provinceCode: String = "", cityCode: String = ""): Long {
        // 先查找是否已存在（使用 first() 获取第一次发射的值）
        val existing = searchCities(name).first().firstOrNull { it.name == name }

        return if (existing != null) {
            existing.id
        } else {
            // 不存在则创建
            val newCity = CityEntity(
                name = name,
                provinceCode = provinceCode,
                cityCode = cityCode
            )
            insertCity(newCity)
        }
    }

    suspend fun ensureDivisionExists(name: String, provinceCode: String, cityCode: String): Long {
        val existing = cityDao.getByCityCode(cityCode)
        if (existing != null) {
            if (existing.name != name || existing.provinceCode != provinceCode) {
                updateCity(existing.copy(name = name, provinceCode = provinceCode))
            }
            return existing.id
        }
        return insertCity(
            CityEntity(name = name, provinceCode = provinceCode, cityCode = cityCode)
        )
    }
}
