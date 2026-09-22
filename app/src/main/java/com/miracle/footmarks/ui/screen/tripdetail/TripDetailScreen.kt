package com.miracle.footmarks.ui.screen.tripdetail

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.ui.theme.AccentOrangeContainer
import com.miracle.footmarks.ui.theme.BorderGray
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TripDetailScreen(
    onBack: () -> Unit,
    onAddRecord: (Long) -> Unit,
    onRecordClick: (Long) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: TripDetailViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val trip = uiState.trip

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(trip?.cityName ?: "旅游记录") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        },
        floatingActionButton = {
            trip?.let {
                FloatingActionButton(onClick = { onAddRecord(it.trip.id) }) {
                    Icon(Icons.Default.Add, contentDescription = "添加景点或美食")
                }
            }
        }
    ) { paddingValues ->
        Box(
            modifier = modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            when {
                uiState.isLoading -> CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
                uiState.error != null -> Text(
                    text = uiState.error.orEmpty(),
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.align(Alignment.Center)
                )
                trip != null -> TripDetailContent(
                    trip = trip,
                    onRecordClick = onRecordClick
                )
            }
        }
    }
}

@Composable
private fun TripDetailContent(
    trip: TripWithCityAndRecords,
    onRecordClick: (Long) -> Unit
) {
    val start = LocalDate.ofEpochDay(trip.trip.startDate / DAY_MILLIS)
    val end = LocalDate.ofEpochDay(trip.trip.endDate / DAY_MILLIS)
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(22.dp),
                colors = CardDefaults.cardColors(
                    containerColor = AccentOrangeContainer
                ),
                border = BorderStroke(1.dp, AccentOrangeContainer.copy(alpha = 0.9f))
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(trip.cityName, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text(formatDateRange(start, end), style = MaterialTheme.typography.bodyMedium)
                    Text(
                        text = "共 ${trip.records.size} 条景点/美食记录",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
        if (trip.records.isEmpty()) {
            item {
                Text(
                    text = "还没有景点或美食记录，点击右下角 + 添加。",
                    modifier = Modifier.padding(vertical = 24.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            items(trip.records, key = { it.id }) { record ->
                TripRecordRow(record = record, onClick = { onRecordClick(record.id) })
            }
        }
    }
}

@Composable
private fun TripRecordRow(record: RecordEntity, onClick: () -> Unit) {
    val photo = (record.photoUris?.split(",") ?: emptyList())
        .plus(record.remotePhotoUrls?.split(",") ?: emptyList())
        .firstOrNull { it.isNotBlank() }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable(onClick = onClick)
            .padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (photo != null) {
            AsyncImage(
                model = photo,
                contentDescription = null,
                modifier = Modifier
                    .size(64.dp)
                    .clip(RoundedCornerShape(8.dp)),
                contentScale = ContentScale.Crop
            )
        } else {
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = if (record.type == RecordType.ATTRACTION) Icons.Default.Place else Icons.Default.Star,
                    contentDescription = null
                )
            }
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(record.name, style = MaterialTheme.typography.titleMedium)
            Text(
                text = LocalDate.ofEpochDay(record.date / DAY_MILLIS)
                    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd")),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Text(
            text = if (record.type == RecordType.ATTRACTION) "景点" else "美食",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

private fun formatDateRange(start: LocalDate, end: LocalDate): String {
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    return if (start == end) start.format(formatter) else "${start.format(formatter)} - ${end.format(formatter)}"
}

private const val DAY_MILLIS = 86_400_000L
