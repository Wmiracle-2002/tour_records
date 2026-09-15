package com.miracle.footmarks.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.repository.AdministrativeDivisionRepository
import com.miracle.footmarks.data.repository.CityRepository
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AdministrativeDivisionRepositoryTest {
    private lateinit var context: Context
    private lateinit var database: FootmarksDatabase

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
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
    fun bundledDataContainsCompleteProvinceCityAreaHierarchy() {
        val repository = AdministrativeDivisionRepository(context)
        val startedAt = System.currentTimeMillis()

        val provinces = repository.getProvinces()
        val elapsed = System.currentTimeMillis() - startedAt
        val cities = provinces.flatMap { it.cities }
        val areas = cities.flatMap { it.areas }

        assertEquals(31, provinces.size)
        assertTrue(areas.size >= 3_000)
        assertTrue(elapsed < 500)
        assertTrue(provinces.any { it.name == "北京市" && it.code == "110000" })
        assertTrue(cities.any { it.name == "阿坝藏族羌族自治州" })
        assertTrue(areas.any { it.name == "昆山市" && it.code == "320583" })
    }

    @Test
    fun searchReturnsBreadcrumbAndNormalizedCodes() {
        val repository = AdministrativeDivisionRepository(context)

        val result = repository.search("昆山").single()

        assertEquals("昆山市", result.name)
        assertEquals("江苏省 · 苏州市 · 昆山市", result.breadcrumb)
        assertEquals("320000", result.provinceCode)
        assertEquals("320583", result.code)
    }

    @Test
    fun sameNamedAreasWithDifferentCodesRemainDistinct() = runBlocking {
        val cityRepository = CityRepository(database.cityDao())

        val firstId = cityRepository.ensureDivisionExists("鼓楼区", "320000", "320106")
        val secondId = cityRepository.ensureDivisionExists("鼓楼区", "350000", "350102")

        assertNotEquals(firstId, secondId)
        assertEquals("320106", cityRepository.getCityById(firstId)?.cityCode)
        assertEquals("350102", cityRepository.getCityById(secondId)?.cityCode)
    }

    @Test
    fun selectingDivisionNormalizesExistingCityWithSameCode() = runBlocking {
        val cityRepository = CityRepository(database.cityDao())
        val oldId = cityRepository.insertCity(
            CityEntity(name = "北京", provinceCode = "北京市", cityCode = "110000")
        )

        val selectedId = cityRepository.ensureDivisionExists("北京市", "110000", "110000")

        assertEquals(oldId, selectedId)
        assertEquals("北京市", cityRepository.getCityById(oldId)?.name)
        assertEquals("110000", cityRepository.getCityById(oldId)?.provinceCode)
    }
}
