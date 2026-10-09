package com.miracle.footmarks.ui.screen.records

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords

class FootprintMapTest {
    private val polygon = listOf(
        listOf(MapPoint(0.0, 0.0), MapPoint(10.0, 0.0), MapPoint(10.0, 10.0), MapPoint(0.0, 10.0)),
        listOf(MapPoint(3.0, 3.0), MapPoint(7.0, 3.0), MapPoint(7.0, 7.0), MapPoint(3.0, 7.0))
    )

    @Test fun polygonHolesAndSeparateIslandsUseSameHitRules() {
        val region = MapRegion("320000", "江苏", listOf(polygon, listOf(listOf(
            MapPoint(20.0, 20.0), MapPoint(21.0, 20.0), MapPoint(21.0, 21.0), MapPoint(20.0, 21.0)
        ))))
        assertTrue(region.contains(MapPoint(1.0, 1.0)))
        assertFalse(region.contains(MapPoint(5.0, 5.0)))
        assertTrue(region.contains(MapPoint(20.5, 20.5)))
        assertFalse(region.contains(MapPoint(15.0, 15.0)))
    }

    @Test fun parsesPolygonAndMultiPolygonAndRejectsInvalidCoordinates() {
        val json = """{"type":"FeatureCollection","features":[
          {"properties":{"adcode":320000,"name":"江苏"},"geometry":{"type":"Polygon","coordinates":[[[118,30],[119,30],[119,31],[118,30]]]}},
          {"properties":{"adcode":350000,"name":"福建"},"geometry":{"type":"MultiPolygon","coordinates":[[[[118,25],[119,25],[119,26],[118,25]]]]}}
        ]}"""
        assertEquals(listOf("320000", "350000"), parseMapRegions(json).map { it.code })
        assertThrows(IllegalArgumentException::class.java) { parseMapRegions(json.replace("118,30", "999,30")) }
        assertThrows(IllegalArgumentException::class.java) { parseMapRegions("""{"type":"FeatureCollection","features":[]}""") }
    }

    @Test fun viewportRoundTripKeepsClickAndDrawingAligned() {
        val region = MapRegion("320000", "江苏", listOf(polygon))
        val viewport = MapViewport(listOf(region), 300.0, 200.0)
        val point = MapPoint(2.0, 8.0)
        val restored = viewport.fromScreen(viewport.toScreen(point))
        assertEquals(point.x, restored.x, 0.000001)
        assertEquals(point.y, restored.y, 0.000001)
        assertTrue(region.contains(restored))
    }

    @Test fun zoomPreservesGestureFocusAndHitCoordinates() {
        val original = MapGestureTransform()
        val focus = MapPoint(150.0, 100.0)
        val zoomed = original.update(focus, MapPoint(0.0, 0.0), 4.0, 300.0, 200.0)
        assertEquals(focus, zoomed.toScreen(original.fromScreen(focus)))
        val point = MapPoint(170.0, 120.0)
        val restored = zoomed.fromScreen(zoomed.toScreen(point))
        assertEquals(point.x, restored.x, 0.000001)
        assertEquals(point.y, restored.y, 0.000001)
        assertEquals(4.0, zoomed.scale, 0.000001)
    }

    @Test fun zoomAndPanStayBoundedAndZoomingOutRestoresWholeMap() {
        val focus = MapPoint(150.0, 100.0)
        val zoomed = MapGestureTransform().update(focus, MapPoint(-9999.0, 9999.0), 100.0, 300.0, 200.0)
        assertEquals(12.0, zoomed.scale, 0.000001)
        assertEquals(MapPoint(-3300.0, 0.0), zoomed.offset)
        val reset = zoomed.update(focus, MapPoint(0.0, 0.0), 0.001, 300.0, 200.0)
        assertEquals(MapGestureTransform(), reset)
    }

    @Test fun provinceCodeNormalizesExistingCodesWithoutGuessingInvalidOnes() {
        assertEquals("320000", mapProvinceCode("320100"))
        assertEquals("110000", mapProvinceCode("110000"))
        assertEquals("420000", mapProvinceCode("429004"))
        assertNull(mapProvinceCode(""))
        assertNull(mapProvinceCode("3201"))
        assertNull(mapProvinceCode("abcdef"))
    }

    @Test fun bundledBoundariesAreParseableAndPreserveAllCountryFeatures() {
        val directory = File("src/main/assets/maps").takeIf { it.isDirectory } ?: File("app/src/main/assets/maps")
        val files = directory.listFiles()!!.filter { it.extension == "json" && it.name != "manifest.json" }
        assertEquals(28, files.size)
        files.forEach { assertTrue(parseMapRegions(it.readText()).isNotEmpty()) }
        assertEquals(35, parseMapRegions(File(directory, "100000.json").readText()).size)
    }

    @Test fun countsTripsNotRecordsAndKeepsUnmatchedTripsVisible() {
        val cities = listOf(
            CityEntity(1, "南京", "32", "320100"),
            CityEntity(2, "北京", "11", "110000"),
            CityEntity(3, "仙桃", "42", "429004"),
            CityEntity(4, "旧城市", "32", "")
        )
        val trips = listOf(1L, 1L, 2L, 3L, 4L).mapIndexed { index, city ->
            TripWithCityAndRecords(TripEntity(index.toLong(), city, index.toLong(), index.toLong()), "城市", emptyList())
        }
        val counts = footprintCounts(trips, cities, setOf("320100", "110000", "429004"))
        assertEquals(mapOf("320100" to 2, "110000" to 1, "429004" to 1), counts.cities)
        assertEquals(mapOf("320000" to 2, "110000" to 1, "420000" to 1), counts.provinces)
        assertEquals(1, counts.unmatched)
        assertEquals(2, tripsForMapCity("320100", trips, cities).size)
        assertTrue(tripsForMapCity("350100", trips, cities).isEmpty())
        assertEquals(0, footprintCounts(emptyList(), cities, emptySet()).unmatched)
    }
}
