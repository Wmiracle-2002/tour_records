package com.miracle.footmarks.ui.screen.addrecord

import android.net.Uri
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.miracle.footmarks.R
import com.miracle.footmarks.data.local.entity.RecordType
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddRecordScreen(
    onSaved: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AddRecordViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    var showCityPicker by remember { mutableStateOf(false) }
    var datePickerTarget by remember { mutableStateOf<DatePickerTarget?>(null) }

    val photoPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        uri?.let { viewModel.addPhoto(it) }
    }

    if (uiState.isLoading) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("添加记录") },
                actions = {
                    TextButton(
                        onClick = onCancel,
                        enabled = !uiState.isSaving
                    ) {
                        Text(stringResource(R.string.action_cancel))
                    }
                    TextButton(
                        onClick = { viewModel.saveRecord(onSaved) },
                        enabled = !uiState.isSaving
                    ) {
                        Text(stringResource(R.string.action_save))
                    }
                }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = modifier
                .fillMaxSize()
                .padding(paddingValues)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Error message
            uiState.error?.let { error ->
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer
                    )
                ) {
                    Text(
                        text = error,
                        modifier = Modifier.padding(12.dp),
                        color = MaterialTheme.colorScheme.onErrorContainer
                    )
                }
            }

            // Record type selector
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                FilterChip(
                    selected = uiState.recordType == RecordType.ATTRACTION,
                    onClick = { viewModel.updateRecordType(RecordType.ATTRACTION) },
                    label = { Text(stringResource(R.string.type_attraction)) },
                    modifier = Modifier.weight(1f)
                )
                FilterChip(
                    selected = uiState.recordType == RecordType.FOOD,
                    onClick = { viewModel.updateRecordType(RecordType.FOOD) },
                    label = { Text(stringResource(R.string.type_food)) },
                    modifier = Modifier.weight(1f)
                )
            }

            Text(
                text = if (uiState.tripId == null) "新旅行" else "添加到已有旅行",
                style = MaterialTheme.typography.titleMedium
            )

            // City selector
            OutlinedCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (uiState.tripId == null) Modifier.clickable { showCityPicker = true }
                        else Modifier
                    )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "旅行城市",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = uiState.cityName.ifBlank { stringResource(R.string.hint_select_city) },
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (uiState.cityName.isBlank())
                            MaterialTheme.colorScheme.onSurfaceVariant
                        else
                            MaterialTheme.colorScheme.onSurface
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                DateFieldCard(
                    label = "旅行开始",
                    date = uiState.tripStartDate,
                    enabled = uiState.tripId == null,
                    onClick = { datePickerTarget = DatePickerTarget.TRIP_START },
                    modifier = Modifier.weight(1f)
                )
                DateFieldCard(
                    label = "旅行结束",
                    date = uiState.tripEndDate,
                    enabled = uiState.tripId == null,
                    onClick = { datePickerTarget = DatePickerTarget.TRIP_END },
                    modifier = Modifier.weight(1f)
                )
            }

            Divider()
            Text("景点 / 美食记录", style = MaterialTheme.typography.titleMedium)

            // Name input
            OutlinedTextField(
                value = uiState.name,
                onValueChange = { viewModel.updateName(it) },
                label = { Text(stringResource(R.string.label_name)) },
                placeholder = { Text(stringResource(R.string.hint_enter_name)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            // Date picker
            OutlinedCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { datePickerTarget = DatePickerTarget.RECORD }
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = stringResource(R.string.label_date),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = uiState.date.format(DateTimeFormatter.ofPattern("yyyy-MM-dd")),
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }

            // Rating
            Column {
                Text(
                    text = stringResource(R.string.label_rating),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    (1..5).forEach { star ->
                        FilterChip(
                            selected = uiState.rating?.toInt() == star,
                            onClick = { viewModel.updateRating(star.toFloat()) },
                            label = { Text("$star") }
                        )
                    }
                    if (uiState.rating != null) {
                        TextButton(onClick = { viewModel.updateRating(null) }) {
                            Text("清除")
                        }
                    }
                }
            }

            // Cost
            OutlinedTextField(
                value = uiState.cost?.toString() ?: "",
                onValueChange = {
                    viewModel.updateCost(it.toFloatOrNull())
                },
                label = { Text(stringResource(R.string.label_cost)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            // Notes
            OutlinedTextField(
                value = uiState.notes,
                onValueChange = { viewModel.updateNotes(it) },
                label = { Text(stringResource(R.string.label_notes)) },
                placeholder = { Text(stringResource(R.string.hint_enter_notes)) },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 5
            )

            // Photos
            Column {
                Text(
                    text = "照片",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(8.dp))
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(uiState.photoUris) { uri ->
                        PhotoItem(
                            uri = uri,
                            onRemove = { viewModel.removePhoto(uri) }
                        )
                    }
                    if (uiState.photoUris.size < 9) item {
                        AddPhotoButton(
                            onClick = {
                                photoPickerLauncher.launch(
                                    PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                                )
                            }
                        )
                    }
                }
            }

            if (uiState.isSaving) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
        }
    }

    if (showCityPicker) {
        CityPickerDialog(
            onDismiss = { showCityPicker = false },
            onCitySelected = { cityId, cityName ->
                viewModel.updateCity(cityId, cityName)
                showCityPicker = false
            }
        )
    }

    datePickerTarget?.let { target ->
        DatePickerDialog(
            currentDate = when (target) {
                DatePickerTarget.TRIP_START -> uiState.tripStartDate
                DatePickerTarget.TRIP_END -> uiState.tripEndDate
                DatePickerTarget.RECORD -> uiState.date
            },
            onDismiss = { datePickerTarget = null },
            onDateSelected = { date ->
                when (target) {
                    DatePickerTarget.TRIP_START -> viewModel.updateTripStartDate(date)
                    DatePickerTarget.TRIP_END -> viewModel.updateTripEndDate(date)
                    DatePickerTarget.RECORD -> viewModel.updateDate(date)
                }
                datePickerTarget = null
            }
        )
    }
}

private enum class DatePickerTarget {
    TRIP_START,
    TRIP_END,
    RECORD
}

@Composable
private fun DateFieldCard(
    label: String,
    date: java.time.LocalDate,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedCard(
        modifier = modifier.then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = date.format(DateTimeFormatter.ofPattern("yyyy-MM-dd")),
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

@Composable
fun PhotoItem(
    uri: Uri,
    onRemove: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier.size(100.dp)) {
        AsyncImage(
            model = uri,
            contentDescription = null,
            modifier = Modifier
                .fillMaxSize()
                .clip(RoundedCornerShape(8.dp)),
            contentScale = ContentScale.Crop
        )
        IconButton(
            onClick = onRemove,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(24.dp)
                .background(
                    MaterialTheme.colorScheme.surface.copy(alpha = 0.8f),
                    RoundedCornerShape(12.dp)
                )
        ) {
            Icon(
                imageVector = Icons.Default.Close,
                contentDescription = "删除",
                modifier = Modifier.size(16.dp)
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddPhotoButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedCard(
        onClick = onClick,
        modifier = modifier.size(100.dp)
    ) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Add,
                contentDescription = stringResource(R.string.action_add_photo),
                modifier = Modifier.size(32.dp)
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DatePickerDialog(
    currentDate: java.time.LocalDate,
    onDismiss: () -> Unit,
    onDateSelected: (java.time.LocalDate) -> Unit
) {
    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = currentDate.toEpochDay() * 86400000L
    )

    androidx.compose.material3.DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    datePickerState.selectedDateMillis?.let { millis ->
                        onDateSelected(
                            java.time.LocalDate.ofEpochDay(millis / 86400000L)
                        )
                    }
                }
            ) {
                Text("确定")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        }
    ) {
        DatePicker(state = datePickerState)
    }
}
