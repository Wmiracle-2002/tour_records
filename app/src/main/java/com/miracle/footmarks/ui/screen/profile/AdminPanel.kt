package com.miracle.footmarks.ui.screen.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.data.remote.AdminUser
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.TripRequest

@Composable
fun AdminPanel(
    onLogout: () -> Unit,
    viewModel: AdminViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsState()
    var creatingUser by remember { mutableStateOf(false) }
    var editingUser by remember { mutableStateOf<AdminUser?>(null) }
    var deletingUser by remember { mutableStateOf<AdminUser?>(null) }
    var editingTrip by remember { mutableStateOf<RemoteTrip?>(null) }
    var creatingTrip by remember { mutableStateOf(false) }
    var deletingTrip by remember { mutableStateOf<RemoteTrip?>(null) }
    var defaultQuota by remember(state.defaultQuota) { mutableStateOf(state.defaultQuota?.toString().orEmpty()) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("管理中心")
        Row {
            TextButton(onClick = viewModel::load) { Text("刷新") }
            TextButton(onClick = onLogout) { Text("退出登录") }
        }
        if (state.working) CircularProgressIndicator()
        state.error?.let { Text(it) }
        state.message?.let { Text(it) }
        OutlinedTextField(defaultQuota, { defaultQuota = it }, label = { Text("新账号每月默认 token 额度") })
        Button(
            onClick = { defaultQuota.toIntOrNull()?.let(viewModel::setDefaultQuota) },
            enabled = defaultQuota.toIntOrNull()?.let { it >= 0 } == true
        ) { Text("保存默认额度") }
        Button(onClick = { creatingUser = true }) { Text("创建普通账号") }
        state.users.forEach { user ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text("${user.username} · ${user.status}")
                    Text("月额度：${user.monthlyTokenLimit?.toString() ?: "使用默认值"}")
                    Text("照片占用：${user.photoBytesUsed / 1024 / 1024} MB")
                    Row {
                        TextButton(onClick = { viewModel.select(user.id) }) { Text("数据") }
                        TextButton(onClick = { editingUser = user }) { Text("管理") }
                        TextButton(onClick = { deletingUser = user }) { Text("删除") }
                    }
                }
            }
        }
        val selected = state.users.firstOrNull { it.id == state.selectedUserId }
        if (selected != null) {
            Text("${selected.username} 的旅行")
            state.selectedQuota?.let { quota ->
                Text("${quota.period} 智能规划：已用 ${quota.used} / ${quota.limit} token，剩余 ${quota.remaining}")
            }
            Button(onClick = { creatingTrip = true }) { Text("新增旅行") }
            state.trips.forEach { trip ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${trip.cityName}  ${trip.startDate} 至 ${trip.endDate}")
                        Text("${trip.records.size} 条景点/美食记录")
                        Row {
                            TextButton(onClick = { editingTrip = trip }) { Text("修改") }
                            TextButton(onClick = { deletingTrip = trip }) { Text("删除") }
                        }
                        AdminRecords(selected.id, trip, viewModel)
                    }
                }
            }
            AdminOtherData(selected.id, state, viewModel)
        }
    }

    if (creatingUser) {
        var username by remember { mutableStateOf("") }
        var password by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { creatingUser = false }, title = { Text("创建普通账号") },
            text = {
                Column {
                    OutlinedTextField(username, { username = it }, label = { Text("用户名") })
                    OutlinedTextField(password, { password = it }, label = { Text("临时密码") }, visualTransformation = PasswordVisualTransformation())
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.createUser(username, password)
                    password = ""
                    creatingUser = false
                }) { Text("创建") }
            },
            dismissButton = { TextButton(onClick = { creatingUser = false }) { Text("取消") } }
        )
    }
    editingUser?.let { user ->
        var password by remember(user.id) { mutableStateOf("") }
        var quota by remember(user.id) { mutableStateOf(user.monthlyTokenLimit?.toString().orEmpty()) }
        AlertDialog(
            onDismissRequest = { editingUser = null }, title = { Text("管理 ${user.username}") },
            text = {
                Column {
                    TextButton(onClick = {
                        viewModel.setStatus(user.id, if (user.status == "active") "disabled" else "active")
                        editingUser = null
                    }) { Text(if (user.status == "active") "停用账号" else "启用账号") }
                    OutlinedTextField(password, { password = it }, label = { Text("重置为临时密码") }, visualTransformation = PasswordVisualTransformation())
                    TextButton(onClick = {
                        viewModel.resetPassword(user.id, password)
                        password = ""
                        editingUser = null
                    }, enabled = password.length >= 12) { Text("重置密码") }
                    OutlinedTextField(quota, { quota = it }, label = { Text("月 token 上限；留空使用默认值") })
                    TextButton(onClick = {
                        viewModel.setQuota(user.id, quota.toIntOrNull())
                        editingUser = null
                    }, enabled = quota.isBlank() || quota.toIntOrNull()?.let { it >= 0 } == true) { Text("保存额度") }
                }
            },
            confirmButton = { TextButton(onClick = { editingUser = null }) { Text("完成") } }
        )
    }
    deletingUser?.let { user ->
        AlertDialog(
            onDismissRequest = { deletingUser = null }, title = { Text("删除 ${user.username}？") },
            text = { Text("该账号的旅行、照片和对话将被删除。") },
            confirmButton = { TextButton(onClick = { viewModel.deleteUser(user.id); deletingUser = null }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { deletingUser = null }) { Text("取消") } }
        )
    }
    val selectedUserId = state.selectedUserId
    if (selectedUserId != null && (creatingTrip || editingTrip != null)) {
        val existing = editingTrip
        var province by remember(existing?.id) { mutableStateOf(existing?.provinceCode.orEmpty()) }
        var cityCode by remember(existing?.id) { mutableStateOf(existing?.cityCode.orEmpty()) }
        var cityName by remember(existing?.id) { mutableStateOf(existing?.cityName.orEmpty()) }
        var start by remember(existing?.id) { mutableStateOf(existing?.startDate.orEmpty()) }
        var end by remember(existing?.id) { mutableStateOf(existing?.endDate.orEmpty()) }
        AlertDialog(
            onDismissRequest = { creatingTrip = false; editingTrip = null },
            title = { Text(if (existing == null) "新增旅行" else "修改旅行") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    OutlinedTextField(province, { province = it }, label = { Text("省代码（6位）") })
                    OutlinedTextField(cityCode, { cityCode = it }, label = { Text("城市代码（6位）") })
                    OutlinedTextField(cityName, { cityName = it }, label = { Text("城市名称") })
                    OutlinedTextField(start, { start = it }, label = { Text("开始 YYYY-MM-DD") })
                    OutlinedTextField(end, { end = it }, label = { Text("结束 YYYY-MM-DD") })
                }
            },
            confirmButton = { TextButton(onClick = {
                val request = TripRequest(province, cityCode, cityName, start, end)
                if (existing == null) viewModel.createTrip(selectedUserId, request)
                else viewModel.updateTrip(selectedUserId, existing.id, request)
                creatingTrip = false
                editingTrip = null
            }) { Text("保存") } },
            dismissButton = { TextButton(onClick = { creatingTrip = false; editingTrip = null }) { Text("取消") } }
        )
    }
    deletingTrip?.let { trip ->
        AlertDialog(
            onDismissRequest = { deletingTrip = null }, title = { Text("删除 ${trip.cityName} 旅行？") },
            confirmButton = { TextButton(onClick = {
                state.selectedUserId?.let { viewModel.deleteTrip(it, trip.id) }
                deletingTrip = null
            }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { deletingTrip = null }) { Text("取消") } }
        )
    }
}
