package com.miracle.footmarks.ui.screen.smartplanning

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.data.remote.RemoteConversation
import com.miracle.footmarks.ui.theme.AccentMintContainer
import com.miracle.footmarks.ui.theme.AccentOrangeContainer
import com.miracle.footmarks.ui.theme.ChatAssistantGreen
import com.miracle.footmarks.ui.theme.ChatUserBlue
import kotlinx.coroutines.delay

@Composable
fun SmartPlanningScreen(
    modifier: Modifier = Modifier,
    onOpenKnowledge: (Long) -> Unit = {},
    viewModel: SmartPlanningViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    SmartPlanningContent(
        uiState = uiState,
        onDraftChange = viewModel::updateDraft,
        onSend = viewModel::send,
        onDismissError = viewModel::dismissError,
        onCreateConversation = viewModel::createNewConversation,
        onOpenConversation = viewModel::openConversation,
        onDeleteConversation = viewModel::deleteConversation,
        onLoadOlderMessages = viewModel::loadOlderMessages,
        onOpenKnowledge = onOpenKnowledge,
        modifier = modifier
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SmartPlanningContent(
    uiState: SmartPlanningUiState,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onDismissError: () -> Unit,
    onCreateConversation: () -> Unit = {},
    onOpenConversation: (String) -> Unit = {},
    onDeleteConversation: (String) -> Unit = {},
    onLoadOlderMessages: () -> Unit = {},
    onOpenKnowledge: (Long) -> Unit = {},
    modifier: Modifier = Modifier
) {
    var showConversations by remember { mutableStateOf(false) }
    var conversationToDelete by remember { mutableStateOf<RemoteConversation?>(null) }
    val listState = rememberLazyListState()
    val isNewConversationSurface = uiState.currentConversationId == null ||
        uiState.isCurrentConversationEmpty

    LaunchedEffect(
        uiState.messages.size, uiState.hasOlderMessages,
        uiState.isSending, uiState.streamingText.length
    ) {
        val lastItemIndex = uiState.messages.size +
            (if (uiState.hasOlderMessages) 1 else 0) +
            (if (uiState.isSending) 1 else 0)
        if (lastItemIndex > 0) listState.scrollToItem(lastItemIndex)
    }

    Scaffold(
        modifier = modifier,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            TopAppBar(
                windowInsets = WindowInsets(0, 0, 0, 0),
                title = {
                    Column {
                        Text("智能计划")
                        Text(
                            "把想去的地方交给灵感",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    TextButton(
                        onClick = onCreateConversation,
                        enabled = !uiState.isCreatingConversation && !uiState.isSending &&
                            !isNewConversationSurface
                    ) {
                        Text(when {
                            uiState.isCreatingConversation -> "创建中…"
                            isNewConversationSurface -> "当前是新对话"
                            else -> "新对话"
                        })
                    }
                    TextButton(onClick = { showConversations = true }) { Text("对话列表") }
                }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .imePadding()
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .padding(horizontal = 16.dp),
                contentPadding = PaddingValues(top = 8.dp, bottom = 8.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(0.92f),
                        shape = RoundedCornerShape(24.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (isNewConversationSurface) {
                                AccentMintContainer
                            } else {
                                AccentOrangeContainer
                            }
                        )
                    ) {
                        Column(
                            modifier = Modifier.padding(18.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text(
                                if (isNewConversationSurface) "开始一段新对话"
                                else "准备出发了吗？",
                                style = MaterialTheme.typography.titleLarge
                            )
                            Text(
                                if (isNewConversationSurface) "告诉我目的地、日期和偏好。"
                                else "告诉我目的地、日期和偏好，一起把旅程想清楚。",
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                }
                if (uiState.hasOlderMessages) {
                    item {
                        TextButton(
                            onClick = onLoadOlderMessages,
                            enabled = !uiState.isLoadingOlderMessages,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(if (uiState.isLoadingOlderMessages) "正在加载…" else "加载更早消息")
                        }
                    }
                }
                items(uiState.messages, key = { it.id }) { message ->
                    ChatBubble(message, onOpenKnowledge)
                }
                if (uiState.isSending || uiState.progressSteps.isNotEmpty()) {
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            AgentProgressCard(uiState)
                            if (uiState.streamingText.isNotEmpty()) {
                                ChatBubble(
                                    ChatMessage(-1, ChatRole.AGENT, uiState.streamingText, "pending"),
                                    onOpenKnowledge
                                )
                            }
                        }
                    }
                }
            }

            uiState.error?.let { error ->
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    color = MaterialTheme.colorScheme.errorContainer,
                    shape = RoundedCornerShape(14.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(start = 14.dp, end = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = error,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.weight(1f)
                        )
                        TextButton(onClick = onDismissError) { Text("关闭") }
                    }
                }
            }

            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(12.dp),
                shape = RoundedCornerShape(26.dp),
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 3.dp
            ) {
                Row(
                    modifier = Modifier.padding(6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.Bottom
                ) {
                    OutlinedTextField(
                        value = uiState.draft,
                        onValueChange = onDraftChange,
                        placeholder = { Text("说说你想去哪里") },
                        modifier = Modifier.weight(1f),
                        minLines = 1,
                        maxLines = 4,
                        shape = RoundedCornerShape(20.dp)
                    )
                    Button(
                        onClick = onSend,
                        enabled = !uiState.isSending && !uiState.isCreatingConversation &&
                            uiState.draft.isNotBlank(),
                        modifier = Modifier.size(52.dp),
                        shape = CircleShape,
                        contentPadding = PaddingValues(0.dp)
                    ) {
                        Icon(Icons.Default.Send, contentDescription = "发送")
                    }
                }
            }
        }
    }

    if (showConversations) {
        ModalBottomSheet(onDismissRequest = { showConversations = false }) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 560.dp)
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("全部对话", style = MaterialTheme.typography.titleLarge)
                if (uiState.isLoadingConversations) {
                    Text("正在加载…", modifier = Modifier.padding(vertical = 12.dp))
                } else if (uiState.conversations.isEmpty()) {
                    Text("还没有保存的对话", modifier = Modifier.padding(vertical = 12.dp))
                } else {
                    LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
                        items(uiState.conversations, key = { it.id }) { conversation ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(
                                    modifier = Modifier
                                        .weight(1f)
                                        .clickable {
                                            onOpenConversation(conversation.id)
                                            showConversations = false
                                        }
                                        .padding(vertical = 12.dp)
                                ) {
                                    Text(conversation.title, style = MaterialTheme.typography.titleMedium)
                                    Text(
                                        "${conversation.messageCount} 条消息",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                TextButton(
                                    onClick = { conversationToDelete = conversation },
                                    enabled = !uiState.isSending
                                ) { Text("删除") }
                            }
                        }
                    }
                }
                TextButton(onClick = { showConversations = false }) { Text("关闭") }
            }
        }
    }

    conversationToDelete?.let { conversation ->
        AlertDialog(
            onDismissRequest = { conversationToDelete = null },
            title = { Text("删除对话？") },
            text = { Text("“${conversation.title}”及其中的消息会被删除。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        onDeleteConversation(conversation.id)
                        conversationToDelete = null
                    }
                ) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { conversationToDelete = null }) { Text("取消") }
            }
        )
    }
}

@Composable
private fun AgentProgressCard(state: SmartPlanningUiState) {
    var elapsedSeconds by remember(state.progressStartedAtMillis) { mutableStateOf(0L) }
    LaunchedEffect(state.progressStartedAtMillis, state.isSending) {
        val startedAt = state.progressStartedAtMillis ?: return@LaunchedEffect
        do {
            elapsedSeconds = ((System.currentTimeMillis() - startedAt) / 1000).coerceAtLeast(0)
            if (!state.isSending) break
            delay(1000)
        } while (true)
    }
    val hasText = state.streamingText.isNotEmpty()
    Surface(
        modifier = Modifier.fillMaxWidth(0.92f),
        color = AccentMintContainer,
        shape = RoundedCornerShape(20.dp)
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.isSending) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                }
                Text(
                    when {
                        !state.isSending -> "本次请求未完成"
                        hasText -> "正在输出回答"
                        else -> "正在准备你的旅行回答"
                    } + " · ${elapsedSeconds}秒",
                    style = MaterialTheme.typography.labelLarge
                )
            }
            if (!hasText || !state.isSending) {
                state.progressSteps.forEach { step ->
                    Text(
                        when (step.status) {
                            "success" -> "✓ ${step.label.removePrefix("正在")} · 已完成"
                            "degraded" -> "△ ${step.label.removePrefix("正在")} · 已生成简化结果"
                            "failed" -> "! ${step.label.removePrefix("正在")} · 未完成"
                            else -> "● ${step.label}"
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (step.status == "failed") MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurface
                    )
                }
            }
        }
    }
}

@Composable
private fun ChatBubble(message: ChatMessage, onOpenKnowledge: (Long) -> Unit) {
    val isUser = message.role == ChatRole.USER
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(if (isUser) 0.84f else 0.92f),
            shape = RoundedCornerShape(
                topStart = 20.dp,
                topEnd = 20.dp,
                bottomStart = if (isUser) 20.dp else 6.dp,
                bottomEnd = 20.dp
            ),
            colors = CardDefaults.cardColors(
                containerColor = if (isUser) ChatUserBlue else ChatAssistantGreen
            )
        ) {
            SelectionContainer {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 13.dp)) {
                    Text(text = message.text)
                    if (!isUser) {
                        Regex("收藏#(\\d+)").findAll(message.text)
                            .mapNotNull { it.groupValues[1].toLongOrNull() }
                            .distinct().take(5).forEach { id ->
                                TextButton(onClick = { onOpenKnowledge(id) }) {
                                    Text("查看收藏 #$id")
                                }
                            }
                    }
                    if (message.status == "failed" || message.status == "pending") {
                        Text(
                            text = if (message.status == "failed") "发送失败，可在输入框重试" else "处理中…",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}
