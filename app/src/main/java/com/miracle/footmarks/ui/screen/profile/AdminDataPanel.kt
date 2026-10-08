package com.miracle.footmarks.ui.screen.profile

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.miracle.footmarks.data.remote.KnowledgeRequest
import com.miracle.footmarks.data.remote.RecordRequest
import com.miracle.footmarks.data.remote.RemoteKnowledge
import com.miracle.footmarks.data.remote.RemoteRecord
import com.miracle.footmarks.data.remote.RemoteTrip

@Composable
internal fun AdminRecords(userId: Long, trip: RemoteTrip, viewModel: AdminViewModel) {
    var editing by remember { mutableStateOf<RemoteRecord?>(null) }
    var adding by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<RemoteRecord?>(null) }
    var uploadTarget by remember { mutableStateOf<Long?>(null) }
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        val recordId = uploadTarget
        if (uri != null && recordId != null) viewModel.uploadImage(userId, recordId, uri)
        uploadTarget = null
    }
    TextButton(onClick = { adding = true }) { Text("添加景点/美食") }
    trip.records.forEach { record ->
        Card(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
            Column(Modifier.padding(8.dp)) {
                Text("${if (record.type == "FOOD") "美食" else "景点"} · ${record.name} · ${record.date}")
                Row {
                    TextButton(onClick = { editing = record }) { Text("修改") }
                    TextButton(onClick = { deleting = record }) { Text("删除") }
                    TextButton(onClick = { uploadTarget = record.id; photoPicker.launch("image/*") }) { Text("上传照片") }
                }
                record.images.orEmpty().forEach { image ->
                    Row {
                        Text(image.originalFilename, modifier = Modifier.weight(1f))
                        TextButton(onClick = { viewModel.deleteImage(userId, image.id) }) { Text("删除照片") }
                    }
                }
            }
        }
    }
    if (adding || editing != null) {
        val old = editing
        var type by remember(old?.id) { mutableStateOf(old?.type ?: "ATTRACTION") }
        var name by remember(old?.id) { mutableStateOf(old?.name.orEmpty()) }
        var date by remember(old?.id) { mutableStateOf(old?.date ?: trip.startDate) }
        var notes by remember(old?.id) { mutableStateOf(old?.notes.orEmpty()) }
        var cost by remember(old?.id) { mutableStateOf(old?.cost.orEmpty()) }
        AlertDialog(
            onDismissRequest = { adding = false; editing = null },
            title = { Text(if (old == null) "添加记录" else "修改记录") },
            text = {
                Column {
                    TextButton(onClick = { type = if (type == "FOOD") "ATTRACTION" else "FOOD" }) {
                        Text(if (type == "FOOD") "美食（点击切换）" else "景点（点击切换）")
                    }
                    OutlinedTextField(name, { name = it }, label = { Text("名称") })
                    OutlinedTextField(date, { date = it }, label = { Text("日期 YYYY-MM-DD") })
                    OutlinedTextField(cost, { cost = it }, label = { Text("花费，可空") })
                    OutlinedTextField(notes, { notes = it }, label = { Text("备注") })
                }
            },
            confirmButton = { TextButton(onClick = {
                val request = RecordRequest(type, name.trim(), date, old?.rating, cost.ifBlank { null }, notes.ifBlank { null })
                if (old == null) viewModel.createRecord(userId, trip.id, request)
                else viewModel.updateRecord(userId, old.id, request)
                adding = false; editing = null
            }, enabled = name.isNotBlank()) { Text("保存") } },
            dismissButton = { TextButton(onClick = { adding = false; editing = null }) { Text("取消") } },
        )
    }
    deleting?.let { record ->
        AlertDialog(
            onDismissRequest = { deleting = null }, title = { Text("删除 ${record.name}？") },
            confirmButton = { TextButton(onClick = { viewModel.deleteRecord(userId, record.id); deleting = null }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
internal fun AdminOtherData(userId: Long, state: AdminState, viewModel: AdminViewModel) {
    var editingKnowledge by remember { mutableStateOf<RemoteKnowledge?>(null) }
    var addingKnowledge by remember { mutableStateOf(false) }
    var preferenceCategory by remember { mutableStateOf<String?>(null) }
    var deletingConversation by remember { mutableStateOf<String?>(null) }
    Text("旅行收藏与攻略")
    Button(onClick = { addingKnowledge = true }) { Text("新增收藏") }
    state.knowledge.forEach { item ->
        Card(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
            Column(Modifier.padding(8.dp)) {
                Text("${item.title} · ${item.cityName}")
                Row {
                    TextButton(onClick = { editingKnowledge = item }) { Text("修改") }
                    TextButton(onClick = { viewModel.deleteKnowledge(userId, item.id) }) { Text("删除") }
                }
            }
        }
    }
    Text("旅行偏好")
    listOf("food_restriction", "attraction_interest", "travel_pace", "budget_tendency").forEach { category ->
        val item = state.preferences.firstOrNull { it.category == category }
        Row {
            Text("$category：${item?.content ?: "未设置"}", modifier = Modifier.weight(1f))
            TextButton(onClick = { preferenceCategory = category }) { Text("编辑") }
            if (item != null) TextButton(onClick = { viewModel.deletePreference(userId, category) }) { Text("删除") }
        }
    }
    Text("对话")
    state.conversations.forEach { conversation ->
        Row {
            Text(conversation.title, modifier = Modifier.weight(1f))
            TextButton(onClick = { deletingConversation = conversation.id }) { Text("删除") }
        }
    }
    if (addingKnowledge || editingKnowledge != null) {
        val item = editingKnowledge
        var category by remember(item?.id) { mutableStateOf(item?.category ?: "note") }
        var title by remember(item?.id) { mutableStateOf(item?.title.orEmpty()) }
        var body by remember(item?.id) { mutableStateOf(item?.body.orEmpty()) }
        var cityCode by remember(item?.id) { mutableStateOf(item?.cityCode.orEmpty()) }
        var cityName by remember(item?.id) { mutableStateOf(item?.cityName.orEmpty()) }
        AlertDialog(
            onDismissRequest = { addingKnowledge = false; editingKnowledge = null },
            title = { Text("旅行收藏") },
            text = { Column {
                OutlinedTextField(category, { category = it }, label = { Text("类型 note/travel_guide/food_guide/attraction_guide") })
                OutlinedTextField(title, { title = it }, label = { Text("标题") })
                OutlinedTextField(body, { body = it }, label = { Text("正文") })
                OutlinedTextField(cityCode, { cityCode = it }, label = { Text("城市代码") })
                OutlinedTextField(cityName, { cityName = it }, label = { Text("城市名称") })
            } },
            confirmButton = { TextButton(onClick = {
                viewModel.saveKnowledge(userId, item?.id, KnowledgeRequest(
                    category, title, body, cityCode, cityName, item?.tags.orEmpty(), item?.source,
                ))
                addingKnowledge = false; editingKnowledge = null
            }, enabled = title.isNotBlank() && body.isNotBlank()) { Text("保存") } },
            dismissButton = { TextButton(onClick = { addingKnowledge = false; editingKnowledge = null }) { Text("取消") } },
        )
    }
    preferenceCategory?.let { category ->
        var content by remember(category) { mutableStateOf(state.preferences.firstOrNull { it.category == category }?.content.orEmpty()) }
        AlertDialog(
            onDismissRequest = { preferenceCategory = null }, title = { Text("修改 $category") },
            text = { OutlinedTextField(content, { content = it }, label = { Text("内容") }) },
            confirmButton = { TextButton(onClick = {
                viewModel.savePreference(userId, category, content.trim()); preferenceCategory = null
            }, enabled = content.isNotBlank()) { Text("保存") } },
            dismissButton = { TextButton(onClick = { preferenceCategory = null }) { Text("取消") } },
        )
    }
    deletingConversation?.let { id ->
        AlertDialog(
            onDismissRequest = { deletingConversation = null }, title = { Text("删除该会话及记忆？") },
            confirmButton = { TextButton(onClick = {
                viewModel.deleteConversation(userId, id); deletingConversation = null
            }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { deletingConversation = null }) { Text("取消") } },
        )
    }
}
