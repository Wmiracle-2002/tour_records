package com.miracle.footmarks.ui.screen.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.BuildConfig
import com.miracle.footmarks.data.local.dao.TravelStats
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    modifier: Modifier = Modifier,
    viewModel: ProfileViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val cloudState by viewModel.cloudState.collectAsState()

    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("个人中心") }) }
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
                onLogin = viewModel::login,
                onRefresh = viewModel::refresh
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
    onLogin: (String, String) -> Unit = { _, _ -> },
    onRefresh: () -> Unit = {}
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
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
                    text = if (cloudState.isCloudMode) "服务端保存文字记录，本机缓存供浏览" else "旅行数据仅保存在当前设备",
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

        CloudAccountCard(cloudState, onLogin, onRefresh)

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

@Composable
private fun CloudAccountCard(
    state: CloudAccountState,
    onLogin: (String, String) -> Unit,
    onRefresh: () -> Unit
) {
    var username by remember { mutableStateOf("shared") }
    var password by remember { mutableStateOf("") }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("共享账号", style = MaterialTheme.typography.titleMedium)
            if (state.isCloudMode) {
                Text("已连接本地服务端；记录页使用本机缓存，写入时需要网络")
                Button(onClick = onRefresh, enabled = !state.isWorking) {
                    Text("刷新共享记录")
                }
            } else {
                OutlinedTextField(
                    value = username, onValueChange = { username = it },
                    label = { Text("用户名") }, singleLine = true
                )
                OutlinedTextField(
                    value = password, onValueChange = { password = it },
                    label = { Text("密码") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation()
                )
                Button(onClick = {
                    onLogin(username, password)
                    password = ""
                }, enabled = !state.isWorking && password.isNotBlank()) {
                    Text("登录并同步")
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
    Card(modifier = modifier) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Text(
                text = value,
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
