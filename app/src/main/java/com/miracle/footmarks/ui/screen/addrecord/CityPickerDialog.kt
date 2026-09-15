package com.miracle.footmarks.ui.screen.addrecord

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.data.repository.AdministrativeLocation
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CityPickerDialog(
    onDismiss: () -> Unit,
    onCitySelected: (Long, String) -> Unit,
    viewModel: CityPickerViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val coroutineScope = rememberCoroutineScope()

    AlertDialog(
        onDismissRequest = onDismiss,
        modifier = Modifier
            .fillMaxWidth()
            .fillMaxHeight(0.85f)
    ) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 6.dp
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text("选择地区", style = MaterialTheme.typography.headlineSmall)

                OutlinedTextField(
                    value = uiState.searchQuery,
                    onValueChange = viewModel::searchCities,
                    label = { Text("搜索城市、自治州或区县") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )

                if (uiState.searchQuery.isBlank()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(uiState.provinces, key = { it.code }) { province ->
                            FilterChip(
                                selected = province.code == uiState.selectedProvinceCode,
                                onClick = { viewModel.selectProvince(province.code) },
                                label = { Text(province.name) }
                            )
                        }
                    }
                }

                Box(modifier = Modifier.weight(1f)) {
                    when {
                        uiState.isLoading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                        uiState.error != null -> Text(
                            text = uiState.error.orEmpty(),
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.align(Alignment.Center)
                        )
                        uiState.locations.isEmpty() -> Text(
                            text = "未找到匹配地区",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.align(Alignment.Center)
                        )
                        else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            items(uiState.locations, key = { it.code }) { location ->
                                LocationItem(
                                    location = location,
                                    onClick = {
                                        coroutineScope.launch {
                                            val cityId = viewModel.ensureLocationExists(location)
                                            onCitySelected(cityId, location.name)
                                        }
                                    }
                                )
                            }
                        }
                    }
                }

                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = onDismiss) { Text("取消") }
                }
            }
        }
    }
}

@Composable
private fun LocationItem(
    location: AdministrativeLocation,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant
    ) {
        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text(location.name, style = MaterialTheme.typography.bodyLarge)
            Text(
                text = location.breadcrumb,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
