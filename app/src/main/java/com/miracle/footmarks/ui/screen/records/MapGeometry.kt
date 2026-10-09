package com.miracle.footmarks.ui.screen.records

import com.google.gson.JsonParser
import kotlin.math.ln
import kotlin.math.min
import kotlin.math.tan

data class MapPoint(val x: Double, val y: Double)

data class MapGestureTransform(val scale: Double = 1.0, val offset: MapPoint = MapPoint(0.0, 0.0)) {
    fun toScreen(point: MapPoint) = MapPoint(point.x * scale + offset.x, point.y * scale + offset.y)
    fun fromScreen(point: MapPoint) = MapPoint((point.x - offset.x) / scale, (point.y - offset.y) / scale)

    fun update(focus: MapPoint, pan: MapPoint, zoom: Double, width: Double, height: Double): MapGestureTransform {
        val nextScale = (scale * zoom).coerceIn(1.0, 12.0)
        if (nextScale == 1.0) return MapGestureTransform()
        val ratio = nextScale / scale
        return MapGestureTransform(nextScale, MapPoint(
            (focus.x + (offset.x - focus.x) * ratio + pan.x).coerceIn(-width * (nextScale - 1.0), 0.0),
            (focus.y + (offset.y - focus.y) * ratio + pan.y).coerceIn(-height * (nextScale - 1.0), 0.0)
        ))
    }
}

data class MapRegion(
    val code: String,
    val name: String,
    val polygons: List<List<List<MapPoint>>>,
    val labelPoint: MapPoint? = null
) {
    fun contains(point: MapPoint): Boolean = polygons.any { polygon ->
        insideRing(point, polygon.first()) && polygon.drop(1).none { insideRing(point, it) }
    }
}

private fun insideRing(point: MapPoint, ring: List<MapPoint>): Boolean {
    var inside = false
    var previous = ring.last()
    for (current in ring) {
        if ((current.y > point.y) != (previous.y > point.y) &&
            point.x < (previous.x - current.x) * (point.y - current.y) /
            (previous.y - current.y) + current.x
        ) inside = !inside
        previous = current
    }
    return inside
}

private fun project(longitude: Double, latitude: Double): MapPoint {
    require(longitude.isFinite() && latitude.isFinite() && longitude in -180.0..180.0 && latitude in -85.0..85.0)
    return MapPoint(Math.toRadians(longitude), ln(tan(Math.PI / 4 + Math.toRadians(latitude) / 2)))
}

fun parseMapRegions(json: String): List<MapRegion> {
    val root = JsonParser.parseString(json).asJsonObject
    require(root.get("type").asString == "FeatureCollection")
    val regions = root.getAsJsonArray("features").map { feature ->
        val value = feature.asJsonObject
        val properties = value.getAsJsonObject("properties")
        val geometry = value.getAsJsonObject("geometry")
        val coordinates = geometry.getAsJsonArray("coordinates")
        val polygons = when (geometry.get("type").asString) {
            "Polygon" -> listOf(coordinates)
            "MultiPolygon" -> coordinates.map { it.asJsonArray }
            else -> throw IllegalArgumentException("不支持的地图边界类型")
        }.map { polygon ->
            require(polygon.size() > 0)
            polygon.map { ring ->
                require(ring.asJsonArray.size() >= 4)
                ring.asJsonArray.map { coordinate ->
                    val pair = coordinate.asJsonArray
                    require(pair.size() >= 2)
                    project(pair[0].asDouble, pair[1].asDouble)
                }
            }
        }
        require(polygons.isNotEmpty())
        val center = properties.get("centroid") ?: properties.get("center")
        MapRegion(
            properties.get("adcode").asString, properties.get("name").asString, polygons,
            center?.takeUnless { it.isJsonNull }?.asJsonArray?.let { project(it[0].asDouble, it[1].asDouble) }
        )
    }
    require(regions.isNotEmpty())
    require(regions.map { it.code }.distinct().size == regions.size)
    return regions
}

class MapViewport(regions: List<MapRegion>, width: Double, height: Double) {
    private val points = regions.flatMap { it.polygons.flatMap { polygon -> polygon.flatten() } }
    private val minX = points.minOf { it.x }
    private val maxY = points.maxOf { it.y }
    private val rangeX = (points.maxOf { it.x } - minX).coerceAtLeast(0.000001)
    private val rangeY = (maxY - points.minOf { it.y }).coerceAtLeast(0.000001)
    private val scale = min(width / rangeX, height / rangeY).coerceAtLeast(0.000001)
    private val left = (width - rangeX * scale) / 2
    private val top = (height - rangeY * scale) / 2

    fun toScreen(point: MapPoint) = MapPoint(left + (point.x - minX) * scale, top + (maxY - point.y) * scale)
    fun fromScreen(point: MapPoint) = MapPoint(minX + (point.x - left) / scale, maxY - (point.y - top) / scale)
}

fun mapProvinceCode(cityCode: String): String? =
    cityCode.takeIf { it.length == 6 && it.all(Char::isDigit) }?.take(2)?.plus("0000")
