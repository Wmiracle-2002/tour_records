package com.miracle.footmarks.data.local.util

import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.repository.CityRepository
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class DatabaseInitializer @Inject constructor(
    private val cityRepository: CityRepository
) {
    /**
     * 初始化一些常用城市数据
     */
    suspend fun initializeCities() {
        // 检查是否已有数据
        var hasData = false
        cityRepository.getAllCities().collect { cities ->
            hasData = cities.isNotEmpty()
        }

        if (hasData) return

        // 插入常用城市
        val cities = listOf(
            CityEntity(name = "北京", provinceCode = "北京市", cityCode = "110000"),
            CityEntity(name = "上海", provinceCode = "上海市", cityCode = "310000"),
            CityEntity(name = "广州", provinceCode = "广东省", cityCode = "440100"),
            CityEntity(name = "深圳", provinceCode = "广东省", cityCode = "440300"),
            CityEntity(name = "杭州", provinceCode = "浙江省", cityCode = "330100"),
            CityEntity(name = "成都", provinceCode = "四川省", cityCode = "510100"),
            CityEntity(name = "西安", provinceCode = "陕西省", cityCode = "610100"),
            CityEntity(name = "重庆", provinceCode = "重庆市", cityCode = "500000"),
            CityEntity(name = "南京", provinceCode = "江苏省", cityCode = "320100"),
            CityEntity(name = "武汉", provinceCode = "湖北省", cityCode = "420100"),
            CityEntity(name = "天津", provinceCode = "天津市", cityCode = "120000"),
            CityEntity(name = "苏州", provinceCode = "江苏省", cityCode = "320500"),
            CityEntity(name = "长沙", provinceCode = "湖南省", cityCode = "430100"),
            CityEntity(name = "郑州", provinceCode = "河南省", cityCode = "410100"),
            CityEntity(name = "青岛", provinceCode = "山东省", cityCode = "370200"),
            CityEntity(name = "大连", provinceCode = "辽宁省", cityCode = "210200"),
            CityEntity(name = "厦门", provinceCode = "福建省", cityCode = "350200"),
            CityEntity(name = "宁波", provinceCode = "浙江省", cityCode = "330200"),
            CityEntity(name = "昆明", provinceCode = "云南省", cityCode = "530100"),
            CityEntity(name = "哈尔滨", provinceCode = "黑龙江省", cityCode = "230100")
        )

        cities.forEach { city ->
            cityRepository.insertCity(city)
        }
    }
}
