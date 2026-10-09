package com.miracle.footmarks.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.miracle.footmarks.data.repository.AdministrativeDivisionRepository
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.ui.screen.records.*
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import android.graphics.Bitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import java.io.File

class FootprintMapScreenTest {
    @get:Rule val rule = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private fun boundaries(code: String) = context.assets.open("maps/$code.json").bufferedReader().use { parseMapRegions(it.readText()) }
    private fun screenshot(name: String) {
        val image = rule.onRoot().captureToImage().asAndroidBitmap()
        val file = File(context.getExternalFilesDir("map-qa"), name)
        file.outputStream().use {
            image.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        val copy = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(
            "cp ${file.absolutePath} /data/local/tmp/footmarks-map-$name"
        )
        android.os.ParcelFileDescriptor.AutoCloseInputStream(copy).use { it.readBytes() }
    }

    @Test fun nationalMapClickSelectsTheActualProvince() {
        val country = boundaries("100000")
        var selected: String? = null
        rule.setContent { FootprintMapContent(
            RecordsUiState(isLoading = false), FootprintMapState(regions = country), {}, { selected = it }, {}, {}, {}, {}
        ) }
        val map = rule.onNodeWithContentDescription("行政区旅行足迹地图")
        map.assertIsDisplayed()
        screenshot("national.png")
        map.performTouchInput {
            val viewport = MapViewport(country, width.toDouble(), height.toDouble())
            val point = viewport.toScreen(country.first { it.code == "320000" }.labelPoint!!)
            click(Offset(point.x.toFloat(), point.y.toFloat()))
        }
        rule.runOnIdle { assertEquals("320000", selected) }
    }

    @Test fun citySelectionShowsItsTripsAndEmptyCityDoesNotShowOtherTrips() {
        val divisions = AdministrativeDivisionRepository(context)
        val locations = divisions.getLocations("320000")
        val state = mutableStateOf(FootprintMapState(
            provinceCode = "320000", provinceName = "江苏省", regions = boundaries("320000"),
            locations = locations, validCityCodes = locations.map { it.code }.toSet()
        ))
        val records = RecordsUiState(
            cities = listOf(CityEntity(1, "南京市", "32", "320100")),
            trips = listOf(TripWithCityAndRecords(TripEntity(7, 1, 0, 0), "南京市", emptyList())),
            isLoading = false
        )
        rule.setContent { FootprintMapContent(records, state.value, {}, {},
            { state.value = state.value.copy(cityCode = it) }, {}, {}, {}) }
        screenshot("province.png")
        rule.onNodeWithText("南京市 · 1次").performScrollTo().performClick()
        rule.onNodeWithText("南京市 · 1次旅行").performScrollTo().assertIsDisplayed()
        rule.runOnIdle { state.value = state.value.copy(cityCode = "320500") }
        rule.onNodeWithText("苏州市 · 0次旅行").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("还没有这里的旅行记录，下一站也许就是这里。").assertIsDisplayed()
        rule.onNodeWithText("南京市 · 1次旅行").assertDoesNotExist()
    }

    @Test fun zoomedShanghaiRemainsClickableAndResetRestoresNationalMap() {
        val country = boundaries("100000")
        var selected: String? = null
        rule.setContent { FootprintMapContent(
            RecordsUiState(isLoading = false), FootprintMapState(regions = country), {}, { selected = it }, {}, {}, {}, {}
        ) }
        val map = rule.onNodeWithContentDescription("行政区旅行足迹地图")
        var transformed = MapGestureTransform()
        map.performTouchInput {
            val viewport = MapViewport(country, width.toDouble(), height.toDouble())
            val focus = viewport.toScreen(country.first { it.code == "310000" }.labelPoint!!)
            // Zoom at Shanghai so that the small municipality stays inside the visible canvas.
            pinch(Offset(focus.x.toFloat() - 12, focus.y.toFloat()),
                Offset(focus.x.toFloat() + 12, focus.y.toFloat()),
                Offset(focus.x.toFloat() - 55, focus.y.toFloat()),
                Offset(focus.x.toFloat() + 55, focus.y.toFloat()))
        }
        val description = map.fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsProperties.StateDescription]
        val scale = description.removePrefix("缩放").removeSuffix("%").toDouble() / 100
        org.junit.Assert.assertTrue(scale > 1)
        map.performTouchInput {
            val viewport = MapViewport(country, width.toDouble(), height.toDouble())
            val focus = viewport.toScreen(country.first { it.code == "310000" }.labelPoint!!)
            transformed = transformed.update(focus, MapPoint(0.0, 0.0), scale, width.toDouble(), height.toDouble())
            val target = transformed.toScreen(focus)
            click(Offset(target.x.toFloat(), target.y.toFloat()))
        }
        rule.runOnIdle { assertEquals("310000", selected) }
        rule.onNodeWithText("复位").performClick()
        map.assert(SemanticsMatcher.expectValue(androidx.compose.ui.semantics.SemanticsProperties.StateDescription, "缩放100%"))
    }
}
