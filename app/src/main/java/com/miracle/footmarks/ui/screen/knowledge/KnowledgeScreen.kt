package com.miracle.footmarks.ui.screen.knowledge

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.data.remote.KnowledgeRequest
import com.miracle.footmarks.data.remote.RemoteKnowledge
import com.miracle.footmarks.data.repository.AdministrativeLocation

private val categories = listOf(
    "note" to "笔记", "travel_guide" to "旅行攻略",
    "food_guide" to "美食攻略", "attraction_guide" to "景点攻略"
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeScreen(
    onBack: () -> Unit,
    initialEntryId: Long = -1,
    viewModel: KnowledgeViewModel = hiltViewModel()
) {
    val state by viewModel.uiState.collectAsState()
    var query by remember { mutableStateOf("") }
    var editing by remember { mutableStateOf<RemoteKnowledge?>(null) }
    var showEditor by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<RemoteKnowledge?>(null) }

    LaunchedEffect(initialEntryId) {
        if (initialEntryId > 0) viewModel.open(initialEntryId)
    }
    LaunchedEffect(state.savedCount) {
        if (state.savedCount > 0) showEditor = false
    }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("我的旅行收藏") },
            navigationIcon = { TextButton(onClick = onBack) { Text("返回") } },
            actions = {
                TextButton(onClick = { editing = null; showEditor = true }, enabled = viewModel.isCloudMode) { Text("添加") }
            }
        )
    }) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (!viewModel.isCloudMode) {
                Text("请先在个人中心登录，再管理云端收藏。")
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = query, onValueChange = { query = it },
                        label = { Text("搜索标题或正文") }, modifier = Modifier.weight(1f),
                        singleLine = true
                    )
                    TextButton(onClick = { viewModel.refresh(query) }) { Text("查找") }
                }
                if (state.isLoading) Text("正在读取收藏…")
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                if (!state.isLoading && state.entries.isEmpty()) Text("还没有匹配的收藏")
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(state.entries, key = { it.id }) { entry ->
                        Card(
                            onClick = { viewModel.open(entry.id) },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(entry.title, style = MaterialTheme.typography.titleMedium)
                                Text("${entry.cityName} · ${categories.firstOrNull { it.first == entry.category }?.second ?: entry.category}")
                                Text(entry.body.take(90), maxLines = 2)
                            }
                        }
                    }
                }
            }
        }
    }

    state.selected?.let { entry ->
        AlertDialog(
            onDismissRequest = viewModel::close,
            title = { Text(entry.title) },
            text = {
                Column(modifier = Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState())) {
                    Text("${entry.cityName} · ${entry.tags.joinToString("、")}")
                    Text(entry.body)
                    entry.source?.let { Text("来源：$it") }
                }
            },
            confirmButton = {
                TextButton(onClick = { editing = entry; showEditor = true; viewModel.close() }) {
                    Text("编辑")
                }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { deleting = entry; viewModel.close() }, enabled = !state.isSaving) {
                        Text("删除")
                    }
                    TextButton(onClick = viewModel::close) { Text("关闭") }
                }
            }
        )
    }
    deleting?.let { entry ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("删除收藏？") },
            text = { Text("将删除“${entry.title}”，此操作无法撤销。") },
            confirmButton = {
                TextButton(onClick = { viewModel.delete(entry.id); deleting = null }) { Text("删除") }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } }
        )
    }
    if (showEditor) {
        KnowledgeEditor(
            original = editing,
            isSaving = state.isSaving,
            error = state.error,
            searchCities = viewModel::searchCities,
            onDismiss = { showEditor = false },
            onSave = { request ->
                viewModel.save(editing?.id, request)
            }
        )
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun KnowledgeEditor(
    original: RemoteKnowledge?,
    isSaving: Boolean,
    error: String?,
    searchCities: (String) -> List<AdministrativeLocation>,
    onDismiss: () -> Unit,
    onSave: (KnowledgeRequest) -> Unit
) {
    var category by remember(original?.id) { mutableStateOf(original?.category ?: "note") }
    var title by remember(original?.id) { mutableStateOf(original?.title ?: "") }
    var body by remember(original?.id) { mutableStateOf(original?.body ?: "") }
    var tags by remember(original?.id) { mutableStateOf(original?.tags?.joinToString("，") ?: "") }
    var source by remember(original?.id) { mutableStateOf(original?.source ?: "") }
    var cityQuery by remember(original?.id) { mutableStateOf(original?.cityName ?: "") }
    var cityCode by remember(original?.id) { mutableStateOf(original?.cityCode ?: "") }
    var cityName by remember(original?.id) { mutableStateOf(original?.cityName ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (original == null) "添加旅行收藏" else "编辑旅行收藏") },
        text = {
            Column(
                modifier = Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                categories.forEach { (value, label) ->
                    FilterChip(selected = category == value, onClick = { category = value }, label = { Text(label) })
                }
                OutlinedTextField(title, { title = it }, label = { Text("标题") }, singleLine = true)
                OutlinedTextField(cityQuery, {
                    cityQuery = it
                    cityCode = ""
                }, label = { Text("城市（输入后选择）") }, singleLine = true)
                if (cityCode.isEmpty()) {
                    searchCities(cityQuery).forEach { city ->
                        TextButton(onClick = {
                            cityCode = city.code
                            cityName = city.name
                            cityQuery = city.breadcrumb
                        }) { Text(city.breadcrumb) }
                    }
                } else Text("已选：$cityName")
                OutlinedTextField(body, { body = it }, label = { Text("正文") }, minLines = 4)
                OutlinedTextField(tags, { tags = it }, label = { Text("标签，用逗号分隔") })
                OutlinedTextField(source, { source = it }, label = { Text("来源说明（可选）") })
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(
                enabled = !isSaving && title.isNotBlank() && body.isNotBlank() && cityCode.isNotBlank(),
                onClick = {
                    onSave(KnowledgeRequest(
                        category, title.trim(), body.trim(), cityCode, cityName,
                        tags.split('，', ',').map { it.trim() }.filter { it.isNotEmpty() },
                        source.trim().ifEmpty { null }
                    ))
                }
            ) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}
