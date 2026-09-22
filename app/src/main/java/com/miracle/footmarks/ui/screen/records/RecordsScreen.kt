package com.miracle.footmarks.ui.screen.records

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.ui.theme.AccentMintContainer
import com.miracle.footmarks.ui.theme.AccentOrangeContainer
import com.miracle.footmarks.ui.theme.BorderGray
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun RecordsScreen(
    onTripClick: (Long) -> Unit = {},
    onRecordClick: (Long) -> Unit,
    onAddClick: () -> Unit,
    onAddToTrip: (Long) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: RecordsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(modifier = modifier.fillMaxSize()) {
        when {
            uiState.isLoading -> CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 16.dp, top = 8.dp, end = 16.dp, bottom = 96.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item { RecordsHeader() }
                if (uiState.trips.isEmpty()) {
                    item { EmptyTimeline(Modifier.fillMaxWidth().padding(vertical = 48.dp)) }
                } else {
                    item { StatsRow(uiState.stats) }
                    items(uiState.trips, key = { it.trip.id }) { trip ->
                        TripCard(
                            item = trip,
                            onTripClick = { onTripClick(trip.trip.id) },
                            onRecordClick = onRecordClick,
                            onAddRecord = { onAddToTrip(trip.trip.id) }
                        )
                    }
                }
            }
        }

        FloatingActionButton(
            onClick = onAddClick,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(16.dp),
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary
        ) {
            Icon(Icons.Default.Add, contentDescription = "新建旅行")
        }
    }
}

@Composable
private fun RecordsHeader() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 12.dp, bottom = 4.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(
            text = "我的足迹",
            style = MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = "把走过的路，留成故事",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun EmptyTimeline(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(
            modifier = Modifier
                .size(72.dp)
                .clip(RoundedCornerShape(24.dp))
                .background(AccentOrangeContainer),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                Icons.Default.Place,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(36.dp)
            )
        }
        Text("还没有旅行记录", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(
            "点击右下角 +，创建第一次旅行",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun StatsRow(stats: TravelStats) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        StatCard("城市", stats.cityCount.toString(), AccentMintContainer, Modifier.weight(1f))
        StatCard("出行", stats.tripCount.toString(), AccentOrangeContainer, Modifier.weight(1f))
    }
}

@Composable
private fun StatCard(
    label: String,
    value: String,
    containerColor: Color,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(18.dp),
        color = containerColor
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(value, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun TripCard(
    item: TripWithCityAndRecords,
    onTripClick: () -> Unit,
    onRecordClick: (Long) -> Unit,
    onAddRecord: () -> Unit
) {
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    val startDate = LocalDate.ofEpochDay(item.trip.startDate / DAY_MILLIS)
    val endDate = LocalDate.ofEpochDay(item.trip.endDate / DAY_MILLIS)

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onTripClick),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, BorderGray),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(AccentOrangeContainer),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Default.Place,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
                Spacer(Modifier.size(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(item.cityName, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(
                        text = if (startDate == endDate) startDate.format(formatter)
                        else "${startDate.format(formatter)} — ${endDate.format(formatter)}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Surface(
                    color = AccentMintContainer,
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text(
                        "${item.records.size} 条",
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                        style = MaterialTheme.typography.labelMedium
                    )
                }
                IconButton(onClick = onAddRecord) {
                    Icon(Icons.Default.Add, contentDescription = "向本次旅行添加记录")
                }
            }

            Spacer(Modifier.height(8.dp))
            item.records.sortedBy { it.date }.forEach { record ->
                RecordRow(record = record, onClick = { onRecordClick(record.id) })
            }
        }
    }
}

@Composable
private fun RecordRow(record: RecordEntity, onClick: () -> Unit) {
    val photo = (record.photoUris?.split(",") ?: emptyList())
        .plus(record.remotePhotoUrls?.split(",") ?: emptyList())
        .firstOrNull { it.isNotBlank() }
    val isAttraction = record.type == RecordType.ATTRACTION

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (photo != null) {
            AsyncImage(
                model = photo,
                contentDescription = null,
                modifier = Modifier
                    .size(56.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentScale = ContentScale.Crop
            )
        } else {
            Box(
                modifier = Modifier
                    .size(56.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(if (isAttraction) AccentOrangeContainer else AccentMintContainer),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = if (isAttraction) Icons.Default.Place else Icons.Default.Star,
                    contentDescription = null,
                    tint = if (isAttraction) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondary
                )
            }
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(record.name, style = MaterialTheme.typography.titleMedium)
            Text(
                "${if (isAttraction) "景点" else "美食"} · " +
                    LocalDate.ofEpochDay(record.date / DAY_MILLIS)
                        .format(DateTimeFormatter.ofPattern("MM-dd")),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        record.rating?.let {
            Text("★ ${it.toInt()}", color = Color(0xFFFFA000), style = MaterialTheme.typography.bodySmall)
        }
    }
}

private const val DAY_MILLIS = 86_400_000L
