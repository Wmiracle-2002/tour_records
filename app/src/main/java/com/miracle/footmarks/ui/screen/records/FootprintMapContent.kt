package com.miracle.footmarks.ui.screen.records

import android.graphics.Paint
import android.graphics.RectF
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import com.miracle.footmarks.ui.theme.AccentMintContainer
import com.miracle.footmarks.ui.theme.BorderGray

@Composable
internal fun RecordsViewToggle(mapSelected: Boolean, onSelect: (Boolean) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(false to "列表", true to "地图").forEach { (map, title) ->
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = if (mapSelected == map) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surface
            ) {
                TextButton(onClick = { onSelect(map) }) { Text(title) }
            }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
internal fun FootprintMapContent(
    records: RecordsUiState,
    state: FootprintMapState,
    onShowList: () -> Unit,
    onProvince: (String?) -> Unit,
    onCity: (String) -> Unit,
    onTripClick: (Long) -> Unit,
    onRecordClick: (Long) -> Unit,
    onAddToTrip: (Long) -> Unit
) {
    BackHandler(enabled = state.provinceCode != null) { onProvince(null) }
    val counts = remember(records.trips, records.cities, state.validCityCodes) {
        footprintCounts(records.trips, records.cities, state.validCityCodes)
    }
    val selectedCity = state.locations.firstOrNull { it.code == state.cityCode }
    val trips = remember(state.cityCode, records.trips, records.cities) {
        state.cityCode?.let { tripsForMapCity(it, records.trips, records.cities) }.orEmpty()
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, top = 8.dp, end = 16.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { RecordsHeader() }
        item { RecordsViewToggle(true) { if (!it) onShowList() } }
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text(state.provinceName ?: "中国 · 我的旅行足迹", style = MaterialTheme.typography.titleLarge)
                    Text(
                        if (state.provinceCode == null) "点省份，看看走过哪些城市"
                        else "点城市，查看每一次旅行",
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
                if (state.provinceCode != null) TextButton(onClick = { onProvince(null) }) { Text("返回全国") }
            }
        }
        item {
            when {
                state.isLoading -> CircularProgressIndicator(modifier = Modifier.padding(24.dp))
                state.error != null -> {
                    Text(state.error, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = { onProvince(state.provinceCode) }) { Text("重试") }
                }
                state.regions.isNotEmpty() -> Surface(shape = RoundedCornerShape(24.dp)) {
                    RegionCanvas(
                        state,
                        if (state.provinceCode == null) counts.provinces else counts.cities,
                        onRegion = { code -> if (state.provinceCode == null) onProvince(code) else onCity(code) }
                    )
                }
            }
        }
        item {
            Text("绿色区域：已有旅行记录 · 数据来源：阿里云DataV.GeoAtlas", style = MaterialTheme.typography.labelSmall)
            if (!state.isLoading && counts.unmatched > 0) {
                Text("${counts.unmatched}条旅行暂未匹配地图城市，仍可在列表查看。", style = MaterialTheme.typography.bodySmall)
            }
        }
        if (!state.isLoading && state.provinceCode != null) {
            item {
                if (state.locations.isEmpty()) {
                    Text("该地区暂无可选记录城市，暂不展示城市细分。")
                } else {
                    Text("城市速选", style = MaterialTheme.typography.titleSmall)
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.locations, key = { it.code }) { city ->
                            FilterChip(
                                selected = state.cityCode == city.code,
                                onClick = { onCity(city.code) },
                                label = { Text("${city.name} · ${counts.cities[city.code] ?: 0}次") }
                            )
                        }
                    }
                }
            }
        }
        if (selectedCity != null && !state.isLoading) {
            item {
                Text("${selectedCity.name} · ${trips.size}次旅行", style = MaterialTheme.typography.titleMedium)
                if (state.regions.none { it.code == selectedCity.code }) {
                    Text("此城市的边界数据尚未收录，旅行记录仍可正常查看。", style = MaterialTheme.typography.bodySmall)
                }
                if (trips.isEmpty()) Text("还没有这里的旅行记录，下一站也许就是这里。")
            }
            items(trips, key = { it.trip.id }) { trip ->
                TripCard(trip, { onTripClick(trip.trip.id) }, onRecordClick, { onAddToTrip(trip.trip.id) })
            }
        }
    }
}

@Composable
private fun RegionCanvas(state: FootprintMapState, counts: Map<String, Int>, onRegion: (String) -> Unit) {
    var canvasSize by remember { mutableStateOf(IntSize.Zero) }
    var transform by remember(state.regions) { mutableStateOf(MapGestureTransform()) }
    val currentTransform by rememberUpdatedState(transform)
    val viewport = remember(state.regions, canvasSize) {
        if (canvasSize.width > 0 && canvasSize.height > 0)
            MapViewport(state.regions, canvasSize.width.toDouble(), canvasSize.height.toDouble()) else null
    }
    val paths = remember(state.regions, viewport) {
        state.regions.map { region ->
            region to Path().apply {
                fillType = PathFillType.EvenOdd
                region.polygons.forEach { polygon ->
                    polygon.forEach { ring ->
                        ring.forEachIndexed { index, point ->
                            val screen = viewport?.toScreen(point) ?: return@forEachIndexed
                            if (index == 0) moveTo(screen.x.toFloat(), screen.y.toFloat())
                            else lineTo(screen.x.toFloat(), screen.y.toFloat())
                        }
                        close()
                    }
                }
            }
        }
    }
    val activeColor = MaterialTheme.colorScheme.primary
    val emptyColor = MaterialTheme.colorScheme.surfaceVariant
    val textColor = MaterialTheme.colorScheme.onSurface
    val selectable = state.locations.map { it.code }.toSet()
    Column {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
            TextButton(enabled = transform.scale > 1.0, onClick = {
                transform = transform.update(MapPoint(canvasSize.width / 2.0, canvasSize.height / 2.0),
                    MapPoint(0.0, 0.0), 1 / 1.5, canvasSize.width.toDouble(), canvasSize.height.toDouble())
            }) { Text("缩小") }
            TextButton(enabled = transform.scale < 12.0, onClick = {
                transform = transform.update(MapPoint(canvasSize.width / 2.0, canvasSize.height / 2.0),
                    MapPoint(0.0, 0.0), 1.5, canvasSize.width.toDouble(), canvasSize.height.toDouble())
            }) { Text("放大") }
            TextButton(onClick = { transform = MapGestureTransform() }) { Text("复位") }
        }
        Canvas(
            modifier = Modifier.fillMaxWidth().height(360.dp).padding(12.dp)
                .clipToBounds()
                .semantics {
                    contentDescription = "行政区旅行足迹地图"
                    stateDescription = "缩放${(transform.scale * 100).toInt()}%"
                }
                .onSizeChanged { canvasSize = it }
                .pointerInput(state.regions, viewport, selectable) {
                    detectTapGestures { tap ->
                        val point = viewport?.fromScreen(currentTransform.fromScreen(MapPoint(tap.x.toDouble(), tap.y.toDouble()))) ?: return@detectTapGestures
                        state.regions.firstOrNull { region ->
                            region.code.length == 6 && region.contains(point) &&
                                (state.provinceCode == null || region.code in selectable)
                        }?.let { onRegion(it.code) }
                    }
                }
                .pointerInput(state.regions, canvasSize) {
                    detectTransformGestures { focus, pan, zoom, _ ->
                        transform = transform.update(MapPoint(focus.x.toDouble(), focus.y.toDouble()),
                            MapPoint(pan.x.toDouble(), pan.y.toDouble()), zoom.toDouble(),
                            canvasSize.width.toDouble(), canvasSize.height.toDouble())
                    }
                }
        ) {
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = textColor.toArgb()
                textSize = 10.dp.toPx()
                textAlign = Paint.Align.CENTER
            }
            withTransform({
                translate(transform.offset.x.toFloat(), transform.offset.y.toFloat())
                scale(transform.scale.toFloat(), transform.scale.toFloat(), pivot = Offset.Zero)
            }) {
                paths.forEach { (region, path) ->
                    drawPath(path, if (region.code == state.cityCode) activeColor.copy(alpha = 0.35f)
                        else if ((counts[region.code] ?: 0) > 0) AccentMintContainer else emptyColor)
                    drawPath(path, BorderGray, style = Stroke(width = 1.dp.toPx() / transform.scale.toFloat()))
                }
            }
            val labelBounds = mutableListOf<RectF>()
            state.regions.sortedByDescending { counts[it.code] ?: 0 }.forEach { region ->
                if (state.provinceCode == null || region.code in selectable) {
                    region.labelPoint?.let { point ->
                        viewport?.toScreen(point)?.let(transform::toScreen)?.let drawLabel@ { screen ->
                            if (screen.x !in 0.0..size.width.toDouble() || screen.y !in 0.0..size.height.toDouble()) return@drawLabel
                            val count = counts[region.code] ?: 0
                            val name = region.name.removeSuffix("省").removeSuffix("市")
                                .removeSuffix("特别行政区").removeSuffix("自治区")
                                .removeSuffix("维吾尔").removeSuffix("壮族").removeSuffix("回族")
                            val label = name + if (count > 0) "·${count}次" else ""
                            val halfWidth = paint.measureText(label) / 2
                            val bounds = RectF(screen.x.toFloat() - halfWidth - 2.dp.toPx(),
                                screen.y.toFloat() - paint.textSize,
                                screen.x.toFloat() + halfWidth + 2.dp.toPx(), screen.y.toFloat() + 2.dp.toPx())
                            if (labelBounds.any { RectF.intersects(it, bounds) }) return@drawLabel
                            labelBounds.add(bounds)
                            drawContext.canvas.nativeCanvas.drawText(label, screen.x.toFloat(), screen.y.toFloat(), paint)
                        }
                    }
                }
            }
        }
    }
}
