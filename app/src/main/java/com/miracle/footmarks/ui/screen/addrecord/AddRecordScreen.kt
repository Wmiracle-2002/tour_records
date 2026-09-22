package com.miracle.footmarks.ui.screen.addrecord

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog as MaterialDatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import com.miracle.footmarks.ui.theme.BorderGray
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddRecordScreen(
    onTripSaved: (Long) -> Unit,
    onRecordSaved: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AddRecordViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val isTripForm = uiState.tripId == null
    var showCityPicker by remember { mutableStateOf(false) }
    var datePickerTarget by remember { mutableStateOf<DatePickerTarget?>(null) }

    val photoPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia()
    ) { uri -> uri?.let(viewModel::addPhoto) }

    if (uiState.isLoading) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (isTripForm) "添加旅游记录" else "添加景点/美食") },
                actions = {
                    TextButton(onClick = onCancel, enabled = !uiState.isSaving) {
                        Text(stringResource(R.string.action_cancel))
                    }
                    TextButton(
                        onClick = {
                            if (isTripForm) viewModel.saveTrip(onTripSaved)
                            else viewModel.saveRecord(onRecordSaved)
                        },
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
            ErrorMessage(uiState.error)

            if (isTripForm) {
                TripFormContent(
                    state = uiState,
                    onCityClick = { showCityPicker = true },
                    onDateClick = { datePickerTarget = it }
                )
            } else {
                RecordFormContent(
                    state = uiState,
                    onRecordTypeChange = viewModel::updateRecordType,
                    onNameChange = viewModel::updateName,
                    onDateClick = { datePickerTarget = DatePickerTarget.RECORD },
                    onRatingChange = viewModel::updateRating,
                    onCostChange = { viewModel.updateCost(it.toFloatOrNull()) },
                    onNotesChange = viewModel::updateNotes,
                    onRemovePhoto = viewModel::removePhoto,
                    onAddPhoto = {
                        photoPickerLauncher.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                        )
                    }
                )
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

@Composable
private fun ErrorMessage(error: String?) {
    error?.let {
        Card(
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)
        ) {
            Text(
                text = it,
                modifier = Modifier.padding(12.dp),
                color = MaterialTheme.colorScheme.onErrorContainer
            )
        }
    }
}

@Composable
private fun TripFormContent(
    state: AddRecordUiState,
    onCityClick: () -> Unit,
    onDateClick: (DatePickerTarget) -> Unit
) {
    Text("新建旅游记录", style = MaterialTheme.typography.titleMedium)
    OutlinedCard(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onCityClick),
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, BorderGray)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.label_city),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = state.cityName.ifBlank { stringResource(R.string.hint_select_city) },
                style = MaterialTheme.typography.bodyLarge,
                color = if (state.cityName.isBlank()) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onSurface
                }
            )
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        DateFieldCard(
            label = "开始日期",
            date = state.tripStartDate,
            onClick = { onDateClick(DatePickerTarget.TRIP_START) },
            modifier = Modifier.weight(1f)
        )
        DateFieldCard(
            label = "结束日期",
            date = state.tripEndDate,
            onClick = { onDateClick(DatePickerTarget.TRIP_END) },
            modifier = Modifier.weight(1f)
        )
    }
    Text(
        text = "保存后可以在旅游记录详情中添加景点或美食。",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecordFormContent(
    state: AddRecordUiState,
    onRecordTypeChange: (RecordType) -> Unit,
    onNameChange: (String) -> Unit,
    onDateClick: () -> Unit,
    onRatingChange: (Float?) -> Unit,
    onCostChange: (String) -> Unit,
    onNotesChange: (String) -> Unit,
    onRemovePhoto: (Uri) -> Unit,
    onAddPhoto: () -> Unit
) {
    Text(
        text = "添加到 ${state.cityName}（${formatDateRange(state.tripStartDate, state.tripEndDate)}）",
        style = MaterialTheme.typography.titleMedium
    )

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(
            selected = state.recordType == RecordType.ATTRACTION,
            onClick = { onRecordTypeChange(RecordType.ATTRACTION) },
            label = { Text(stringResource(R.string.type_attraction)) },
            modifier = Modifier.weight(1f)
        )
        FilterChip(
            selected = state.recordType == RecordType.FOOD,
            onClick = { onRecordTypeChange(RecordType.FOOD) },
            label = { Text(stringResource(R.string.type_food)) },
            modifier = Modifier.weight(1f)
        )
    }

    OutlinedTextField(
        value = state.name,
        onValueChange = onNameChange,
        label = { Text(stringResource(R.string.label_name)) },
        placeholder = { Text(stringResource(R.string.hint_enter_name)) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true
    )

    OutlinedCard(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onDateClick)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.label_date),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = state.date.format(DateTimeFormatter.ofPattern("yyyy-MM-dd")),
                style = MaterialTheme.typography.bodyLarge
            )
        }
    }

    Column {
        Text(
            text = stringResource(R.string.label_rating),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            (1..5).forEach { star ->
                FilterChip(
                    selected = state.rating?.toInt() == star,
                    onClick = { onRatingChange(star.toFloat()) },
                    label = { Text("$star") }
                )
            }
            if (state.rating != null) {
                TextButton(onClick = { onRatingChange(null) }) { Text("清除") }
            }
        }
    }

    OutlinedTextField(
        value = state.cost?.toString() ?: "",
        onValueChange = onCostChange,
        label = { Text(stringResource(R.string.label_cost)) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true
    )

    OutlinedTextField(
        value = state.notes,
        onValueChange = onNotesChange,
        label = { Text(stringResource(R.string.label_notes)) },
        placeholder = { Text(stringResource(R.string.hint_enter_notes)) },
        modifier = Modifier.fillMaxWidth(),
        minLines = 3,
        maxLines = 5
    )

    Column {
        Text("照片", style = MaterialTheme.typography.labelMedium)
        Spacer(modifier = Modifier.height(8.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.photoUris) { uri ->
                PhotoItem(uri = uri, onRemove = { onRemovePhoto(uri) })
            }
            if (state.photoUris.size < 9) {
                item { AddPhotoButton(onClick = onAddPhoto) }
            }
        }
    }
}

private fun formatDateRange(start: LocalDate, end: LocalDate): String {
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    return if (start == end) start.format(formatter) else "${start.format(formatter)} - ${end.format(formatter)}"
}

private enum class DatePickerTarget {
    TRIP_START,
    TRIP_END,
    RECORD
}

@Composable
private fun DateFieldCard(
    label: String,
    date: LocalDate,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedCard(
        modifier = modifier.clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, BorderGray)
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
                    .clip(RoundedCornerShape(14.dp)),
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
            Icon(Icons.Default.Close, contentDescription = "删除", modifier = Modifier.size(16.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddPhotoButton(onClick: () -> Unit, modifier: Modifier = Modifier) {
        OutlinedCard(
            onClick = onClick,
            modifier = modifier.size(100.dp),
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, BorderGray)
        ) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
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
    currentDate: LocalDate,
    onDismiss: () -> Unit,
    onDateSelected: (LocalDate) -> Unit
) {
    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = currentDate.toEpochDay() * 86_400_000L
    )

    MaterialDatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    datePickerState.selectedDateMillis?.let { millis ->
                        onDateSelected(LocalDate.ofEpochDay(millis / 86_400_000L))
                    }
                }
            ) { Text("确定") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") }
        }
    ) {
        DatePicker(state = datePickerState)
    }
}
