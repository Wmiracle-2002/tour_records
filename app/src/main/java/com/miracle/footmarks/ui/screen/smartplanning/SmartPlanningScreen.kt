package com.miracle.footmarks.ui.screen.smartplanning

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel

@Composable
fun SmartPlanningScreen(
    modifier: Modifier = Modifier,
    viewModel: SmartPlanningViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    SmartPlanningContent(
        uiState = uiState,
        onDraftChange = viewModel::updateDraft,
        onSend = viewModel::send,
        onDismissError = viewModel::dismissError,
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
    modifier: Modifier = Modifier
) {
    val listState = rememberLazyListState()
    LaunchedEffect(uiState.messages.size, uiState.isSending) {
        val lastItemIndex = if (uiState.isSending) {
            uiState.messages.size + 1
        } else {
            uiState.messages.size
        }
        if (lastItemIndex > 0) {
            listState.scrollToItem(lastItemIndex)
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("智能规划") }) }
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
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Card(
                        modifier = Modifier
                            .fillMaxWidth(0.88f)
                            .padding(top = 16.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.secondaryContainer
                        )
                    ) {
                        Column(
                            modifier = Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text(
                                text = "你好，我是足迹智能规划助手",
                                style = MaterialTheme.typography.titleMedium
                            )
                            Text(
                                text = "告诉我目的地、日期和偏好，我会帮你整理旅行计划。",
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                }
                items(uiState.messages, key = { it.id }) { message ->
                    ChatBubble(message)
                }
                if (uiState.isSending) {
                    item {
                        Text(
                            text = "正在规划…",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 4.dp)
                        )
                    }
                }
            }

            uiState.error?.let { error ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = error,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.weight(1f)
                    )
                    TextButton(onClick = onDismissError) {
                        Text("关闭")
                    }
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.Bottom
            ) {
                OutlinedTextField(
                    value = uiState.draft,
                    onValueChange = onDraftChange,
                    label = { Text("输入你的旅行想法") },
                    modifier = Modifier.weight(1f),
                    minLines = 1,
                    maxLines = 4
                )
                Button(
                    onClick = onSend,
                    enabled = !uiState.isSending && uiState.draft.isNotBlank()
                ) {
                    Text("发送")
                }
            }
        }
    }
}

@Composable
private fun ChatBubble(message: ChatMessage) {
    val isUser = message.role == ChatRole.USER
    Card(
        modifier = Modifier.fillMaxWidth(if (isUser) 0.88f else 1f),
        colors = CardDefaults.cardColors(
            containerColor = if (isUser) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Text(
            text = message.text,
            modifier = Modifier.padding(16.dp)
        )
    }
}
