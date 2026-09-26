package com.miracle.footmarks.data.repository

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AdministrativeLocationTest {
    private val jiangsu = AdministrativeProvince(
        code = "320000", name = "江苏省", cities = listOf(
            AdministrativeCity(
                code = "320500", name = "苏州市", areas = listOf(
                    AdministrativeArea("320583", "昆山市"),
                    AdministrativeArea("320505", "虎丘区")
                )
            )
        )
    )

    @Test
    fun prefectureIsSelectableButItsCountiesAreOnlySearchAliases() {
        assertEquals(listOf("苏州市"), locationsFor(jiangsu).map { it.name })
        assertEquals("320500", searchLocations(listOf(jiangsu), "昆山").single().code)
        assertEquals("江苏省 · 苏州市", searchLocations(listOf(jiangsu), "虎丘").single().breadcrumb)
    }

    @Test
    fun municipalityAppearsOnceAndItsDistrictsSearchToTheCity() {
        val beijing = AdministrativeProvince(
            code = "110000", name = "北京市", cities = listOf(
                AdministrativeCity("110100", "市辖区", listOf(AdministrativeArea("110108", "海淀区")))
            )
        )
        assertEquals(listOf("110000"), locationsFor(beijing).map { it.code })
        assertEquals("北京市", searchLocations(listOf(beijing), "海淀").single().name)
    }

    @Test
    fun directlyAdministeredCitiesRemainSelectableButCountiesDoNot() {
        val hubei = AdministrativeProvince(
            code = "420000", name = "湖北省", cities = listOf(
                AdministrativeCity(
                    code = "429000", name = "省直辖县级行政区划", areas = listOf(
                        AdministrativeArea("429004", "仙桃市"),
                        AdministrativeArea("429021", "神农架林区")
                    )
                )
            )
        )
        assertEquals(listOf("仙桃市"), locationsFor(hubei).map { it.name })
        assertTrue(searchLocations(listOf(hubei), "神农架").isEmpty())
    }
}
