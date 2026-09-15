package com.miracle.footmarks.ui.screen.editrecord

import android.net.Uri
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
import com.miracle.footmarks.ui.screen.addrecord.CityPickerDialog
import com.miracle.footmarks.ui.screen.addrecord.AddPhotoButton
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EditRecordScreen(
    onSaved: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: EditRecordViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    var showCityPicker by remember { mutableStateOf(false) }
    var showDatePicker by remember { mutableStateOf(false) }

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
                title = { Text("编辑记录") },
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
            // 错误提示
            uiState.error?.let { error ->
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer
                    )
                ) {
                    Text(
                        text = error,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }

            // 记录类型
            Text("记录类型", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = uiState.recordType == RecordType.ATTRACTION,
                    onClick = { viewModel.updateRecordType(RecordType.ATTRACTION) },
                    label = { Text(stringResource(R.string.type_attraction)) }
                )
                FilterChip(
                    selected = uiState.recordType == RecordType.FOOD,
                    onClick = { viewModel.updateRecordType(RecordType.FOOD) },
                    label = { Text(stringResource(R.string.type_food)) }
                )
            }

            // 城市
            OutlinedCard(
                onClick = { showCityPicker = true },
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = stringResource(R.string.label_city),
                        style = MaterialTheme.typography.labelMedium
                    )
                    Text(
                        text = if (uiState.cityName.isNotBlank()) uiState.cityName
                        else stringResource(R.string.hint_select_city),
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (uiState.cityName.isNotBlank())
                            MaterialTheme.colorScheme.onSurface
                        else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            OutlinedCard(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "旅行时间",
                        style = MaterialTheme.typography.labelMedium
                    )
                    Text(
                        text = if (uiState.tripStartDate == uiState.tripEndDate) {
                            uiState.tripStartDate.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"))
                        } else {
                            "${uiState.tripStartDate.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"))} ～ " +
                                uiState.tripEndDate.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"))
                        },
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Text(
                        text = "记录日期需在此范围内",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            // 名称
            OutlinedTextField(
                value = uiState.name,
                onValueChange = { viewModel.updateName(it) },
                label = { Text(stringResource(R.string.label_name)) },
                placeholder = { Text(stringResource(R.string.hint_enter_name)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            // 日期
            OutlinedCard(
                onClick = { showDatePicker = true },
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = stringResource(R.string.label_date),
                        style = MaterialTheme.typography.labelMedium
                    )
                    Text(
                        text = uiState.date.format(DateTimeFormatter.ofPattern("yyyy-MM-dd")),
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }

            // 评分
            Text(stringResource(R.string.label_rating), style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (1..5).forEach { star ->
                    FilterChip(
                        selected = uiState.rating?.toInt() == star,
                        onClick = {
                            viewModel.updateRating(
                                if (uiState.rating?.toInt() == star) null else star.toFloat()
                            )
                        },
                        label = { Text("$star ⭐") }
                    )
                }
            }

            // 花费
            OutlinedTextField(
                value = uiState.cost?.toString() ?: "",
                onValueChange = { viewModel.updateCost(it.toFloatOrNull()) },
                label = { Text(stringResource(R.string.label_cost)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            // 备注
            OutlinedTextField(
                value = uiState.notes,
                onValueChange = { viewModel.updateNotes(it) },
                label = { Text(stringResource(R.string.label_notes)) },
                placeholder = { Text(stringResource(R.string.hint_enter_notes)) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 120.dp),
                minLines = 4,
                maxLines = 8
            )

            // 照片
            Text(stringResource(R.string.action_add_photo), style = MaterialTheme.typography.labelLarge)
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

    if (showDatePicker) {
        androidx.compose.material3.DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    showDatePicker = false
                }) {
                    Text("确定")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) {
                    Text("取消")
                }
            }
        ) {
            val datePickerState = rememberDatePickerState(
                initialSelectedDateMillis = uiState.date.toEpochDay() * 86400000L
            )
            DatePicker(state = datePickerState)

            LaunchedEffect(datePickerState.selectedDateMillis) {
                datePickerState.selectedDateMillis?.let { millis ->
                    viewModel.updateDate(
                        java.time.LocalDate.ofEpochDay(millis / 86400000L)
                    )
                }
            }
        }
    }
}

@Composable
private fun PhotoItem(
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
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentScale = ContentScale.Crop
        )

        IconButton(
            onClick = onRemove,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(24.dp)
                .background(
                    MaterialTheme.colorScheme.surface.copy(alpha = 0.8f),
                    shape = RoundedCornerShape(12.dp)
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
