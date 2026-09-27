package com.miracle.footmarks.ui.screen.profile

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.BuildConfig
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.remote.RemotePreference
import com.miracle.footmarks.ui.theme.AccentMintContainer
import com.miracle.footmarks.ui.theme.BorderGray
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    onOpenLogin: () -> Unit = {},
    modifier: Modifier = Modifier,
    viewModel: ProfileViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val cloudState by viewModel.cloudState.collectAsState()
    val preferencesState by viewModel.preferencesState.collectAsState()

    Scaffold(
        modifier = modifier,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            TopAppBar(
                title = { Text("个人中心") },
                windowInsets = WindowInsets(0, 0, 0, 0)
            )
        }
    ) { paddingValues ->
        if (uiState.isLoading) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            ProfileContent(
                stats = uiState.stats,
                versionName = BuildConfig.VERSION_NAME,
                modifier = Modifier.padding(paddingValues),
                cloudState = cloudState,
                onOpenLogin = onOpenLogin,
                onRefresh = viewModel::refresh,
                preferences = preferencesState.items,
                preferencesLoading = preferencesState.isLoading,
                preferencesWorking = preferencesState.isWorking,
                preferencesMessage = preferencesState.message,
                preferencesError = preferencesState.error,
                onSavePreference = viewModel::savePreference,
                onDeletePreference = viewModel::deletePreference
            )
        }
    }
}

@Composable
fun ProfileContent(
    stats: TravelStats,
    versionName: String,
    modifier: Modifier = Modifier,
    cloudState: CloudAccountState = CloudAccountState(),
    onOpenLogin: () -> Unit = {},
    onRefresh: () -> Unit = {},
    preferences: List<RemotePreference> = emptyList(),
    preferencesLoading: Boolean = false,
    preferencesWorking: Boolean = false,
    preferencesMessage: String? = null,
    preferencesError: String? = null,
    onSavePreference: (String, String) -> Unit = { _, _ -> },
    onDeletePreference: (String) -> Unit = {}
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = androidx.compose.foundation.shape.RoundedCornerShape(24.dp),
            colors = CardDefaults.cardColors(containerColor = AccentMintContainer),
            border = BorderStroke(1.dp, AccentMintContainer.copy(alpha = 0.9f))
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Text(
                    text = if (cloudState.isCloudMode) "共享旅行者" else "本地旅行者",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = if (cloudState.isCloudMode) {
                        "已连接云端服务，本机保留缓存用于浏览。"
                    } else {
                        "旅行数据仅保存在当前设备。"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
            }
        }

        Text("旅行统计", style = MaterialTheme.typography.titleMedium)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            StatCard("城市", stats.cityCount.toString(), Modifier.weight(1f))
            StatCard("出行", stats.tripCount.toString(), Modifier.weight(1f))
        }
        StatCard(
            label = "总花费",
            value = String.format(Locale.US, "¥ %.2f", stats.totalCost),
            modifier = Modifier.fillMaxWidth()
        )

        CloudAccountCard(cloudState, onOpenLogin, onRefresh)

        TravelPreferencesCard(
            isCloudMode = cloudState.isCloudMode,
            items = preferences,
            isLoading = preferencesLoading,
            isWorking = preferencesWorking,
            message = preferencesMessage,
            error = preferencesError,
            onOpenLogin = onOpenLogin,
            onSave = onSavePreference,
            onDelete = onDeletePreference
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text("关于足迹", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "版本 $versionName",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

private val preferenceCategories = listOf(
    "food_restriction" to "饮食偏好/忌口",
    "attraction_interest" to "景点兴趣",
    "travel_pace" to "旅行节奏",
    "budget_tendency" to "预算倾向"
)

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun TravelPreferencesCard(
    isCloudMode: Boolean,
    items: List<RemotePreference>,
    isLoading: Boolean,
    isWorking: Boolean,
    message: String?,
    error: String?,
    onOpenLogin: () -> Unit,
    onSave: (String, String) -> Unit,
    onDelete: (String) -> Unit
) {
    var editorOpen by remember { mutableStateOf(false) }
    var selectedCategory by remember { mutableStateOf(preferenceCategories.first().first) }
    var editingPreference by remember { mutableStateOf<RemotePreference?>(null) }
    var content by remember { mutableStateOf("") }
    var deletingPreference by remember { mutableStateOf<RemotePreference?>(null) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = androidx.compose.foundation.shape.RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, BorderGray)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("长期旅行偏好", style = MaterialTheme.typography.titleMedium)
            Text(
                "只保存你明确要求记住的内容；会影响推荐，不会代替实时查询。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (!isCloudMode) {
                Text("登录共享账号后可在多台设备间管理偏好。")
                Button(onClick = onOpenLogin) { Text("登录后管理") }
            } else {
                if (isLoading) CircularProgressIndicator()
                items.forEach { item ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(preferenceCategoryLabel(item.category), fontWeight = FontWeight.SemiBold)
                            Text(item.content, style = MaterialTheme.typography.bodyMedium)
                        }
                        TextButton(
                            enabled = !isWorking,
                            onClick = {
                                editingPreference = item
                                selectedCategory = item.category
                                content = item.content
                                editorOpen = true
                            }
                        ) { Text("修改") }
                        TextButton(
                            enabled = !isWorking,
                            onClick = { deletingPreference = item }
                        ) { Text("删除") }
                    }
                }
                Button(
                    enabled = !isWorking,
                    onClick = {
                        editingPreference = null
                        selectedCategory = preferenceCategories.first().first
                        content = ""
                        editorOpen = true
                    }
                ) { Text("添加偏好") }
                message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        }
    }

    if (editorOpen) {
        AlertDialog(
            onDismissRequest = { editorOpen = false },
            title = { Text(if (editingPreference == null) "添加旅行偏好" else "修改旅行偏好") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (editingPreference == null) {
                        preferenceCategories.chunked(2).forEach { row ->
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                row.forEach { (category, label) ->
                                    FilterChip(
                                        selected = selectedCategory == category,
                                        onClick = { selectedCategory = category },
                                        label = { Text(label) }
                                    )
                                }
                            }
                        }
                    } else {
                        Text(preferenceCategoryLabel(selectedCategory))
                    }
                    OutlinedTextField(
                        value = content,
                        onValueChange = { content = it.take(240) },
                        label = { Text("偏好内容") },
                        placeholder = { Text("例如：不吃辣") },
                        supportingText = { Text("最多 240 字") },
                        singleLine = false
                    )
                }
            },
            confirmButton = {
                TextButton(
                    enabled = content.isNotBlank() && !isWorking,
                    onClick = {
                        onSave(selectedCategory, content.trim())
                        editorOpen = false
                    }
                ) { Text("保存") }
            },
            dismissButton = {
                TextButton(onClick = { editorOpen = false }) { Text("取消") }
            }
        )
    }
    deletingPreference?.let { item ->
        AlertDialog(
            onDismissRequest = { deletingPreference = null },
            title = { Text("删除旅行偏好？") },
            text = { Text("将删除“${preferenceCategoryLabel(item.category)}：${item.content}”。") },
            confirmButton = {
                TextButton(
                    enabled = !isWorking,
                    onClick = {
                        onDelete(item.category)
                        deletingPreference = null
                    }
                ) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { deletingPreference = null }) { Text("取消") }
            }
        )
    }
}

private fun preferenceCategoryLabel(category: String): String =
    preferenceCategories.firstOrNull { it.first == category }?.second ?: "旅行偏好"

@Composable
private fun CloudAccountCard(
    state: CloudAccountState,
    onOpenLogin: () -> Unit,
    onRefresh: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = androidx.compose.foundation.shape.RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, BorderGray)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("共享账号", style = MaterialTheme.typography.titleMedium)
            if (state.isCloudMode) {
                Text("已连接云端服务，记录页会使用同步后的共享记录。")
                Button(onClick = onRefresh, enabled = !state.isWorking) {
                    Text("刷新共享记录")
                }
            } else {
                Text("登录后可以在多台设备间同步旅行记录。")
                Button(onClick = onOpenLogin) {
                    Text("登录共享账号")
                }
            }
            if (state.isWorking) CircularProgressIndicator()
            state.message?.let { Text(it) }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}

@Composable
private fun StatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        shape = androidx.compose.foundation.shape.RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, BorderGray)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Text(value, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
