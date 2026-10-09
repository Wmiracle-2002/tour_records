package com.miracle.footmarks.ui.screen.profile

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.IconButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Star
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.miracle.footmarks.ui.theme.AccentMint
import com.miracle.footmarks.ui.theme.AccentMintContainer
import com.miracle.footmarks.ui.theme.AccentOrange
import com.miracle.footmarks.ui.theme.AccentOrangeContainer
import com.miracle.footmarks.ui.theme.AccentSky
import com.miracle.footmarks.ui.theme.BorderGray
import com.miracle.footmarks.ui.theme.SurfaceWhite
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    onOpenLogin: () -> Unit = {},
    onOpenAccount: () -> Unit = {},
    onOpenKnowledge: () -> Unit = {},
    modifier: Modifier = Modifier,
    viewModel: ProfileViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val cloudState by viewModel.cloudState.collectAsState()
    val preferencesState by viewModel.preferencesState.collectAsState()

    if (cloudState.requiresPasswordChange) {
        ChangePasswordDialog(
            mandatory = true,
            isWorking = cloudState.isWorking,
            error = cloudState.error,
            onDismiss = viewModel::logout,
            onSubmit = viewModel::changePassword,
        )
        return
    }

    if (cloudState.role == "admin") {
        AdminPanel(onLogout = viewModel::logout)
        return
    }

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
                onOpenLogin = { viewModel.prepareLogin(); onOpenLogin() },
                onOpenAccount = onOpenAccount,
                onOpenKnowledge = onOpenKnowledge,
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
    onOpenAccount: () -> Unit = {},
    onOpenKnowledge: () -> Unit = {},
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
            modifier = Modifier.fillMaxWidth().clickable {
                if (cloudState.isCloudMode) onOpenAccount() else onOpenLogin()
            },
            shape = RoundedCornerShape(24.dp),
            colors = CardDefaults.cardColors(containerColor = AccentOrangeContainer)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier.background(AccentOrange, CircleShape).padding(14.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(Icons.Default.Place, contentDescription = null, tint = SurfaceWhite)
                }
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = if (cloudState.isCloudMode) cloudState.username ?: "旅行者账号" else "旅行者账号",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = if (cloudState.isCloudMode) "已登录 · 查看账号与用量 ›" else "登录或注册，保存你的旅行记录 ›",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
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

        TravelPreferencesCard(
            isCloudMode = cloudState.isCloudMode,
            items = preferences,
            isLoading = preferencesLoading,
            isWorking = preferencesWorking,
            message = preferencesMessage,
            error = preferencesError,
            onSave = onSavePreference,
            onDelete = onDeletePreference
        )

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = AccentSky.copy(alpha = 0.13f))
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Star, contentDescription = null, tint = AccentSky)
                    Column {
                    Text("我的旅行收藏", style = MaterialTheme.typography.titleMedium)
                    Text("笔记、攻略与美食灵感")
                    }
                }
                TextButton(onClick = onOpenKnowledge) { Text("查看") }
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
            border = BorderStroke(1.dp, BorderGray)
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text("关于足迹", style = MaterialTheme.typography.titleMedium)
                Text("记录每次出发，收藏每段心动。", style = MaterialTheme.typography.bodyMedium)
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
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = AccentMintContainer.copy(alpha = 0.65f))
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("旅行偏好", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "只保存你明确要求记住的内容；会影响推荐，不会代替实时查询。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (!isCloudMode) {
                Text("登录后可在多台设备间同步偏好。", style = MaterialTheme.typography.bodyMedium)
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountManagementScreen(
    onBack: () -> Unit,
    onOpenLogin: () -> Unit,
    viewModel: ProfileViewModel
) {
    val state by viewModel.cloudState.collectAsState()
    LaunchedEffect(state.isCloudMode) {
        if (!state.isCloudMode) onBack()
    }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("账号管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "返回")
                    }
                },
                windowInsets = WindowInsets(0, 0, 0, 0)
            )
        },
        contentWindowInsets = WindowInsets(0, 0, 0, 0)
    ) { paddingValues ->
        AccountManagementContent(
            state = state,
            onOpenLogin = { viewModel.prepareLogin(); onOpenLogin() },
            onRefresh = viewModel::refresh,
            onLogout = viewModel::logout,
            onDeleteAccount = viewModel::deleteMyAccount,
            onChangePassword = viewModel::changePassword,
            modifier = Modifier.padding(paddingValues)
        )
    }
}

@Composable
fun AccountManagementContent(
    state: CloudAccountState,
    modifier: Modifier = Modifier,
    onOpenLogin: () -> Unit = {},
    onRefresh: () -> Unit = {},
    onLogout: () -> Unit = {},
    onDeleteAccount: (String) -> Unit = {},
    onChangePassword: (String, String) -> Unit = { _, _ -> }
) {
    var deleting by remember { mutableStateOf(false) }
    var changingPassword by remember { mutableStateOf(false) }
    var password by remember { mutableStateOf("") }
    Column(
        modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (state.isCloudMode) SurfaceWhite else AccentOrangeContainer
        ),
        border = if (state.isCloudMode) BorderStroke(1.dp, BorderGray) else null
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            if (state.isCloudMode) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("账号与同步", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text("● 已连接", style = MaterialTheme.typography.bodySmall, color = AccentMint)
                }
                Text("${state.username ?: "旅行者账号"} · 旅程已与云端连接", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (state.isWorking) CircularProgressIndicator()
            state.message?.let { Text(it) }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
    state.quota?.let { quota ->
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = AccentOrangeContainer.copy(alpha = 0.65f))
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("智能规划额度", fontWeight = FontWeight.SemiBold)
                    Text(quota.period, style = MaterialTheme.typography.bodySmall)
                }
                LinearProgressIndicator(
                    progress = if (quota.limit > 0) (quota.used.toFloat() / quota.limit).coerceIn(0f, 1f) else 0f,
                    modifier = Modifier.fillMaxWidth(),
                    color = AccentOrange,
                    trackColor = SurfaceWhite
                )
                Text("已用 ${quota.used.tokenCount()} / ${quota.limit.tokenCount()} token")
                Text("剩余 ${quota.remaining.tokenCount()} token", color = AccentOrange)
            }
        }
    }
    Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, BorderGray)) {
        Column {
            AccountAction("刷新云端记录", !state.isWorking, onRefresh)
            AccountAction("修改密码", !state.isWorking) { changingPassword = true }
            AccountAction("切换账号", !state.isWorking, onOpenLogin)
            AccountAction("退出登录", !state.isWorking, onLogout)
        }
    }
    TextButton(onClick = { deleting = true }, enabled = !state.isWorking,
        modifier = Modifier.align(Alignment.End)) {
        Text("注销账号", color = MaterialTheme.colorScheme.error)
    }
    }
    if (deleting) {
        AlertDialog(
            onDismissRequest = { deleting = false; password = "" },
            title = { Text("确认注销账号") },
            text = {
                Column {
                    Text("账号及云端旅行、照片、对话将被删除。请输入密码确认。")
                    OutlinedTextField(password, { password = it }, label = { Text("密码") },
                        visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                }
            },
            confirmButton = { TextButton(onClick = {
                onDeleteAccount(password)
                password = ""
                deleting = false
            }, enabled = password.isNotBlank()) { Text("确认注销") } },
            dismissButton = { TextButton(onClick = { deleting = false; password = "" }) { Text("取消") } }
        )
    }
    if (changingPassword) {
        ChangePasswordDialog(
            mandatory = false, isWorking = state.isWorking, error = state.error,
            onDismiss = { changingPassword = false },
            onSubmit = { old, new -> onChangePassword(old, new); changingPassword = false },
        )
    }
}

@Composable
private fun AccountAction(label: String, enabled: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).padding(16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
        Text("›", color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun Int.tokenCount(): String = String.format(Locale.US, "%,d", this)

@Composable
private fun ChangePasswordDialog(
    mandatory: Boolean,
    isWorking: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onSubmit: (String, String) -> Unit,
) {
    var current by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { if (!mandatory) onDismiss() },
        title = { Text(if (mandatory) "请修改临时密码" else "修改密码") },
        text = {
            Column {
                OutlinedTextField(current, { current = it }, label = { Text("当前密码") },
                    visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                OutlinedTextField(next, { next = it }, label = { Text("新密码，至少 12 位") },
                    visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSubmit(current, next); current = ""; next = "" },
                enabled = !isWorking && current.isNotBlank() && next.length >= 12) { Text("保存并重新登录") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(if (mandatory) "退出登录" else "取消") } },
    )
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
